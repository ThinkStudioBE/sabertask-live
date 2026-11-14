"""Clients: what happens after a deal is won."""

import calendar
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from .. import config
from ..auth import current_user
from ..db import get_session
from ..models import Client, Company, Meeting, User
from ..serializers import client_dict, meeting_dict

router = APIRouter(prefix="/api", tags=["clients"])


def add_months(start: date, months: int) -> date:
    """Month arithmetic that survives the 31st: clamped to the month's length."""
    month = start.month - 1 + months
    year = start.year + month // 12
    month = month % 12 + 1
    day = min(start.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def roll_meeting(session: Session, client: Client, held_on: date,
                 user_id: Optional[int], summary: Optional[str] = None,
                 actions: Optional[str] = None, health: Optional[str] = None) -> Meeting:
    """Log a check-in, move the next one a month on from when it was held, and
    rebuild the task so Today always carries exactly one."""
    meeting = Meeting(
        client_id=client.id, held_on=held_on, summary=summary,
        actions=actions, health=health or client.health, user_id=user_id,
    )
    session.add(meeting)
    client.last_meeting_on = held_on
    client.next_meeting_date = add_months(held_on, 1)
    if health:
        client.health = health
    client.updated_at = datetime.utcnow()
    session.add(client)
    session.commit()
    session.refresh(meeting)

    from .deals import sync_meeting_task
    sync_meeting_task(session, client)
    return meeting


@router.get("/clients")
def list_clients(status: str = "active", segment: str = "",
                 session: Session = Depends(get_session),
                 user: User = Depends(current_user)):
    companies = {c.id: c for c in session.exec(select(Company)).all()}
    users = {u.id: u for u in session.exec(select(User)).all()}
    clients = session.exec(select(Client)).all()
    segments = {s for s in segment.split(",") if s}

    rows = []
    for client in clients:
        company = companies.get(client.company_id)
        if status and status != "all" and client.status != status:
            continue
        if segments and (not company or company.segment not in segments):
            continue
        rows.append(client_dict(client, company, users.get(client.owner_id)))
    rows.sort(key=lambda r: -(r["mrr"] or 0))

    active = [c for c in clients if c.status == "active"]
    churned = [c for c in clients if c.status == "churned"]
    today = date.today()
    stats = {
        "count": len(active),
        "mrr": sum(c.mrr for c in active),
        "arr": sum(c.mrr for c in active) * 12,
        "seats": sum(c.seats for c in active),
        "due_now": len([
            c for c in active if c.next_meeting_date and c.next_meeting_date <= today
        ]),
        "at_risk": len([c for c in active if c.health == "risk"]),
        "watch": len([c for c in active if c.health == "watch"]),
        "churned": len(churned),
        "retention": (
            round(100.0 * len(active) / max(1, len(active) + len(churned)))
        ),
    }

    by_segment = []
    for seg in config.SEGMENTS:
        picked = [r for r in rows if r.get("segment") == seg["key"]]
        if not picked:
            continue
        by_segment.append({
            "segment": seg["key"], "short": seg["short"], "label": seg["label"],
            "color": seg["color"], "count": len(picked),
            "mrr": sum(r["mrr"] for r in picked),
        })

    return {"clients": rows, "stats": stats, "by_segment": by_segment}


@router.get("/clients/{client_id}")
def get_client(client_id: int, session: Session = Depends(get_session),
               user: User = Depends(current_user)):
    client = session.get(Client, client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="No such client")
    company = session.get(Company, client.company_id)
    users = {u.id: u for u in session.exec(select(User)).all()}
    meetings = session.exec(
        select(Meeting).where(Meeting.client_id == client_id)
        .order_by(Meeting.held_on.desc())
    ).all()
    return {
        "client": client_dict(client, company, users.get(client.owner_id)),
        "meetings": [meeting_dict(m, users.get(m.user_id)) for m in meetings],
    }


class MeetingIn(BaseModel):
    held_on: Optional[date] = None
    summary: Optional[str] = None
    actions: Optional[str] = None
    health: Optional[str] = None


@router.post("/clients/{client_id}/meetings")
def log_meeting(client_id: int, payload: MeetingIn,
                session: Session = Depends(get_session),
                user: User = Depends(current_user)):
    client = session.get(Client, client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="No such client")
    meeting = roll_meeting(
        session, client, payload.held_on or date.today(), user.id,
        summary=payload.summary, actions=payload.actions, health=payload.health,
    )
    return meeting_dict(meeting, user)


class ClientPatch(BaseModel):
    health: Optional[str] = None
    mrr: Optional[float] = None
    seats: Optional[int] = None
    next_meeting_date: Optional[date] = None
    go_live_on: Optional[date] = None
    owner_id: Optional[int] = None
    status: Optional[str] = None
    churn_reason: Optional[str] = None
    notes: Optional[str] = None


@router.patch("/clients/{client_id}")
def patch_client(client_id: int, payload: ClientPatch,
                 session: Session = Depends(get_session),
                 user: User = Depends(current_user)):
    client = session.get(Client, client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="No such client")
    explicit = payload.dict(exclude_unset=True)
    for field, value in explicit.items():
        setattr(client, field, value)

    if explicit.get("status") == "churned":
        client.churned_on = date.today()
        client.next_meeting_date = None
    if explicit.get("status") == "active":
        # Churn is reversible; the meeting rhythm restarts from today.
        client.churned_on = None
        client.churn_reason = None
        if not client.next_meeting_date:
            client.next_meeting_date = add_months(date.today(), 1)

    client.updated_at = datetime.utcnow()
    session.add(client)
    session.commit()
    session.refresh(client)

    from .deals import sync_meeting_task
    sync_meeting_task(session, client)

    company = session.get(Company, client.company_id)
    users = {u.id: u for u in session.exec(select(User)).all()}
    return client_dict(client, company, users.get(client.owner_id))
