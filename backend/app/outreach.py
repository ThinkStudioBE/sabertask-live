"""Cold mail drafting.

A rep opens a prospect and gets a first mail that already knows who it is
talking to: the industry, the crew size, the number of sites and the tool they
run today are all in the record, so none of that should have to be retyped.

Two drafters live here. The template one is always available and costs nothing;
it reads from the same facts a rep would use. The Claude one writes the mail
properly and is used when a key is configured. Both go through `draft_for`,
which falls back rather than failing: a screen that shows an error where the
mail should be is worse than one that shows a slightly plainer mail.
"""

import os
import re
from typing import Optional, Tuple

from . import config, settings_store

# What the mail leans on per industry: the one thing that sector loses sleep
# over, written the way a rep would say it rather than as a feature.
INDUSTRY_ANGLE = {
    "cleaning": (
        "For cleaning that usually shows up as the same argument every month: the "
        "client says a site was skipped, and nobody can prove otherwise."
    ),
    "window": (
        "For window cleaning it is the route: who did which facade, in what order, "
        "and what the invoice can actually stand behind."
    ),
    "landscaping": (
        "In green maintenance it is the rounds: which plots were done this week, "
        "what the crew found there, and what the client sees of it."
    ),
    "facility": (
        "In facility management it is the contract: work orders spread over "
        "buildings, and an SLA you can only report on after the fact."
    ),
    "winter": (
        "In winter services it is proof: a salt run logged on paper arrives days "
        "later, and that is exactly the paperwork you get held to."
    ),
    "municipal": (
        "For a public service it is the file: every district works slightly "
        "differently, and the audit trail has to hold up long after the job."
    ),
}

SUBJECTS = [
    "{company}: proof of the work, not the paperwork",
    "{field_staff} people, {sites} sites, one app",
    "A question about how {company} plans its week",
]
# The one that needs numbers is only usable when we have them.
SUBJECTS_NO_NUMBERS = [s for s in SUBJECTS if "{field_staff}" not in s]


def _greeting(contact_name: Optional[str]) -> str:
    """A role title is not a person, so it never gets a first name."""
    if not contact_name:
        return "there"
    name = contact_name.strip()
    if not name:
        return "there"
    # "Manager Wegendistricten" is a role, "Anne Mikkelsen" is a person. Two
    # capitalised words with no lowercase function word is the usable signal we
    # have; when in doubt the whole string is used, which always reads correctly.
    lowered = name.lower()
    # A placeholder is not a person and must never be greeted as one.
    if any(word in lowered for word in ("contact", "team", "office", "info")):
        return "there"
    first = name.split()[0]
    if first.lower() in ("manager", "director", "head", "ict-projectleider", "ict"):
        return name
    return first


def facts_for(company, deal, contact, rep) -> dict:
    """Everything either drafter is allowed to use. Nothing is invented here."""
    seats = (deal.worker_seats or 0) + (deal.planner_seats or 0) + (deal.admin_seats or 0)
    return {
        "company": company.name,
        "city": company.city or "",
        "country": settings_store.country_label(company.country or "", company.country or ""),
        "segment": company.segment,
        "segment_label": config.SEGMENT_LABEL.get(company.segment, company.segment),
        "field_staff": company.field_staff or 0,
        "sites": company.sites or 0,
        # Left empty rather than guessed. A first mail that tells a company what
        # it runs today, wrongly, is worse than one that does not mention it.
        "current_tool": company.current_tool or None,
        "contact_name": contact.name if contact else None,
        "greeting": _greeting(contact.name if contact else None),
        "seats": seats,
        "trial_days": config.TRIAL_DAYS,
        "rep_name": rep.name if rep else "Sabertask",
        "rep_title": rep.title if rep else "Sales",
        "angle": INDUSTRY_ANGLE.get(company.segment, ""),
    }


# ------------------------------------------------------------- the template ---

def template_draft(facts: dict) -> Tuple[str, str]:
    pool = SUBJECTS if (facts["field_staff"] and facts["sites"]) else SUBJECTS_NO_NUMBERS
    subject = pool[(facts["field_staff"] + len(facts["company"])) % len(pool)]
    subject = subject.format(
        company=facts["company"], field_staff=facts["field_staff"], sites=facts["sites"],
    )

    size = ""
    if facts["field_staff"] and facts["sites"]:
        size = ("You have about " + str(facts["field_staff"]) + " people out on "
                + str(facts["sites"]) + " sites every week, ")
    elif facts["field_staff"]:
        size = "You have about " + str(facts["field_staff"]) + " people in the field, "

    body = (
        "Hi " + facts["greeting"] + ",\n\n"
        + (size + "and from here the planning runs on " + facts["current_tool"]
           + ". That usually means the office hears what happened the day after "
             "it happened.\n\n"
           if facts["current_tool"] else
           size.rstrip(", ") + (" and the office" if size else "The office")
           + " usually hears what happened the day after it happened.\n\n")
        + (facts["angle"] + "\n\n" if facts["angle"] else "")
        + "Sabertask puts the job in the hands of the crew: clock in and out with "
        "GPS, the day's task list on the phone, photos of the work as it is done. "
        "The office sees it live and invoices from the same data, so nothing is "
        "re-keyed on a Friday afternoon.\n\n"
        "Teams your size usually start on one branch, around " + str(facts["seats"])
        + " users, with a " + str(facts["trial_days"]) + "-day trial on the full "
        "product. Worth twenty minutes?\n\n"
        + facts["rep_name"] + "\n" + facts["rep_title"] + " | " + config.BRAND
    )
    return subject, body


# ---------------------------------------------------------------- via Claude ---

SYSTEM = (
    "You write first-contact sales emails for Sabertask, which sells field "
    "service management software to companies whose people work on sites rather "
    "than at desks: cleaning, window cleaning, landscaping, facility management, "
    "winter services and public works.\n\n"
    "Sabertask is a mobile app for the crew (clock in and out with GPS, the day's "
    "tasks, photo documentation) and a web dashboard for the office (planning, "
    "shifts, quality reports, invoicing from the same data). It is sold per user "
    "per month on three role tiers and starts with a 30-day trial of everything.\n\n"
    "Rules. Write to one named reader, in English, under 160 words. Use the "
    "reader's name exactly as you are given it, with no Mr, Ms or any title you "
    "would have to guess at. Open with "
    "something true about their operation from the facts you are given, never "
    "with a compliment or a question about their day. Name the one thing their "
    "sector loses time or money on, then what changes. No bullet lists, no bold, "
    "no exclamation marks, no 'I hope this finds you well', no 'revolutionise', "
    "no 'solution'. Ask for twenty minutes, not for a yes. Invent nothing: if a "
    "number is not in the facts, leave it out.\n\n"
    "Answer with the subject on the first line as 'Subject: ...', then a blank "
    "line, then the mail, ending with the sender's name and title."
)


def _complain(reason: str) -> None:
    """Failures belong in the server log, not on the screen. A rep looking at a
    prospect should never be reading about our plumbing."""
    print("[mail] falling back to the plain drafter: " + reason)


def claude_draft(facts: dict) -> Optional[Tuple[str, str]]:
    """Returns None on any failure, so the caller can fall back quietly."""
    if not config.MAIL_AI_ENABLED:
        return None
    key = os.getenv("ANTHROPIC_API_KEY")
    if not key:
        _complain("no ANTHROPIC_API_KEY set")
        return None
    try:
        import anthropic
    except ImportError:
        _complain("the anthropic package is not installed")
        return None

    lines = [
        "Company: " + facts["company"],
        "Industry: " + facts["segment_label"],
        "Where: " + (facts["city"] + ", " if facts["city"] else "") + facts["country"],
        "People in the field: " + str(facts["field_staff"]),
        "Sites served: " + str(facts["sites"]),
        "What they run today: " + (facts["current_tool"] or "not known, do not guess"),
        "Writing to: " + (facts["contact_name"] or "no named contact, address the role"),
        "Seats we would start with: " + str(facts["seats"]),
        "Sender: " + facts["rep_name"] + ", " + facts["rep_title"],
    ]
    try:
        client = anthropic.Anthropic(api_key=key)
        response = client.messages.create(
            model=config.MAIL_MODEL,
            # The mail is short, but the model thinks before it writes and that
            # thinking comes out of the same budget. Too small a ceiling does not
            # produce a shorter mail, it produces a mail that stops mid-sentence.
            max_tokens=8000,
            # The mail is short but it is the first thing a prospect reads,
            # so this is not the place to economise on thinking.
            output_config={"effort": "medium"},
            system=SYSTEM,
            messages=[{"role": "user", "content": "\n".join(lines)}],
        )
        stop = getattr(response, "stop_reason", None)
        if stop == "refusal":
            _complain("the request was declined")
            return None
        if stop == "max_tokens":
            # Half a mail is worse than a plain one: it would sit there looking
            # finished and go out mid-sentence.
            _complain("the answer ran into the token ceiling")
            return None
        text = "".join(
            block.text for block in response.content
            if getattr(block, "type", "") == "text"
        ).strip()
    except Exception as error:
        _complain(type(error).__name__ + ": " + str(error)[:200])
        return None

    if not text:
        _complain("an empty answer came back")
        return None
    match = re.match(r"\s*subject\s*:\s*(.+?)\n(.*)", text, re.IGNORECASE | re.DOTALL)
    if not match:
        _complain("the answer had no subject line")
        return None
    subject = match.group(1).strip()
    body = match.group(2).strip()
    if not subject or not body:
        return None
    return subject, body


def draft_for(company, deal, contact, rep) -> Tuple[str, str, str]:
    """(subject, body, who wrote it). Claude when it can, the template otherwise."""
    facts = facts_for(company, deal, contact, rep)
    written = claude_draft(facts)
    if written is not None:
        return written[0], written[1], "claude"
    subject, body = template_draft(facts)
    return subject, body, "template"
