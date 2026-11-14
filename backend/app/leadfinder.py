"""Find leads: a plain-English brief turned into real companies on the map.

The search itself is free and keyless. Nominatim resolves each city to a box,
Overpass returns every business inside it that carries one of the tags we are
after, and OpenStreetMap already holds the name, address, website and phone. A
run costs nothing but time, which matters for a tool a sales floor is meant to
use daily rather than once.

Claude only reads the brief and says what to look for. That is one call per
search, not one per lead, and when it is unavailable the brief is read with
keywords instead, so the tab works without a key.

Three lessons from the same tool elsewhere are kept here on purpose:
a bounding box is a rectangle and a country is not, so every clause is also
intersected with the real border (a box round Liege reaches over Aachen);
Overpass answers a query it could not run with HTTP 200 and an empty list, so
its `remark` is read rather than trusted as "nothing there"; and this machine's
system Python is linked against a TLS library with no TLS 1.3, so some mirrors
refuse its handshake while `curl` on the same host reaches them fine, which is
why a transport error falls through to a curl subprocess instead of being taken
for a mirror being down.

Everything that comes back is a real company off the public map. There is no
stand-in data in this module and there must never be: this build is the one
pointed at real prospects, and a fictional row here is one nobody downstream
can tell from a found one.
"""

import json
import os
import re
import subprocess
import time
from typing import Dict, List, Optional, Tuple

import httpx

from . import config, settings_store

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
# Several mirrors, tried in order. They are run by volunteers and any one of
# them can be down, rate-limited or unreachable from a given host, which looks
# exactly like "no results" if there is nothing to fall back to.
#
# Only full-planet instances belong here. A regional extract answers happily
# and returns nothing for everywhere it does not cover, and that is worse than
# a server being down: an empty list reads as "this city has no cleaning
# companies". Override the list with OVERPASS_URLS to point at one deliberately
# (overpass.osm.ch carries Switzerland, and is reachable from some hosts these
# three refuse).
OVERPASS_URLS = [
    url.strip() for url in os.getenv(
        "OVERPASS_URLS",
        "https://overpass-api.de/api/interpreter,"
        "https://overpass.kumi.systems/api/interpreter,"
        "https://overpass.private.coffee/api/interpreter",
    ).split(",") if url.strip()
]
# OSM asks automated clients to identify themselves. A product name, never a
# person's address.
USER_AGENT = "SabertaskSales/1.0 (+https://www.sabertask.com)"
# Overpass is free and queues: a busy endpoint accepts the connection and then
# says nothing until a slot frees. Fifteen seconds is a demo's patience and it
# throws away answers that were on their way, so this build waits properly.
OVERPASS_TIMEOUT = 45
# How long the whole map phase may take before the search gives up. Generous,
# because there is nothing to fall back on here: an empty list is the honest
# answer and a slow one beats a wrong one. It has to cover every mirror in the
# list being unreachable in turn, or the one that would have answered is never
# reached.
MAP_BUDGET = 150
HTTP_TIMEOUT = 15

MAX_CITIES = 3
MAX_TAGS = 4


# What each of our industries looks like on the map. The generic office tag is
# only ever a last resort: a lead that matched it tells us nothing about what
# the company does, and the score says so.
SECTOR_TAGS = {
    "cleaning": ["craft=cleaning", "office=cleaning"],
    "window": ["craft=window_cleaning", "craft=cleaning"],
    "landscaping": ["craft=gardener", "shop=garden_centre", "landuse=plant_nursery"],
    "facility": ["office=facility_management", "office=property_management"],
    "winter": ["craft=snow_removal", "craft=gardener"],
    "municipal": ["office=government", "amenity=townhall"],
}
GENERIC_TAGS = ["office=company"]

# Words that say what a company actually does, whatever tag it was filed under.
SECTOR_WORDS = {
    "cleaning": ["clean", "schoonmaak", "reiniging", "rengor", "rengjor", "staed",
                 "propret", "hygien", "net "],
    "window": ["window", "glas", "ruiten", "gevel", "vindu", "vindue", "fonster"],
    "landscaping": ["garden", "tuin", "groen", "hoven", "landscap", "park",
                    "anlaggning", "anlegg", "jardin", "green"],
    "facility": ["facility", "facilit", "vastgoed", "property", "building",
                 "ejendom", "fastighet", "service"],
    "winter": ["winter", "snow", "sneeuw", "gladheid", "vinter", "salt", "strooi"],
    "municipal": ["gemeente", "kommun", "commune", "stad", "city", "municipal",
                  "vejdrift", "wegen", "public"],
}

# Somewhere to start when the brief names no city, for the countries we happen
# to know well. This is a convenience and never a gate: a country that is not
# in here is searched whole, which is what makes a country added from Settings
# work in the very next search without a line of code.
SEED_CITIES = {
    "BE": ["Antwerpen", "Gent", "Brussel"],
    "NL": ["Rotterdam", "Utrecht", "Amsterdam"],
    "LU": ["Luxembourg", "Esch-sur-Alzette"],
    "DK": ["Kobenhavn", "Aarhus", "Odense"],
    "SE": ["Stockholm", "Goteborg", "Malmo"],
    "NO": ["Oslo", "Bergen", "Trondheim"],
    "FI": ["Helsinki", "Tampere", "Turku"],
}

PLACE_TYPES = ("city", "town", "municipality", "village", "suburb")


class SearchFailed(Exception):
    """The search could not run. Says why in words a rep can act on.

    It carries the criteria when the brief was already read, so the caller can
    say what was being looked for without paying for a second reading of the
    same sentence.
    """

    def __init__(self, message, criteria=None):
        super().__init__(message)
        self.criteria = criteria


# ------------------------------------------------------------------ criteria ---

CRITERIA_SYSTEM = (
    "You turn a salesperson's brief into search criteria for Sabertask, which "
    "sells field service management software to companies whose people work on "
    "sites: cleaning, window cleaning, landscaping and green maintenance, "
    "facility management, winter services, and municipal or public works.\n\n"
    "Answer with JSON only, no prose, no code fence, in this shape:\n"
    '{"segments": ["cleaning"], "countries": ["BE","NL"], "cities": ["Antwerpen"], '
    '"summary": "one sentence naming what is being looked for"}\n\n'
    "segments must come from: cleaning, window, landscaping, facility, winter, "
    "municipal. countries from: BE, NL, LU, DK, SE, NO. Give at most three "
    "cities, real ones, spelled as the locals write them without accents. If the "
    "brief names no city, leave cities empty. If the brief names no country, "
    "leave countries empty. Never invent a segment that is not in the list: pick "
    "the closest one."
)


def _keyword_criteria(brief: str) -> dict:
    """Read the brief without a model. Crude, and it says so in the summary."""
    text = (brief or "").lower()
    segments = [key for key, words in SECTOR_WORDS.items()
                if any(word.strip() in text for word in words)]
    live = settings_store.countries()
    countries = [row["key"] for row in live
                 if row["key"].lower() in text.split()
                 or row["label"].lower() in text]
    cities = []
    for code, names in SEED_CITIES.items():
        for name in names:
            if name.lower() in text:
                cities.append(name)
                if code not in countries:
                    countries.append(code)
    return {
        "segments": segments or ["cleaning"],
        "countries": countries,
        "cities": cities[:MAX_CITIES],
        "summary": "read from the brief without a model",
    }


def criteria_from_brief(brief: str) -> dict:
    """One call, not one per lead. Falls back to keywords rather than failing."""
    criteria = None
    key = os.getenv("ANTHROPIC_API_KEY")
    if key and config.MAIL_AI_ENABLED:
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=key)
            response = client.messages.create(
                model=config.MAIL_MODEL,
                max_tokens=4000,
                output_config={"effort": "low"},
                system=CRITERIA_SYSTEM,
                messages=[{"role": "user", "content": brief}],
            )
            if getattr(response, "stop_reason", None) in ("refusal", "max_tokens"):
                raise ValueError("no usable answer")
            text = "".join(b.text for b in response.content
                           if getattr(b, "type", "") == "text").strip()
            match = re.search(r"\{.*\}", text, re.DOTALL)
            criteria = json.loads(match.group(0)) if match else None
        except Exception as error:
            print("[leads] reading the brief without a model: "
                  + type(error).__name__ + ": " + str(error)[:160])
            criteria = None
    if not isinstance(criteria, dict):
        criteria = _keyword_criteria(brief)

    segments = [s for s in criteria.get("segments") or [] if s in SECTOR_TAGS]
    known = set(settings_store.country_codes())
    countries = [c for c in criteria.get("countries") or [] if c in known]
    cities = [str(c).strip() for c in criteria.get("cities") or [] if str(c).strip()]
    if not segments:
        segments = ["cleaning"]
    if not countries:
        countries = ["BE", "NL"] if not cities else []
    return {
        "segments": segments[:3],
        "countries": countries,
        "cities": cities[:MAX_CITIES],
        "summary": str(criteria.get("summary") or "")[:200],
    }


def tags_for(segments: List[str]) -> List[str]:
    tags = []
    for segment in segments:
        for tag in SECTOR_TAGS.get(segment, []):
            if tag not in tags:
                tags.append(tag)
    return (tags or list(GENERIC_TAGS))[:MAX_TAGS]


# --------------------------------------------------------------- the search ---

def _bbox(place: str, require_place: bool = False) -> Optional[Tuple[tuple, Optional[str]]]:
    """'Gent, Belgium' to (box, country). Several results are asked for and the
    first settlement among them wins: Nominatim ranks by prominence, not by
    type, so a city that also names its province otherwise answers with the
    province.

    The country comes back with the box because the caller must not have to
    assume one. A box around Zurich filed under Belgium intersects a Belgian
    border with a Swiss rectangle and matches nothing at all, and an empty
    answer looks exactly like a city with no companies in it.

    `require_place` refuses anything that is not a settlement. It is for the
    case where the country is a guess: asked for "Rotterdam, Belgium" Nominatim
    answers with a street or a hamlet rather than nothing, and the guess would
    stand, putting a Dutch city in Belgium.
    """
    response = httpx.get(
        NOMINATIM_URL,
        params={"q": place, "format": "jsonv2", "limit": 5, "addressdetails": 1},
        headers={"User-Agent": USER_AGENT}, timeout=HTTP_TIMEOUT,
    )
    response.raise_for_status()
    results = response.json()
    if not results:
        return None
    best = next((r for kind in PLACE_TYPES for r in results
                 if r.get("addresstype") == kind), None)
    if best is None:
        if require_place:
            return None
        best = results[0]
    south, north, west, east = (float(v) for v in best["boundingbox"])
    code = (best.get("address") or {}).get("country_code") or ""
    code = code.upper() if code.upper() in settings_store.country_codes() else None
    return (south, west, north, east), code


def _query(tags: List[str], country: str, boxes: List[tuple]) -> str:
    """One country's question.

    One query per country rather than one for all of them, because the cap is
    per country: `out` applies to a whole result set, so a single query across
    three countries could come back as fifty leads from one of them and none
    from the other two.

    Each clause is intersected with the real border as well as any bounding
    box. A box is a rectangle and a country is not, so a box drawn round a
    border city reaches into its neighbours, and everything caught there would
    be filed under the country we asked for rather than the one it is in.
    """
    code = country.upper()
    area = "c_" + code.lower()
    preamble = 'area["ISO3166-1"="' + code + '"]["admin_level"="2"]->.' + area + ";\n"
    clauses = ""
    for tag in tags:
        key, _, value = tag.partition("=")
        selector = '["' + key.strip() + '"="' + value.strip() + '"]'
        if boxes:
            for box in boxes:
                clauses += ("  nwr" + selector + "(area." + area + ")("
                            + ",".join("%.6f" % v for v in box) + ");\n")
        else:
            # No city named and none on file: the whole country. The cap is
            # what keeps that sane, and it is in the query rather than applied
            # to the answer so the server never does work we throw away.
            clauses += "  nwr" + selector + "(area." + area + ");\n"
    return ("[out:json][timeout:" + str(OVERPASS_TIMEOUT) + "];\n" + preamble
            + "(\n" + clauses + ");\n"
            + "out tags center " + str(config.LEAD_CAP_PER_COUNTRY) + ";\n")


def _curl(url: str, query: str, budget: float) -> Optional[dict]:
    """Ask the mirror again through curl, which has its own TLS.

    The system Python here is linked against LibreSSL 2.8.3, which speaks no
    TLS 1.3, so a host that requires it refuses the handshake and httpx reports
    a connection error. That is indistinguishable from the server being down,
    and it is not: curl on the same machine gets through. Worth the subprocess,
    because without it the main Overpass endpoint is simply unreachable.
    """
    try:
        result = subprocess.run(
            ["curl", "-sS", "--max-time", str(int(budget)),
             "-A", USER_AGENT, "--data-urlencode", "data@-", url],
            input=query.encode("utf-8"), stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, timeout=budget + 5,
        )
    except (OSError, subprocess.SubprocessError) as error:
        print("[leads] curl could not reach " + url + ": " + str(error)[:120])
        return None
    if result.returncode != 0:
        print("[leads] curl exited " + str(result.returncode) + " for " + url
              + ": " + result.stderr.decode("utf-8", "replace")[:120])
        return None
    try:
        return json.loads(result.stdout.decode("utf-8", "replace"))
    except ValueError:
        print("[leads] " + url + " answered curl with something that is not JSON")
        return None


def _ask(url: str, query: str, budget: float) -> Optional[List[dict]]:
    """One mirror, one retry. None means "ask the next mirror"."""
    for attempt in range(2):
        try:
            with httpx.Client(timeout=budget) as client:
                response = client.post(url, data={"data": query},
                                       headers={"User-Agent": USER_AGENT})
        except httpx.HTTPError as error:
            # Only a failure to connect is worth asking curl about. A read
            # timeout means the handshake worked and the server is just slow,
            # and spending the same budget again on a slower client only burns
            # the time the next mirror needed.
            if not isinstance(error, httpx.ConnectError):
                print("[leads] " + url + ": " + type(error).__name__)
                return None
            print("[leads] " + url + " refused the handshake, trying curl")
            payload = _curl(url, query, budget)
            if payload is None:
                return None
            return _elements(payload)
        if response.status_code in (429, 504):
            if attempt == 0:
                time.sleep(2)
                continue
            return None
        if response.status_code >= 400:
            return None
        return _elements(response.json())
    return None


def _elements(payload: dict) -> List[dict]:
    """Read one Overpass answer.

    Overpass answers a query it abandoned with 200 and an empty list. Left
    unread that is indistinguishable from "this city has nothing", so it is
    raised rather than passed to the next mirror: asking somebody else the same
    oversized question gets the same answer.
    """
    remark = (payload.get("remark") or "").lower()
    if "error" in remark:
        raise SearchFailed("The search was too big for OpenStreetMap to run. "
                           "Name fewer cities, or one industry at a time.")
    return payload.get("elements", [])


# When the map has just refused us, every later search would pay the same budget
# to be told the same thing. One failure buys quiet for a quarter of an hour.
MAP_QUIET_FOR = 900
_map_down_until = 0.0


def map_is_down() -> bool:
    return time.time() < _map_down_until


def _overpass(query: str) -> List[dict]:
    global _map_down_until
    if map_is_down():
        raise SearchFailed("The map was unreachable a moment ago, so this search "
                           "did not wait for it again.")
    deadline = time.time() + MAP_BUDGET
    for url in OVERPASS_URLS:
        left = deadline - time.time()
        if left < 5:
            break
        elements = _ask(url, query, min(left, OVERPASS_TIMEOUT))
        if elements is not None:
            return elements
    _map_down_until = time.time() + MAP_QUIET_FOR
    raise SearchFailed("No OpenStreetMap server is answering right now. "
                       "Try again in a minute.")


def _segment_for(name: str, tag_segments: List[str], element: dict) -> str:
    """What this company does, by its name first and its tag second."""
    text = (name or "").lower()
    for segment in SECTOR_WORDS:
        if any(word.strip() in text for word in SECTOR_WORDS[segment]):
            return segment
    tags = element.get("tags", {})
    for segment, wanted in SECTOR_TAGS.items():
        for tag in wanted:
            key, _, value = tag.partition("=")
            if tags.get(key) == value:
                return segment
    return tag_segments[0] if tag_segments else "facility"


def _size_points(field_staff: Optional[int]) -> int:
    """How well the size fits what Sabertask sells.

    This is the part of the score that is about the company rather than about
    how complete its record happens to be. Seats are per person in the field,
    so a bigger crew is a bigger deal, and a size nobody knows yet is treated as
    small rather than as a blank.
    """
    if not field_staff:
        return 5
    if field_staff >= 200:
        return 20
    if field_staff >= 120:
        return 15
    if field_staff >= 60:
        return 10
    return 5


def _score(lead: dict) -> int:
    """How much of a prospect this is before anybody has spoken to them.

    A mailbox and a phone number count separately. They are not the same thing
    to a rep: one can be written to today, the other has to be called.
    """
    score = 10
    if lead["website"]:
        score += 20
    if lead["email"]:
        score += 12
    if lead["phone"]:
        score += 8
    if lead["street"]:
        score += 8
    if lead["matched_name"]:
        score += 12
    if lead["matched_tag"]:
        score += 10
    score += _size_points(lead.get("field_staff"))
    return min(score, 100)


def _clean(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    value = str(value).strip()
    return value[:300] or None


def _plan(criteria: dict) -> List[Tuple[str, List[str]]]:
    """[(country, [city, ...])], where an empty city list means the whole country.

    A city the brief names is placed by the geocoder rather than by us, and a
    country nobody has written seed cities for is searched whole. That is what
    lets a country added from Settings work in the very next search.
    """
    by_country = {}
    order = []

    for city in criteria["cities"]:
        by_country.setdefault(None, [])
        if city not in by_country[None]:
            by_country[None].append(city)
        if None not in order:
            order.append(None)

    if not order:
        for code in criteria["countries"]:
            order.append(code)
            by_country[code] = list(SEED_CITIES.get(code, []))[:MAX_CITIES]

    return [(code, by_country[code]) for code in order]


def search(brief: str) -> Tuple[dict, List[dict]]:
    """(criteria, leads). Raises SearchFailed with something a rep can act on."""
    criteria = criteria_from_brief(brief)
    tags = tags_for(criteria["segments"])
    plan = _plan(criteria)
    if not plan:
        raise SearchFailed("Nothing to search. Name an industry and a city or "
                           "a country in the brief.", criteria)

    if map_is_down():
        criteria["searched"] = [c for _code, cities in plan for c in cities]
        criteria["areas"] = []
        raise SearchFailed("The map was unreachable a moment ago, so this search "
                           "did not wait for it again.", criteria)

    # Resolve every named city to a box and, crucially, to the country the map
    # says it is in. A box around Zurich filed under Belgium matches nothing,
    # and an empty answer reads exactly like a city with no companies in it.
    live = set(settings_store.country_codes())
    boxes_by_country = {}
    searched = []
    for code, cities in plan:
        if code is not None and not cities:
            boxes_by_country.setdefault(code, [])
            searched.append(settings_store.country_label(code, code))
            continue
        for city in cities:
            place = city + (", " + settings_store.country_label(code) if code else "")
            try:
                found = _bbox(place)
            except httpx.HTTPError:
                found = None
            if found is None and code is None:
                for guess in live:
                    try:
                        found = _bbox(city + ", " + settings_store.country_label(guess),
                                      require_place=True)
                    except httpx.HTTPError:
                        found = None
                    time.sleep(1)   # one Nominatim call a second, guesses too
                    if found is not None:
                        code = guess
                        break
            if found is None:
                continue
            box, resolved = found
            where = resolved or code
            if where is None:
                continue
            boxes_by_country.setdefault(where, []).append(box)
            searched.append(city)
            time.sleep(1)   # Nominatim asks for no more than one call a second

    criteria["searched"] = searched
    criteria["tags"] = tags
    criteria["countries_searched"] = sorted(boxes_by_country)
    criteria["cap_per_country"] = config.LEAD_CAP_PER_COUNTRY
    if not boxes_by_country:
        raise SearchFailed("None of those places could be found on the map.", criteria)

    # One query per country, and the budget is spent in the order they were
    # asked for: a country that is never reached is reported rather than
    # silently returning nothing.
    deadline = time.time() + MAP_BUDGET
    elements_by_country = {}
    skipped = []
    failure = None
    for code in sorted(boxes_by_country):
        if time.time() > deadline:
            skipped.append(code)
            continue
        try:
            elements_by_country[code] = _overpass(_query(tags, code, boxes_by_country[code]))
        except SearchFailed as error:
            failure = error
            skipped.append(code)
    criteria["skipped_countries"] = skipped
    if not elements_by_country:
        if failure is not None:
            failure.criteria = criteria
            raise failure
        raise SearchFailed("No OpenStreetMap server is answering right now.", criteria)

    leads = []
    for code, elements in elements_by_country.items():
        kept = 0
        for element in elements:
            if kept >= config.LEAD_CAP_PER_COUNTRY:
                break       # a mirror that ignored the cap does not get to
            tags_on = element.get("tags", {})
            name = _clean(tags_on.get("name"))
            if not name:
                continue
            city = _clean(tags_on.get("addr:city"))
            country = (tags_on.get("addr:country") or "").upper()
            if country not in live:
                # The query was bounded by this country's own border, so the
                # country is known even when the record does not carry it.
                country = code
            street = _clean(tags_on.get("addr:street"))
            if street and tags_on.get("addr:housenumber"):
                street = street + " " + str(tags_on["addr:housenumber"])[:12]

            segment = _segment_for(name, criteria["segments"], element)
            matched_name = any(word.strip() in name.lower()
                               for word in SECTOR_WORDS.get(segment, []))
            matched_tag = any(
                tags_on.get(tag.partition("=")[0]) == tag.partition("=")[2]
                for tag in SECTOR_TAGS.get(segment, [])
            )
            lead = {
                "osm_id": str(element.get("type", "")) + "/" + str(element.get("id", "")),
                "name": name,
                "segment": segment,
                "country": country,
                "city": city,
                "street": street,
                "website": _clean(tags_on.get("website") or tags_on.get("contact:website")),
                "phone": _clean(tags_on.get("phone") or tags_on.get("contact:phone")),
                "email": _clean(tags_on.get("email") or tags_on.get("contact:email")),
                "matched_name": matched_name,
                "matched_tag": matched_tag,
            }
            lead["score"] = _score(lead)
            leads.append(lead)
            kept += 1

    leads.sort(key=lambda row: -row["score"])
    return criteria, leads
