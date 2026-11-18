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
                   "hallways, on weekly, biweekly and monthly rounds.",
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
                   "the service agreements for all of it.",
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
IMPORT_FIELDS = [
    {"key": "company_name", "label": "Company name", "aliases": ["company", "organisation", "organization", "name", "bedrijf", "virksomhed"], "required": True},
    {"key": "website", "label": "Website", "aliases": ["url", "site", "domain"]},
    {"key": "country", "label": "Country", "aliases": ["land", "country code"]},
    {"key": "city", "label": "City", "aliases": ["town", "stad", "by"]},
    {"key": "segment", "label": "Segment", "aliases": ["industry", "sector", "branche"]},
    {"key": "field_staff", "label": "Field staff", "aliases": ["employees", "staff", "headcount", "workers"]},
    {"key": "contact_name", "label": "Contact name", "aliases": ["contact", "person", "full name"]},
    {"key": "contact_role", "label": "Contact role", "aliases": ["role", "title", "job title", "function"]},
    {"key": "contact_email", "label": "Contact email", "aliases": ["email", "e-mail", "mail"]},
    {"key": "contact_phone", "label": "Contact phone", "aliases": ["phone", "telephone", "tel", "mobile"]},
    {"key": "notes", "label": "Notes", "aliases": ["note", "comment", "remarks"]},
]
EXPORT_HEADERS = [
    "Email Address", "First Name", "Last Name", "Company", "Country", "City",
    "Segment", "Stage", "Owner", "Tags",
]
