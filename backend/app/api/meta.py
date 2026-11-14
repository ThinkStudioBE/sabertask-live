"""One call that hands the SPA every catalogue it needs to render labels."""

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from .. import config, settings_store
from ..auth import current_user
from ..db import get_session
from ..models import User
from ..routing import segment_desk
from ..serializers import user_dict

router = APIRouter(prefix="/api", tags=["meta"])


@router.get("/meta")
def meta(session: Session = Depends(get_session), user: User = Depends(current_user)):
    team = session.exec(select(User).where(User.active == True)).all()  # noqa: E712
    return {
        "app": {
            "name": config.APP_NAME,
            "brand": config.BRAND,
            "tagline": config.TAGLINE,
            "trial_days": config.TRIAL_DAYS,
            "lead_cap_per_country": config.LEAD_CAP_PER_COUNTRY,
        },
        # Amounts travel in the base currency and are converted where they are
        # drawn, so this block is everything the frontend needs to render money.
        "currency": {
            "current": (user.currency or config.BASE_CURRENCY),
            "symbol": config.CURRENCY_BY_KEY.get(
                user.currency or config.BASE_CURRENCY,
                config.CURRENCY_BY_KEY[config.BASE_CURRENCY])["symbol"],
            "per_base": config.CURRENCY_BY_KEY.get(
                user.currency or config.BASE_CURRENCY,
                config.CURRENCY_BY_KEY[config.BASE_CURRENCY])["per_base"],
            "base": config.BASE_CURRENCY,
            "as_of": config.FX_DATE,
            "options": config.CURRENCIES,
        },
        "me": user_dict(user),
        "team": [user_dict(u) for u in team],
        "stages": config.STAGES,
        "extra_stages": config.EXTRA_STAGES,
        "board_stages": config.BOARD_STAGES,
        "stage_steps": config.STAGE_NEXT_STEP,
        "segments": config.SEGMENTS,
        "segment_desk": segment_desk(session),
        "countries": settings_store.countries(),
        "size_bands": config.SIZE_BANDS,
        "channels": config.CHANNELS,
        "note_kinds": config.NOTE_KINDS,
        "task_kinds": config.TASK_KINDS,
        "priorities": config.PRIORITIES,
        "lost_reasons": config.LOST_REASONS,
        "health_states": config.HEALTH_STATES,
        "seat_tiers": config.SEAT_TIERS,
        "plans": config.PLANS,
    }
