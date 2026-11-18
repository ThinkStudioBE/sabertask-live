"""Settings a person can change while the app runs.

Two of them, and they are different kinds of thing. The country set belongs to
the installation: it decides where searches may look, and `settings_store`
persists it so a country added here works in the very next search with no
restart. The reporting currency belongs to the person, so it lives on their
user row and changes nothing anybody else sees.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from .. import config, registers, settings_store
from ..auth import current_user
from ..db import get_session
from ..models import Company, Lead, User

router = APIRouter(prefix="/api", tags=["settings"])


def _currency_block(user: User) -> dict:
    spec = config.CURRENCY_BY_KEY.get(user.currency or config.BASE_CURRENCY,
                                      config.CURRENCY_BY_KEY[config.BASE_CURRENCY])
    return {
        "current": spec["key"],
        "symbol": spec["symbol"],
        "per_base": spec["per_base"],
        "base": config.BASE_CURRENCY,
        "as_of": config.FX_DATE,
        "options": config.CURRENCIES,
    }


@router.get("/settings")
def read_settings(session: Session = Depends(get_session),
                  user: User = Depends(current_user)):
    # How many records already lean on each country, so removing one is an
    # informed decision rather than a surprise.
    in_use = {}
    for row in session.exec(select(Company)).all():
        if row.country:
            in_use[row.country] = in_use.get(row.country, 0) + 1
    for row in session.exec(select(Lead)).all():
        if row.country:
            in_use[row.country] = in_use.get(row.country, 0) + 1

    countries = []
    for row in settings_store.countries():
        entry = dict(row)
        entry["in_use"] = in_use.get(row["key"], 0)
        # Which source a search will use here. Worth showing on the country
        # itself: adding a market says nothing about how well it can be
        # searched, and the two sources are not close in coverage.
        entry["register"] = registers.register_for(row["key"])
        countries.append(entry)

    return {
        "countries": countries,
        "currency": _currency_block(user),
        "lead_cap_per_country": config.LEAD_CAP_PER_COUNTRY,
    }


class CountryIn(BaseModel):
    code: str
    label: Optional[str] = None


@router.post("/settings/countries")
def add_country(payload: CountryIn, user: User = Depends(current_user)):
    try:
        row = settings_store.add_country(payload.code, payload.label)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))
    return row


@router.delete("/settings/countries/{code}")
def remove_country(code: str, user: User = Depends(current_user)):
    """Takes a country out of the search. Records already found there stay:
    they are real companies and deleting them to tidy a setting would be the
    wrong trade."""
    if len(settings_store.country_codes()) <= 1:
        raise HTTPException(status_code=400,
                            detail="Keep at least one country to search in")
    if not settings_store.remove_country(code):
        raise HTTPException(status_code=404, detail="Not in the list")
    return {"ok": True}


class CurrencyIn(BaseModel):
    currency: str


@router.patch("/settings/currency")
def set_currency(payload: CurrencyIn, session: Session = Depends(get_session),
                 user: User = Depends(current_user)):
    key = (payload.currency or "").strip().upper()
    if key not in config.CURRENCY_BY_KEY:
        raise HTTPException(status_code=400, detail="Not a currency this app knows")
    user.currency = key
    session.add(user)
    session.commit()
    session.refresh(user)
    return _currency_block(user)
