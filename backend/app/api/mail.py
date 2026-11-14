"""Cold mail: draft, edit, send by hand, log the send.

The deliberate omission is sending, and on this build it is not a convenience:
every address here belongs to a real company found on the map. The app drafts
the mail and records that it went out; a person reads it, decides, and sends it
from their own mailbox. Nothing leaves this machine on its own.
"""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from .. import config, settings_store
from ..auth import current_user
from ..db import get_session
from ..models import Company, Contact, Deal, MailDraft, Note, User
from ..outreach import draft_for
from ..serializers import deal_mrr
from .deals import apply_standard_step, log_stage_event

router = APIRouter(prefix="/api", tags=["mail"])


def _utcnow():
    return datetime.utcnow()


def _contact_for(session: Session, company_id: int,
                 deal: Optional[Deal]) -> Optional[Contact]:
    """The deal's own contact wins; otherwise the company's primary one."""
    if deal is not None and deal.primary_contact_id:
        contact = session.get(Contact, deal.primary_contact_id)
        if contact is not None:
            return contact
    contacts = session.exec(
        select(Contact).where(Contact.company_id == company_id)).all()
    for contact in contacts:
        if contact.is_primary:
            return contact
    return contacts[0] if contacts else None


def _row(deal: Deal, company: Company, owner: Optional[User],
         contact: Optional[Contact], draft: Optional[MailDraft]) -> dict:
    return {
        "deal_id": deal.id,
        "company_id": company.id,
        "company": company.name,
        "city": company.city,
        "flag": settings_store.country_flag(company.country or ""),
        "segment": company.segment,
        "segment_short": config.SEGMENT_SHORT.get(company.segment or "", ""),
        "segment_color": config.SEGMENT_COLOR.get(company.segment or "", "#94a3b8"),
        "stage": deal.stage,
        "stage_label": config.STAGE_LABEL.get(deal.stage, deal.stage),
        "field_staff": company.field_staff,
        "current_tool": company.current_tool,
        "mrr": deal_mrr(deal),
        "owner": {"id": owner.id, "name": owner.name, "initials": owner.initials,
                  "color": owner.color} if owner else None,
        "to_name": (draft.to_name if draft else None) or (contact.name if contact else None),
        "to_email": (draft.to_email if draft else None) or (contact.email if contact else None),
        "subject": draft.subject if draft else "",
        "body": draft.body if draft else "",
        "status": draft.status if draft else "none",
        "edited": bool(draft.edited) if draft else False,
        "sent_at": draft.sent_at.isoformat() if draft and draft.sent_at else None,
        "skipped_reason": draft.skipped_reason if draft else None,
    }


def _eligible(session: Session, user: User, mine: bool):
    deals = session.exec(select(Deal).where(Deal.stage.in_(config.MAIL_STAGES))).all()
    if mine:
        deals = [d for d in deals if d.owner_id == user.id]
    companies = {c.id: c for c in session.exec(select(Company)).all()}
    users = {u.id: u for u in session.exec(select(User)).all()}
    drafts = {d.deal_id: d for d in session.exec(select(MailDraft)).all()}
    return deals, companies, users, drafts


@router.get("/mail")
def list_mail(scope: str = "team", segment: str = "", status: str = "",
              session: Session = Depends(get_session),
              user: User = Depends(current_user)):
    deals, companies, users, drafts = _eligible(session, user, scope == "mine")
    segments = {s for s in segment.split(",") if s}

    rows = []
    counts = {"none": 0, "draft": 0, "sent": 0, "skipped": 0}
    for deal in deals:
        company = companies.get(deal.company_id)
        if company is None:
            continue
        if segments and company.segment not in segments:
            continue
        draft = drafts.get(deal.id)
        counts[draft.status if draft else "none"] = \
            counts.get(draft.status if draft else "none", 0) + 1
        if status and (draft.status if draft else "none") != status:
            continue
        rows.append(_row(deal, company, users.get(deal.owner_id),
                         _contact_for(session, company.id, deal), draft))

    # No mailbox, no mail: those rows are shown but can never be sent, so they
    # sit at the bottom rather than at the top of a prospecting list.
    rows.sort(key=lambda r: (r["to_email"] is None, -r["mrr"]))
    # How a mail got written is kept in the row but never sent to the browser:
    # the rep's screen is about the prospect, not about our plumbing.
    return {
        "rows": rows,
        "counts": counts,
        "stages": [config.STAGE_LABEL.get(s, s) for s in config.MAIL_STAGES],
    }


def _write_draft(session: Session, deal: Deal, company: Company,
                 user: User, force: bool) -> MailDraft:
    draft = session.exec(
        select(MailDraft).where(MailDraft.deal_id == deal.id)).first()
    if draft is not None and draft.subject and not force:
        return draft

    contact = _contact_for(session, company.id, deal)
    owner = session.get(User, deal.owner_id) if deal.owner_id else user
    subject, body, written_by = draft_for(company, deal, contact, owner)

    if draft is None:
        draft = MailDraft(deal_id=deal.id, company_id=company.id)
        session.add(draft)
    draft.to_name = contact.name if contact else None
    draft.to_email = contact.email if contact else None
    draft.subject = subject
    draft.body = body
    draft.written_by = written_by
    draft.edited = False
    if draft.status == "skipped":
        draft.status = "draft"
        draft.skipped_reason = None
    elif draft.status != "sent":
        draft.status = "draft"
    draft.updated_at = _utcnow()
    session.commit()
    session.refresh(draft)
    return draft


def _deal_and_company(session: Session, deal_id: int):
    deal = session.get(Deal, deal_id)
    if deal is None:
        raise HTTPException(status_code=404, detail="No such deal")
    company = session.get(Company, deal.company_id)
    if company is None:
        raise HTTPException(status_code=404, detail="No such company")
    return deal, company


@router.post("/mail/{deal_id}/draft")
def draft_one(deal_id: int, session: Session = Depends(get_session),
              user: User = Depends(current_user)):
    deal, company = _deal_and_company(session, deal_id)
    draft = _write_draft(session, deal, company, user, force=True)
    return _row(deal, company, session.get(User, deal.owner_id) if deal.owner_id else None,
                _contact_for(session, company.id, deal), draft)


@router.post("/mail/draft-all")
def draft_all(scope: str = "team", session: Session = Depends(get_session),
              user: User = Depends(current_user)):
    deals, companies, _users, drafts = _eligible(session, user, scope == "mine")
    written = 0
    for deal in deals:
        company = companies.get(deal.company_id)
        if company is None:
            continue
        existing = drafts.get(deal.id)
        if existing is not None and existing.status in ("sent", "skipped"):
            continue
        if existing is not None and existing.subject:
            continue
        _write_draft(session, deal, company, user, force=False)
        written += 1
    return {"written": written}


class DraftPatch(BaseModel):
    subject: Optional[str] = None
    body: Optional[str] = None
    to_email: Optional[str] = None


@router.patch("/mail/{deal_id}")
def edit_draft(deal_id: int, payload: DraftPatch,
               session: Session = Depends(get_session),
               user: User = Depends(current_user)):
    deal, company = _deal_and_company(session, deal_id)
    draft = session.exec(
        select(MailDraft).where(MailDraft.deal_id == deal.id)).first()
    if draft is None:
        raise HTTPException(status_code=404, detail="Nothing drafted yet")
    if draft.status == "sent":
        raise HTTPException(status_code=400, detail="That mail has already gone out")

    data = payload.dict(exclude_unset=True)
    for field in ("subject", "body", "to_email"):
        if field in data and data[field] is not None:
            setattr(draft, field, data[field])
    if "subject" in data or "body" in data:
        draft.edited = True
        draft.written_by = "rep"
    draft.updated_at = _utcnow()
    session.commit()
    session.refresh(draft)
    return _row(deal, company, session.get(User, deal.owner_id) if deal.owner_id else None,
                _contact_for(session, company.id, deal), draft)


@router.post("/mail/{deal_id}/sent")
def mark_sent(deal_id: int, session: Session = Depends(get_session),
              user: User = Depends(current_user)):
    """The rep sent it from their own mailbox; this records what the pipeline
    needs to know. A lead that has been written to is contacted, and the deal
    picks up the follow-up step that goes with that stage."""
    deal, company = _deal_and_company(session, deal_id)
    draft = session.exec(
        select(MailDraft).where(MailDraft.deal_id == deal.id)).first()
    if draft is None or not draft.subject:
        raise HTTPException(status_code=400, detail="Nothing drafted yet")

    now = _utcnow()
    draft.status = "sent"
    draft.sent_at = now
    draft.updated_at = now

    session.add(Note(
        deal_id=deal.id, user_id=user.id, kind="email",
        body="Cold mail sent to " + (draft.to_email or "the contact")
             + ': "' + draft.subject + '"',
    ))
    deal.last_touch_at = now
    deal.touch_count = (deal.touch_count or 0) + 1
    if deal.stage == "lead":
        log_stage_event(session, deal, deal.stage, "contacted", user.id)
        deal.stage = "contacted"
        deal.stage_changed_at = now
        apply_standard_step(deal, "contacted", {})
    deal.updated_at = now
    session.commit()
    session.refresh(draft)
    return _row(deal, company, session.get(User, deal.owner_id) if deal.owner_id else None,
                _contact_for(session, company.id, deal), draft)


class SkipIn(BaseModel):
    reason: Optional[str] = None


@router.post("/mail/{deal_id}/skip")
def skip(deal_id: int, payload: SkipIn, session: Session = Depends(get_session),
         user: User = Depends(current_user)):
    """Do not write to this one. Kept as a row rather than a deletion, so the
    next bulk draft does not quietly put it back on the list."""
    deal, company = _deal_and_company(session, deal_id)
    draft = session.exec(
        select(MailDraft).where(MailDraft.deal_id == deal.id)).first()
    if draft is None:
        draft = MailDraft(deal_id=deal.id, company_id=company.id)
        session.add(draft)
    draft.status = "skipped"
    draft.skipped_reason = payload.reason or "Not a fit"
    draft.updated_at = _utcnow()
    session.commit()
    session.refresh(draft)
    return _row(deal, company, session.get(User, deal.owner_id) if deal.owner_id else None,
                _contact_for(session, company.id, deal), draft)
