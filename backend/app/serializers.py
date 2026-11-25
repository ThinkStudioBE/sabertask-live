"""The shared value model, and the dicts the API hands the frontend.

One rule holds the whole app together: a deal's value is recurring. Seats on
each role tier times that tier's rate is MRR; everything else is derived from
it, so no screen can quote a different number than another.
"""

from datetime import date, datetime
from typing import Optional

from . import config, settings_store
from .models import Client, Company, Contact, Deal, Meeting, Note, Quote, Task, User


# ---------------------------------------------------------------- the money ---

def seat_pairs(holder):
    """[(tier key, seats, rate)] off a deal or a quote, in catalogue order.

    Driven by config.SEAT_KEYS rather than written out, so a new tier on their
    price list needs a column and nothing else.
    """
    return [
        (key,
         getattr(holder, key + "_seats", 0) or 0,
         getattr(holder, key + "_rate", 0.0) or 0.0)
        for key in config.SEAT_KEYS
    ]


def seat_lines(deal: Deal):
    """One line per tier actually bought, with its own MRR.

    A custom-priced tier with no rate yet is still listed: it carries the seats
    somebody promised, and hiding it would hide why the MRR looks low.
    """
    return [
        {
            "key": key,
            "label": config.SEAT_LABEL[key],
            "seats": seats,
            "rate": rate,
            "mrr": seats * rate,
            "custom": key in config.SEAT_CUSTOM,
            "rate_missing": key in config.SEAT_CUSTOM and rate <= 0,
        }
        for key, seats, rate in seat_pairs(deal)
        if seats > 0
    ]


def total_seats(deal: Deal) -> int:
    return sum(seats for _, seats, _ in seat_pairs(deal))


def deal_mrr(deal: Deal) -> float:
    return sum(seats * rate for _, seats, rate in seat_pairs(deal))


def rate_missing(deal: Deal) -> bool:
    """True when a negotiated tier has seats but no price, so MRR reads short."""
    return any(
        key in config.SEAT_CUSTOM and seats > 0 and rate <= 0
        for key, seats, rate in seat_pairs(deal)
    )


def plan_for(deal: Deal) -> str:
    """A deal is an Enterprise deal exactly when it has Enterprise seats."""
    return "enterprise" if (getattr(deal, "enterprise_seats", 0) or 0) > 0 else "standard"


def deal_acv(deal: Deal) -> float:
    """What the first contract term is worth in total, onboarding included."""
    return deal_mrr(deal) * (deal.contract_months or 12) + (deal.onboarding_fee or 0.0)


def deal_probability(deal: Deal) -> int:
    if deal.probability is not None:
        return deal.probability
    return config.STAGE_PROBABILITY.get(deal.stage, 0)


def deal_weighted(deal: Deal) -> float:
    return deal_mrr(deal) * deal_probability(deal) / 100.0


def days_since(moment) -> Optional[int]:
    if moment is None:
        return None
    if isinstance(moment, datetime):
        moment = moment.date()
    return (date.today() - moment).days


# ------------------------------------------------------------------- shapes ---

def user_dict(user: Optional[User]):
    if user is None:
        return None
    return {
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "title": user.title,
        "role": user.role,
        "initials": user.initials or "".join(p[0] for p in user.name.split()[:2]).upper(),
        "color": user.color,
        "segments": [s.strip() for s in (user.segments or "").split(",") if s.strip()],
        "segment_labels": [
            config.SEGMENT_SHORT.get(s.strip(), s.strip())
            for s in (user.segments or "").split(",") if s.strip()
        ],
    }


def company_dict(company: Company, owner: Optional[User] = None, extra=None):
    out = {
        "id": company.id,
        "name": company.name,
        "website": company.website,
        "segment": company.segment,
        "segment_label": config.SEGMENT_LABEL.get(company.segment or "", ""),
        "segment_short": config.SEGMENT_SHORT.get(company.segment or "", ""),
        "segment_color": config.SEGMENT_COLOR.get(company.segment or "", "#94a3b8"),
        "country": company.country,
        "country_label": settings_store.country_label(company.country or ""),
        "flag": settings_store.country_flag(company.country or ""),
        "city": company.city,
        "size_band": company.size_band,
        "size_label": config.SIZE_LABEL.get(company.size_band or "", ""),
        "field_staff": company.field_staff,
        "sites": company.sites,
        "language": company.language,
        "source_channel": company.source_channel,
        "source_label": config.CHANNEL_LABEL.get(company.source_channel or "", ""),
        "current_tool": company.current_tool,
        "notes": company.notes,
        "owner": user_dict(owner),
    }
    if extra:
        out.update(extra)
    return out


def contact_dict(contact: Contact):
    return {
        "id": contact.id,
        "company_id": contact.company_id,
        "name": contact.name,
        "role_title": contact.role_title,
        "email": contact.email,
        "phone": contact.phone,
        "is_primary": contact.is_primary,
        "notes": contact.notes,
    }


def deal_dict(deal: Deal, company: Optional[Company] = None,
              owner: Optional[User] = None, contact: Optional[Contact] = None,
              extra=None):
    mrr = deal_mrr(deal)
    out = {
        "id": deal.id,
        "title": deal.title,
        "company_id": deal.company_id,
        "company": company.name if company else None,
        "country": company.country if company else None,
        "flag": settings_store.country_flag((company.country if company else "") or ""),
        "city": company.city if company else None,
        # The drawer is where a rep judges a prospect, so the site has to be
        # one click away there too, not only on the lead that became it.
        "website": company.website if company else None,
        # Their CRM's id for this deal, so the drawer can offer a way
        # straight into HubSpot instead of asking a rep to search for it.
        "hubspot_id": deal.hubspot_id,
        "segment": company.segment if company else None,
        "segment_label": config.SEGMENT_LABEL.get((company.segment if company else "") or "", ""),
        "segment_short": config.SEGMENT_SHORT.get((company.segment if company else "") or "", ""),
        "segment_color": config.SEGMENT_COLOR.get((company.segment if company else "") or "", "#94a3b8"),
        "field_staff": company.field_staff if company else None,
        "plan": deal.plan,
        "plan_label": config.PLAN_LABEL.get(deal.plan, deal.plan),
        "seat_lines": seat_lines(deal),
        "worker_seats": deal.worker_seats,
        "planner_seats": deal.planner_seats,
        "admin_seats": deal.admin_seats,
        "enterprise_seats": deal.enterprise_seats,
        "worker_rate": deal.worker_rate,
        "planner_rate": deal.planner_rate,
        "admin_rate": deal.admin_rate,
        "enterprise_rate": deal.enterprise_rate,
        "rate_missing": rate_missing(deal),
        "seats": total_seats(deal),
        "contract_months": deal.contract_months,
        "onboarding_fee": deal.onboarding_fee,
        "mrr": mrr,
        "arr": mrr * 12,
        "acv": deal_acv(deal),
        "probability": deal_probability(deal),
        "weighted": deal_weighted(deal),
        "stage": deal.stage,
        "stage_label": config.STAGE_LABEL.get(deal.stage, deal.stage),
        "channel": deal.channel,
        "channel_label": config.CHANNEL_LABEL.get(deal.channel, deal.channel),
        "owner": user_dict(owner),
        "contact": contact_dict(contact) if contact else None,
        "next_action": deal.next_action,
        "next_action_date": deal.next_action_date.isoformat() if deal.next_action_date else None,
        "touch_count": deal.touch_count,
        "last_touch_at": deal.last_touch_at.isoformat() if deal.last_touch_at else None,
        "days_since_touch": days_since(deal.last_touch_at),
        "days_in_stage": days_since(deal.stage_changed_at),
        "trial_started_on": deal.trial_started_on.isoformat() if deal.trial_started_on else None,
        "trial_day": (
            (date.today() - deal.trial_started_on).days
            if deal.stage == "trial" and deal.trial_started_on else None
        ),
        "expected_close_date": deal.expected_close_date.isoformat() if deal.expected_close_date else None,
        "lost_reason": deal.lost_reason,
        "lost_reason_label": config.LOST_REASON_LABEL.get(deal.lost_reason or "", ""),
        "lost_reason_note": deal.lost_reason_note,
        "notes": deal.notes,
        "created_at": deal.created_at.isoformat(),
        "stage_changed_at": deal.stage_changed_at.isoformat(),
        "won_at": deal.won_at.isoformat() if deal.won_at else None,
    }
    if extra:
        out.update(extra)
    return out


def note_dict(note: Note, author: Optional[User] = None):
    return {
        "id": note.id,
        "deal_id": note.deal_id,
        "kind": note.kind,
        "kind_label": config.NOTE_KIND_LABEL.get(note.kind, note.kind),
        "body": note.body,
        "author": user_dict(author),
        "created_at": note.created_at.isoformat(),
    }


def task_dict(task: Task, owner: Optional[User] = None, deal: Optional[Deal] = None,
              company: Optional[Company] = None):
    due = task.due_date
    return {
        "id": "task-" + str(task.id),
        "raw_id": task.id,
        "source": "task",
        "title": task.title,
        "kind": task.kind,
        "kind_label": config.TASK_KIND_LABEL.get(task.kind, task.kind),
        "priority": task.priority,
        "due_date": due.isoformat() if due else None,
        "overdue_days": (date.today() - due).days if due else 0,
        "owner": user_dict(owner),
        "deal_id": task.deal_id,
        "company_id": task.company_id,
        "client_id": task.client_id,
        "company": company.name if company else None,
        "segment": company.segment if company else None,
        "segment_short": config.SEGMENT_SHORT.get((company.segment if company else "") or "", ""),
        "segment_color": config.SEGMENT_COLOR.get((company.segment if company else "") or "", "#94a3b8"),
        "mrr": deal_mrr(deal) if deal else 0.0,
        "stage": deal.stage if deal else None,
        "stage_label": config.STAGE_LABEL.get(deal.stage, "") if deal else None,
        "notes": task.notes,
        "done": task.done,
    }


def quote_dict(quote: Quote):
    return {
        "id": quote.id,
        "deal_id": quote.deal_id,
        "number": quote.number,
        "plan": quote.plan,
        "plan_label": config.PLAN_LABEL.get(quote.plan, quote.plan),
        "seats": total_seats(quote),
        "worker_seats": quote.worker_seats,
        "planner_seats": quote.planner_seats,
        "admin_seats": quote.admin_seats,
        "enterprise_seats": quote.enterprise_seats,
        "contract_months": quote.contract_months,
        "onboarding_fee": quote.onboarding_fee,
        "mrr": quote.mrr,
        "acv": quote.acv,
        "company_name": quote.company_name,
        "contact_name": quote.contact_name,
        "valid_until": quote.valid_until.isoformat(),
        "status": quote.status,
        "sent_at": quote.sent_at.isoformat() if quote.sent_at else None,
        "created_at": quote.created_at.isoformat(),
        "url": "/quote/" + quote.number,
    }


def client_dict(client: Client, company: Optional[Company] = None,
                owner: Optional[User] = None, extra=None):
    out = {
        "id": client.id,
        "company_id": client.company_id,
        "deal_id": client.deal_id,
        "company": company.name if company else None,
        "country": company.country if company else None,
        "flag": settings_store.country_flag((company.country if company else "") or ""),
        "city": company.city if company else None,
        "segment": company.segment if company else None,
        "segment_label": config.SEGMENT_LABEL.get((company.segment if company else "") or "", ""),
        "segment_short": config.SEGMENT_SHORT.get((company.segment if company else "") or "", ""),
        "segment_color": config.SEGMENT_COLOR.get((company.segment if company else "") or "", "#94a3b8"),
        "mrr": client.mrr,
        "arr": client.mrr * 12,
        "seats": client.seats,
        "started_on": client.started_on.isoformat() if client.started_on else None,
        "go_live_on": client.go_live_on.isoformat() if client.go_live_on else None,
        "next_meeting_date": client.next_meeting_date.isoformat() if client.next_meeting_date else None,
        "meeting_overdue_days": (
            (date.today() - client.next_meeting_date).days if client.next_meeting_date else None
        ),
        "last_meeting_on": client.last_meeting_on.isoformat() if client.last_meeting_on else None,
        "health": client.health,
        "health_label": config.HEALTH_LABEL.get(client.health, client.health),
        "health_color": config.HEALTH_COLOR.get(client.health, "#94a3b8"),
        "status": client.status,
        "churned_on": client.churned_on.isoformat() if client.churned_on else None,
        "churn_reason": client.churn_reason,
        "months_live": (
            max(0, (date.today() - client.started_on).days // 30) if client.started_on else 0
        ),
        "owner": user_dict(owner),
        "notes": client.notes,
    }
    if extra:
        out.update(extra)
    return out


def meeting_dict(meeting: Meeting, author: Optional[User] = None):
    return {
        "id": meeting.id,
        "client_id": meeting.client_id,
        "held_on": meeting.held_on.isoformat(),
        "summary": meeting.summary,
        "actions": meeting.actions,
        "health": meeting.health,
        "health_label": config.HEALTH_LABEL.get(meeting.health or "", ""),
        "author": user_dict(author),
    }
