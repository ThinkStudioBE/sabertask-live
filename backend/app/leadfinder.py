"""Find leads: a plain-English brief turned into real companies.

Two sources, and the country decides which. Where the country publishes an
official business register that can be searched by activity, that is the
source, because every company is in it by law and these industries are the ones
the map misses: in Antwerp the register holds 256 cleaning companies and the
map holds 13. `registers.py` has the per-country detail and the list of markets
that have no usable register, which fall through to the map below.

The map is the fallback and is free and keyless. Nominatim resolves each city
to a box, Overpass returns every business inside it that carries one of the
tags we are after, and OpenStreetMap already holds the name, address, website
and phone. A run costs nothing but time, which matters for a tool a sales floor
is meant to use daily rather than once.

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

Everything that comes back is a real company, off an official register or off
the public map. There is no stand-in data in this module and there must never
be: this build is the one pointed at real prospects, and a fictional row here
is one nobody downstream can tell from a found one.
"""

import json
import os
import re
import subprocess
import time
from typing import Dict, List, Optional, Tuple

import httpx

from . import config, registers, settings_store

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
        # Ordered by what actually answers. The French instance is first
        # because it is the one that has been reliable from here and from the
        # host: the main endpoint hands back an error page as often as a
        # result, and the rest queue.
        "https://overpass.openstreetmap.fr/api/interpreter,"
        "https://overpass-api.de/api/interpreter,"
        "https://overpass.kumi.systems/api/interpreter,"
        "https://overpass.private.coffee/api/interpreter,"
        "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    ).split(",") if url.strip()
]
# OSM asks automated clients to identify themselves. A product name, never a
# person's address.
USER_AGENT = "SabertaskSales/1.0 (+https://www.sabertask.com)"
# Overpass is free and queues: a busy endpoint accepts the connection and then
# says nothing until a slot frees. Fifteen seconds is a demo's patience and it
# throws away answers that were on their way, so this build waits properly.
OVERPASS_TIMEOUT = 30
# How long the whole map phase may take before the search gives up. Generous,
# because there is nothing to fall back on here: an empty list is the honest
# answer and a slow one beats a wrong one. It has to cover every mirror in the
# list being unreachable in turn, or the one that would have answered is never
# reached.
# Kept under the edge timeout in front of the service, which cuts a request off
# at about a hundred seconds and hands back an empty body. A search that runs
# over that shows the rep nothing at all, so the budget stops first and the
# countries it did not reach are reported by name instead.
MAP_BUDGET = 70
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

# Words distinctive enough to find a company by its name alone. Drawn from
# SECTOR_WORDS, minus the ones that would drag in half a city: "park" catches
# every parking garage, "service" catches everything, "salt" and "city" are
# words before they are industries.
TOO_BROAD = {"park", "green", "salt", "city", "stad", "service", "net", "public"}


def name_pattern(segment):
    """A regex for finding a company by its name rather than by its tag.

    Kept, and deliberately not used in the query. The idea is sound: a sector
    whose tag nobody fills in is invisible, and the name is the thing those
    companies do have. The measurement killed it.

    Antwerp, through the fastest mirror: the tag-only query answers in 7
    seconds. Adding a name clause, even paired with `["office"]` so it only
    reads businesses and even with the word list cut to four, takes **80**. The
    cost is the scan itself, not the size of the regex. Behind a proxy that cuts
    a request off at a hundred seconds, that is not a slower search, it is an
    empty screen.

    What it brought back does not pay for that either: two genuine cleaning
    companies the tags had missed, and for facility management a page of estate
    agents, because "vastgoed" is what they call themselves too.

    The honest fix for a thin sector is a different source, a business register
    rather than a map. Left here so nobody spends the evening rediscovering it.
    """
    words = sorted({w.strip().lower() for w in SECTOR_WORDS.get(segment, [])
                    if len(w.strip()) >= 4 and w.strip() not in TOO_BROAD})
    return "|".join(words)

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


def _query(tags: List[str], country: str, cities: List[str],
           boxes: Optional[List[tuple]] = None,
           segments: Optional[List[str]] = None) -> str:
    """One country's question.

    One query per country rather than one for all of them, because the cap is
    per country: `out` applies to a whole result set, so a single query across
    three countries could come back as fifty leads from one of them and none
    from the other two.

    Cities are resolved inside the query, by name, within the country's own
    boundary. That is better than handing in a bounding box from a geocoder in
    two ways. It needs no second service, which matters because the geocoder
    rate-limits and refuses datacentre addresses outright, and it uses the
    city's real outline: a box drawn round a border city reaches into the
    neighbouring country, and everything caught there would be filed under the
    country we asked for rather than the one it is in.
    """
    code = country.upper()
    area = "c_" + code.lower()
    lines = ['area["ISO3166-1"="' + code + '"]["admin_level"="2"]->.' + area + ";"]

    scopes = []
    for index, city in enumerate(cities or []):
        name = city.replace('"', "")
        scope = "a_" + str(index)
        # admin_level 6 to 10 covers city, municipality, borough and district
        # across the markets this runs in, which do not agree on a number.
        lines.append('rel(area.' + area + ')["name"="' + name + '"]'
                     '["admin_level"~"^(6|7|8|9|10)$"];')
        lines.append("map_to_area->." + scope + ";")
        scopes.append(scope)

    # Two ways in. The tags are precise and thin; the names are broad and
    # exactly where the companies a sector tag never got are hiding.
    selectors = []
    for tag in tags:
        key, _, value = tag.partition("=")
        selectors.append('["' + key.strip() + '"="' + value.strip() + '"]')
    # Searching on the name as well was tried and measured, and it is off: see
    # name_pattern for what it costs and what it brings back.

    clauses = ""
    for selector in selectors:
        if scopes:
            for scope in scopes:
                clauses += "  nwr" + selector + "(area." + scope + ");\n"
        elif boxes:
            for box in boxes:
                clauses += ("  nwr" + selector + "(area." + area + ")("
                            + ",".join("%.6f" % v for v in box) + ");\n")
        else:
            # No city named: the whole country. The cap is what keeps that sane,
            # and it is in the query rather than applied to the answer so the
            # server never does work we throw away.
            clauses += "  nwr" + selector + "(area." + area + ");\n"

    return ("[out:json][timeout:" + str(OVERPASS_TIMEOUT) + "];\n"
            + "\n".join(lines) + "\n"
            + "(\n" + clauses + ");\n"
            + "out tags center " + str(config.LEAD_CAP_PER_COUNTRY) + ";\n")


# Why each mirror did not answer, for the run in progress. An operator looking
# at a failed search should not have to read a server log to find out whether
# the map refused us, queued us or was never reachable at all.
_reasons = []


def _note(url: str, reason: str) -> None:
    host = url.split("//")[-1].split("/")[0]
    _reasons.append(host + ": " + reason)
    print("[leads] " + host + ": " + reason)


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
        _note(url, "curl could not reach it: " + str(error)[:90])
        return None
    if result.returncode != 0:
        _note(url, "curl exited " + str(result.returncode) + ": "
              + result.stderr.decode("utf-8", "replace").strip()[:90])
        return None
    try:
        return json.loads(result.stdout.decode("utf-8", "replace"))
    except ValueError:
        _note(url, "answered curl with something that is not JSON")
        return None


def _ask(url: str, query: str, budget: float) -> Optional[List[dict]]:
    """One mirror, one retry. None means "ask the next mirror"."""
    for attempt in range(2):
        try:
            with httpx.Client(timeout=budget, follow_redirects=True) as client:
                response = client.post(url, data={"data": query},
                                       headers={"User-Agent": USER_AGENT})
        except httpx.HTTPError as error:
            # Only a failure to connect is worth asking curl about. A read
            # timeout means the handshake worked and the server is just slow,
            # and spending the same budget again on a slower client only burns
            # the time the next mirror needed.
            if not isinstance(error, httpx.ConnectError):
                _note(url, type(error).__name__)
                return None
            _note(url, "refused the handshake, retrying through curl")
            payload = _curl(url, query, budget)
            if payload is None:
                return None
            return _elements(payload)
        if response.status_code in (429, 504):
            if attempt == 0:
                time.sleep(2)
                continue
            _note(url, "too busy (HTTP " + str(response.status_code) + ")")
            return None
        if response.status_code >= 400:
            _note(url, "HTTP " + str(response.status_code))
            return None
        try:
            payload = response.json()
        except ValueError:
            # A mirror that is unwell answers with an HTML error page. Reading
            # that as "no results" is the mistake this module exists to avoid.
            _note(url, "answered with something that is not JSON")
            return None
        return _elements(payload)
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
    del _reasons[:]
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
                       + ("Tried " + "; ".join(_reasons) + "." if _reasons else ""))


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

    The bands run past a thousand because the Norwegian register publishes
    employee counts and the real ones go that high: ISS has ten thousand people
    in Oslo alone. Stopping at two hundred put that company in the same bucket
    as a firm fifty times smaller, which is the one comparison this number
    exists to make.
    """
    if not field_staff:
        return 5
    if field_staff >= 1000:
        return 30
    if field_staff >= 500:
        return 26
    if field_staff >= 200:
        return 22
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


def _plan(criteria: dict) -> List[Tuple[Optional[str], List[str]]]:
    """[(country, [city, ...])], where an empty city list means the whole country
    and a country of None means the brief named a city without one.

    When the brief gives both, each named city is paired with each named
    country: the query resolves the name inside that country's own boundary and
    comes back empty where it does not exist, so a wrong pairing costs nothing
    and a right one needs no geocoder.
    """
    cities = criteria["cities"]
    countries = criteria["countries"]

    if cities and countries:
        return [(code, list(cities)) for code in countries]
    if cities:
        return [(None, list(cities))]
    return [(code, list(SEED_CITIES.get(code, []))[:MAX_CITIES]) for code in countries]


def search(brief: str) -> Tuple[dict, List[dict]]:
    """(criteria, leads). Raises SearchFailed with something a rep can act on."""
    criteria = criteria_from_brief(brief)
    tags = tags_for(criteria["segments"])
    plan = _plan(criteria)
    if not plan:
        raise SearchFailed("Nothing to search. Name an industry and a city or "
                           "a country in the brief.", criteria)

    live = set(settings_store.country_codes())

    # Group the plan by country. A city whose country the brief did not give is
    # placed by the geocoder; if that refuses us, the city is tried inside every
    # country in the set, which both sources can do by name on their own.
    cities_by_country = {}
    floating = []
    for code, cities in plan:
        if code is None:
            floating.extend(cities)
        else:
            cities_by_country.setdefault(code, []).extend(cities)

    for city in floating:
        placed = None
        try:
            found = _bbox(city)
        except httpx.HTTPError as error:
            _note(NOMINATIM_URL, type(error).__name__)
            found = None
        if found is not None:
            _box, placed = found
            time.sleep(1)   # Nominatim asks for no more than one call a second
        if placed and placed in live:
            cities_by_country.setdefault(placed, []).append(city)
        else:
            # Nobody told us and nothing would, so ask every market. Each query
            # resolves the name inside that country and comes back empty where
            # the city does not exist, which is the answer we wanted anyway.
            for code in sorted(live):
                cities_by_country.setdefault(code, []).append(city)

    criteria["searched"] = sorted({c for cities in cities_by_country.values()
                                   for c in cities}) or [
        settings_store.country_label(code) for code in cities_by_country]
    criteria["tags"] = tags
    criteria["countries_searched"] = sorted(cities_by_country)
    criteria["cap_per_country"] = config.LEAD_CAP_PER_COUNTRY
    if not cities_by_country:
        raise SearchFailed("Nothing to search. Name an industry and a city or "
                           "a country in the brief.", criteria)

    cap = config.LEAD_CAP_PER_COUNTRY
    leads = []
    sources = {}
    skipped = []
    failure = None

    # The register first, where the country has one. It is both better and
    # faster: one indexed lookup against an official list instead of a scan of
    # a volunteer map, and it holds the companies that never had a shopfront to
    # map. A country whose register cannot be reached is not reported empty, it
    # is handed to the map below.
    on_the_map = []
    for code in sorted(cities_by_country):
        if not registers.has_register(code):
            on_the_map.append(code)
            continue
        try:
            rows = registers.search(code, criteria["segments"],
                                    cities_by_country[code], cap)
        except registers.RegisterFailed as error:
            print("[leads] " + code + " register unavailable, falling back to "
                  "the map: " + str(error)[:160])
            _note(registers.register_for(code) or code, str(error)[:80])
            on_the_map.append(code)
            continue
        sources[code] = registers.register_for(code)
        for row in rows[:cap]:
            leads.append(_from_register(row))

    # Then the map, for everything else, on a budget. The budget is the proxy
    # in front of this app cutting a request off at a hundred seconds: a country
    # that is never reached is reported rather than silently returning nothing.
    if on_the_map:
        if map_is_down():
            skipped.extend(on_the_map)
            failure = SearchFailed(
                "The map was unreachable a moment ago, so this search did not "
                "wait for it again.", criteria)
        else:
            deadline = time.time() + MAP_BUDGET
            for code in on_the_map:
                if time.time() > deadline:
                    skipped.append(code)
                    continue
                try:
                    elements = _overpass(
                        _query(tags, code, cities_by_country[code],
                               segments=criteria["segments"]))
                except SearchFailed as error:
                    failure = error
                    skipped.append(code)
                    continue
                sources[code] = "map"
                kept = 0
                for element in elements:
                    if kept >= cap:
                        break   # a mirror that ignored the cap does not get to
                    lead = _from_element(element, code, criteria, live)
                    if lead is None:
                        continue
                    leads.append(lead)
                    kept += 1

    criteria["skipped_countries"] = skipped
    criteria["sources"] = sources
    if not sources:
        if failure is not None:
            failure.criteria = criteria
            raise failure
        raise SearchFailed("No source answered for any of these countries.",
                           criteria)

    # Score first, then crew size. Two companies can score the same and not be
    # the same prospect at all: seats are per person in the field, so where the
    # size is known it breaks the tie, and where it is not the lead keeps its
    # place rather than dropping below everything that happens to have a number.
    leads.sort(key=lambda row: (-row["score"], -(row.get("field_staff") or 0)))
    return criteria, leads


def _from_register(row: dict) -> dict:
    """A register row as a lead.

    `matched_tag` is true by definition here: the company is filed under this
    activity by the authority it files with, which is a stronger statement than
    a tag somebody typed on a map.

    `matched_name` is deliberately false, which is not the same as saying the
    name does not match. That signal exists for the map, where the name is the
    only clue about what a business does. Here the activity is already known
    from the register, so scoring the name again rewards a coincidence: ISS has
    ten thousand people in Oslo and Coor sixteen hundred, and the only reason
    Coor outranked them was the word "cleaning" sitting in its company name.
    """
    name = _clean(row.get("name")) or ""
    segment = row.get("segment") or "facility"
    lead = {
        "osm_id": row["source_id"],
        "name": name,
        "segment": segment,
        "country": row.get("country"),
        "city": _clean(row.get("city")),
        "street": _clean(row.get("street")),
        "website": _clean(row.get("website")),
        "phone": _clean(row.get("phone")),
        "email": _clean(row.get("email")),
        "field_staff": row.get("field_staff"),
        "matched_name": False,
        "matched_tag": True,
    }
    lead["score"] = _score(lead)
    return lead


def _from_element(element: dict, code: str, criteria: dict,
                  live: set) -> Optional[dict]:
    """One Overpass element as a lead, or None when it is not usable."""
    tags_on = element.get("tags", {})
    name = _clean(tags_on.get("name"))
    if not name:
        return None
    country = (tags_on.get("addr:country") or "").upper()
    if country not in live:
        # The query was bounded by this country's own border, so the country is
        # known even when the record does not carry it.
        country = code
    street = _clean(tags_on.get("addr:street"))
    if street and tags_on.get("addr:housenumber"):
        street = street + " " + str(tags_on["addr:housenumber"])[:12]

    segment = _segment_for(name, criteria["segments"], element)
    lead = {
        "osm_id": str(element.get("type", "")) + "/" + str(element.get("id", "")),
        "name": name,
        "segment": segment,
        "country": country,
        "city": _clean(tags_on.get("addr:city")),
        "street": street,
        "website": _clean(tags_on.get("website") or tags_on.get("contact:website")),
        "phone": _clean(tags_on.get("phone") or tags_on.get("contact:phone")),
        "email": _clean(tags_on.get("email") or tags_on.get("contact:email")),
        "field_staff": None,
        "matched_name": any(word.strip() in name.lower()
                            for word in SECTOR_WORDS.get(segment, [])),
        "matched_tag": any(
            tags_on.get(tag.partition("=")[0]) == tag.partition("=")[2]
            for tag in SECTOR_TAGS.get(segment, [])
        ),
    }
    lead["score"] = _score(lead)
    return lead
