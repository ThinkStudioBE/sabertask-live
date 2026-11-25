"""Settings that a person can change while the app is running.

`config.py` holds the defaults. This holds what somebody edited, in a JSON file
next to the database, and every consumer reads through the accessor functions
below rather than through `config`. That indirection is the whole feature: a
country added from the Settings screen has to work in the next search, in the
same process, with no restart and no deploy. A module-level constant copied at
import time cannot do that, which is exactly the trap this avoids.

So: never `from .settings_store import countries` and never bind the result to
a module constant. Call `settings_store.countries()` where you need it.
"""

import json
import threading
import time
from typing import Dict, List, Optional

from sqlmodel import Session, select

from . import config

# How long a reader may keep what it last saw. Short, because the point of this
# module is that a country added on one screen is searchable on the next
# request; long enough that drawing a list of five hundred rows does not become
# five hundred queries.
CACHE_TTL = 5.0

_lock = threading.Lock()
_cache = None
_cache_until = 0.0


def _defaults() -> dict:
    return {
        "countries": [dict(row) for row in config.COUNTRIES],
    }


def _read() -> dict:
    """What is stored, merged over the defaults."""
    global _cache, _cache_until
    if _cache is not None and time.time() < _cache_until:
        return _cache

    data = _defaults()
    try:
        from .db import engine
        from .models import AppSetting
        with Session(engine) as session:
            for row in session.exec(select(AppSetting)).all():
                try:
                    value = json.loads(row.value)
                except ValueError:
                    continue
                if value is not None:
                    data[row.key] = value
    except Exception as error:
        # A settings read must never be the thing that takes a page down. The
        # defaults are a working configuration.
        print("[settings] could not be read (" + type(error).__name__ + "), using defaults")

    _cache, _cache_until = data, time.time() + CACHE_TTL
    return data


def _store(key: str, value) -> None:
    global _cache, _cache_until
    from .db import engine
    from .models import AppSetting
    with Session(engine) as session:
        row = session.get(AppSetting, key)
        if row is None:
            row = AppSetting(key=key)
        row.value = json.dumps(value, ensure_ascii=False)
        row.updated_at = __import__("datetime").datetime.utcnow()
        session.add(row)
        session.commit()
    _cache = None
    _cache_until = 0.0


def get(key: str, default=None):
    """One stored setting, or the default. For settings that are a block of
    their own rather than a list the whole app reads, like the connection to a
    customer's CRM."""
    value = _read().get(key)
    return default if value is None else value


def put(key: str, value) -> None:
    """Store one setting and drop the cache, so the next read sees it."""
    _store(key, value)


# ---------------------------------------------------------------- countries ---

def countries() -> List[dict]:
    """[{key, label, flag}], in the order they were added."""
    rows = []
    for row in _read().get("countries") or []:
        code = str(row.get("key") or "").strip().upper()
        if len(code) != 2 or not code.isalpha():
            continue
        rows.append({
            "key": code,
            "label": str(row.get("label") or code).strip() or code,
            "flag": row.get("flag") or config.flag_for(code),
        })
    return rows


def country_codes() -> List[str]:
    return [row["key"] for row in countries()]


def country_label(code: str, fallback: str = "") -> str:
    code = (code or "").strip().upper()
    for row in countries():
        if row["key"] == code:
            return row["label"]
    return fallback or code


def country_flag(code: str) -> str:
    code = (code or "").strip().upper()
    for row in countries():
        if row["key"] == code:
            return row["flag"]
    # A company can outlive the country being removed from the set, and its row
    # should still carry a flag rather than go blank.
    return config.flag_for(code)


def add_country(code: str, label: Optional[str] = None) -> Dict[str, str]:
    code = (code or "").strip().upper()
    if len(code) != 2 or not code.isalpha():
        raise ValueError("A country is a two-letter ISO code, like PT or IE")
    with _lock:
        data = _read()
        rows = [dict(r) for r in data.get("countries") or []]
        for row in rows:
            if str(row.get("key", "")).upper() == code:
                if label:
                    row["label"] = label.strip()
                    row["flag"] = config.flag_for(code)
                    _store("countries", rows)
                return {"key": code, "label": row.get("label") or code,
                        "flag": row.get("flag") or config.flag_for(code)}
        row = {"key": code, "label": (label or code).strip() or code,
               "flag": config.flag_for(code)}
        rows.append(row)
        _store("countries", rows)
        return row


def remove_country(code: str) -> bool:
    code = (code or "").strip().upper()
    with _lock:
        data = _read()
        rows = [dict(r) for r in data.get("countries") or []]
        kept = [r for r in rows if str(r.get("key", "")).upper() != code]
        if len(kept) == len(rows):
            return False
        _store("countries", kept)
        return True
