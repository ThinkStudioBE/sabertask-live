"""What goes into the customer's HubSpot, and what is left alone.

The customer keeps working in their own CRM. This sends what Sabertask knows
into it and then gets out of the way, under three rules that are the whole
design:

**Match before creating.** A company is looked up by its website domain and
then by its exact name, a contact by email address. A prospect that is already
in their CRM is updated, never duplicated. Duplicates are how an integration
quietly ruins a CRM, and they are nearly impossible to clean up afterwards.

**Never overwrite what they wrote.** Of HubSpot's own fields, only the empty
ones are filled. If their sales rep typed a phone number and ours has another,
theirs stays. The only fields written unconditionally are the ones this
integration owns, which carry the `sabertask_` prefix and exist for exactly
that reason.

**Say where it came from.** Every record this touches gets a link back to the
same prospect here, so somebody in HubSpot can see the connection rather than
wonder where a company came from. The ids come back the other way too, so a
rep here can open the record in HubSpot in one click.

Nothing in here may break the thing that triggered it. Adding a lead to the
pipeline has to work whether or not HubSpot answers, so every entry point
catches its own failures and leaves a reason on the connection instead.
"""

from typing import List, Optional, Tuple

import httpx
from sqlmodel import Session, select

from . import config, hubspot, settings_store
from .models import Company, Contact, Deal, User
from .serializers import deal_mrr, total_seats

API = "https://api.hubapi.com"

# The properties this integration owns. They are created once per portal, in
# their own group, so a HubSpot user can see at a glance which fields come from
# here and which are theirs.
GROUP = "sabertask"
COMPANY_PROPERTIES = [
    ("sabertask_url", "Sabertask record", "string"),
    ("sabertask_segment", "Sabertask industry desk", "string"),
    ("sabertask_field_staff", "People in the field", "number"),
    ("sabertask_fit", "Sabertask fit score", "number"),
]
DEAL_PROPERTIES = [
    ("sabertask_url", "Sabertask record", "string"),
    ("sabertask_seats", "Seats", "number"),
    ("sabertask_mrr", "Monthly recurring (base currency)", "number"),
]


class SyncError(Exception):
    """Something HubSpot refused, in words worth showing."""


# ------------------------------------------------------------------- plumbing ---

def _call(method: str, path: str, payload: Optional[dict] = None,
          params: Optional[dict] = None) -> Optional[dict]:
    token = hubspot.access_token()
    try:
        response = httpx.request(
            method, API + path, timeout=25.0, json=payload, params=params,
            headers={"Authorization": "Bearer " + token,
                     "Content-Type": "application/json"})
    except httpx.HTTPError as error:
        raise SyncError("HubSpot could not be reached: " + type(error).__name__)
    if response.status_code == 404:
        return None
    if response.status_code >= 400:
        try:
            message = response.json().get("message") or ""
        except ValueError:
            message = ""
        raise SyncError(message[:250] or ("HubSpot refused the request ("
                                          + str(response.status_code) + ")"))
    if not response.content:
        return {}
    try:
        return response.json()
    except ValueError:
        return {}


def _domain(website: Optional[str]) -> Optional[str]:
    if not website:
        return None
    host = str(website).split("//")[-1].split("/")[0].lower()
    host = host.split("@")[-1].split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    return host or None


def _record_url(kind: str, local_id) -> str:
    """Back to the same prospect here. A HubSpot user clicking this lands on
    the record that caused theirs to exist."""
    return config.PUBLIC_URL.rstrip("/") + "/#" + kind + "/" + str(local_id)


def portal_url(kind: str, hubspot_id: str) -> Optional[str]:
    """The other direction: the record in their HubSpot, for a button here."""
    portal = hubspot.status().get("portal_id")
    if not portal or not hubspot_id:
        return None
    return ("https://app.hubspot.com/contacts/" + str(portal) + "/" + kind
            + "/" + str(hubspot_id))


# ---------------------------------------------------------------- properties ---

def ensure_properties() -> None:
    """Create this integration's own fields, once per portal.

    Idempotent on purpose: HubSpot answers with a conflict when the property is
    already there, and that is a success as far as this is concerned.
    """
    done = settings_store.get("hubspot_properties") or {}
    portal = str(hubspot.status().get("portal_id") or "")
    if done.get(portal):
        return

    try:
        _call("POST", "/crm/v3/properties/companies/groups",
              {"name": GROUP, "label": "Sabertask"})
    except SyncError:
        pass        # already there, or this portal does not allow groups
    try:
        _call("POST", "/crm/v3/properties/deals/groups",
              {"name": GROUP, "label": "Sabertask"})
    except SyncError:
        pass

    for object_type, properties in (("companies", COMPANY_PROPERTIES),
                                    ("deals", DEAL_PROPERTIES)):
        for name, label, kind in properties:
            try:
                _call("POST", "/crm/v3/properties/" + object_type, {
                    "name": name, "label": label, "type": kind,
                    "fieldType": "number" if kind == "number" else "text",
                    "groupName": GROUP,
                })
            except SyncError:
                pass    # a property that already exists is the state we want

    done[portal] = True
    settings_store.put("hubspot_properties", done)


# -------------------------------------------------------------------- lookups ---

def _search(object_type: str, prop: str, value: str) -> Optional[str]:
    """Their record for this company or person, if they already have one."""
    if not value:
        return None
    payload = {"limit": 1, "properties": ["hs_object_id"], "filterGroups": [
        {"filters": [{"propertyName": prop, "operator": "EQ", "value": value}]}]}
    found = _call("POST", "/crm/v3/objects/" + object_type + "/search", payload)
    results = (found or {}).get("results") or []
    return str(results[0]["id"]) if results else None


def _existing(object_type: str, hubspot_id: Optional[str]) -> Optional[dict]:
    if not hubspot_id:
        return None
    return _call("GET", "/crm/v3/objects/" + object_type + "/" + str(hubspot_id),
                 params={"properties": "name,domain,city,country,phone,"
                                       "website,email,firstname,lastname"})


def _only_empty(current: Optional[dict], wanted: dict) -> dict:
    """Their data wins. Ours fills the gaps.

    The properties this integration owns are exempt: those are ours to keep
    current, and nobody in HubSpot is typing into them by hand.
    """
    if current is None:
        return wanted
    have = (current.get("properties") or {})
    out = {}
    for key, value in wanted.items():
        if value in (None, ""):
            continue
        if key.startswith("sabertask_") or not str(have.get(key) or "").strip():
            out[key] = value
    return out


# --------------------------------------------------------------------- push ---

def push_company(session: Session, company: Company, fit: Optional[int] = None) -> str:
    domain = _domain(company.website)
    hubspot_id = company.hubspot_id
    if not hubspot_id and domain:
        hubspot_id = _search("companies", "domain", domain)
    if not hubspot_id:
        hubspot_id = _search("companies", "name", company.name)

    wanted = {
        "name": company.name,
        "domain": domain,
        "website": company.website,
        "city": company.city,
        "country": settings_store.country_label(company.country or "",
                                                company.country or ""),
        "sabertask_url": _record_url("company", company.id),
        "sabertask_segment": config.SEGMENT_LABEL.get(company.segment or "", ""),
        "sabertask_field_staff": company.field_staff,
        "sabertask_fit": fit,
    }
    current = _existing("companies", hubspot_id)
    if hubspot_id and current is None:
        hubspot_id = None       # deleted on their side; make a fresh one
    properties = _only_empty(current, wanted)

    if hubspot_id:
        if properties:
            _call("PATCH", "/crm/v3/objects/companies/" + hubspot_id,
                  {"properties": properties})
    else:
        created = _call("POST", "/crm/v3/objects/companies",
                        {"properties": properties})
        hubspot_id = str((created or {}).get("id") or "")

    if hubspot_id and company.hubspot_id != hubspot_id:
        company.hubspot_id = hubspot_id
        session.add(company)
    return hubspot_id


def push_contact(session: Session, contact: Contact, company_hubspot_id: str) -> Optional[str]:
    """A desk mailbox is a contact too: it is how the customer reaches them."""
    if not contact or not contact.email:
        return None
    hubspot_id = contact.hubspot_id or _search("contacts", "email", contact.email)
    name = (contact.name or "").strip()
    first, _, last = name.partition(" ")
    wanted = {
        "email": contact.email,
        "firstname": first or name,
        "lastname": last or None,
        "jobtitle": contact.role_title,
        "phone": contact.phone,
    }
    current = _existing("contacts", hubspot_id)
    if hubspot_id and current is None:
        hubspot_id = None
    properties = _only_empty(current, wanted)

    if hubspot_id:
        if properties:
            _call("PATCH", "/crm/v3/objects/contacts/" + hubspot_id,
                  {"properties": properties})
    else:
        created = _call("POST", "/crm/v3/objects/contacts", {"properties": properties})
        hubspot_id = str((created or {}).get("id") or "")

    if hubspot_id:
        if contact.hubspot_id != hubspot_id:
            contact.hubspot_id = hubspot_id
            session.add(contact)
        _associate("contact", hubspot_id, "company", company_hubspot_id)
    return hubspot_id


def _associate(from_type: str, from_id: str, to_type: str, to_id: str) -> None:
    if not (from_id and to_id):
        return
    try:
        _call("PUT", "/crm/v4/objects/" + from_type + "/" + from_id
              + "/associations/default/" + to_type + "/" + to_id)
    except SyncError:
        pass    # an association that already exists is the state we want


# Our stages, in the order a deal moves through them. Mapped onto whatever the
# customer's own pipeline looks like by position, because no two CRMs name
# these the same and theirs is the one that is right for them.
def _stage_map() -> Tuple[Optional[str], dict]:
    pipelines = _call("GET", "/crm/v3/pipelines/deals") or {}
    results = pipelines.get("results") or []
    if not results:
        return None, {}
    pipeline = results[0]
    stages = sorted(pipeline.get("stages") or [],
                    key=lambda row: row.get("displayOrder", 0))
    if not stages:
        return pipeline.get("id"), {}

    won = next((s["id"] for s in stages
                if (s.get("metadata") or {}).get("isClosed") == "true"
                and float((s.get("metadata") or {}).get("probability", 0)) >= 1), None)
    lost = next((s["id"] for s in stages
                 if (s.get("metadata") or {}).get("isClosed") == "true"
                 and float((s.get("metadata") or {}).get("probability", 1)) <= 0), None)
    open_stages = [s["id"] for s in stages
                   if (s.get("metadata") or {}).get("isClosed") != "true"] or [stages[0]["id"]]

    ours = [key for key in config.STAGE_LABEL if key not in ("won", "lost")]
    mapping = {}
    for index, key in enumerate(ours):
        # Spread our stages over theirs by position: a pipeline with three
        # stages gets our seven mapped onto it in order rather than crammed
        # into the first one.
        slot = min(len(open_stages) - 1,
                   int(index * len(open_stages) / max(1, len(ours))))
        mapping[key] = open_stages[slot]
    mapping["won"] = won or open_stages[-1]
    mapping["lost"] = lost or open_stages[-1]
    return pipeline.get("id"), mapping


def push_deal(session: Session, deal: Deal, company: Company,
              company_hubspot_id: str, contact_hubspot_id: Optional[str],
              stages: Optional[Tuple[Optional[str], dict]] = None) -> str:
    pipeline_id, mapping = stages if stages is not None else _stage_map()
    hubspot_id = deal.hubspot_id
    wanted = {
        "dealname": company.name + " - " + (deal.title or "Sabertask"),
        "amount": round(deal_mrr(deal) * max(1, deal.contract_months or 12), 2),
        "sabertask_url": _record_url("deal", deal.id),
        "sabertask_seats": total_seats(deal),
        "sabertask_mrr": round(deal_mrr(deal), 2),
    }
    if pipeline_id:
        wanted["pipeline"] = pipeline_id
    if mapping.get(deal.stage):
        wanted["dealstage"] = mapping[deal.stage]
    if deal.expected_close_date:
        wanted["closedate"] = deal.expected_close_date.isoformat()

    current = _existing("deals", hubspot_id)
    if hubspot_id and current is None:
        hubspot_id = None
    # The stage is ours to keep current: a deal that moves here should move
    # there, otherwise the two pipelines drift apart within a week.
    properties = _only_empty(current, wanted)
    if "dealstage" in wanted:
        properties["dealstage"] = wanted["dealstage"]

    if hubspot_id:
        if properties:
            _call("PATCH", "/crm/v3/objects/deals/" + hubspot_id,
                  {"properties": properties})
    else:
        created = _call("POST", "/crm/v3/objects/deals", {"properties": properties})
        hubspot_id = str((created or {}).get("id") or "")

    if hubspot_id:
        if deal.hubspot_id != hubspot_id:
            deal.hubspot_id = hubspot_id
            session.add(deal)
        _associate("deal", hubspot_id, "company", company_hubspot_id)
        if contact_hubspot_id:
            _associate("deal", hubspot_id, "contact", contact_hubspot_id)
    return hubspot_id


# ------------------------------------------------------------- entry points ---

def _remember(error: Optional[str]) -> None:
    data = settings_store.get(hubspot.SETTING_KEY) or {}
    if not data:
        return
    if error:
        data["sync_error"] = error[:250]
    else:
        data.pop("sync_error", None)
    settings_store.put(hubspot.SETTING_KEY, data)


def connected() -> bool:
    return bool(hubspot.status().get("connected"))


def push_one(session: Session, deal: Deal, fit: Optional[int] = None,
             stages=None) -> None:
    """One prospect, company first so the deal has something to hang on."""
    company = session.get(Company, deal.company_id)
    if company is None:
        return
    ensure_properties()
    company_id = push_company(session, company, fit)
    contact = session.exec(
        select(Contact).where(Contact.company_id == company.id)).first()
    contact_id = push_contact(session, contact, company_id) if contact else None
    push_deal(session, deal, company, company_id, contact_id, stages)
    session.commit()


def push_quietly(session: Session, deal: Deal, fit: Optional[int] = None) -> None:
    """For the moment a rep adds a lead to the pipeline.

    Never raises. Adding a lead has to work whether or not a CRM somewhere is
    answering, so a failure here is remembered on the connection and shown on
    the Settings screen rather than thrown at somebody who was doing something
    else entirely.
    """
    if not connected():
        return
    try:
        push_one(session, deal, fit)
        _remember(None)
    except (SyncError, hubspot.HubSpotError) as error:
        session.rollback()
        _remember(str(error))
        print("[hubspot] " + str(error)[:200])


def sync_all(session: Session) -> dict:
    """Everything here into their CRM: prospects and existing clients both.

    The clients matter as much as the prospects. A CRM that holds only what
    Sabertask is still chasing, and not who already pays them, is a CRM their
    people will stop trusting within a month.
    """
    if not connected():
        raise SyncError("No HubSpot account is connected.")
    ensure_properties()
    stages = _stage_map()
    done = 0
    failed = []
    for deal in session.exec(select(Deal)).all():
        try:
            push_one(session, deal, None, stages)
            done += 1
        except (SyncError, hubspot.HubSpotError) as error:
            session.rollback()
            failed.append(str(error)[:120])
    _remember(failed[0] if failed else None)
    return {"synced": done, "failed": len(failed),
            "first_error": failed[0] if failed else None}
