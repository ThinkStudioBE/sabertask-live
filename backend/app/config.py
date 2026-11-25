"""Static configuration for Sabertask Sales.

Everything the UI labels, prices or colours comes from this file, so the app
can be retuned without touching the API or the frontend.

This is the live build: it runs on real companies found with the lead search
and ships with no prospects of its own. Its twin, the sales demo, is the one
filled with invented data; nothing here should ever grow a fictional record.
"""

import os
from pathlib import Path

APP_NAME = "Sabertask Sales"
BRAND = "Sabertask"
TAGLINE = "Smart field service management for service businesses"

BASE_DIR = Path(__file__).resolve().parent.parent          # backend/
PROJECT_DIR = BASE_DIR.parent                              # sabertask-live/
FRONTEND_DIR = PROJECT_DIR / "frontend" / "static"

# Everything this app learns lives here: the database and the editable settings.
# On a host with a mounted disk, point DATA_DIR at it. The prospects in here are
# real companies somebody went looking for, so losing them to a restart is data
# loss rather than a reset.
DATA_DIR = Path(os.getenv("DATA_DIR", str(BASE_DIR)))
DB_PATH = Path(os.getenv("DB_PATH", str(DATA_DIR / "sabertask-live.db")))

SESSION_COOKIE = "sabertask_live_session"
SESSION_SECRET = os.getenv("SESSION_SECRET", "sabertask-live-secret-change-me")
SESSION_MAX_AGE = 60 * 60 * 24 * 30  # 30 days
SESSION_SECURE = os.getenv("SESSION_SECURE", "false").strip().lower() not in {
    "0", "false", "no", "off",
}

APP_PASSWORD = os.getenv("SABERTASK_PASSWORD", "Sabertask2026!")

# ----------------------------------------------------------------- currency ---
# Sabertask's own market signals are Danish, so the pipeline is kept in kroner.
# Every amount is stored in this one currency and converted only for display.
# Flipping a reporting currency must never rewrite what is in the database:
# two people on the same pipeline read it in different money, and the numbers
# underneath stay the same.
BASE_CURRENCY = "DKK"

# Fixed for the trial, on purpose. A live FX feed would make yesterday's report
# unreproducible and add a dependency that can fail in front of a customer. The
# date is shown in the app so nobody reads these as today's rates.
FX_DATE = "2026-11-14"
CURRENCIES = [
    {"key": "DKK", "symbol": "kr", "label": "Danish kroner", "per_base": 1.0},
    {"key": "EUR", "symbol": "EUR", "label": "Euro", "per_base": 0.134},
    {"key": "USD", "symbol": "USD", "label": "US dollars", "per_base": 0.145},
]
CURRENCY_BY_KEY = {c["key"]: c for c in CURRENCIES}
CURRENCY = BASE_CURRENCY          # what the seats below are priced in
CURRENCY_SYMBOL = "kr"


def money(amount, currency=None):
    """1234567 -> '1.234.567 kr'. Converts from the base currency on the way."""
    spec = CURRENCY_BY_KEY.get(currency or BASE_CURRENCY, CURRENCY_BY_KEY[BASE_CURRENCY])
    whole = int(round((amount or 0) * spec["per_base"]))
    text = "{:,}".format(whole).replace(",", ".")
    return text + " " + spec["symbol"]


# ------------------------------------------------------------------- seats ---
# Sabertask prices per user per month, in four tiers (their pricing page, four
# cards, all billed "/ user / month"). A deal therefore carries a seat count per
# tier rather than one number, and MRR is their sum. Rates live on the deal as
# well as here, so a rep can discount without the catalogue moving.
# Enterprise is the exception the catalogue cannot hold: the page prints
# "Custom" where the others print a price, so its rate is 0 here and the rep
# types the negotiated one on the deal. Until they do, the deal's MRR is short
# by those seats, and `rate_missing` on the deal says so out loud rather than
# letting the forecast quietly read low.
SEAT_TIERS = [
    {
        "key": "worker",
        "label": "Worker",
        "audience": "Field staff",
        "rate": 69.0,
        "includes": "Mobile app, clock in/out with GPS, daily task list, photo documentation",
    },
    {
        "key": "planner",
        "label": "Worker with planning",
        "audience": "Team leaders / supervisors",
        "rate": 139.0,
        "includes": "Everything in Worker, plus task assignment, planning calendar, quality reporting",
    },
    {
        "key": "admin",
        "label": "Admin",
        "audience": "Office / management",
        "rate": 279.0,
        "includes": "Everything above, plus the web dashboard, employee and shift management, invoicing and billing",
    },
    {
        "key": "enterprise",
        "label": "Enterprise",
        "audience": "Large organisations with complex integrations",
        "rate": 0.0,
        "custom": True,
        "includes": "Everything in Admin, plus custom integrations (NAV, ServiceNow, other enterprise systems) and advanced reporting and configuration",
    },
]
SEAT_RATE = {tier["key"]: tier["rate"] for tier in SEAT_TIERS}
SEAT_LABEL = {tier["key"]: tier["label"] for tier in SEAT_TIERS}
SEAT_KEYS = [tier["key"] for tier in SEAT_TIERS]
# Tiers whose price is negotiated per deal, not taken from the catalogue.
SEAT_CUSTOM = [tier["key"] for tier in SEAT_TIERS if tier.get("custom")]

# The plan is no longer something a rep picks: Enterprise is a seat tier now, so
# a deal is an Enterprise deal exactly when it has Enterprise seats on it. Kept
# as a stored field because a sent quote must keep the wording it was sent with.
PLANS = [
    {"key": "standard", "label": "Standard"},
    {"key": "enterprise", "label": "Enterprise", "note": "Custom integrations and reporting"},
]
PLAN_LABEL = {plan["key"]: plan["label"] for plan in PLANS}

TRIAL_DAYS = 30  # Sabertask gives 30 days of full access

# ------------------------------------------------------------------ stages ---
# Outbound-first funnel shaped around how a field service platform is actually
# bought: a demo, then scoping of the service agreements, then the free trial,
# then paper.
STAGES = [
    {"key": "lead", "label": "Lead", "probability": 5,
     "hint": "Sourced, not contacted"},
    {"key": "contacted", "label": "Contacted", "probability": 10,
     "hint": "Written to, nothing back"},
    # Between the mail and the meeting there is a gap that used to be invisible.
    # Somebody opens the mail, clicks through to sabertask.com, reads the page
    # for their industry, maybe opens the booking form, and then does not book.
    # Filed under Contacted that person looks identical to someone who never
    # reacted at all, and they are not: they are the warmest thing in the
    # pipeline short of a booked demo, and the window to call them is short.
    #
    # It is a stage rather than a flag because the question it answers is "how
    # many of the people we interested did we fail to convert", and a funnel is
    # the only thing that answers that. The drop from Engaged to Demo booked is
    # the number worth watching: a bad one means the mail is doing its job and
    # the follow-up is not.
    {"key": "engaged", "label": "Engaged", "probability": 15,
     "hint": "Visited the site or started booking, no demo yet"},
    {"key": "demo", "label": "Demo booked", "probability": 25,
     "hint": "Meeting in the diary"},
    {"key": "scoping", "label": "Scoping", "probability": 40,
     "hint": "Demo done, working out the fit"},
    {"key": "trial", "label": "Trial", "probability": 60,
     "hint": "30-day trial running"},
    {"key": "proposal", "label": "Proposal", "probability": 80,
     "hint": "Seats and price on the table"},
    {"key": "won", "label": "Won", "probability": 100,
     "hint": "Signed, rolling out"},
]
EXTRA_STAGES = [
    {"key": "lost", "label": "Lost", "probability": 0, "hint": "Closed out"},
    {"key": "nurture", "label": "Nurture", "probability": 5,
     "hint": "Parked, revisit later"},
]
ALL_STAGES = STAGES + EXTRA_STAGES
STAGE_LABEL = {s["key"]: s["label"] for s in ALL_STAGES}
STAGE_PROBABILITY = {s["key"]: s["probability"] for s in ALL_STAGES}
OPEN_STAGES = [s["key"] for s in STAGES if s["key"] != "won"] + ["nurture"]
BOARD_STAGES = [s["key"] for s in STAGES]

# The step a deal arrives with when it lands in a stage, and how long the rep has
# before it goes red. One table so the whole app agrees on what "chased" means.
STAGE_NEXT_STEP = {
    "lead": {"step": "Send the intro mail", "days": None},
    "contacted": {"step": "Follow-up call", "days": 3},
    # Two days, not three. Somebody who has just been on the site is warm now
    # and cold by the end of the week, and the whole point of noticing the
    # visit is to ring while they still remember making it.
    "engaged": {"step": "Call while the visit is fresh", "days": 2},
    "demo": {"step": "Run the demo", "days": 5},
    "scoping": {"step": "Send the scoping summary", "days": 3},
    "trial": {"step": "Check in on trial usage", "days": 7},
    "proposal": {"step": "Chase the proposal", "days": 4},
    "won": {"step": "Plan the rollout kick-off", "days": 5},
    "lost": {"step": "Log why we lost", "days": 1},
    "nurture": {"step": None, "days": None},
}
STANDARD_STEPS = {v["step"] for v in STAGE_NEXT_STEP.values() if v["step"]}
STAGE_HINT = {s["key"]: s.get("hint", "") for s in ALL_STAGES}

# Nobody at these stages has shown us anything yet. Named here rather than
# written out wherever it is needed, because the day a stage is added the
# question "has this prospect reacted to us" has to move with it, and a set of
# keys typed into a report is exactly the thing that does not move.
PRE_ENGAGEMENT_STAGES = ("lead", "contacted")

# ---------------------------------------------------------------- segments ---
# The industries Sabertask names on its own site. These are not a cosmetic tag:
# the sales floor is split by industry, one rep per set of industries, so a
# lead's segment is what decides whose desk it lands on. Every list, card and
# board in the app therefore shows the segment in its own colour, and the
# segment filter is the first control in the filter bar.
#
# The first five are sabertask.com's own "Target industries", one page each, and
# `profile` and `pain` are read off those pages rather than invented here. They
# are not decoration: `profile` is what a rep is actually looking for when they
# search, and `pain` is the first line of the conversation that follows. Both
# are shown in the app beside the industry.
#
# `municipal` is ours and not theirs. There is no industry page for it. It is
# here because the home page says Sabertask supports "businesses and
# municipalities", the facility page advertises OIOXML and calls itself
# public-sector ready, and a town that runs this work with its own crews buys
# the same seats as a contractor. Anyone pruning this list should know that the
# other five can be checked against the site and this one cannot.
SEGMENTS = [
    {
        "key": "cleaning", "label": "Cleaning companies", "short": "Cleaning",
        "color": "#4f7aa0",
        "profile": "Contract cleaners working recurring service agreements: "
                   "stairway washes, office cleaning, deep cleans, lobbies and "
                   "hallways, on weekly, biweekly and monthly rounds. In North "
                   "America the same company trades as janitorial, commercial "
                   "cleaning, housekeeping or facility services, and the ones "
                   "Sabertask names as ideal clients run 12 to 45 people.",
        "pain": "Schedules rebuilt in Excel every week, photos in WhatsApp, "
                "timesheets on paper, and clients ringing to ask whether anyone "
                "actually showed up.",
    },
    {
        "key": "window", "label": "Window cleaning", "short": "Window",
        "color": "#4e8a84",
        "profile": "Window cleaners running recurring rounds, from a team of "
                   "two to over two hundred. The work is route-driven: many "
                   "small stops a day, every four weeks per address.",
        "pain": "Too much driving on badly ordered routes, forgotten "
                "appointments, invoicing by hand on Friday afternoons, and no "
                "proof the round was done.",
    },
    {
        "key": "landscaping", "label": "Landscaping & green maintenance",
        "short": "Landscaping", "color": "#5d8a5a",
        "profile": "Landscape contractors with crews on seasonal contracts: "
                   "lawn maintenance through the growing season, hedge work, "
                   "mulching, spring and autumn clean-ups, for housing "
                   "associations, office parks and estates.",
        "pain": "Crews criss-crossing town in the wrong order, weather wiping "
                "out the week's plan, callbacks that never get billed, and job "
                "costs that only surface weeks after the job.",
    },
    {
        "key": "facility", "label": "Facility management", "short": "Facility",
        "color": "#7d6c9c",
        "profile": "Facility and property managers running portfolios of "
                   "dozens to hundreds of buildings, who buy and coordinate "
                   "cleaning, window and garden work per building and carry "
                   "the service agreements for all of it. This is the buyer, "
                   "not the contractor: a firm trading as Facility Services "
                   "with its own cleaners on the payroll is a cleaning "
                   "company and belongs on the cleaning desk.",
        "pain": "Service agreements scattered across spreadsheets, maintenance "
                "lost in email threads, no proof of what was done at which "
                "building, and tenants and owners chasing for updates.",
    },
    {
        "key": "winter", "label": "Winter services", "short": "Winter",
        "color": "#7b818c",
        "profile": "Snow removal, salting, gritting and de-icing contractors "
                   "dispatching trucks on weather triggers. Sabertask sells "
                   "them a module of its own, SnowManager, and says it already "
                   "has over five hundred of them.",
        "pain": "Calls flooding in at four in the morning, routes built by "
                "hand at three, customers ringing for an ETA, and disputes "
                "afterwards about whether the site was cleared at all.",
    },
    {
        "key": "municipal", "label": "Municipal & public services",
        "short": "Municipal", "color": "#a9864e",
        "profile": "Towns, municipalities and public bodies that run this work "
                   "with their own crews and vehicles rather than buying it in.",
        "pain": "The same work as a contractor's, under procurement rules and "
                "with residents rather than clients asking where the crew is.",
    },
]
SEGMENT_PROFILE = {s["key"]: s.get("profile", "") for s in SEGMENTS}
SEGMENT_PAIN = {s["key"]: s.get("pain", "") for s in SEGMENTS}
SEGMENT_LABEL = {s["key"]: s["label"] for s in SEGMENTS}
SEGMENT_SHORT = {s["key"]: s["short"] for s in SEGMENTS}
SEGMENT_COLOR = {s["key"]: s["color"] for s in SEGMENTS}
SEGMENT_KEYS = [s["key"] for s in SEGMENTS]

# ----------------------------------------------------------- ideal clients ---
# Sabertask handed over twelve of its ideal clients on 2026-11-24: Pro
# Housekeepers, GBC Facility Services, Hero Facility Services, Cristal Clear
# Cleaning, Office Pride Pensacola, Total Facility Solutions, ProFi Facility
# Maintenance, General Facility Care, WeClean Commercial Cleaning, Clean Slate
# Janitorial, American Cleaning Services and Service Keepers Maintenance.
#
# What the twelve have in common is the profile this tool is supposed to be
# hunting, so it is written down here rather than left in a mailbox:
#
#   - All twelve are contract cleaners or building-services contractors.
#     Eleven are filed under SIC 7349, building cleaning and maintenance; the
#     twelfth under 1542, nonresidential construction, and it cleans too.
#   - All twelve have between 12 and 45 people. Not one is a giant and not one
#     is a two-man outfit, which is why `leadfinder._size_points` scores that
#     band highest instead of rewarding headcount without end.
#   - Seven of the twelve call themselves "facility" something while doing
#     janitorial work. In North America that is a cleaner's word, not a
#     property manager's, so `leadfinder.SECTOR_WORDS` reads those phrases as
#     cleaning and the cleaning desk gets them.
#   - All twelve are in Florida: Miami, Tampa, Orlando, Jacksonville, Fort
#     Lauderdale, Melbourne, Pensacola, Coconut Creek. Hence the US seed
#     cities in `leadfinder.SEED_CITIES`.
#
# The band is the observed one and nothing is rounded up to make it look
# tidier. Anybody widening it should be looking at a new list, not at a hunch.
IDEAL_CLIENT = {
    "staff_min": 12,
    "staff_max": 45,
    "segments": ["cleaning", "facility"],
    "source": "twelve of Sabertask's own customers, Florida, given 2026-11-24",
    "note": "12 to 45 people in the field, contract cleaning or building "
            "services, whatever the name on the van says. Seven of the twelve "
            "trade as \"facility\" something and still do janitorial work.",
    # These twelve are CUSTOMERS, not prospects. Sabertask handed them over as
    # the shape to look for, which is why they are written down here rather than
    # loaded into the pipeline: a customer sitting in the mail queue is one
    # misclick away from being sold the product they already pay for. They were
    # in the pipeline once, on 2026-11-24, and were taken out again on
    # 2026-11-25 before anything was sent.
    "examples": [
        ("Pro Housekeepers", "Tampa", 27),
        ("GBC Facility Services", "Miami", 25),
        ("Hero Facility Services", "Melbourne", 45),
        ("Cristal Clear Cleaning", "Jacksonville", 21),
        ("Office Pride Commercial Cleaning of Pensacola", "Pensacola", 21),
        ("Total Facility Solutions", "Miami", 13),
        ("ProFi Construction & Maintenance", "Fort Lauderdale", 34),
        ("General Facility Care", "Tampa", 13),
        ("WeClean Commercial Cleaning", "Coconut Creek", 13),
        ("Clean Slate Janitorial Services", "Orlando", 12),
        ("American Cleaning Services", "Orlando", 40),
        ("Service Keepers Maintenance", "Miami", 32),
    ],
}

def flag_for(code):
    """The flag emoji for any ISO 3166-1 alpha-2 code, computed rather than
    looked up. A table would be one more place to edit when a country is added
    from the Settings screen, and the whole point of that screen is that adding
    one takes no code."""
    code = (code or "").strip().upper()
    if len(code) != 2 or not code.isalpha():
        return ""
    return "".join(chr(0x1F1E6 + ord(letter) - ord("A")) for letter in code)


# Where the trial starts looking. This is only the default: the set is editable
# at runtime from Settings and `settings_store` is what every consumer reads, so
# a country added there works in the search immediately and without a restart.
# Nothing in the search path may hard-code this list.
COUNTRIES = [
    {"key": code, "label": label, "flag": flag_for(code)}
    for code, label in [
        ("BE", "Belgium"),
        ("NL", "Netherlands"),
        ("US", "United States"),
        ("CA", "Canada"),
        ("DK", "Denmark"),
        ("NO", "Norway"),
        ("SE", "Sweden"),
        ("FI", "Finland"),
    ]
]
COUNTRY_LABEL = {c["key"]: c["label"] for c in COUNTRIES}
COUNTRY_FLAG = {c["key"]: c["flag"] for c in COUNTRIES}

SIZE_BANDS = [
    {"key": "small", "label": "Under 25 field staff"},
    {"key": "mid", "label": "25-100 field staff"},
    {"key": "large", "label": "100-500 field staff"},
    {"key": "xl", "label": "500+ field staff"},
]
SIZE_LABEL = {s["key"]: s["label"] for s in SIZE_BANDS}

# ---------------------------------------------------------------- channels ---
CHANNELS = [
    {"key": "demo_request", "label": "Demo request"},
    {"key": "outbound_mail", "label": "Outbound mail"},
    {"key": "cold_call", "label": "Cold call"},
    {"key": "linkedin", "label": "LinkedIn"},
    {"key": "referral", "label": "Referral"},
    {"key": "trade_fair", "label": "Trade fair"},
    {"key": "tender", "label": "Public tender"},
]
CHANNEL_LABEL = {c["key"]: c["label"] for c in CHANNELS}

NOTE_KINDS = [
    {"key": "note", "label": "Note"},
    {"key": "call", "label": "Call"},
    {"key": "email", "label": "Email"},
    {"key": "meeting", "label": "Meeting"},
    {"key": "demo", "label": "Demo"},
    {"key": "proposal", "label": "Proposal"},
]
NOTE_KIND_LABEL = {n["key"]: n["label"] for n in NOTE_KINDS}
# A note is just a note; everything else counts as a real touch on the account.
TOUCH_KINDS = {"call", "email", "meeting", "demo", "proposal"}

TASK_KINDS = [
    {"key": "todo", "label": "To do"},
    {"key": "call", "label": "Call"},
    {"key": "email", "label": "Email"},
    {"key": "meeting", "label": "Meeting"},
    {"key": "demo", "label": "Demo"},
    {"key": "onboarding", "label": "Onboarding"},
]
TASK_KIND_LABEL = {t["key"]: t["label"] for t in TASK_KINDS}

PRIORITIES = [
    {"key": "high", "label": "High"},
    {"key": "normal", "label": "Normal"},
    {"key": "low", "label": "Low"},
]
PRIORITY_WEIGHT = {"high": 0, "normal": 1, "low": 2}

LOST_REASONS = [
    {"key": "price", "label": "Too expensive"},
    {"key": "competitor", "label": "Went to a competitor"},
    {"key": "in_house", "label": "Building it in house"},
    {"key": "no_budget", "label": "No budget this year"},
    {"key": "no_decision", "label": "No decision made"},
    {"key": "integration", "label": "Missing integration"},
    {"key": "procurement", "label": "Lost the tender"},
    {"key": "adoption", "label": "Field staff would not adopt it"},
]
LOST_REASON_LABEL = {r["key"]: r["label"] for r in LOST_REASONS}

HEALTH_STATES = [
    {"key": "green", "label": "Healthy", "color": "#5d8a5a"},
    {"key": "watch", "label": "Watch", "color": "#a9864e"},
    {"key": "risk", "label": "At risk", "color": "#ab5f58"},
]
HEALTH_LABEL = {h["key"]: h["label"] for h in HEALTH_STATES}
HEALTH_COLOR = {h["key"]: h["color"] for h in HEALTH_STATES}

# ------------------------------------------------------------------ quotes ---
# ------------------------------------------------------------------- mail ---
# Cold mail is drafted here and sent by hand. Nothing in this app talks to a
# mail server. Every address in here belongs to a real company, so sending is
# a person's job: the app drafts, somebody reads it and sends it themselves.
#
# The mails are written by Claude. A key is all it takes, so the only switch is
# one to turn it off (MAIL_AI=0) if a deployment must not call out. Without a
# key there is a plain drafter as a last resort, so the screen is never broken,
# but that is a fallback and not the product.
MAIL_AI_ENABLED = os.getenv("MAIL_AI", "1").lower() not in ("0", "false", "no")
MAIL_MODEL = os.getenv("MAIL_MODEL", "claude-opus-5-5")
# Which stages are still worth a first mail.
MAIL_STAGES = ["lead", "contacted", "nurture"]

# ------------------------------------------------------------------ leads ---
# The ceiling on one search, per country, counted over every industry in that
# search together. Three countries in one brief can therefore return 150 leads
# and the total grows with the set, which is the user's own decision: there is
# deliberately no overall ceiling on top of it.
#
# A ceiling rather than a default. The map is a free service run by volunteers,
# and a run that can pull thousands of records is both a bad neighbour and a
# review list nobody will ever work through. Deliberately not an env var and
# not a setting, so it cannot be raised from the dashboard or by a deployment.
# Enforced in the Overpass query, one query per country so the limit binds per
# country, and again as a clamp in the endpoint in case a mirror ignores it.
#
# The screens present this as a limit of the trial, because that is what it is
# to whoever is being sold the product (frontend: leadCapNote). Worth knowing
# before anybody promises an uncapped version: raising this number alone does
# not deliver one. The free map is both the reason for the ceiling and the
# reason there is little above it, so an uncapped search needs a source that is
# paid for per record: a prospecting export, a places API, or a register where
# the country has one.
LEAD_CAP_PER_COUNTRY = 50

QUOTE_PREFIX = "ST"
QUOTE_VALID_DAYS = 30

SABERTASK_PROFILE = {
    "name": "Sabertask",
    "legal_name": "Sabertask Lda.",
    "address": "Avenida da Liberdade 110, 1269-046 Lisboa, Portugal",
    "email": "hello@sabertask.com",
    "website": "www.sabertask.com",
    "vat": "PT 515 482 991",
}

QUOTE_DEFAULT_INTRO = (
    "Thank you for the time your team gave us. Below is the subscription we "
    "discussed, priced per user per month on the role tiers your people actually "
    "need. Onboarding, data import and training are included in the figure shown."
)
QUOTE_DEFAULT_TERMS = (
    "Prices are per user per month, excluding VAT, billed monthly in arrears. "
    "The subscription runs for the term shown and renews for the same term unless "
    "cancelled 30 days before it ends. Seats can be added at any time and are "
    "charged pro rata; seats can be reduced at the end of a term. All data is "
    "hosted in the EU and remains the customer's property."
)

# ------------------------------------------------------------- CSV mapping ---
IMPORT_MAX_ROWS = 5000
# The columns the importer reads. `reject` is for a header that would match an
# alias and mean something else: a prospecting export carries "Company Linkedin
# Url" next to "Website", and "url" would otherwise make the LinkedIn page the
# company's website on any file that has no Website column at all.
IMPORT_FIELDS = [
    {"key": "company_name", "label": "Company name", "aliases": ["company", "organisation", "organization", "name", "bedrijf", "virksomhed"], "required": True},
    {"key": "website", "label": "Website", "aliases": ["url", "site", "domain"], "reject": ["linkedin", "facebook", "twitter", "instagram"]},
    {"key": "country", "label": "Country", "aliases": ["land", "country code"]},
    {"key": "city", "label": "City", "aliases": ["town", "stad", "by"]},
    {"key": "address", "label": "Address", "aliases": ["company address", "street", "adres", "adresse"]},
    {"key": "state", "label": "State or province", "aliases": ["company state", "province", "region", "county"]},
    {"key": "segment", "label": "Segment", "aliases": ["industry", "sector", "branche"]},
    {"key": "sic", "label": "SIC code", "aliases": ["sic code", "sic codes", "naics", "activity code"]},
    {"key": "revenue", "label": "Annual revenue", "aliases": ["revenue", "turnover", "omzet"]},
    {"key": "field_staff", "label": "Field staff", "aliases": ["employees", "staff", "headcount", "workers"]},
    {"key": "contact_name", "label": "Contact name", "aliases": ["contact", "person", "full name"]},
    {"key": "contact_role", "label": "Contact role", "aliases": ["role", "title", "job title", "function"]},
    {"key": "contact_email", "label": "Contact email", "aliases": ["email", "e-mail", "mail"]},
    {"key": "contact_phone", "label": "Contact phone", "aliases": ["phone", "telephone", "tel", "mobile"]},
    {"key": "notes", "label": "Notes", "aliases": ["note", "comment", "remarks"]},
]
# A country as a prospecting export writes it. The live set is editable from
# Settings and its own labels are read first, so this is only for the spellings
# that do not match a label: "USA" for United States, the local name for a
# country whose label is in English.
COUNTRY_ALIASES = {
    "united states": "US", "united states of america": "US", "usa": "US",
    "u.s.": "US", "u.s.a.": "US", "united kingdom": "GB", "uk": "GB",
    "canada": "CA", "belgium": "BE", "belgie": "BE", "belgi\u00eb": "BE",
    "belgique": "BE", "netherlands": "NL", "the netherlands": "NL",
    "nederland": "NL", "holland": "NL", "denmark": "DK", "danmark": "DK",
    "norway": "NO", "norge": "NO", "sweden": "SE", "sverige": "SE",
    "finland": "FI", "suomi": "FI", "germany": "DE", "deutschland": "DE",
    "france": "FR", "ireland": "IE", "spain": "ES", "italy": "IT",
}

# States and provinces, so a one-line address can be read without a column
# saying which part is which. "6902 E Adamo Dr, Tampa, Florida, United States,
# 33619" is four things and a postcode, and the city is the part this app
# wants. Only the two markets that write an address that way are listed.
STATE_NAMES = {
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado",
    "connecticut", "delaware", "district of columbia", "florida", "georgia",
    "hawaii", "idaho", "illinois", "indiana", "iowa", "kansas", "kentucky",
    "louisiana", "maine", "maryland", "massachusetts", "michigan", "minnesota",
    "mississippi", "missouri", "montana", "nebraska", "nevada",
    "new hampshire", "new jersey", "new mexico", "new york", "north carolina",
    "north dakota", "ohio", "oklahoma", "oregon", "pennsylvania",
    "rhode island", "south carolina", "south dakota", "tennessee", "texas",
    "utah", "vermont", "virginia", "washington", "west virginia", "wisconsin",
    "wyoming", "puerto rico",
    "alberta", "british columbia", "manitoba", "new brunswick",
    "newfoundland and labrador", "nova scotia", "ontario",
    "prince edward island", "quebec", "qu\u00e9bec", "saskatchewan",
}

# The US activity code these exports carry, where it means one of our
# industries. Only codes that are unambiguous are here: 7349 is building
# cleaning and maintenance, which is eleven of the twelve ideal clients, and
# 1542 (nonresidential construction) is deliberately absent because a builder
# is not a cleaner even when it cleans. Anything not listed falls through to
# the industry the importer was given, so a wrong desk is never guessed.
SIC_SEGMENT = {
    "7349": "cleaning",      # building cleaning and maintenance services, nec
    "7217": "cleaning",      # carpet and upholstery cleaning
    "0782": "landscaping",   # lawn and garden services
    "0783": "landscaping",   # ornamental shrub and tree services
    "6512": "facility",      # operators of nonresidential buildings
    "6513": "facility",      # operators of apartment buildings
    "6531": "facility",      # real estate agents and managers
}
# SIC division J, 91 through 97, is public administration whole and entire.
SIC_PUBLIC_PREFIXES = ("91", "92", "93", "94", "95", "96", "97")

EXPORT_HEADERS = [
    "Email Address", "First Name", "Last Name", "Company", "Country", "City",
    "Segment", "Stage", "Owner", "Tags",
]
