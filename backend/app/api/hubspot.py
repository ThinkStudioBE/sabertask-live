"""Connect, check and disconnect the customer's HubSpot.

The customer does all three from the Settings screen. Nothing here ever hands
a token back to a browser: the status is built by `hubspot.status()`, which is
a different shape from what is stored precisely so that cannot happen by
accident.
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session

from .. import hubspot
from ..auth import current_user
from ..db import get_session
from ..models import User

router = APIRouter(prefix="/api", tags=["hubspot"])


@router.get("/hubspot")
def read_status(session: Session = Depends(get_session),
                user: User = Depends(current_user)):
    return hubspot.status()


@router.post("/hubspot/connect")
def connect(session: Session = Depends(get_session),
            user: User = Depends(current_user)):
    """Where to send the customer. The browser does the rest."""
    if not hubspot.configured():
        raise HTTPException(
            status_code=400,
            detail="This installation has no HubSpot app keys yet, so there is "
                   "nothing to connect to. Set HUBSPOT_CLIENT_ID and "
                   "HUBSPOT_CLIENT_SECRET first.")
    return {"url": hubspot.authorize_url(hubspot.make_state(user.id))}


@router.post("/hubspot/check")
def check(session: Session = Depends(get_session),
          user: User = Depends(current_user)):
    """Ask HubSpot whether the stored connection still works. Stored is not the
    same as alive: a customer can revoke this app from their own side, and
    until somebody asks, both screens look identical."""
    try:
        return hubspot.check()
    except hubspot.HubSpotError as error:
        raise HTTPException(status_code=400, detail=str(error))


@router.post("/hubspot/disconnect")
def disconnect(session: Session = Depends(get_session),
               user: User = Depends(current_user)):
    hubspot.disconnect()
    return hubspot.status()


def _page(title: str, body: str, ok: bool) -> HTMLResponse:
    """The one screen in this app HubSpot itself sends somebody to, so it
    stands on its own: no session, no scripts, no app shell. It says what
    happened and offers the way back."""
    colour = "#1f9d55" if ok else "#b23c3c"
    return HTMLResponse(
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>" + title + "</title><style>"
        "body{margin:0;min-height:100vh;display:flex;align-items:center;"
        "justify-content:center;background:#f4f5f8;"
        "font:15px/1.6 -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;"
        "color:#23242a}"
        ".card{background:#fff;padding:34px 38px;border-radius:14px;max-width:460px;"
        "box-shadow:0 10px 40px rgba(20,22,40,.10)}"
        "h1{margin:0 0 10px;font-size:19px;color:" + colour + "}"
        "p{margin:0 0 18px;color:#5a5d68}"
        "a{display:inline-block;background:#4a5cb8;color:#fff;text-decoration:none;"
        "padding:10px 18px;border-radius:8px;font-weight:600}"
        "</style></head><body><div class='card'><h1>" + title + "</h1>"
        "<p>" + body + "</p>"
        "<a href='/'>Back to Sabertask Sales</a></div></body></html>",
        status_code=200 if ok else 400)


@router.get("/hubspot/callback")
def callback(request: Request, code: str = "", state: str = "",
             error: str = "", error_description: str = "",
             session: Session = Depends(get_session)):
    """Where HubSpot sends the customer back.

    Deliberately not behind the login. The customer may well have been bounced
    through a HubSpot login and come back with a stale session here, and
    throwing away an authorisation they already granted for that reason would
    be maddening. What proves this round trip is ours is the signed state,
    which is checked before anything is exchanged or stored.
    """
    if error:
        return _page("HubSpot was not connected",
                     (error_description or error)[:300], False)

    user_id = hubspot.read_state(state)
    if user_id is None:
        return _page("That link is not valid any more",
                     "Start the connection again from the Settings screen. A "
                     "connection link is only good for fifteen minutes.", False)
    if not code:
        return _page("HubSpot sent no authorisation",
                     "Nothing was connected. Try again from Settings.", False)

    who = session.get(User, user_id)
    try:
        state_after = hubspot.exchange(code, who.name if who else "")
    except hubspot.HubSpotError as error_out:
        return _page("HubSpot refused the connection", str(error_out)[:300], False)

    account = state_after.get("account") or ("portal " + str(state_after.get("portal_id")))
    return _page("HubSpot is connected",
                 "This installation is now connected to <strong>" + str(account)
                 + "</strong>. You can see it, test it and disconnect it again "
                   "under Settings.", True)


@router.get("/hubspot/callback/")
def callback_slash(request: Request, code: str = "", state: str = "",
                   error: str = "", error_description: str = "",
                   session: Session = Depends(get_session)):
    """HubSpot matches the redirect to the character, and a trailing slash is
    the kind of thing that gets typed into the app's settings by hand."""
    return callback(request, code, state, error, error_description, session)
