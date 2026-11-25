"""Deals: the pipeline itself."""

from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from .. import config, hubspot_sync
from ..auth import current_user
from ..db import get_session
from ..models import (Client, Company, Contact, Deal, MailDraft, Note, StageEvent,
                      Task, User)
from ..routing import owner_for_segment
from ..serializers import (
    contact_dict, deal_dict, deal_mrr, note_dict, plan_for, total_seats, user_dict,
)

router = APIRouter(prefix="/api", tags=["deals"])


# ------------------------------------------------------------------ helpers ---

def _lookup(session: Session):
    companies = {c.id: c for c in session.exec(select(Company)).all()}
    users = {u.id: u for u in session.exec(select(User)).all()}
    contacts = {c.id: c for c in session.exec(select(Contact)).all()}
    return companies, users, contacts


def apply_standard_step(deal: Deal, new_stage: str, explicit: dict) -> None:
    """Stamp the stage's standard next step and its deadline.

    A step the rep wrote themselves survives: only a blank step, or one that is
    still a previous stage's standard wording, gets replaced. Anything the
    request sent explicitly always wins.
    """
    if "next_action" in explicit or "next_action_date" in explicit:
        return
    standard = config.STAGE_NEXT_STEP.get(new_stage, {})
    step = standard.get("step")
    if not step:
        return
    current = (deal.next_action or "").strip()
    if current and current not in config.STANDARD_STEPS:
        return
    deal.next_action = step
    days = standard.get("days")
    deal.next_action_date = date.today() + timedelta(days=days) if days is not None else None


def client_from_deal(session: Session, deal: Deal) -> Optional[Client]:
    """A won deal opens a client file. Idempotent, so re-winning changes nothing."""
    if deal.stage != "won":
        return None
    existing = session.exec(select(Client).where(Client.deal_id == deal.id)).first()
    if existing:
        return existing
    today = date.today()
    client = Client(
        company_id=deal.company_id,
        deal_id=deal.id,
        mrr=deal_mrr(deal),
        seats=total_seats(deal),
        started_on=today,
        go_live_on=today + timedelta(days=21),
        next_meeting_date=today + timedelta(days=30),
        health="green",
        owner_id=deal.owner_id,
        status="active",
    )
    session.add(client)
    session.commit()
    session.refresh(client)
    sync_meeting_task(session, client)
    return client


def sync_meeting_task(session: Session, client: Client) -> None:
    """Exactly one open dated task per active client, so the monthly check-in
    always shows up in Today. Deleted and recreated, never edited in place."""
    stale = session.exec(
        select(Task).where(Task.client_id == client.id, Task.done == False)  # noqa: E712
    ).all()
    for task in stale:
        session.delete(task)
    session.commit()

    if client.status != "active" or not client.next_meeting_date:
        return
    company = session.get(Company, client.company_id)
    session.add(Task(
        title="Monthly check-in with " + (company.name if company else "client"),
        kind="meeting",
        priority="high" if client.health == "risk" else "normal",
        due_date=client.next_meeting_date,
        owner_id=client.owner_id,
        client_id=client.id,
        company_id=client.company_id,
    ))
    session.commit()


def log_stage_event(session: Session, deal: Deal, from_stage: Optional[str],
                    to_stage: str, user_id: Optional[int]) -> None:
    session.add(StageEvent(
        deal_id=deal.id, from_stage=from_stage, to_stage=to_stage,
        mrr=deal_mrr(deal), user_id=user_id,
    ))


# -------------------------------------------------------------------- list ---

@router.get("/deals")
def list_deals(
    stage: str = "",
    segment: str = "",
    country: str = "",
    owner_id: Optional[int] = None,
    channel: str = "",
    q: str = "",
    open_only: bool = False,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
):
    companies, users, contacts = _lookup(session)
    deals = session.exec(select(Deal)).all()
    # Which deals have a cold mail written and still waiting to go out. The mail
    # lives on the deal now, so the board has to be able to say so without
    # anybody opening every card.
    waiting = {d.deal_id for d in session.exec(
        select(MailDraft).where(MailDraft.status == "draft")).all()}

    stages = {s for s in stage.split(",") if s}
    segments = {s for s in segment.split(",") if s}
    countries = {c for c in country.split(",") if c}
    needle = q.strip().lower()

    rows = []
    for deal in deals:
        company = companies.get(deal.company_id)
        if stages and deal.stage not in stages:
            continue
        if open_only and deal.stage in {"won", "lost"}:
            continue
        if segments and (not company or company.segment not in segments):
            continue
        if countries and (not company or company.country not in countries):
            continue
        if owner_id and deal.owner_id != owner_id:
            continue
        if channel and deal.channel != channel:
            continue
        if needle:
            haystack = " ".join(filter(None, [
                deal.title, company.name if company else "",
                company.city if company else "", deal.notes or "",
            ])).lower()
            if needle not in haystack:
                continue
        rows.append(deal_dict(
            deal, company, users.get(deal.owner_id),
            contacts.get(deal.primary_contact_id),
            extra={"draft_waiting": deal.id in waiting},
        ))

    rows.sort(key=lambda r: (-r["mrr"], r["company"] or ""))
    totals = {
        "count": len(rows),
        "mrr": sum(r["mrr"] for r in rows),
        "weighted": sum(r["weighted"] for r in rows),
        "acv": sum(r["acv"] for r in rows),
    }
    # The whole point of the industry split: these are the per-industry subtotals
    # each rep is measured on.
    by_segment = []
    for seg in config.SEGMENTS:
        picked = [r for r in rows if r["segment"] == seg["key"]]
        if not picked:
            continue
        by_segment.append({
            "segment": seg["key"],
            "label": seg["label"],
            "short": seg["short"],
            "color": seg["color"],
            "count": len(picked),
            "mrr": sum(r["mrr"] for r in picked),
            "weighted": sum(r["weighted"] for r in picked),
        })
    by_segment.sort(key=lambda r: -r["mrr"])
    return {"deals": rows, "totals": totals, "by_segment": by_segment}


@router.get("/deals/{deal_id}")
def get_deal(deal_id: int, session: Session = Depends(get_session),
             user: User = Depends(current_user)):
    deal = session.get(Deal, deal_id)
    if deal is None:
        raise HTTPException(status_code=404, detail="No such deal")
    companies, users, contacts = _lookup(session)
    company = companies.get(deal.company_id)

    notes = session.exec(
        select(Note).where(Note.deal_id == deal_id).order_by(Note.created_at.desc())
    ).all()
    events = session.exec(
        select(StageEvent).where(StageEvent.deal_id == deal_id)
        .order_by(StageEvent.created_at)
    ).all()
    company_contacts = session.exec(
        select(Contact).where(Contact.company_id == deal.company_id)
    ).all()

    from ..models import Quote
    from ..serializers import quote_dict
    quotes = session.exec(
        select(Quote).where(Quote.deal_id == deal_id).order_by(Quote.created_at.desc())
    ).all()

    return {
        "deal": deal_dict(deal, company, users.get(deal.owner_id),
                          contacts.get(deal.primary_contact_id)),
        "notes": [note_dict(n, users.get(n.user_id)) for n in notes],
        "history": [
            {
                "from": e.from_stage,
                "from_label": config.STAGE_LABEL.get(e.from_stage or "", ""),
                "to": e.to_stage,
                "to_label": config.STAGE_LABEL.get(e.to_stage, e.to_stage),
                "at": e.created_at.isoformat(),
                "by": user_dict(users.get(e.user_id)),
            }
            for e in events
        ],
        "contacts": [contact_dict(c) for c in company_contacts],
        "quotes": [quote_dict(q) for q in quotes],
    }


# ------------------------------------------------------------------ create ---

class DealIn(BaseModel):
    company_id: Optional[int] = None
    company_name: Optional[str] = None
    segment: Optional[str] = None
    country: Optional[str] = None
    city: Optional[str] = None
    title: Optional[str] = None
    worker_seats: int = 0
    planner_seats: int = 0
    admin_seats: int = 0
    enterprise_seats: int = 0
    enterprise_rate: float = 0.0
    contract_months: int = 12
    onboarding_fee: float = 0.0
    stage: str = "lead"
    channel: str = "outbound_mail"
    owner_id: Optional[int] = None
    notes: Optional[str] = None


@router.post("/deals")
def create_deal(payload: DealIn, session: Session = Depends(get_session),
                user: User = Depends(current_user)):
    company = None
    if payload.company_id:
        company = session.get(Company, payload.company_id)
    if company is None:
        name = (payload.company_name or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="A company is required")
        company = session.exec(
            select(Company).where(Company.name == name)
        ).first()
        if company is None:
            company = Company(
                name=name, segment=payload.segment, country=payload.country,
                city=payload.city,
            )
            session.add(company)
            session.commit()
            session.refresh(company)

    # Unassigned leads go to whoever owns that industry.
    owner_id = payload.owner_id
    if owner_id is None:
        routed = owner_for_segment(session, company.segment)
        owner_id = routed.id if routed else user.id
    if company.owner_id is None:
        company.owner_id = owner_id
        session.add(company)

    deal = Deal(
        company_id=company.id,
        title=(payload.title or "").strip() or (company.name + " - Sabertask rollout"),
        worker_seats=payload.worker_seats,
        planner_seats=payload.planner_seats,
        admin_seats=payload.admin_seats,
        enterprise_seats=payload.enterprise_seats,
        worker_rate=config.SEAT_RATE["worker"],
        planner_rate=config.SEAT_RATE["planner"],
        admin_rate=config.SEAT_RATE["admin"],
        # Enterprise is "Custom" on their price list, so the catalogue rate is 0
        # and whatever the rep negotiated comes in on the payload.
        enterprise_rate=payload.enterprise_rate or config.SEAT_RATE["enterprise"],
        contract_months=payload.contract_months,
        onboarding_fee=payload.onboarding_fee,
        stage=payload.stage,
        channel=payload.channel,
        owner_id=owner_id,
        notes=payload.notes,
    )
    deal.plan = plan_for(deal)
    apply_standard_step(deal, deal.stage, {})
    session.add(deal)
    session.commit()
    session.refresh(deal)
    log_stage_event(session, deal, None, deal.stage, user.id)
    session.commit()

    companies, users, contacts = _lookup(session)
    return deal_dict(deal, company, users.get(deal.owner_id), None)


# ------------------------------------------------------------------- patch ---

class DealPatch(BaseModel):
    title: Optional[str] = None
    worker_seats: Optional[int] = None
    planner_seats: Optional[int] = None
    admin_seats: Optional[int] = None
    enterprise_seats: Optional[int] = None
    worker_rate: Optional[float] = None
    planner_rate: Optional[float] = None
    admin_rate: Optional[float] = None
    enterprise_rate: Optional[float] = None
    contract_months: Optional[int] = None
    onboarding_fee: Optional[float] = None
    stage: Optional[str] = None
    probability: Optional[int] = None
    channel: Optional[str] = None
    owner_id: Optional[int] = None
    primary_contact_id: Optional[int] = None
    next_action: Optional[str] = None
    next_action_date: Optional[date] = None
    expected_close_date: Optional[date] = None
    trial_started_on: Optional[date] = None
    lost_reason: Optional[str] = None
    lost_reason_note: Optional[str] = None
    notes: Optional[str] = None


@router.patch("/deals/{deal_id}")
def patch_deal(deal_id: int, payload: DealPatch,
               session: Session = Depends(get_session),
               user: User = Depends(current_user)):
    deal = session.get(Deal, deal_id)
    if deal is None:
        raise HTTPException(status_code=404, detail="No such deal")

    explicit = payload.dict(exclude_unset=True)
    old_stage = deal.stage

    for field, value in explicit.items():
        setattr(deal, field, value)

    if "stage" in explicit and explicit["stage"] != old_stage:
        new_stage = explicit["stage"]
        deal.stage_changed_at = datetime.utcnow()
        if new_stage == "won":
            deal.won_at = datetime.utcnow()
        if new_stage == "lost":
            deal.lost_at = datetime.utcnow()
        if new_stage == "trial" and deal.trial_started_on is None:
            deal.trial_started_on = date.today()
        if new_stage not in {"lost"}:
            deal.lost_reason = None
            deal.lost_reason_note = None
        apply_standard_step(deal, new_stage, explicit)
        log_stage_event(session, deal, old_stage, new_stage, user.id)

    # Giving a reason clears the chore of recording one.
    if explicit.get("lost_reason") and deal.next_action == config.STAGE_NEXT_STEP["lost"]["step"]:
        deal.next_action = None
        deal.next_action_date = None

    deal.plan = plan_for(deal)
    deal.updated_at = datetime.utcnow()
    session.add(deal)
    session.commit()
    session.refresh(deal)

    if deal.stage == "won":
        client_from_deal(session, deal)

    # Their CRM follows this one. A pipeline that moves here and stands still
    # in HubSpot is worse than no integration at all: two boards, one of them
    # quietly wrong, and the rep believes whichever he opened last.
    hubspot_sync.push_quietly(session, deal)

    companies, users, contacts = _lookup(session)
    return deal_dict(deal, companies.get(deal.company_id), users.get(deal.owner_id),
                     contacts.get(deal.primary_contact_id))


# ------------------------------------------------------------------- notes ---

class NoteIn(BaseModel):
    kind: str = "note"
    body: str
    next_action: Optional[str] = None
    next_action_date: Optional[date] = None


@router.post("/deals/{deal_id}/notes")
def add_note(deal_id: int, payload: NoteIn,
             session: Session = Depends(get_session),
             user: User = Depends(current_user)):
    deal = session.get(Deal, deal_id)
    if deal is None:
        raise HTTPException(status_code=404, detail="No such deal")
    body = payload.body.strip()
    if not body:
        raise HTTPException(status_code=400, detail="Write something first")

    note = Note(deal_id=deal_id, user_id=user.id, kind=payload.kind, body=body)
    session.add(note)

    # A note is a note; a call, mail or meeting is a touch on the account.
    if payload.kind in config.TOUCH_KINDS:
        deal.touch_count = (deal.touch_count or 0) + 1
        deal.last_touch_at = datetime.utcnow()
    if payload.next_action is not None:
        deal.next_action = payload.next_action or None
        deal.next_action_date = payload.next_action_date
    deal.updated_at = datetime.utcnow()
    session.add(deal)
    session.commit()
    session.refresh(note)
    return note_dict(note, user)
