"""CSV in and out, on the standard library alone.

Import guesses the column mapping, previews it, and only then writes. Every
imported row lands as a company, a primary contact and a lead deal, routed to
the rep who owns that industry.

A prospecting export (Apollo and the like) is the file this is pointed at most
of the time, and it does not write the columns this app would ask for: the
city is buried in a one-line address, the country is spelled out, the industry
is a SIC code, and there is a LinkedIn URL sitting next to the website. All
four are read here, because a rep uploading his own list should not have to
rebuild it in a spreadsheet first. Nothing is guessed: a code we do not know
and an address we cannot read leave the field empty rather than wrong.
"""

import csv
import io
import re
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlmodel import Session, select

from .. import config, settings_store
from ..leadfinder import site_url
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
        reject = [r.lower() for r in field.get("reject", [])]
        free = [h for h in headers
                if h not in taken and not any(r in lowered[h] for r in reject)]
        for header in free:
            if lowered[header] in wanted:
                mapping[field["key"]] = header
                taken.add(header)
                break
        if field["key"] in mapping:
            continue
        for header in free:
            if any(alias in lowered[header] for alias in wanted):
                mapping[field["key"]] = header
                taken.add(header)
                break
    return mapping


# A postcode as the last part of an address, and one glued to the front of a
# city the way most of Europe writes it ("2000 Antwerpen"). A postcode has to
# carry a digit somewhere and be short: that is what keeps "M5H 2N2" out of the
# city field and leaves "Coconut Creek" in it.
TRAILING_POSTCODE = re.compile(r"^(?=.*[0-9])[A-Za-z0-9][A-Za-z0-9\- ]{2,9}$")
LEADING_POSTCODE = re.compile(r"^[0-9]{4,6}\s+")


def _country_code(value: Optional[str]) -> Optional[str]:
    """A country as a file writes it, turned into the code the app stores.

    The live set is read first, so a country added from Settings is understood
    here without a line of code, and `config.COUNTRY_ALIASES` only carries the
    spellings that do not match a label. This used to be `value.upper()[:2]`,
    which turned "United States" into the country UN.
    """
    text = (value or "").strip()
    if not text:
        return None
    lowered = text.lower()
    for row in settings_store.countries():
        if lowered in (row["label"].lower(), row["key"].lower()):
            return row["key"]
    code = config.COUNTRY_ALIASES.get(lowered)
    if code:
        return code
    if len(text) == 2 and text.isalpha():
        return text.upper()
    return None


def _from_address(address: Optional[str],
                  state_hint: Optional[str]):
    """(city, country) read off a one-line address, either one possibly None.

    Prospecting exports put the whole address in one cell: street, city, state,
    country, postcode, with the street and the state each missing as often as
    not. Reading it backwards is what makes that cell usable. Drop the
    postcode; take the country if the next part is one; drop the part after
    that if it is the state (the file's own state column settles it, and a list
    of states and provinces covers a file that has no such column); what is
    left at the end is the city.
    """
    parts = [p.strip() for p in (address or "").split(",") if p.strip()]
    if not parts:
        return None, None

    if TRAILING_POSTCODE.match(parts[-1]):
        parts.pop()

    country = None
    if parts:
        country = _country_code(parts[-1])
        if country:
            parts.pop()

    if parts:
        hint = (state_hint or "").strip().lower()
        last = parts[-1].lower()
        if (hint and last == hint) or last in config.STATE_NAMES:
            parts.pop()

    if not parts:
        return None, country
    city = LEADING_POSTCODE.sub("", parts[-1]).strip()
    # A single part carrying a number is a street, and a street is not a city.
    if not city or (len(parts) == 1 and any(ch.isdigit() for ch in city)):
        return None, country
    return city[:120], country


def _segment_from_sic(value: Optional[str]) -> Optional[str]:
    """The desk an activity code points at, or None.

    One cell can hold several codes ("7349, 7381"): the first that means
    something here wins. A code that means nothing here returns None rather
    than a guess, because the industry decides whose desk the lead lands on.
    """
    for raw in re.split(r"[^0-9]+", value or ""):
        if not raw:
            continue
        code = raw.zfill(4)[:4]
        if code in config.SIC_SEGMENT:
            return config.SIC_SEGMENT[code]
        if code[:2] in config.SIC_PUBLIC_PREFIXES:
            return "municipal"
    return None


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

        # The file's own industry column, then its activity code, then the
        # industry the importer was given. The code is the better authority of
        # the three that are in the file: it is what the company is registered
        # as, not what a column happens to be called.
        segment = (value(row, "segment")
                   or _segment_from_sic(value(row, "sic"))
                   or payload.default_segment or "").strip() or None
        if segment and segment not in config.SEGMENT_KEYS:
            # Accept the human label as well as the key.
            for key, label in config.SEGMENT_LABEL.items():
                if segment.lower() in (label.lower(), config.SEGMENT_SHORT[key].lower()):
                    segment = key
                    break
            else:
                segment = payload.default_segment

        city = value(row, "city")
        country = _country_code(value(row, "country"))
        if not city or not country:
            from_city, from_country = _from_address(value(row, "address"),
                                                    value(row, "state"))
            city = city or from_city
            country = country or from_country
        country = country or _country_code(payload.default_country)

        notes = value(row, "notes")
        if not notes:
            # What the file carries that has no column of its own. Written down
            # rather than dropped, and said to come from the file so nobody
            # reads it as something a rep found out.
            extra = []
            if value(row, "sic"):
                extra.append("SIC " + value(row, "sic"))
            if value(row, "revenue"):
                extra.append("annual revenue " + value(row, "revenue"))
            state = value(row, "state")
            if state and state.lower() != (city or "").lower():
                extra.append(state)
            if extra:
                notes = "From the import file: " + ", ".join(extra) + "."

        routed = owner_for_segment(session, segment)
        company = Company(
            name=name,
            website=site_url(value(row, "website")),
            segment=segment,
            country=country,
            city=city,
            field_staff=staff,
            notes=notes,
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
            settings_store.country_label(company.country or ""), company.city or "",
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
