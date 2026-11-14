"""CSV in and out, on the standard library alone.

Import guesses the column mapping, previews it, and only then writes. Every
imported row lands as a company, a primary contact and a lead deal, routed to
the rep who owns that industry.
"""

import csv
import io
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlmodel import Session, select

from .. import config
from ..auth import current_user
from ..db import get_session
from ..models import Client, Company, Contact, Deal, StageEvent, User
from ..routing import owner_for_segment

router = APIRouter(prefix="/api", tags=["transfer"])


def _read(raw: bytes):
    text = raw.decode("utf-8-sig", errors="replace")
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = ";" if sample.count(";") > sample.count(",") else ","
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    rows = []
    for index, row in enumerate(reader):
        if index >= config.IMPORT_MAX_ROWS:
            break
        rows.append(row)
    return reader.fieldnames or [], rows, delimiter


def _guess(headers):
    """Exact label, then exact alias, then alias as a substring."""
    mapping = {}
    taken = set()
    lowered = {h: (h or "").strip().lower() for h in headers}
    for field in config.IMPORT_FIELDS:
        wanted = [field["label"].lower()] + [a.lower() for a in field.get("aliases", [])]
        for header in headers:
            if header in taken:
                continue
            if lowered[header] in wanted:
                mapping[field["key"]] = header
                taken.add(header)
                break
        if field["key"] in mapping:
            continue
        for header in headers:
            if header in taken:
                continue
            if any(alias in lowered[header] for alias in wanted):
                mapping[field["key"]] = header
                taken.add(header)
                break
    return mapping


@router.post("/import/analyze")
async def analyze(file: UploadFile = File(...),
                  session: Session = Depends(get_session),
                  user: User = Depends(current_user)):
    headers, rows, delimiter = _read(await file.read())
    if not headers:
        raise HTTPException(status_code=400, detail="That file has no header row")
    return {
        "headers": headers,
        "delimiter": delimiter,
        "row_count": len(rows),
        "mapping": _guess(headers),
        "fields": config.IMPORT_FIELDS,
        "preview": rows[:5],
        # The parsed rows come back whole, so committing writes the file the
        # caller actually uploaded rather than the five rows it previewed.
        "rows": rows,
    }


class CommitIn(BaseModel):
    rows: list
    mapping: dict
    default_segment: Optional[str] = None
    default_country: Optional[str] = None


@router.post("/import/commit")
def commit(payload: CommitIn, session: Session = Depends(get_session),
           user: User = Depends(current_user)):
    mapping = payload.mapping or {}
    if not mapping.get("company_name"):
        raise HTTPException(status_code=400, detail="Map a column to the company name first")

    existing = {c.name.strip().lower(): c for c in session.exec(select(Company)).all()}
    created, skipped = 0, 0

    def value(row, key):
        column = mapping.get(key)
        if not column:
            return None
        got = (row.get(column) or "").strip()
        return got or None

    for row in payload.rows:
        name = value(row, "company_name")
        if not name:
            skipped += 1
            continue
        if name.strip().lower() in existing:
            skipped += 1
            continue

        staff = value(row, "field_staff")
        try:
            staff = int(str(staff).strip()) if staff else None
        except ValueError:
            staff = None

        segment = (value(row, "segment") or payload.default_segment or "").strip() or None
        if segment and segment not in config.SEGMENT_KEYS:
            # Accept the human label as well as the key.
            for key, label in config.SEGMENT_LABEL.items():
                if segment.lower() in (label.lower(), config.SEGMENT_SHORT[key].lower()):
                    segment = key
                    break
            else:
                segment = payload.default_segment

        routed = owner_for_segment(session, segment)
        company = Company(
            name=name,
            website=value(row, "website"),
            segment=segment,
            country=(value(row, "country") or payload.default_country or "").upper()[:2] or None,
            city=value(row, "city"),
            field_staff=staff,
            notes=value(row, "notes"),
            source_channel="outbound_mail",
            owner_id=routed.id if routed else user.id,
        )
        session.add(company)
        session.commit()
        session.refresh(company)
        existing[name.strip().lower()] = company

        contact_name = value(row, "contact_name")
        contact = None
        if contact_name:
            contact = Contact(
                company_id=company.id, name=contact_name,
                role_title=value(row, "contact_role"),
                email=value(row, "contact_email"),
                phone=value(row, "contact_phone"),
                is_primary=True,
            )
            session.add(contact)
            session.commit()
            session.refresh(contact)

        deal = Deal(
            company_id=company.id,
            primary_contact_id=contact.id if contact else None,
            title=company.name + " - Sabertask rollout",
            worker_seats=max(0, staff or 0),
            planner_seats=max(1, round((staff or 8) / 10)),
            admin_seats=2,
            stage="lead",
            channel="outbound_mail",
            owner_id=company.owner_id,
            next_action=config.STAGE_NEXT_STEP["lead"]["step"],
        )
        session.add(deal)
        session.commit()
        session.refresh(deal)
        session.add(StageEvent(deal_id=deal.id, to_stage="lead", user_id=user.id))
        session.commit()
        created += 1

    return {"created": created, "skipped": skipped}


@router.get("/export/contacts.csv")
def export_contacts(scope: str = "all", segment: str = "",
                    session: Session = Depends(get_session),
                    user: User = Depends(current_user)):
    companies = {c.id: c for c in session.exec(select(Company)).all()}
    users = {u.id: u for u in session.exec(select(User)).all()}
    clients = {c.company_id: c for c in session.exec(select(Client)).all()}
    deals = session.exec(select(Deal)).all()
    stage_by_company = {}
    for deal in deals:
        if deal.company_id not in stage_by_company or deal.stage not in {"won", "lost"}:
            stage_by_company[deal.company_id] = deal.stage
    segments = {s for s in segment.split(",") if s}

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(config.EXPORT_HEADERS)

    for contact in session.exec(select(Contact)).all():
        if not contact.email:
            continue  # a mailing list row without an address is noise
        company = companies.get(contact.company_id)
        if company is None:
            continue
        if segments and company.segment not in segments:
            continue
        is_client = company.id in clients and clients[company.id].status == "active"
        if scope == "customers" and not is_client:
            continue
        if scope == "prospects" and is_client:
            continue

        parts = contact.name.split()
        first = parts[0] if parts else ""
        last = " ".join(parts[1:]) if len(parts) > 1 else ""
        stage = stage_by_company.get(company.id, "")
        owner = users.get(company.owner_id)
        tags = ", ".join(filter(None, [
            "Sabertask customer" if is_client else "Sabertask prospect",
            config.STAGE_LABEL.get(stage, ""),
            config.SEGMENT_LABEL.get(company.segment or "", ""),
        ]))
        writer.writerow([
            contact.email, first, last, company.name,
            config.COUNTRY_LABEL.get(company.country or "", ""), company.city or "",
            config.SEGMENT_LABEL.get(company.segment or "", ""),
            config.STAGE_LABEL.get(stage, ""),
            owner.name if owner else "", tags,
        ])

    buffer.seek(0)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="sabertask-contacts.csv"'},
    )
