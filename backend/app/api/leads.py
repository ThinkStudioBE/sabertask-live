"""Find leads: search, review, then push the good ones into the pipeline."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from .. import config, settings_store
from ..auth import current_user
from ..db import get_session
from ..leadfinder import SearchFailed, search
from ..models import Company, Contact, Deal, Lead, LeadSearch, User
from ..routing import owner_for_segment
from .deals import apply_standard_step, log_stage_event

router = APIRouter(prefix="/api", tags=["leads"])

# What a brand new prospect is worth until somebody asks them. Small on purpose:
# a forecast should not move because a search ran.
# A first guess so a fresh lead is not worth nothing: Enterprise is left at 0
# because that tier is a negotiation, never an assumption.
STARTER_SEATS = {"worker": 20, "planner": 3, "admin": 1, "enterprise": 0}


def _row(lead: Lead) -> dict:
    return {
        "id": lead.id,
        "name": lead.name,
        "segment": lead.segment,
        "segment_short": config.SEGMENT_SHORT.get(lead.segment or "", ""),
        "segment_color": config.SEGMENT_COLOR.get(lead.segment or "", "#94a3b8"),
        "country": lead.country,
        "flag": settings_store.country_flag(lead.country or ""),
        "city": lead.city,
        "street": lead.street,
        "website": lead.website,
        "phone": lead.phone,
        "email": lead.email,
        "field_staff": lead.field_staff,
        "score": lead.score,
        "status": lead.status,
        "company_id": lead.company_id,
        "search_id": lead.search_id,
    }


def _known(session: Session) -> set:
    """Names already in the pipeline, so a search cannot re-offer them."""
    return {(c.name or "").strip().lower()
            for c in session.exec(select(Company)).all()}


class BriefIn(BaseModel):
    brief: str


@router.post("/leads/search")
def run_search(payload: BriefIn, session: Session = Depends(get_session),
               user: User = Depends(current_user)):
    brief = (payload.brief or "").strip()
    if len(brief) < 4:
        raise HTTPException(status_code=400, detail="Say what you are looking for")

    # A search that cannot reach the map says so. There is nothing to stand in
    # with: every row on this list is a company somebody can ring up, and the
    # moment that stops being true the list is worth nothing.
    try:
        criteria, found = search(brief)
    except SearchFailed as error:
        raise HTTPException(status_code=502, detail=str(error))
    from_map = len(found)

    known = _known(session)
    existing = session.exec(select(Lead)).all()
    seen = {lead.osm_id for lead in existing}
    fresh = [row for row in found
             if row["osm_id"] not in seen and row["name"].strip().lower() not in known]
    # The second clamp, per country, because that is how the cap is written:
    # fifty from each country in the search, counted over every industry in it
    # together. The Overpass query already asks for no more than this, so
    # reaching it here means a mirror ignored the limit, which is exactly the
    # case a cap written in one place only does not cover.
    per_country = {}
    rows = []
    for row in fresh:
        code = row.get("country") or "??"
        if per_country.get(code, 0) >= config.LEAD_CAP_PER_COUNTRY:
            continue
        per_country[code] = per_country.get(code, 0) + 1
        rows.append(row)

    record = LeadSearch(
        brief=brief, summary=criteria.get("summary") or None,
        segments=",".join(criteria.get("segments") or []),
        cities=",".join(criteria.get("searched") or criteria.get("cities") or []),
        found=from_map, user_id=user.id,
    )
    session.add(record)
    session.commit()
    session.refresh(record)

    landed = 0
    for row in rows:
        if row["osm_id"] in seen:
            continue
        seen.add(row["osm_id"])
        landed += 1
        session.add(Lead(
            osm_id=row["osm_id"], name=row["name"], segment=row["segment"],
            country=row["country"], city=row["city"], street=row["street"],
            website=row["website"], phone=row["phone"], email=row["email"],
            score=row["score"], brief=brief, search_id=record.id,
            field_staff=row.get("field_staff"),
        ))
    record.kept = landed
    session.commit()

    return {
        "search_id": record.id,
        "found": from_map,
        "shown": landed,
        "already_known": max(0, from_map - len(fresh)),
        "limit": config.LEAD_CAP_PER_COUNTRY,
        "cap_per_country": config.LEAD_CAP_PER_COUNTRY,
        "countries": criteria.get("countries_searched", []),
        "skipped": [settings_store.country_label(c)
                    for c in criteria.get("skipped_countries", [])],
        "capped": any(n >= config.LEAD_CAP_PER_COUNTRY for n in per_country.values()),
        # Which source answered for each country. A country with an official
        # register is searched there; the rest come off the map. Worth showing,
        # because the two do not find the same companies and a rep comparing
        # two searches should be able to see which one they are reading.
        "sources": [{"country": settings_store.country_label(code),
                     "source": name}
                    for code, name in sorted(
                        (criteria.get("sources") or {}).items())],
        "criteria": {
            "segments": [config.SEGMENT_SHORT.get(s, s) for s in criteria["segments"]],
            "cities": criteria.get("searched", []) or criteria.get("cities", []),
            "summary": criteria.get("summary", ""),
        },
    }


@router.get("/leads/searches")
def list_searches(session: Session = Depends(get_session),
                  user: User = Depends(current_user)):
    """What has already been looked for, newest first."""
    records = session.exec(select(LeadSearch)).all()
    users = {u.id: u for u in session.exec(select(User)).all()}
    leads = session.exec(select(Lead)).all()

    added = {}
    for lead in leads:
        if lead.status == "added" and lead.search_id:
            added[lead.search_id] = added.get(lead.search_id, 0) + 1

    rows = []
    for record in sorted(records, key=lambda r: r.created_at, reverse=True)[:12]:
        keys = [k for k in (record.segments or "").split(",") if k]
        owner = users.get(record.user_id)
        rows.append({
            "id": record.id,
            "brief": record.brief,
            "cities": [c for c in (record.cities or "").split(",") if c],
            "segments": [{"key": k,
                          "short": config.SEGMENT_SHORT.get(k, k),
                          "color": config.SEGMENT_COLOR.get(k, "#94a3b8")}
                         for k in keys],
            "kept": record.kept,
            "added": added.get(record.id, 0),
            "by": owner.name.split(" ")[0] if owner else None,
            "when": record.created_at.isoformat(),
        })
    return {"searches": rows}


@router.get("/leads")
def list_leads(status: str = "new", segment: str = "", search_id: Optional[int] = None,
               session: Session = Depends(get_session),
               user: User = Depends(current_user)):
    leads = session.exec(select(Lead)).all()
    segments = {s for s in segment.split(",") if s}

    counts = {"new": 0, "added": 0, "dismissed": 0}
    rows = []
    for lead in leads:
        counts[lead.status] = counts.get(lead.status, 0) + 1
        if segments and lead.segment not in segments:
            continue
        if search_id and lead.search_id != search_id:
            continue
        if status and lead.status != status:
            continue
        rows.append(_row(lead))
    rows.sort(key=lambda row: -row["score"])

    by_segment = {}
    for row in rows:
        by_segment[row["segment_short"]] = by_segment.get(row["segment_short"], 0) + 1
    return {"rows": rows, "counts": counts, "by_segment": by_segment,
            "cap_per_country": config.LEAD_CAP_PER_COUNTRY}


@router.post("/leads/{lead_id}/add")
def add_to_pipeline(lead_id: int, session: Session = Depends(get_session),
                    user: User = Depends(current_user)):
    """Becomes a company and a deal at `lead`, on the desk that owns its industry."""
    lead = session.get(Lead, lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="No such lead")
    if lead.status == "added":
        raise HTTPException(status_code=400, detail="Already in the pipeline")

    owner = _push(session, lead, user)
    return {"lead": _row(lead), "company_id": lead.company_id,
            "owner": owner.name if owner else None}


def _push(session: Session, lead: Lead, user: User) -> Optional[User]:
    """The work of turning one lead into a company and a deal.

    Its own function because the floor adds leads one at a time and in bulk, and
    the two must put the same thing in the pipeline: same contact, same routing,
    same opening stage.
    """
    company = session.exec(
        select(Company).where(Company.name == lead.name)).first()
    if company is None:
        company = Company(
            name=lead.name, segment=lead.segment, country=lead.country,
            city=lead.city, website=lead.website, field_staff=lead.field_staff,
            source_channel="outbound_mail",
            notes="Found on OpenStreetMap: " + " ".join(
                part for part in [lead.street, lead.city] if part),
        )
        session.add(company)
        session.commit()
        session.refresh(company)

    # The mailbox came with the lead, so carry it across. Without a contact the
    # company lands in the pipeline unreachable, and the cold mail tab would have
    # nowhere to write to.
    contact = None
    if lead.email or lead.phone:
        contact = session.exec(
            select(Contact).where(Contact.company_id == company.id)).first()
        if contact is None:
            contact = Contact(
                company_id=company.id,
                # A role, never a person. The address and the number come off
                # the public map; who reads them is not ours to invent, and a
                # placeholder name would be indistinguishable from a real one
                # to everybody downstream.
                name="Main contact",
                role_title="Published contact details, no named person",
                email=lead.email, phone=lead.phone, is_primary=True,
            )
            session.add(contact)
            session.commit()
            session.refresh(contact)

    routed = owner_for_segment(session, company.segment)
    owner_id = routed.id if routed else user.id
    if company.owner_id is None:
        company.owner_id = owner_id
        session.add(company)

    deal = Deal(
        company_id=company.id,
        primary_contact_id=contact.id if contact else None,
        title=company.name + " - Sabertask rollout",
        worker_seats=STARTER_SEATS["worker"],
        planner_seats=STARTER_SEATS["planner"],
        admin_seats=STARTER_SEATS["admin"],
        worker_rate=config.SEAT_RATE["worker"],
        planner_rate=config.SEAT_RATE["planner"],
        admin_rate=config.SEAT_RATE["admin"],
        enterprise_rate=config.SEAT_RATE["enterprise"],
        stage="lead", channel="outbound_mail", owner_id=owner_id,
        notes="Found with a lead search, not spoken to yet.",
    )
    apply_standard_step(deal, "lead", {})
    session.add(deal)
    session.commit()
    session.refresh(deal)
    log_stage_event(session, deal, None, "lead", user.id)

    lead.status = "added"
    lead.company_id = company.id
    session.commit()
    return session.get(User, owner_id)


class AddAllIn(BaseModel):
    segment: str = ""
    search_id: Optional[int] = None


@router.post("/leads/add-all")
def add_all(payload: AddAllIn, session: Session = Depends(get_session),
            user: User = Depends(current_user)):
    """Everything still waiting on the review list, in one go.

    Scoped by whatever the rep is looking at, not by everything ever found: a
    button that quietly also adds the leads behind a filter is a button nobody
    trusts twice.
    """
    segments = {s for s in payload.segment.split(",") if s}
    leads = session.exec(select(Lead).where(Lead.status == "new")).all()

    owners = {}
    added = 0
    for lead in sorted(leads, key=lambda row: -row.score):
        if segments and lead.segment not in segments:
            continue
        if payload.search_id and lead.search_id != payload.search_id:
            continue
        owner = _push(session, lead, user)
        if owner:
            owners[owner.name.split(" ")[0]] = owners.get(owner.name.split(" ")[0], 0) + 1
        added += 1

    return {"added": added, "owners": owners}


@router.post("/leads/{lead_id}/dismiss")
def dismiss(lead_id: int, session: Session = Depends(get_session),
            user: User = Depends(current_user)):
    lead = session.get(Lead, lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="No such lead")
    lead.status = "dismissed"
    session.commit()
    return _row(lead)
