"""SQLModel tables for Sabertask Sales.

Deliberately plain: every column is an int, str, float, bool, date or datetime
and the relations are foreign keys that the API joins in Python. That keeps the
module readable on Python 3.9, where `from __future__ import annotations`
together with SQLModel relationships is a known trap.
"""

from datetime import date, datetime
from typing import Optional

from sqlmodel import Field, SQLModel


def utcnow():
    return datetime.utcnow()


class User(SQLModel, table=True):
    """A Sabertask sales rep. Deals have an owner, reports break down per rep."""

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    email: str = Field(index=True, unique=True)
    password_hash: str
    title: Optional[str] = None
    role: str = Field(default="rep")  # rep | manager
    initials: Optional[str] = None
    color: str = Field(default="#4a5cb8")
    # What this person reads amounts in. Display only: every figure is
    # stored in the base currency, so two people can read one pipeline in
    # different money without either of them changing it.
    currency: str = Field(default="DKK")
    # Which industries this rep owns, as a comma-separated list of SEGMENTS keys.
    # The sales floor is split by industry, so this is what decides where a new
    # lead is routed. A manager leaves it empty and sees everything.
    segments: Optional[str] = None
    active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=utcnow)


class Company(SQLModel, table=True):
    """A prospect organisation. The field-service specifics (how many people in
    the field, how many sites they serve) are what the seat count is argued from."""

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    website: Optional[str] = None
    segment: Optional[str] = None       # a SEGMENTS key
    country: Optional[str] = None       # a COUNTRIES key
    city: Optional[str] = None
    size_band: Optional[str] = None     # a SIZE_BANDS key
    field_staff: Optional[int] = None   # people who would carry the mobile app
    sites: Optional[int] = None         # buildings / routes / sites serviced
    language: Optional[str] = None
    source_channel: Optional[str] = None
    current_tool: Optional[str] = None  # what they run today, the thing we displace
    notes: Optional[str] = None
    owner_id: Optional[int] = Field(default=None, foreign_key="user.id")
    # The same organisation in the customer's own CRM. Stored rather than
    # looked up every time, because it is what keeps a second sync from
    # creating a second company beside the one it made last week.
    hubspot_id: Optional[str] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class Contact(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="company.id", index=True)
    name: str
    role_title: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    is_primary: bool = Field(default=False)
    hubspot_id: Optional[str] = Field(default=None, index=True)
    notes: Optional[str] = None
    created_at: datetime = Field(default_factory=utcnow)


class Deal(SQLModel, table=True):
    """A subscription opportunity.

    Value is never a one-off number: seats on each role tier times that tier's
    rate gives MRR, and everything else (ACV, weighted forecast) is derived from
    it. The rates are stored on the deal so a discount survives a price change.
    """

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="company.id", index=True)
    primary_contact_id: Optional[int] = Field(default=None, foreign_key="contact.id")
    title: str

    plan: str = Field(default="standard")          # derived: enterprise seats -> enterprise
    worker_seats: int = Field(default=0)
    planner_seats: int = Field(default=0)
    admin_seats: int = Field(default=0)
    enterprise_seats: int = Field(default=0)
    worker_rate: float = Field(default=69.0)
    planner_rate: float = Field(default=139.0)
    admin_rate: float = Field(default=279.0)
    enterprise_rate: float = Field(default=0.0)    # "Custom" on their price list
    contract_months: int = Field(default=12)
    onboarding_fee: float = Field(default=0.0)

    hubspot_id: Optional[str] = Field(default=None, index=True)
    stage: str = Field(default="lead", index=True)
    probability: Optional[int] = None              # override; else the stage default
    channel: str = Field(default="outbound_mail")
    owner_id: Optional[int] = Field(default=None, foreign_key="user.id", index=True)

    next_action: Optional[str] = None
    next_action_date: Optional[date] = Field(default=None, index=True)
    last_touch_at: Optional[datetime] = None
    touch_count: int = Field(default=0)

    trial_started_on: Optional[date] = None
    expected_close_date: Optional[date] = None
    lost_reason: Optional[str] = None
    lost_reason_note: Optional[str] = None
    notes: Optional[str] = None

    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    stage_changed_at: datetime = Field(default_factory=utcnow)
    won_at: Optional[datetime] = None
    lost_at: Optional[datetime] = None


class StageEvent(SQLModel, table=True):
    """Every stage move, so the funnel report can count deals that ever reached a
    stage rather than only the ones sitting in it right now."""

    id: Optional[int] = Field(default=None, primary_key=True)
    deal_id: int = Field(foreign_key="deal.id", index=True)
    from_stage: Optional[str] = None
    to_stage: str
    mrr: float = Field(default=0.0)
    user_id: Optional[int] = Field(default=None, foreign_key="user.id")
    created_at: datetime = Field(default_factory=utcnow)


class Note(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    deal_id: int = Field(foreign_key="deal.id", index=True)
    user_id: Optional[int] = Field(default=None, foreign_key="user.id")
    kind: str = Field(default="note")
    body: str
    created_at: datetime = Field(default_factory=utcnow)


class Task(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    title: str
    kind: str = Field(default="todo")
    priority: str = Field(default="normal")
    due_date: Optional[date] = Field(default=None, index=True)
    owner_id: Optional[int] = Field(default=None, foreign_key="user.id", index=True)
    deal_id: Optional[int] = Field(default=None, foreign_key="deal.id", index=True)
    company_id: Optional[int] = Field(default=None, foreign_key="company.id")
    client_id: Optional[int] = Field(default=None, foreign_key="client.id", index=True)
    notes: Optional[str] = None
    done: bool = Field(default=False, index=True)
    done_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=utcnow)


class Quote(SQLModel, table=True):
    """An immutable snapshot of a deal's commercials at the moment it was sent.

    Editing the deal afterwards must never rewrite a document a customer is
    holding, so every figure is copied in rather than looked up.
    """

    id: Optional[int] = Field(default=None, primary_key=True)
    deal_id: int = Field(foreign_key="deal.id", index=True)
    number: str = Field(index=True, unique=True)
    plan: str
    worker_seats: int
    planner_seats: int
    admin_seats: int
    enterprise_seats: int = Field(default=0)
    worker_rate: float
    planner_rate: float
    admin_rate: float
    enterprise_rate: float = Field(default=0.0)
    contract_months: int
    onboarding_fee: float = Field(default=0.0)
    mrr: float
    acv: float
    company_name: str
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    valid_until: date
    status: str = Field(default="draft")  # draft | sent | accepted | declined
    intro: Optional[str] = None
    terms: Optional[str] = None
    sent_at: Optional[datetime] = None
    decided_at: Optional[datetime] = None
    created_by: Optional[int] = Field(default=None, foreign_key="user.id")
    created_at: datetime = Field(default_factory=utcnow)


class Client(SQLModel, table=True):
    """A won deal, after the handover. Opened automatically the moment a deal
    reaches `won`, so nothing has to be re-keyed."""

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="company.id", index=True)
    deal_id: Optional[int] = Field(default=None, foreign_key="deal.id", index=True)
    mrr: float = Field(default=0.0)
    seats: int = Field(default=0)
    started_on: Optional[date] = None
    go_live_on: Optional[date] = None
    next_meeting_date: Optional[date] = Field(default=None, index=True)
    last_meeting_on: Optional[date] = None
    health: str = Field(default="green")
    owner_id: Optional[int] = Field(default=None, foreign_key="user.id")
    status: str = Field(default="active", index=True)  # active | churned
    churned_on: Optional[date] = None
    churn_reason: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class Meeting(SQLModel, table=True):
    """A logged post-sale check-in. Writing one rolls the client's next meeting
    date forward a month and restates their health."""

    id: Optional[int] = Field(default=None, primary_key=True)
    client_id: int = Field(foreign_key="client.id", index=True)
    held_on: date
    summary: Optional[str] = None
    actions: Optional[str] = None
    health: Optional[str] = None
    user_id: Optional[int] = Field(default=None, foreign_key="user.id")
    created_at: datetime = Field(default_factory=utcnow)


class MailDraft(SQLModel, table=True):
    """A cold mail for one deal: drafted here, sent by hand, logged on the way back.

    One row per deal, rewritten when a rep asks for a new draft. The body a rep
    edited is theirs, so a redraft only overwrites it when they ask for one.
    """

    id: Optional[int] = Field(default=None, primary_key=True)
    deal_id: int = Field(foreign_key="deal.id", index=True, unique=True)
    company_id: int = Field(foreign_key="company.id", index=True)
    to_name: Optional[str] = None
    to_email: Optional[str] = None
    subject: str = Field(default="")
    body: str = Field(default="")
    written_by: str = Field(default="template")   # template | claude | rep
    status: str = Field(default="draft", index=True)  # draft | sent | skipped
    edited: bool = Field(default=False)
    sent_at: Optional[datetime] = None
    skipped_reason: Optional[str] = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class Lead(SQLModel, table=True):
    """A company found on the map, before anybody decided it is worth a deal.

    Kept apart from `Company` on purpose: a search turns up names nobody has
    looked at yet, and letting those straight into the pipeline would mean the
    floor's numbers include whatever OpenStreetMap happened to hold that day.
    """

    id: Optional[int] = Field(default=None, primary_key=True)
    osm_id: str = Field(index=True)
    name: str
    segment: str = Field(default="facility", index=True)
    country: Optional[str] = None
    city: Optional[str] = None
    street: Optional[str] = None
    website: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    field_staff: Optional[int] = None
    score: int = Field(default=0, index=True)
    brief: Optional[str] = None
    search_id: Optional[int] = Field(default=None, foreign_key="leadsearch.id", index=True)
    status: str = Field(default="new", index=True)   # new | added | dismissed
    company_id: Optional[int] = Field(default=None, foreign_key="company.id")
    found_at: datetime = Field(default_factory=utcnow)


class LeadSearch(SQLModel, table=True):
    """One search, kept so the floor can see what has already been looked for.

    Two reps asking the same thing a week apart is wasted work, and a lead on
    its own does not say which brief turned it up.
    """

    id: Optional[int] = Field(default=None, primary_key=True)
    brief: str
    summary: Optional[str] = None
    segments: Optional[str] = None     # csv of industry keys
    cities: Optional[str] = None       # csv of the places actually searched
    found: int = Field(default=0)      # what the map returned
    kept: int = Field(default=0)       # what ended up on the review list
    user_id: Optional[int] = Field(default=None, foreign_key="user.id")
    created_at: datetime = Field(default_factory=utcnow)


class RegisterCompany(SQLModel, table=True):
    """One company out of a country's official business register.

    Loaded from a published extract rather than fetched per search, because the
    countries that publish their register as a file do not also offer a query
    API: Belgium's is a four-gigabyte download. Filtered to the six industries
    this app sells into it is about thirty thousand rows, which is small enough
    to keep here and search in milliseconds.

    Countries whose register answers live (Norway, Finland) are not in this
    table at all. They are asked at search time, so their rows are never stale.

    `source` carries which extract this came from and when, because a register
    file is a snapshot: a company that closed last week is still in it, and a
    rep deserves to know how old the list is.
    """

    id: Optional[int] = Field(default=None, primary_key=True)
    country: str = Field(index=True)
    reg_id: str = Field(index=True)          # the official company number
    name: str
    nace: Optional[str] = None               # the register's own activity code
    segment: str = Field(default="facility", index=True)
    zipcode: Optional[str] = None
    city: Optional[str] = Field(default=None, index=True)
    street: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    website: Optional[str] = None
    source: Optional[str] = None


class AppSetting(SQLModel, table=True):
    """Settings somebody edited, kept in the database rather than in a file.

    The host this runs on has an ephemeral filesystem, so a JSON file next to
    the code would quietly reset the country set on every restart. The database
    is the one place that survives, so that is where it goes.
    """

    key: str = Field(primary_key=True)
    value: str = Field(default="")          # JSON
    updated_at: datetime = Field(default_factory=utcnow)
