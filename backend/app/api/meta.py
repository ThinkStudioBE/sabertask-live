"""One call that hands the SPA every catalogue it needs to render labels."""

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from .. import config
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
            "currency": config.CURRENCY,
            "symbol": config.CURRENCY_SYMBOL,
            "trial_days": config.TRIAL_DAYS,
        },
        "me": user_dict(user),
        "team": [user_dict(u) for u in team],
        "stages": config.STAGES,
        "extra_stages": config.EXTRA_STAGES,
        "board_stages": config.BOARD_STAGES,
        "stage_steps": config.STAGE_NEXT_STEP,
        "segments": config.SEGMENTS,
        "segment_desk": segment_desk(session),
        "countries": config.COUNTRIES,
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
