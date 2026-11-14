"""Today: one urgency feed.

Real tasks and the next step written on a deal are the same thing to the person
doing the work, so they are merged into one list rather than living on two
screens. A deal's step appears with the id `deal-{id}` and is completed through
the same endpoint.
"""

from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from .. import config
from ..auth import current_user
from ..db import get_session
from ..models import Company, Deal, Task, User
from ..serializers import deal_mrr, task_dict, user_dict

router = APIRouter(prefix="/api", tags=["today"])


def _bucket(due: Optional[date]) -> str:
    if due is None:
        return "no_date"
    today = date.today()
    if due < today:
        return "overdue"
    if due == today:
        return "today"
    if due <= today + timedelta(days=7):
        return "week"
    return "later"


@router.get("/today")
def today(scope: str = "mine", segment: str = "",
          session: Session = Depends(get_session),
          user: User = Depends(current_user)):
    companies = {c.id: c for c in session.exec(select(Company)).all()}
    users = {u.id: u for u in session.exec(select(User)).all()}
    deals = {d.id: d for d in session.exec(select(Deal)).all()}
    segments = {s for s in segment.split(",") if s}

    items = []

    for task in session.exec(select(Task).where(Task.done == False)).all():  # noqa: E712
        deal = deals.get(task.deal_id) if task.deal_id else None
        company = companies.get(task.company_id) if task.company_id else (
            companies.get(deal.company_id) if deal else None
        )
        items.append(task_dict(task, users.get(task.owner_id), deal, company))

    # The other half of the feed: a deal's own next step, which is where most of
    # the day's work actually lives.
    for deal in deals.values():
        if deal.stage in {"won", "lost"} or not deal.next_action:
            continue
        company = companies.get(deal.company_id)
        due = deal.next_action_date
        items.append({
            "id": "deal-" + str(deal.id),
            "raw_id": deal.id,
            "source": "deal",
            "title": deal.next_action,
            "kind": "todo",
            "kind_label": "Next step",
            "priority": "normal",
            "due_date": due.isoformat() if due else None,
            "overdue_days": (date.today() - due).days if due else 0,
            "owner": user_dict(users.get(deal.owner_id)),
            "deal_id": deal.id,
            "company_id": deal.company_id,
            "client_id": None,
            "company": company.name if company else None,
            "segment": company.segment if company else None,
            "segment_short": config.SEGMENT_SHORT.get((company.segment if company else "") or "", ""),
            "segment_color": config.SEGMENT_COLOR.get((company.segment if company else "") or "", "#94a3b8"),
            "mrr": deal_mrr(deal),
            "stage": deal.stage,
            "stage_label": config.STAGE_LABEL.get(deal.stage, deal.stage),
            "notes": None,
            "done": False,
        })

    if scope == "mine":
        items = [i for i in items if i["owner"] and i["owner"]["id"] == user.id]
    if segments:
        items = [i for i in items if i.get("segment") in segments]

    # Most overdue first, then priority, then the biggest money.
    items.sort(key=lambda i: (
        -i["overdue_days"],
        config.PRIORITY_WEIGHT.get(i["priority"], 1),
        -(i["mrr"] or 0),
    ))

    groups = {"overdue": [], "today": [], "week": [], "later": [], "no_date": []}
    for item in items:
        due = date.fromisoformat(item["due_date"]) if item["due_date"] else None
        groups[_bucket(due)].append(item)

    by_segment = []
    for seg in config.SEGMENTS:
        picked = [i for i in items if i.get("segment") == seg["key"]]
        if not picked:
            continue
        by_segment.append({
            "segment": seg["key"], "short": seg["short"], "label": seg["label"],
            "color": seg["color"], "count": len(picked),
            "overdue": len([i for i in picked if i["overdue_days"] > 0]),
        })

    return {
        "groups": groups,
        "counts": {k: len(v) for k, v in groups.items()},
        "due_now": len(groups["overdue"]) + len(groups["today"]),
        "by_segment": by_segment,
    }


class TaskIn(BaseModel):
    title: str
    kind: str = "todo"
    priority: str = "normal"
    due_date: Optional[date] = None
    owner_id: Optional[int] = None
    deal_id: Optional[int] = None
    company_id: Optional[int] = None
    notes: Optional[str] = None


@router.post("/tasks")
def create_task(payload: TaskIn, session: Session = Depends(get_session),
                user: User = Depends(current_user)):
    title = payload.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="A title is required")
    task = Task(**payload.dict())
    task.title = title
    if task.owner_id is None:
        task.owner_id = user.id
    session.add(task)
    session.commit()
    session.refresh(task)
    company = session.get(Company, task.company_id) if task.company_id else None
    deal = session.get(Deal, task.deal_id) if task.deal_id else None
    return task_dict(task, user, deal, company)


class CompleteIn(BaseModel):
    """Completing a deal's step asks what comes next, so no deal goes quiet.
    `next_step` of None with `nothing_planned` true is the deliberate escape."""
    next_step: Optional[str] = None
    next_step_date: Optional[date] = None
    nothing_planned: bool = False
    log_note: Optional[str] = None


@router.post("/today/{item_id}/complete")
def complete_item(item_id: str, payload: CompleteIn,
                  session: Session = Depends(get_session),
                  user: User = Depends(current_user)):
    if item_id.startswith("task-"):
        task = session.get(Task, int(item_id[5:]))
        if task is None:
            raise HTTPException(status_code=404, detail="No such task")
        task.done = True
        task.done_at = datetime.utcnow()
        session.add(task)

        # A client's monthly check-in regenerates itself rather than vanishing.
        if task.client_id:
            from ..models import Client
            from .clients import roll_meeting
            client = session.get(Client, task.client_id)
            if client and client.status == "active":
                roll_meeting(session, client, date.today(), user.id,
                             summary=payload.log_note)
        session.commit()
        return {"ok": True}

    if item_id.startswith("deal-"):
        deal = session.get(Deal, int(item_id[5:]))
        if deal is None:
            raise HTTPException(status_code=404, detail="No such deal")
        if payload.log_note:
            from ..models import Note
            session.add(Note(deal_id=deal.id, user_id=user.id, kind="note",
                             body=payload.log_note))
        if payload.nothing_planned:
            deal.next_action = None
            deal.next_action_date = None
        else:
            deal.next_action = (payload.next_step or "").strip() or None
            deal.next_action_date = payload.next_step_date
        deal.last_touch_at = datetime.utcnow()
        deal.touch_count = (deal.touch_count or 0) + 1
        deal.updated_at = datetime.utcnow()
        session.add(deal)
        session.commit()
        return {"ok": True}

    raise HTTPException(status_code=400, detail="Unknown item")
