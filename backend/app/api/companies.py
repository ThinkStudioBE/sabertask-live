"""Companies and their contacts."""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from .. import config
from ..auth import current_user
from ..db import get_session
from ..models import Client, Company, Contact, Deal, User
from ..routing import owner_for_segment
from ..leadfinder import site_url
from ..serializers import company_dict, contact_dict, deal_dict, deal_mrr

router = APIRouter(prefix="/api", tags=["companies"])


@router.get("/companies")
def list_companies(segment: str = "", country: str = "", owner_id: Optional[int] = None,
                   q: str = "", session: Session = Depends(get_session),
                   user: User = Depends(current_user)):
    companies = session.exec(select(Company)).all()
    deals = session.exec(select(Deal)).all()
    users = {u.id: u for u in session.exec(select(User)).all()}
    clients = {c.company_id: c for c in session.exec(select(Client)).all()}
    contacts = session.exec(select(Contact)).all()

    deals_by_company = {}
    for deal in deals:
        deals_by_company.setdefault(deal.company_id, []).append(deal)
    primary_by_company = {}
    for contact in contacts:
        if contact.is_primary:
            primary_by_company[contact.company_id] = contact
        primary_by_company.setdefault(contact.company_id, contact)

    segments = {s for s in segment.split(",") if s}
    countries = {c for c in country.split(",") if c}
    needle = q.strip().lower()

    rows = []
    for company in companies:
        if segments and company.segment not in segments:
            continue
        if countries and company.country not in countries:
            continue
        if owner_id and company.owner_id != owner_id:
            continue
        if needle and needle not in " ".join(filter(None, [
            company.name, company.city or "", company.website or "",
        ])).lower():
            continue

        own = deals_by_company.get(company.id, [])
        open_deals = [d for d in own if d.stage not in {"won", "lost"}]
        client = clients.get(company.id)
        contact = primary_by_company.get(company.id)
        rows.append(company_dict(company, users.get(company.owner_id), {
            "deal_count": len(own),
            "open_count": len(open_deals),
            "open_mrr": sum(deal_mrr(d) for d in open_deals),
            "stage": open_deals[0].stage if open_deals else (own[0].stage if own else None),
            "stage_label": config.STAGE_LABEL.get(
                open_deals[0].stage if open_deals else (own[0].stage if own else ""), ""),
            "is_client": client is not None and client.status == "active",
            "contact": contact_dict(contact) if contact else None,
        }))

    rows.sort(key=lambda r: (-(r["open_mrr"] or 0), r["name"]))

    by_segment = []
    for seg in config.SEGMENTS:
        picked = [r for r in rows if r["segment"] == seg["key"]]
        by_segment.append({
            "segment": seg["key"], "label": seg["label"], "short": seg["short"],
            "color": seg["color"], "count": len(picked),
            "mrr": sum(r["open_mrr"] or 0 for r in picked),
        })
    return {"companies": rows, "by_segment": by_segment, "count": len(rows)}


@router.get("/companies/{company_id}")
def get_company(company_id: int, session: Session = Depends(get_session),
                user: User = Depends(current_user)):
    company = session.get(Company, company_id)
    if company is None:
        raise HTTPException(status_code=404, detail="No such company")
    users = {u.id: u for u in session.exec(select(User)).all()}
    deals = session.exec(select(Deal).where(Deal.company_id == company_id)).all()
    contacts = session.exec(select(Contact).where(Contact.company_id == company_id)).all()
    client = session.exec(select(Client).where(Client.company_id == company_id)).first()
    return {
        "company": company_dict(company, users.get(company.owner_id)),
        "deals": [deal_dict(d, company, users.get(d.owner_id)) for d in deals],
        "contacts": [contact_dict(c) for c in contacts],
        "client_id": client.id if client else None,
    }


class CompanyIn(BaseModel):
    name: str
    website: Optional[str] = None
    segment: Optional[str] = None
    country: Optional[str] = None
    city: Optional[str] = None
    size_band: Optional[str] = None
    field_staff: Optional[int] = None
    sites: Optional[int] = None
    current_tool: Optional[str] = None
    source_channel: Optional[str] = None
    owner_id: Optional[int] = None
    notes: Optional[str] = None


@router.post("/companies")
def create_company(payload: CompanyIn, session: Session = Depends(get_session),
                   user: User = Depends(current_user)):
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="A name is required")
    company = Company(**payload.dict())
    company.name = name
    # Typed by hand, so it arrives as "www.foo.be" as often as not, and an
    # address without a scheme is a link that points back at us.
    company.website = site_url(company.website)
    if company.owner_id is None:
        routed = owner_for_segment(session, company.segment)
        company.owner_id = routed.id if routed else user.id
    session.add(company)
    session.commit()
    session.refresh(company)
    users = {u.id: u for u in session.exec(select(User)).all()}
    return company_dict(company, users.get(company.owner_id))


class CompanyPatch(BaseModel):
    name: Optional[str] = None
    website: Optional[str] = None
    segment: Optional[str] = None
    country: Optional[str] = None
    city: Optional[str] = None
    size_band: Optional[str] = None
    field_staff: Optional[int] = None
    sites: Optional[int] = None
    current_tool: Optional[str] = None
    source_channel: Optional[str] = None
    owner_id: Optional[int] = None
    notes: Optional[str] = None
    reroute: Optional[bool] = None


@router.patch("/companies/{company_id}")
def patch_company(company_id: int, payload: CompanyPatch,
                  session: Session = Depends(get_session),
                  user: User = Depends(current_user)):
    company = session.get(Company, company_id)
    if company is None:
        raise HTTPException(status_code=404, detail="No such company")
    explicit = payload.dict(exclude_unset=True)
    reroute = explicit.pop("reroute", False)
    for field, value in explicit.items():
        setattr(company, field, value)
    if "website" in explicit:
        company.website = site_url(company.website)

    # Moving a company to another industry moves it to that industry's rep,
    # unless the caller named an owner in the same breath.
    if reroute and "owner_id" not in explicit:
        routed = owner_for_segment(session, company.segment)
        if routed:
            company.owner_id = routed.id
            for deal in session.exec(select(Deal).where(Deal.company_id == company_id)).all():
                if deal.stage not in {"won", "lost"}:
                    deal.owner_id = routed.id
                    session.add(deal)

    company.updated_at = datetime.utcnow()
    session.add(company)
    session.commit()
    session.refresh(company)
    users = {u.id: u for u in session.exec(select(User)).all()}
    return company_dict(company, users.get(company.owner_id))


class ContactIn(BaseModel):
    name: str
    role_title: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    is_primary: bool = False
    notes: Optional[str] = None


@router.post("/companies/{company_id}/contacts")
def add_contact(company_id: int, payload: ContactIn,
                session: Session = Depends(get_session),
                user: User = Depends(current_user)):
    company = session.get(Company, company_id)
    if company is None:
        raise HTTPException(status_code=404, detail="No such company")
    if payload.is_primary:
        for other in session.exec(select(Contact).where(Contact.company_id == company_id)).all():
            other.is_primary = False
            session.add(other)
    contact = Contact(company_id=company_id, **payload.dict())
    session.add(contact)
    session.commit()
    session.refresh(contact)
    return contact_dict(contact)
