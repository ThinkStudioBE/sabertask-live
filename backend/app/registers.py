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
    DK   CVR, which is Erhvervsstyrelsen's own Elasticsearch. Free, but not
         open: a user id and a password are issued by email after a signed
         declaration, in up to three weeks. The adapter below is written and
         switched off, waiting on CVR_USER and CVR_PASSWORD.
    SE   Bolagsverket does not register industry codes at all; the codes come
         from the statistics office and its company data needs an agreement.
    NL   the KVK API has no activity-code search. Name, street and place only,
         which is not the question a prospector asks.
    US   no national register. Fifty state registers, no shared code system.
    CA   no national register with activity codes either.

SE, NL, US and CA stay on the map, and Denmark with them until its
credentials arrive. A country nobody has written an adapter for simply falls
through, so adding a country in Settings keeps working the way it did.

There is no stand-in data here, as everywhere in this build: a register row is
a real company or there is no row.
"""

import json
import os
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
#
# Denmark subdivides further than either, so three of its six are not simply the
# Danish spelling of the same number:
#
#   * 81.22 becomes three codes. 812210 vinduespolering is window cleaning on
#     its own, 812220 is chimney sweeping and 812290 is the rest of the building
#     and industrial cleaning. Only 812210 is the window segment, which leaves
#     the chimney sweeps out of a list they do not belong on.
#   * 68.32 becomes 683210, managing property under contract, and 683220,
#     ejerforeninger. An ejerforening is a building's owners' association: it
#     buys this work rather than sells it, so only 683210 is a prospect.
#   * Snow is not split off at all. It sits in 812900, andre rengoeringsydelser,
#     with the rest of the outdoor cleaning, which is also where the European
#     class puts snow and ice removal.
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
    "DK": {
        "facility": ["811000", "683210"],
        "cleaning": ["812100"],
        "window": ["812210"],
        "landscaping": ["813000"],
        "winter": ["812900"],
        "municipal": ["841100"],
    },
    "BE": {
        # Belgium splits property management by what is being managed, so both
        # halves are here: the facility profile is the manager who holds the
        # service agreements for a portfolio, residential or not. Leaving them
        # out left Belgium with 835 facility companies where the other three
        # countries all count their property managers in. It is now 5,169.
        "facility": ["81100", "68321", "68322"],
        "cleaning": ["81210"],
        "window": ["81220"],
        "landscaping": ["81300"],
        "winter": ["81290"],
        # The OCMW is a municipality's own social-care arm and runs the care
        # homes and service flats in the town. Same crews, same buildings, same
        # seats, and it nearly doubles what Belgium has under municipal.
        "municipal": ["84114", "84115"],
    },
}

REGISTER_NAMES = {
    "NO": "Enhetsregisteret",
    "FI": "PRH / YTJ",
    "DK": "CVR",
    "BE": "KBO",
}


class RegisterFailed(Exception):
    """This country's register could not answer. The caller falls back."""


def register_for(code: str) -> Optional[str]:
    """The register's name for a country, or None when it has none here.

    None also covers a register that exists but cannot be reached yet, which at
    the moment means Denmark without its credentials. Settings shows this name
    on the country to say where a search will go, so a name here that the search
    does not actually use would be a label that lies.
    """
    code = (code or "").upper()
    return REGISTER_NAMES.get(code) if _usable(code) else None


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


# ------------------------------------------------------------------- Denmark ---
#
# CVR's system interface: Erhvervsstyrelsen's own Elasticsearch, documented at
# erhvervsstyrelsen.dk/kom-godt-igang-med-elasticSearch. Free to use and free to
# apply for, but not open. A user id and password are issued by email after a
# signed declaration, and the published turnaround is up to three weeks.
#
# UNTESTED, and deliberately so rather than by neglect. There are no credentials
# on this machine, the endpoint answers 401 without them, and so not one line
# below has seen a real response. It is written against that guide for the field
# paths, the Basic auth, the query DSL and the ten-document default, and against
# the field names used by open-source clients of the same endpoint. Two things
# follow from being unable to run it:
#
#   * Where the guide does not settle a detail, the spot says "unverified" and
#     what was assumed instead.
#   * A wrong field path in an Elasticsearch filter does not fail. It matches
#     nothing, which reads exactly like "Denmark has no cleaning companies",
#     the one answer this module forbids. So an empty answer is probed before
#     it is believed, at the end of `_denmark`.

# The guide's own examples write plain http and Basic auth, so the password
# travels in clear to a government host. That is Erhvervsstyrelsen's choice of
# transport rather than one made here; whether https also answers is worth a
# try on the first day there is a password to try it with.
CVR_URL = "http://distribution.virk.dk/cvr-permanent/virksomhed/_search"

# Every field path the queries use, in one place: they are the one part of this
# adapter most likely to need a correction once a real response arrives.
_CVR_ROOT = "Vrvirksomhed"
_CVR_META = _CVR_ROOT + ".virksomhedMetadata"
_CVR_BRANCHE = _CVR_META + ".nyesteHovedbranche.branchekode"
_CVR_POSTDISTRIKT = _CVR_META + ".nyesteBeliggenhedsadresse.postdistrikt"
_CVR_KOMMUNE = _CVR_META + ".nyesteBeliggenhedsadresse.kommune.kommuneNavn"
_CVR_STAFF = _CVR_META + ".nyesteAarsbeskaeftigelse.antalAnsatte"

# sammensatStatus is the register's own plain-language status, and the guide
# points at it as the field that holds the real answer. Only a status that says
# the company is finished or on its way there keeps it off the list. Anything
# unrecognised is kept: a word nobody here has seen before is not evidence that
# a company is gone.
CVR_DEAD = ("OPHOER", "OPH\u00d8R", "OPLOES", "OPL\u00d8S", "SLETTET",
            "KONKURS", "LIKVIDATION", "TVANGS")


def _cvr_auth():
    """The CVR credentials, or None for as long as they are missing."""
    user = (os.getenv("CVR_USER") or "").strip()
    password = (os.getenv("CVR_PASSWORD") or "").strip()
    return (user, password) if user and password else None


def _post_json(url: str, body: dict, auth) -> dict:
    """POST a query and parse the answer.

    No curl fallback, unlike `_get_json`. That one exists because this machine's
    TLS is too old for some hosts, and this endpoint is plain HTTP, so there is
    no handshake here to fail.
    """
    try:
        response = httpx.post(url, json=body, auth=auth,
                              headers={"User-Agent": USER_AGENT,
                                       "Content-Type": "application/json"},
                              timeout=HTTP_TIMEOUT)
    except httpx.HTTPError as error:
        raise RegisterFailed(type(error).__name__ + ": " + str(error)[:160])
    if response.status_code in (401, 403):
        raise RegisterFailed("CVR refused the credentials (HTTP "
                             + str(response.status_code) + ")")
    try:
        response.raise_for_status()
        return response.json()
    except Exception as error:
        raise RegisterFailed("CVR: " + type(error).__name__ + ": "
                             + str(error)[:140])


def _cvr_body(codes: List[str], city: Optional[str], size: int) -> dict:
    """One query: every wanted activity code at once, in one town or the country.

    One request rather than Norway's code-by-code loop, because the guide
    reserves the right to cut off an account that leans on the service, and each
    hit carries its own activity code so the segments can be told apart
    afterwards anyway.
    """
    must = [{"terms": {_CVR_BRANCHE: codes}}]
    if city:
        # Unverified: which field a plain town name can match. The guide's
        # examples reach into the metadata block with flat dotted paths, so the
        # paths are sound, but a Danish post district is written "Koebenhavn K"
        # where the municipality is "Koebenhavn", and whether these are analysed
        # text or keywords decides which of the two a bare town name hits. Both
        # are offered and one is enough, which is right either way round.
        must.append({"bool": {"minimum_should_match": 1, "should": [
            {"match_phrase": {_CVR_POSTDISTRIKT: city}},
            {"match_phrase": {_CVR_KOMMUNE: city}},
        ]}})
    return {
        "size": size,
        # The metadata object whole rather than its leaves. It is the register's
        # own denormalised "latest value" block, so asking for all of it means a
        # mistaken leaf path costs nothing, while a full company document with
        # every historical name and address would be megabytes per page.
        "_source": [_CVR_ROOT + ".cvrNummer",
                    _CVR_ROOT + ".virksomhedMetadata",
                    _CVR_ROOT + ".reklamebeskyttet",
                    _CVR_ROOT + ".telefonNummer",
                    _CVR_ROOT + ".elektroniskPost",
                    _CVR_ROOT + ".hjemmeside"],
        "query": {"bool": {"must": must}},
        # Biggest crew first, for Norway's reason: seats are per person in the
        # field, so the largest employer in a town is the largest deal in it.
        # unmapped_type keeps a sort on a field this index may not carry from
        # taking the whole query down with it.
        "sort": [{_CVR_STAFF: {"order": "desc", "missing": "_last",
                               "unmapped_type": "long"}}],
    }


def _cvr_hits(auth, codes: List[str], city: Optional[str], size: int) -> list:
    payload = _post_json(CVR_URL, _cvr_body(codes, city, size), auth)
    return (payload.get("hits") or {}).get("hits") or []


def _cvr_first(values) -> Optional[str]:
    """The first contact detail that is current and not marked secret.

    `hemmelig` is the company saying it does not want this one published, and a
    `periode.gyldigTil` is a detail it has since replaced.
    """
    for item in values or []:
        if not isinstance(item, dict):
            continue
        if item.get("hemmelig"):
            continue
        if (item.get("periode") or {}).get("gyldigTil"):
            continue
        value = str(item.get("kontaktoplysning") or "").strip()
        if value:
            return value
    return None


def _impersonal(address: str) -> bool:
    """Whether a mailbox belongs to the organisation rather than to a person.

    Borrowed, not copied. The rule lives in `tools/extract_kbo.py` because that
    is where it runs over four gigabytes of Belgian register, and there is no
    second copy of it here on purpose: one rule about whose mailbox this is, in
    one place, so the two countries can never drift apart on it. If that module
    is not importable, no Danish mailbox is carried across at all, which errs
    the safe way.
    """
    try:
        from tools.extract_kbo import impersonal
    except Exception:
        return False
    return bool(impersonal(address))


def _cvr_contacts(company: dict, meta: dict):
    """Phone, mailbox and homepage, as the company registered them itself.

    The mailbox has one more gate than the other two: it has to be the
    organisation's own and not a named colleague's. A legal entity is free to
    publish a person's address, and when it does the company stays on the list
    while that address does not.
    """
    phone = _cvr_first(company.get("telefonNummer"))
    email = _cvr_first(company.get("elektroniskPost"))
    website = _cvr_first(company.get("hjemmeside"))

    # Unverified: the three arrays above are documented by clients of this
    # endpoint rather than by the guide, which only ever shows the metadata
    # block. nyesteKontaktoplysninger is in that block but is a flat list with
    # nothing saying which string is which, so it is read by shape and only for
    # whatever the arrays did not already give.
    if not (phone and email and website):
        for value in meta.get("nyesteKontaktoplysninger") or []:
            value = str(value or "").strip()
            if not value:
                continue
            if "@" in value:
                email = email or value
            elif sum(character.isdigit() for character in value) >= 6:
                phone = phone or value
            elif "." in value:
                website = website or value

    if email and not _impersonal(email):
        email = None
    return phone or None, email or None, website or None


def _cvr_staff(meta: dict) -> Optional[int]:
    """How many people, the most complete count first. The quarterly and monthly
    figures are there for a company too young to have an annual one yet."""
    for key in ("nyesteAarsbeskaeftigelse", "nyesteKvartalsbeskaeftigelse",
                "nyesteMaanedsbeskaeftigelse"):
        count = (meta.get(key) or {}).get("antalAnsatte")
        if isinstance(count, bool):
            continue
        if isinstance(count, (int, float)):
            return int(count)
    return None


def _cvr_lead(number: str, company: dict, meta: dict) -> Optional[dict]:
    address = meta.get("nyesteBeliggenhedsadresse") or {}
    street = " ".join(
        str(part) for part in [address.get("vejnavn"),
                               address.get("husnummerFra"),
                               address.get("bogstavFra")]
        if part not in (None, "")).strip() or None
    name = str((meta.get("nyesteNavn") or {}).get("navn") or "").strip()
    if not name:
        return None
    phone, email, website = _cvr_contacts(company, meta)
    return {
        "source_id": "cvr/" + number,
        "name": name,
        "segment": _segment_of(
            "DK", (meta.get("nyesteHovedbranche") or {}).get("branchekode") or ""),
        "country": "DK",
        # Left in the register's own capitalisation. CVR writes a post district
        # as "Koebenhavn K", and title-casing that would be a guess dressed up
        # as tidiness.
        "city": (address.get("postdistrikt") or "").strip() or None,
        "street": street,
        "website": website,
        "phone": phone,
        "email": email,
        "field_staff": _cvr_staff(meta),
    }


def _denmark(segments: List[str], cities: List[str], cap: int) -> List[dict]:
    auth = _cvr_auth()
    if auth is None:
        raise RegisterFailed("CVR_USER and CVR_PASSWORD are not set")

    codes = _codes_for("DK", segments)
    if not codes:
        return []
    places = [c.strip() for c in cities if c and c.strip()] or [None]

    leads: List[dict] = []
    seen = set()
    hits_seen = 0
    unflagged = 0
    for place in places:
        if len(leads) >= cap:
            break
        hits = _cvr_hits(auth, codes, place, min(cap, 100))
        hits_seen += len(hits)
        for hit in hits:
            if len(leads) >= cap:
                break
            source = hit.get("_source") or {}
            # Unverified: whether the document is wrapped under its type name.
            # The guide's query paths all start "Vrvirksomhed.", so it almost
            # certainly is, and the fallback costs one line.
            company = source.get(_CVR_ROOT) or source
            number = str(company.get("cvrNummer") or "").strip()
            if not number or number in seen:
                continue
            meta = company.get("virksomhedMetadata") or {}
            status = str(meta.get("sammensatStatus") or "").upper()
            if any(word in status for word in CVR_DEAD):
                continue
            # CVR-loven section 19, subsection 2: a company that has registered
            # reklamebeskyttelse must not have its register data used for direct
            # marketing by a private legal entity, and writing to people is what
            # this pipeline is for. So the flag decides, and a row whose flag
            # cannot be read is left out rather than guessed at. The declaration
            # signed to get these credentials is a promise about this exact
            # thing, which makes it a hard filter and not a preference.
            protected = company.get("reklamebeskyttet")
            if protected is None:
                unflagged += 1
                continue
            if protected:
                continue
            lead = _cvr_lead(number, company, meta)
            if lead is None:
                continue
            seen.add(number)
            leads.append(lead)

    if leads:
        return leads

    # Nothing came back. Before reporting that, establish which kind of nothing
    # it is, because a mistaken field path matches no documents and is
    # indistinguishable from an empty country. Denmark has thousands of cleaning
    # companies, so a code filter that finds none of them is a broken query, and
    # raising hands the search to the map instead of telling a rep that Denmark
    # has no cleaners in it.
    if not hits_seen:
        if any(places) and _cvr_hits(auth, codes, None, 1):
            return []       # the codes do work; these towns simply have none
        raise RegisterFailed("CVR matched no company at all for "
                             + ", ".join(codes) + ", so the query is wrong")
    if unflagged and unflagged == hits_seen:
        raise RegisterFailed("CVR answered without reklamebeskyttet, which this "
                             "search may not go ahead without")
    return []


# ------------------------------------------------------------------- dispatch ---

ADAPTERS = {
    "NO": _norway,
    "FI": _finland,
    "DK": _denmark,
    "BE": _belgium,
}

# An adapter that needs credentials only counts as present once it has them.
# Both `has_register` and `register_for` go through this, so what Settings tells
# a user about where a country gets searched cannot drift from where the search
# actually goes, and Denmark keeps running on the map until the day CVR_USER and
# CVR_PASSWORD appear in the environment.
GATES = {
    "DK": lambda: _cvr_auth() is not None,
}


def _usable(code: str) -> bool:
    code = (code or "").upper()
    if code not in ADAPTERS:
        return False
    gate = GATES.get(code)
    return gate() if gate else True


def has_register(code: str) -> bool:
    return _usable(code)


def search(code: str, segments: List[str], cities: List[str],
           cap: int) -> List[dict]:
    """This country's register, or RegisterFailed. Never an empty-looking lie:
    a register that cannot be reached raises, so the caller can fall back to the
    map instead of reporting that the country has no companies in it."""
    if not _usable(code):
        raise RegisterFailed("no register adapter for " + str(code))
    adapter = ADAPTERS[(code or "").upper()]
    return adapter(segments, cities, max(1, cap))
