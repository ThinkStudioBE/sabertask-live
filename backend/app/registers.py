"""Official business registers, for the countries that publish one.

The map finds a company only if somebody mapped it, and for these industries
most of them nobody did: a cleaning firm works in other people's buildings and
a landscaper works in other people's gardens, so neither has a shopfront worth
a pin. A register has no such gap. Every company in the country is in it by
law, filed under what it actually does.

Measured against OpenStreetMap, in Antwerp, for the same two industries:

    facility     register 37    map  1
    cleaning     register 256   map 13

So where a register exists, it is the source and the map is the fallback. Not
every market has one that can be searched by activity, and that is the whole
reason this module is a lookup table rather than one function:

    BE   the KBO open-data extract, loaded into this database. Free.
    NO   Enhetsregisteret, live JSON API, no key, no registration.
    FI   PRH avoindata, live JSON API, no key, no registration.
    DK   the CVR system interface is free but granted by email, after a signed
         declaration, in up to three weeks. Not wired up: nobody has applied.
    SE   Bolagsverket does not register industry codes at all; the codes come
         from the statistics office and its company data needs an agreement.
    NL   the KVK API has no activity-code search. Name, street and place only,
         which is not the question a prospector asks.
    US   no national register. Fifty state registers, no shared code system.
    CA   no national register with activity codes either.

Those six stay on the map. A country nobody has written an adapter for simply
falls through, so adding a country in Settings keeps working the way it did.

There is no stand-in data here, as everywhere in this build: a register row is
a real company or there is no row.
"""

import json
import subprocess
from typing import Dict, List, Optional

import httpx

HTTP_TIMEOUT = 25.0
USER_AGENT = "sabertask-sales/1.0 (business register lookup)"

# What each register calls the six industries. These are national versions of
# the same European classification, which is why they almost line up and why
# "almost" has to be written out per country rather than assumed.
#
# Norway does not split 81.29, so winter work sits with the gardeners, which is
# also where the map puts it: in Norway the firm that cuts the grass is the firm
# that clears the snow. Finland does split it, into street cleaning and other.
CODES: Dict[str, Dict[str, List[str]]] = {
    "NO": {
        "facility": ["81.100", "68.320"],
        "cleaning": ["81.210"],
        "window": ["81.220"],
        "landscaping": ["81.300"],
        "winter": ["81.300"],
        "municipal": ["84.110"],
    },
    "FI": {
        "facility": ["81100", "68320"],
        "cleaning": ["81210"],
        "window": ["81220"],
        "landscaping": ["81300"],
        "winter": ["81291", "81299"],
        "municipal": ["84110"],
    },
    "BE": {
        "facility": ["81100"],
        "cleaning": ["81210"],
        "window": ["81220"],
        "landscaping": ["81300"],
        "winter": ["81290"],
        "municipal": ["84114"],
    },
}

REGISTER_NAMES = {
    "NO": "Enhetsregisteret",
    "FI": "PRH / YTJ",
    "BE": "KBO",
}


class RegisterFailed(Exception):
    """This country's register could not answer. The caller falls back."""


def register_for(code: str) -> Optional[str]:
    """The register's name for a country, or None when it has none here."""
    return REGISTER_NAMES.get((code or "").upper())


def _get_json(url: str, params: dict) -> dict:
    """GET and parse, with a curl fallback.

    The reason is this machine rather than the registers: the system Python is
    linked against a TLS library with no TLS 1.3, so some hosts refuse its
    handshake while curl on the same box reaches them. Only a transport error
    falls through; a timeout or an HTTP error is the server's answer and is
    reported as one.
    """
    try:
        response = httpx.get(url, params=params,
                             headers={"User-Agent": USER_AGENT},
                             timeout=HTTP_TIMEOUT)
        response.raise_for_status()
        return response.json()
    except httpx.ConnectError:
        pass
    except httpx.HTTPError as error:
        raise RegisterFailed(type(error).__name__ + ": " + str(error)[:160])

    query = httpx.QueryParams(params)
    full = url + ("&" if "?" in url else "?") + str(query)
    try:
        done = subprocess.run(
            ["curl", "-s", "--max-time", str(int(HTTP_TIMEOUT)),
             "-A", USER_AGENT, full],
            capture_output=True, timeout=HTTP_TIMEOUT + 5,
        )
        return json.loads(done.stdout.decode("utf-8", "replace"))
    except Exception as error:
        raise RegisterFailed("curl: " + type(error).__name__ + ": " + str(error)[:120])


def _codes_for(code: str, segments: List[str]) -> List[str]:
    table = CODES.get(code, {})
    out = []
    for segment in segments:
        for value in table.get(segment, []):
            if value not in out:
                out.append(value)
    return out


def _segment_of(code: str, value: str) -> str:
    """Which of the six a register's own activity code belongs to."""
    table = CODES.get(code, {})
    value = (value or "").strip()
    for segment in ("cleaning", "window", "landscaping", "winter",
                    "municipal", "facility"):
        if value in table.get(segment, []):
            return segment
    return "facility"


# --------------------------------------------------------------------- Norway ---

BRREG_URL = "https://data.brreg.no/enhetsregisteret/api/enheter"
BRREG_KOMMUNER = "https://data.brreg.no/enhetsregisteret/api/kommuner"
_kommuner: Dict[str, str] = {}


def _kommune_numbers(cities: List[str]) -> List[str]:
    """City names to the municipality numbers the register filters on.

    The whole list is 365 rows and is fetched once, because a name the register
    does not know has to be told apart from a name it does: guessing a number
    would return somebody else's municipality.
    """
    global _kommuner
    if not _kommuner:
        payload = _get_json(BRREG_KOMMUNER, {"size": 1000})
        rows = (payload.get("_embedded") or {}).get("kommuner") or []
        _kommuner = {row["navn"].upper(): row["nummer"] for row in rows}
    numbers = []
    for city in cities:
        number = _kommuner.get(city.strip().upper())
        if number and number not in numbers:
            numbers.append(number)
    return numbers


def _norway(segments: List[str], cities: List[str], cap: int) -> List[dict]:
    codes = _codes_for("NO", segments)
    places = _kommune_numbers(cities) if cities else [None]
    if cities and not places:
        return []       # named cities, none of them Norwegian

    leads = []
    seen = set()
    for code in codes:
        for place in places:
            if len(leads) >= cap:
                return leads
            # Biggest crew first. Seats are per person in the field, so the
            # largest employer in a municipality is the largest deal in it, and
            # without this the register answers alphabetically: fifty companies
            # whose names begin with a digit.
            params = {"naeringskode": code, "size": min(cap, 100),
                      "sort": "antallAnsatte,DESC"}
            if place:
                params["kommunenummer"] = place
            payload = _get_json(BRREG_URL, params)
            rows = (payload.get("_embedded") or {}).get("enheter") or []
            for row in rows:
                if len(leads) >= cap:
                    return leads
                number = str(row.get("organisasjonsnummer") or "")
                if not number or number in seen:
                    continue
                if row.get("konkurs") or row.get("underAvvikling"):
                    continue    # bankrupt or winding up is not a prospect
                seen.add(number)
                address = row.get("forretningsadresse") or {}
                street = ", ".join(address.get("adresse") or []) or None
                leads.append({
                    "source_id": "brreg/" + number,
                    "name": row.get("navn") or "",
                    "segment": _segment_of(
                        "NO", (row.get("naeringskode1") or {}).get("kode") or code),
                    "country": "NO",
                    "city": (address.get("poststed") or "").title() or None,
                    "street": street,
                    "website": None,
                    "phone": None,
                    "email": None,
                    "field_staff": row.get("antallAnsatte"),
                })
    return leads


# -------------------------------------------------------------------- Finland ---

PRH_URL = "https://avoindata.prh.fi/opendata-ytj-api/v3/companies"


def _finland(segments: List[str], cities: List[str], cap: int) -> List[dict]:
    codes = _codes_for("FI", segments)
    places = list(cities) if cities else [None]

    leads = []
    seen = set()
    for code in codes:
        for place in places:
            if len(leads) >= cap:
                return leads
            params = {"mainBusinessLine": code}
            if place:
                params["location"] = place
            payload = _get_json(PRH_URL, params)
            for row in payload.get("companies") or []:
                if len(leads) >= cap:
                    return leads
                number = ((row.get("businessId") or {}).get("value") or "")
                if not number or number in seen:
                    continue
                # The register keeps ceased companies, so a company with no
                # live registration is skipped rather than sold to.
                entries = row.get("registeredEntries") or []
                live = any(entry.get("description") != "Ceased"
                           and not entry.get("endDate") for entry in entries)
                if entries and not live:
                    continue
                seen.add(number)
                name = _current_name(row.get("names") or [])
                if not name:
                    continue
                # Take the first address that actually carries a place. Some
                # records hold none at all, and the list is not ordered.
                addresses = row.get("addresses") or []
                address = next((a for a in addresses if a.get("postOffices")),
                               addresses[0] if addresses else {})
                offices = address.get("postOffices") or []
                city = next((o.get("city") for o in offices
                             if o.get("languageCode") == "1"), None)
                street = " ".join(part for part in [
                    (address.get("street") or "").title(),
                    str(address.get("buildingNumber") or ""),
                ] if part).strip() or None
                leads.append({
                    "source_id": "prh/" + number,
                    "name": name,
                    "segment": _segment_of(
                        "FI", (row.get("mainBusinessLine") or {}).get("type") or code),
                    "country": "FI",
                    "city": (city or "").title() or None,
                    "street": street,
                    "website": None,
                    "phone": None,
                    "email": None,
                    "field_staff": None,
                })
    return leads


def _current_name(names: List[dict]) -> Optional[str]:
    """The name in use now. The register keeps every former name beside it, and
    the first one in the list is not reliably the current one."""
    live = [n for n in names if n.get("type") == "1" and not n.get("endDate")]
    if live:
        return live[0].get("name")
    trade = [n for n in names if n.get("type") == "1"]
    trade.sort(key=lambda n: n.get("endDate") or "", reverse=True)
    return trade[0].get("name") if trade else None


# ------------------------------------------------------------------- Belgium ---

def _belgium(segments: List[str], cities: List[str], cap: int) -> List[dict]:
    """The KBO extract, out of this app's own database.

    Belgium publishes its register as a download and not as a query API, so the
    rows are loaded ahead of time by `load_register.py`. When nobody has loaded
    them this raises rather than returning nothing, so the search falls back to
    the map instead of reporting that Belgium has no cleaning companies.

    Ordered by what a rep can act on: a mailbox first, then a website, then a
    phone number. The register holds a contact detail for about one company in
    seven, and those are the ones worth putting at the top of the list.
    """
    from sqlalchemy import case, func
    from sqlmodel import Session, or_, select

    from .db import engine
    from .models import RegisterCompany

    wanted = [s for s in segments if s in CODES["BE"]] or ["cleaning"]

    with Session(engine) as session:
        query = select(RegisterCompany).where(
            RegisterCompany.country == "BE",
            RegisterCompany.segment.in_(wanted),
        )
        if cities:
            clauses = [func.lower(RegisterCompany.city).like(c.strip().lower() + "%")
                       for c in cities if c.strip()]
            if clauses:
                query = query.where(or_(*clauses))
        query = query.order_by(
            case((RegisterCompany.email.is_(None), 1), else_=0),
            case((RegisterCompany.website.is_(None), 1), else_=0),
            case((RegisterCompany.phone.is_(None), 1), else_=0),
            RegisterCompany.name,
        ).limit(cap)
        rows = session.exec(query).all()

        if not rows:
            loaded = session.exec(
                select(func.count()).select_from(RegisterCompany)
                .where(RegisterCompany.country == "BE")
            ).one()
            if not loaded:
                raise RegisterFailed("the Belgian register is not loaded")

    return [{
        "source_id": "kbo/" + row.reg_id,
        "name": row.name,
        "segment": row.segment,
        "country": "BE",
        "city": row.city or None,
        "street": row.street or None,
        "website": row.website or None,
        "phone": row.phone or None,
        "email": row.email or None,
        "field_staff": None,
    } for row in rows]


# ------------------------------------------------------------------- dispatch ---

ADAPTERS = {
    "NO": _norway,
    "FI": _finland,
    "BE": _belgium,
}


def has_register(code: str) -> bool:
    return (code or "").upper() in ADAPTERS


def search(code: str, segments: List[str], cities: List[str],
           cap: int) -> List[dict]:
    """This country's register, or RegisterFailed. Never an empty-looking lie:
    a register that cannot be reached raises, so the caller can fall back to the
    map instead of reporting that the country has no companies in it."""
    adapter = ADAPTERS.get((code or "").upper())
    if adapter is None:
        raise RegisterFailed("no register adapter for " + str(code))
    return adapter(segments, cities, max(1, cap))
