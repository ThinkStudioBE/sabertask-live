"""Which rep gets a lead.

The sales floor is split by industry: every segment has exactly one rep who
owns it, declared on `User.segments`. Anything that creates a company or a deal
without naming an owner routes through here, so a lead can never arrive
unassigned and a rep never has to hunt through someone else's industry.
"""

from typing import List, Optional

from sqlmodel import Session, select

from . import config
from .models import User


def rep_segments(user: User) -> List[str]:
    if not user.segments:
        return []
    return [s.strip() for s in user.segments.split(",") if s.strip()]


def owner_for_segment(session: Session, segment: Optional[str]) -> Optional[User]:
    """The rep who owns this industry, or None if nobody claims it."""
    if not segment:
        return None
    reps = session.exec(select(User).where(User.active == True)).all()  # noqa: E712
    for rep in reps:
        if segment in rep_segments(rep):
            return rep
    return None


def segment_desk(session: Session):
    """[{segment, label, short, color, owner}] - the industry-to-rep map the UI
    shows so everyone can see at a glance whose desk an industry sits on."""
    reps = session.exec(select(User).where(User.active == True)).all()  # noqa: E712
    owner_by_segment = {}
    for rep in reps:
        for key in rep_segments(rep):
            owner_by_segment.setdefault(key, rep)

    from .serializers import user_dict

    desk = []
    for seg in config.SEGMENTS:
        owner = owner_by_segment.get(seg["key"])
        desk.append({
            "segment": seg["key"],
            "label": seg["label"],
            "short": seg["short"],
            "color": seg["color"],
            "owner": user_dict(owner),
        })
    return desk
