"""Quotes: a frozen snapshot of the commercials, and a page you can print."""

from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlmodel import Session, select

from .. import config
from ..auth import current_user
from ..db import get_session
from ..models import Company, Contact, Deal, Quote, User
from ..serializers import deal_acv, deal_mrr, quote_dict, seat_lines

router = APIRouter(tags=["quotes"])


def next_number(session: Session) -> str:
    year = date.today().year
    prefix = config.QUOTE_PREFIX + "-" + str(year) + "-"
    existing = session.exec(select(Quote).where(Quote.number.like(prefix + "%"))).all()
    highest = 0
    for quote in existing:
        try:
            highest = max(highest, int(quote.number.rsplit("-", 1)[1]))
        except (ValueError, IndexError):
            continue
    return prefix + str(highest + 1).zfill(4)


class QuoteIn(BaseModel):
    intro: Optional[str] = None
    terms: Optional[str] = None
    valid_days: int = config.QUOTE_VALID_DAYS


@router.post("/api/deals/{deal_id}/quotes")
def create_quote(deal_id: int, payload: QuoteIn,
                 session: Session = Depends(get_session),
                 user: User = Depends(current_user)):
    deal = session.get(Deal, deal_id)
    if deal is None:
        raise HTTPException(status_code=404, detail="No such deal")
    company = session.get(Company, deal.company_id)
    contact = session.get(Contact, deal.primary_contact_id) if deal.primary_contact_id else None

    quote = Quote(
        deal_id=deal.id,
        number=next_number(session),
        plan=deal.plan,
        worker_seats=deal.worker_seats,
        planner_seats=deal.planner_seats,
        admin_seats=deal.admin_seats,
        worker_rate=deal.worker_rate,
        planner_rate=deal.planner_rate,
        admin_rate=deal.admin_rate,
        contract_months=deal.contract_months,
        onboarding_fee=deal.onboarding_fee,
        mrr=deal_mrr(deal),
        acv=deal_acv(deal),
        company_name=company.name if company else "",
        contact_name=contact.name if contact else None,
        contact_email=contact.email if contact else None,
        valid_until=date.today() + timedelta(days=payload.valid_days),
        status="draft",
        intro=payload.intro or config.QUOTE_DEFAULT_INTRO,
        terms=payload.terms or config.QUOTE_DEFAULT_TERMS,
        created_by=user.id,
    )
    session.add(quote)
    session.commit()
    session.refresh(quote)
    return quote_dict(quote)


class QuotePatch(BaseModel):
    status: str


@router.patch("/api/quotes/{quote_id}")
def patch_quote(quote_id: int, payload: QuotePatch,
                session: Session = Depends(get_session),
                user: User = Depends(current_user)):
    quote = session.get(Quote, quote_id)
    if quote is None:
        raise HTTPException(status_code=404, detail="No such quote")
    if payload.status not in {"draft", "sent", "accepted", "declined"}:
        raise HTTPException(status_code=400, detail="Unknown status")
    quote.status = payload.status
    if payload.status == "sent" and quote.sent_at is None:
        quote.sent_at = datetime.utcnow()
    if payload.status in {"accepted", "declined"}:
        quote.decided_at = datetime.utcnow()
    session.add(quote)
    session.commit()
    session.refresh(quote)
    return quote_dict(quote)


# ------------------------------------------------------- the printable page ---

def _esc(text) -> str:
    return (str(text or "")
            .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


@router.get("/quote/{number}", response_class=HTMLResponse)
def quote_page(number: str, session: Session = Depends(get_session)):
    """Self-contained A4 page. Print to PDF: no PDF dependency anywhere."""
    quote = session.exec(select(Quote).where(Quote.number == number)).first()
    if quote is None:
        raise HTTPException(status_code=404, detail="No such quote")

    lines = []
    for key, seats, rate in (
        ("worker", quote.worker_seats, quote.worker_rate),
        ("planner", quote.planner_seats, quote.planner_rate),
        ("admin", quote.admin_seats, quote.admin_rate),
    ):
        if not seats:
            continue
        tier = next(t for t in config.SEAT_TIERS if t["key"] == key)
        lines.append(
            '<tr><td><strong>' + _esc(tier["label"]) + '</strong>'
            '<div class="sub">' + _esc(tier["audience"]) + ' &middot; ' + _esc(tier["includes"]) + '</div></td>'
            '<td class="num">' + str(seats) + '</td>'
            '<td class="num">' + config.money(rate) + '</td>'
            '<td class="num">' + config.money(seats * rate) + '</td></tr>'
        )
    if quote.onboarding_fee:
        lines.append(
            '<tr><td><strong>Onboarding &amp; data import</strong>'
            '<div class="sub">One-off: setup, import of your service agreements, on-site training</div></td>'
            '<td class="num">1</td><td class="num">' + config.money(quote.onboarding_fee) + '</td>'
            '<td class="num">' + config.money(quote.onboarding_fee) + '</td></tr>'
        )

    profile = config.SABERTASK_PROFILE
    seats_total = (quote.worker_seats or 0) + (quote.planner_seats or 0) + (quote.admin_seats or 0)

    html = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>""" + _esc(quote.number) + """ - Sabertask</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@500;700;800&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
<style>
  :root { --ink:#161c26; --brand:#4a5cb8; --muted:#7b818c; --line:#e2e8f0; --tint:#f0f2f9; }
  * { box-sizing:border-box; }
  body { margin:0; background:#f1f5f9; font-family:Inter,system-ui,sans-serif; color:var(--ink); }
  .bar { position:sticky; top:0; display:flex; gap:12px; justify-content:center;
         padding:14px; background:var(--ink); }
  .bar button, .bar a { font:600 14px Inter,sans-serif; padding:9px 18px; border-radius:9px;
         border:0; cursor:pointer; background:var(--brand); color:#fff; text-decoration:none; }
  .bar a { background:rgba(255,255,255,.12); }
  .page { width:210mm; min-height:297mm; margin:24px auto; background:#fff; padding:18mm 16mm;
          box-shadow:0 18px 50px rgba(10,15,24,.14); }
  header { display:flex; justify-content:space-between; align-items:flex-start;
           border-bottom:3px solid var(--brand); padding-bottom:16px; }
  .logo { font:800 30px 'Plus Jakarta Sans',sans-serif; letter-spacing:-.6px; }
  .logo span { color:var(--brand); }
  .meta { text-align:right; font-size:12px; color:var(--muted); line-height:1.7; }
  .meta .num { font:800 17px 'Plus Jakarta Sans',sans-serif; color:var(--ink); letter-spacing:.4px; }
  h1 { font:800 22px 'Plus Jakarta Sans',sans-serif; margin:28px 0 4px; }
  .to { font-size:13px; color:var(--muted); line-height:1.8; margin-bottom:22px; }
  .to strong { color:var(--ink); font-size:15px; }
  .intro { font-size:13.5px; line-height:1.75; color:#334155; background:var(--tint);
           border-left:3px solid var(--brand); padding:14px 16px; border-radius:0 8px 8px 0; }
  table { width:100%; border-collapse:collapse; margin:24px 0 0; font-size:13px; }
  th { text-align:left; font:600 11px Inter,sans-serif; text-transform:uppercase;
       letter-spacing:.9px; color:var(--muted); border-bottom:1px solid var(--line);
       padding:0 0 9px; }
  td { padding:13px 0; border-bottom:1px solid var(--line); vertical-align:top; }
  td.num, th.num { text-align:right; white-space:nowrap; padding-left:14px; }
  .sub { font-size:11.5px; color:var(--muted); margin-top:3px; max-width:330px; line-height:1.5; }
  .totals { margin-top:18px; margin-left:auto; width:62%; font-size:13.5px; }
  .totals div { display:flex; justify-content:space-between; padding:7px 0; }
  .totals .grand { border-top:2px solid var(--ink); margin-top:7px; padding-top:11px;
                   font:800 17px 'Plus Jakarta Sans',sans-serif; }
  .totals .mrr { background:var(--tint); margin:7px -12px 0; padding:11px 12px; border-radius:8px;
                 font:700 15px 'Plus Jakarta Sans',sans-serif; color:var(--brand); }
  .terms { margin-top:34px; font-size:11.5px; color:var(--muted); line-height:1.8; }
  .terms h3 { font:700 12px Inter,sans-serif; text-transform:uppercase; letter-spacing:.9px;
              color:var(--ink); margin:0 0 7px; }
  footer { margin-top:30px; padding-top:14px; border-top:1px solid var(--line);
           font-size:11px; color:var(--muted); display:flex; justify-content:space-between; }
  @media print {
    @page { size:A4; margin:0; }
    body { background:#fff; }
    .bar { display:none; }
    .page { margin:0; box-shadow:none; width:auto; min-height:auto; }
  }
</style></head><body>
<div class="bar">
  <button onclick="window.print()">Save as PDF</button>
  <a href="/">Back to the pipeline</a>
</div>
<div class="page">
  <header>
    <div>
      <div class="logo">Saber<span>task</span></div>
      <div class="meta" style="text-align:left;margin-top:6px">""" + _esc(config.TAGLINE) + """</div>
    </div>
    <div class="meta">
      <div class="num">""" + _esc(quote.number) + """</div>
      <div>Issued """ + quote.created_at.strftime("%d %B %Y") + """</div>
      <div>Valid until """ + quote.valid_until.strftime("%d %B %Y") + """</div>
    </div>
  </header>

  <h1>Subscription proposal</h1>
  <div class="to">
    <strong>""" + _esc(quote.company_name) + """</strong><br>
    """ + (_esc(quote.contact_name) + "<br>" if quote.contact_name else "") + """
    """ + (_esc(quote.contact_email) if quote.contact_email else "") + """
  </div>

  <div class="intro">""" + _esc(quote.intro) + """</div>

  <table>
    <thead><tr>
      <th>Role tier</th><th class="num">Users</th>
      <th class="num">Per user / month</th><th class="num">Monthly</th>
    </tr></thead>
    <tbody>""" + "".join(lines) + """</tbody>
  </table>

  <div class="totals">
    <div><span>Users in total</span><span>""" + str(seats_total) + """</span></div>
    <div><span>Contract term</span><span>""" + str(quote.contract_months) + """ months</span></div>
    <div class="mrr"><span>Monthly subscription</span><span>""" + config.money(quote.mrr) + """</span></div>
    <div class="grand"><span>Total over """ + str(quote.contract_months) + """ months</span>
      <span>""" + config.money(quote.acv) + """</span></div>
  </div>

  <div class="terms">
    <h3>Terms</h3>
    """ + _esc(quote.terms) + """
  </div>

  <footer>
    <span>""" + _esc(profile["legal_name"]) + """ &middot; """ + _esc(profile["address"]) + """</span>
    <span>""" + _esc(profile["email"]) + """ &middot; """ + _esc(profile["website"]) + """</span>
  </footer>
</div>
</body></html>"""
    return HTMLResponse(html)
