"""Reports. Every aggregation is done in Python: no raw SQL, no dialect traps."""

from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from .. import config
from ..auth import current_user
from ..db import get_session
from ..models import Client, Company, Deal, StageEvent, User
from ..routing import rep_segments
from ..serializers import deal_acv, deal_mrr, deal_weighted, user_dict

router = APIRouter(prefix="/api", tags=["reports"])


@router.get("/reports")
def reports(session: Session = Depends(get_session), user: User = Depends(current_user)):
    deals = session.exec(select(Deal)).all()
    companies = {c.id: c for c in session.exec(select(Company)).all()}
    users = session.exec(select(User).where(User.active == True)).all()  # noqa: E712
    events = session.exec(select(StageEvent)).all()
    clients = session.exec(select(Client)).all()

    open_deals = [d for d in deals if d.stage not in {"won", "lost"}]
    won = [d for d in deals if d.stage == "won"]
    lost = [d for d in deals if d.stage == "lost"]

    # ------------------------------------------------------------- funnel ---
    ever_reached = {}
    for event in events:
        ever_reached.setdefault(event.to_stage, set()).add(event.deal_id)
    funnel = []
    for stage in config.STAGES:
        here = [d for d in deals if d.stage == stage["key"]]
        reached = len(ever_reached.get(stage["key"], set()))
        funnel.append({
            "stage": stage["key"],
            "label": stage["label"],
            "count": len(here),
            "mrr": sum(deal_mrr(d) for d in here),
            "ever_reached": reached,
        })
    first = funnel[0]["ever_reached"] or 1
    for row in funnel:
        row["conversion"] = round(100.0 * row["ever_reached"] / first)

    # ---------------------------------------------- the industry breakdown ---
    # The floor is split by industry, so this is the report people actually
    # argue about: whose patch is producing and whose is not.
    owner_by_segment = {}
    for rep in users:
        for key in rep_segments(rep):
            owner_by_segment.setdefault(key, rep)

    by_segment = []
    for seg in config.SEGMENTS:
        seg_deals = [d for d in deals if (companies.get(d.company_id) or Company(name="")).segment == seg["key"]]
        seg_open = [d for d in seg_deals if d.stage not in {"won", "lost"}]
        seg_won = [d for d in seg_deals if d.stage == "won"]
        seg_lost = [d for d in seg_deals if d.stage == "lost"]
        decided = len(seg_won) + len(seg_lost)
        by_segment.append({
            "segment": seg["key"],
            "label": seg["label"],
            "short": seg["short"],
            "color": seg["color"],
            "owner": user_dict(owner_by_segment.get(seg["key"])),
            "open_count": len(seg_open),
            "open_mrr": sum(deal_mrr(d) for d in seg_open),
            "weighted": sum(deal_weighted(d) for d in seg_open),
            "won_count": len(seg_won),
            "won_mrr": sum(deal_mrr(d) for d in seg_won),
            "lost_count": len(seg_lost),
            "win_rate": round(100.0 * len(seg_won) / decided) if decided else None,
        })
    by_segment.sort(key=lambda r: -r["open_mrr"])

    # --------------------------------------------------------------- team ---
    team = []
    for rep in users:
        own = [d for d in deals if d.owner_id == rep.id]
        rep_open = [d for d in own if d.stage not in {"won", "lost"}]
        rep_won = [d for d in own if d.stage == "won"]
        rep_lost = [d for d in own if d.stage == "lost"]
        decided = len(rep_won) + len(rep_lost)
        team.append({
            "user": user_dict(rep),
            "segments": [
                {"short": config.SEGMENT_SHORT.get(k, k), "color": config.SEGMENT_COLOR.get(k, "#94a3b8")}
                for k in rep_segments(rep)
            ],
            "open_count": len(rep_open),
            "open_mrr": sum(deal_mrr(d) for d in rep_open),
            "weighted": sum(deal_weighted(d) for d in rep_open),
            "won_count": len(rep_won),
            "won_mrr": sum(deal_mrr(d) for d in rep_won),
            "win_rate": round(100.0 * len(rep_won) / decided) if decided else None,
        })
    team.sort(key=lambda r: -r["won_mrr"])

    # ------------------------------------------------------------ channel ---
    channels = []
    for channel in config.CHANNELS:
        own = [d for d in deals if d.channel == channel["key"]]
        if not own:
            continue
        ch_won = [d for d in own if d.stage == "won"]
        ch_lost = [d for d in own if d.stage == "lost"]
        decided = len(ch_won) + len(ch_lost)
        engaged = [d for d in own if d.stage not in {"lead", "contacted", "lost"}]
        channels.append({
            "channel": channel["key"],
            "label": channel["label"],
            "count": len(own),
            "engage_rate": round(100.0 * len(engaged) / len(own)),
            "win_rate": round(100.0 * len(ch_won) / decided) if decided else None,
            "won_mrr": sum(deal_mrr(d) for d in ch_won),
        })
    channels.sort(key=lambda r: -r["won_mrr"])

    # ----------------------------------------------------------- why lost ---
    reasons = {}
    for deal in lost:
        key = deal.lost_reason or "no_decision"
        bucket = reasons.setdefault(key, {
            "reason": key,
            "label": config.LOST_REASON_LABEL.get(key, key),
            "count": 0, "mrr": 0.0, "notes": [],
        })
        bucket["count"] += 1
        bucket["mrr"] += deal_mrr(deal)
        if deal.lost_reason_note:
            company = companies.get(deal.company_id)
            bucket["notes"].append({
                "company": company.name if company else "",
                "note": deal.lost_reason_note,
            })
    lost_rows = sorted(reasons.values(), key=lambda r: -r["count"])

    # -------------------------------------------------------- new MRR 12m ---
    today = date.today()
    months = []
    for back in range(11, -1, -1):
        month = today.month - back
        year = today.year + (month - 1) // 12
        month = (month - 1) % 12 + 1
        start = datetime(year, month, 1)
        end = datetime(year + (1 if month == 12 else 0), 1 if month == 12 else month + 1, 1)
        landed = [d for d in won if d.won_at and start <= d.won_at < end]
        months.append({
            "label": start.strftime("%b"),
            "year": year,
            "count": len(landed),
            "mrr": sum(deal_mrr(d) for d in landed),
        })

    # ------------------------------------------------------- days to win ---
    spans = [
        (d.won_at.date() - d.created_at.date()).days
        for d in won if d.won_at and d.created_at
    ]
    avg_days = round(sum(spans) / len(spans)) if spans else None

    decided_all = len(won) + len(lost)
    active_clients = [c for c in clients if c.status == "active"]

    return {
        "headline": {
            "open_count": len(open_deals),
            "open_mrr": sum(deal_mrr(d) for d in open_deals),
            "weighted": sum(deal_weighted(d) for d in open_deals),
            "pipeline_acv": sum(deal_acv(d) for d in open_deals),
            "won_count": len(won),
            "won_mrr": sum(deal_mrr(d) for d in won),
            "live_mrr": sum(c.mrr for c in active_clients),
            "win_rate": round(100.0 * len(won) / decided_all) if decided_all else None,
            "avg_days_to_win": avg_days,
        },
        "funnel": funnel,
        "by_segment": by_segment,
        "team": team,
        "channels": channels,
        "lost": lost_rows,
        "months": months,
    }
