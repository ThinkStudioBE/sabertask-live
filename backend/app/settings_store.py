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
import os
import threading
from typing import Dict, List, Optional

from . import config

SETTINGS_PATH = config.BASE_DIR / "settings.json"

_lock = threading.Lock()
_cache = None
_cache_stamp = None


def _defaults() -> dict:
    return {
        "countries": [dict(row) for row in config.COUNTRIES],
    }


def _read() -> dict:
    """The file, merged over the defaults. Re-read whenever it changes on disk,
    so another process editing it is picked up too."""
    global _cache, _cache_stamp
    try:
        stamp = os.path.getmtime(SETTINGS_PATH)
    except OSError:
        stamp = None

    if _cache is not None and stamp == _cache_stamp:
        return _cache

    data = _defaults()
    if stamp is not None:
        try:
            with open(SETTINGS_PATH, "r") as handle:
                stored = json.load(handle)
            if isinstance(stored, dict):
                data.update({k: v for k, v in stored.items() if v is not None})
        except (ValueError, OSError):
            # A corrupt settings file must not take the app down with it: the
            # defaults are a working configuration.
            print("[settings] " + str(SETTINGS_PATH) + " could not be read, using defaults")

    _cache, _cache_stamp = data, stamp
    return data


def _write(data: dict) -> None:
    global _cache, _cache_stamp
    with open(SETTINGS_PATH, "w") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
    _cache = data
    try:
        _cache_stamp = os.path.getmtime(SETTINGS_PATH)
    except OSError:
        _cache_stamp = None


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
                    data["countries"] = rows
                    _write(data)
                return {"key": code, "label": row.get("label") or code,
                        "flag": row.get("flag") or config.flag_for(code)}
        row = {"key": code, "label": (label or code).strip() or code,
               "flag": config.flag_for(code)}
        rows.append(row)
        data["countries"] = rows
        _write(data)
        return row


def remove_country(code: str) -> bool:
    code = (code or "").strip().upper()
    with _lock:
        data = _read()
        rows = [dict(r) for r in data.get("countries") or []]
        kept = [r for r in rows if str(r.get("key", "")).upper() != code]
        if len(kept) == len(rows):
            return False
        data["countries"] = kept
        _write(data)
        return True
