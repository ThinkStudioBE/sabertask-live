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

BUNDLED_DB = BASE_DIR / "sabertask-live.db"
DB_PATH = Path(os.getenv("DB_PATH", str(BUNDLED_DB)))

SESSION_COOKIE = "sabertask_live_session"
SESSION_SECRET = os.getenv("SESSION_SECRET", "sabertask-live-secret-change-me")
SESSION_MAX_AGE = 60 * 60 * 24 * 30  # 30 days
SESSION_SECURE = os.getenv("SESSION_SECURE", "false").strip().lower() not in {
    "0", "false", "no", "off",
}

APP_PASSWORD = os.getenv("SABERTASK_PASSWORD", "Sabertask2026!")

# ----------------------------------------------------------------- currency ---
# Sabertask's own market signals are Danish, so the pipeline is kept in kroner.
CURRENCY = "DKK"
CURRENCY_SYMBOL = "kr"


def money(amount):
    """1234567 -> '1.234.567 kr' (Danish thousands separator)."""
    whole = int(round(amount or 0))
    text = "{:,}".format(whole).replace(",", ".")
    return text + " " + CURRENCY_SYMBOL


# ------------------------------------------------------------------- seats ---
# Sabertask prices per user per month, in three role tiers. A deal therefore
# carries three seat counts rather than one, and MRR is their sum. Rates live on
# the deal as well as here, so a rep can discount without the catalogue moving.
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
]
SEAT_RATE = {tier["key"]: tier["rate"] for tier in SEAT_TIERS}
SEAT_LABEL = {tier["key"]: tier["label"] for tier in SEAT_TIERS}
SEAT_KEYS = [tier["key"] for tier in SEAT_TIERS]

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
    {"key": "lead", "label": "Lead", "probability": 5},
    {"key": "contacted", "label": "Contacted", "probability": 10},
    {"key": "demo", "label": "Demo booked", "probability": 25},
    {"key": "scoping", "label": "Scoping", "probability": 40},
    {"key": "trial", "label": "Trial", "probability": 60},
    {"key": "proposal", "label": "Proposal", "probability": 80},
    {"key": "won", "label": "Won", "probability": 100},
]
EXTRA_STAGES = [
    {"key": "lost", "label": "Lost", "probability": 0},
    {"key": "nurture", "label": "Nurture", "probability": 5},
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
    "demo": {"step": "Run the demo", "days": 5},
    "scoping": {"step": "Send the scoping summary", "days": 3},
    "trial": {"step": "Check in on trial usage", "days": 7},
    "proposal": {"step": "Chase the proposal", "days": 4},
    "won": {"step": "Plan the rollout kick-off", "days": 5},
    "lost": {"step": "Log why we lost", "days": 1},
    "nurture": {"step": None, "days": None},
}
STANDARD_STEPS = {v["step"] for v in STAGE_NEXT_STEP.values() if v["step"]}

# ---------------------------------------------------------------- segments ---
# The industries Sabertask names on its own site. These are not a cosmetic tag:
# the sales floor is split by industry, one rep per set of industries, so a
# lead's segment is what decides whose desk it lands on. Every list, card and
# board in the app therefore shows the segment in its own colour, and the
# segment filter is the first control in the filter bar.
SEGMENTS = [
    {"key": "cleaning", "label": "Cleaning companies", "short": "Cleaning", "color": "#4f7aa0"},
    {"key": "window", "label": "Window cleaning", "short": "Window", "color": "#4e8a84"},
    {"key": "landscaping", "label": "Landscaping & green maintenance", "short": "Landscaping", "color": "#5d8a5a"},
    {"key": "facility", "label": "Facility management", "short": "Facility", "color": "#7d6c9c"},
    {"key": "winter", "label": "Winter services", "short": "Winter", "color": "#7b818c"},
    {"key": "municipal", "label": "Municipal & public services", "short": "Municipal", "color": "#a9864e"},
]
SEGMENT_LABEL = {s["key"]: s["label"] for s in SEGMENTS}
SEGMENT_SHORT = {s["key"]: s["short"] for s in SEGMENTS}
SEGMENT_COLOR = {s["key"]: s["color"] for s in SEGMENTS}
SEGMENT_KEYS = [s["key"] for s in SEGMENTS]

COUNTRIES = [
    {"key": "BE", "label": "Belgium", "flag": "\U0001F1E7\U0001F1EA"},
    {"key": "NL", "label": "Netherlands", "flag": "\U0001F1F3\U0001F1F1"},
    {"key": "LU", "label": "Luxembourg", "flag": "\U0001F1F1\U0001F1FA"},
    {"key": "DK", "label": "Denmark", "flag": "\U0001F1E9\U0001F1F0"},
    {"key": "SE", "label": "Sweden", "flag": "\U0001F1F8\U0001F1EA"},
    {"key": "NO", "label": "Norway", "flag": "\U0001F1F3\U0001F1F4"},
    {"key": "CH", "label": "Switzerland", "flag": "\U0001F1E8\U0001F1ED"},
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
# The hard ceiling on one search, and a ceiling rather than a default: this is
# a trial, the map is a free service run by volunteers, and a run that can pull
# thousands of records is both a bad neighbour and a review list nobody will
# ever work through. Deliberately not an env var and not a setting, so it
# cannot be raised from the dashboard or from a deployment by accident. It is
# clamped in the search endpoint and again in the Overpass query, because the
# point is not to fetch ten thousand rows and throw all but a hundred away.
LEAD_HARD_CAP = 100

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
