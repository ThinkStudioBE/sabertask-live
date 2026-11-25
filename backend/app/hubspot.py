"""The customer's own HubSpot, connected by the customer.

Nobody at Sabertask or at Think Studio ever signs in to a customer's CRM. The
customer clicks Connect, HubSpot asks them whether this app may act on their
portal, and what comes back is a token for that portal and nothing else. That
is the whole reason this is OAuth rather than a key somebody pastes in a chat
window: the permission is given inside HubSpot, by the person who owns the
data, and it can be taken back there just as easily.

Two halves have to be in place for the button to work:

* The app side, once, by us: a HubSpot developer account with an app in it, and
  its client id and secret set as HUBSPOT_CLIENT_ID and HUBSPOT_CLIENT_SECRET.
  Until those are set the Settings screen says so instead of showing a button
  that cannot work.
* The portal side, per customer: the Connect button.

What is stored per connection is the refresh token, the current access token
and who the portal is. The access token lives half an hour; the refresh token
is what actually keeps the connection alive, so it is the one thing here that
must never be logged, returned by an endpoint or shown on a screen. The status
the frontend gets is deliberately a different shape from what is stored, so a
token cannot leak by somebody adding a field to the wrong dictionary.
"""

import base64
import hashlib
import hmac
import json
import time
from typing import Optional, Tuple

import httpx

from . import config, settings_store

AUTHORIZE_URL = "https://app.hubspot.com/oauth/authorize"
TOKEN_URL = "https://api.hubapi.com/oauth/v1/token"
ACCOUNT_URL = "https://api.hubapi.com/account-info/v3/details"

SETTING_KEY = "hubspot"

# What the app asks the customer to agree to. Read as well as write, because a
# prospect that is already in their CRM should be recognised rather than
# created a second time.
SCOPES = [
    "oauth",
    "crm.objects.companies.read",
    "crm.objects.companies.write",
    "crm.objects.contacts.read",
    "crm.objects.contacts.write",
    "crm.objects.deals.read",
    "crm.objects.deals.write",
    # To create this integration's own fields in their portal, in their own
    # group, so a HubSpot user can see which values come from Sabertask and
    # which are theirs. Without these the sync still works; it simply has
    # nowhere to write the link back to the record here.
    "crm.schemas.companies.read",
    "crm.schemas.companies.write",
    "crm.schemas.deals.read",
    "crm.schemas.deals.write",
]

# A token is swapped a little before it dies rather than after, so a sync that
# takes a minute does not fail halfway on an expiry nobody could have seen.
REFRESH_MARGIN = 120
# How long the customer has between clicking Connect and HubSpot sending them
# back. Long enough to read the consent screen, short enough that a link lying
# in a browser history is worthless.
STATE_MAX_AGE = 900


class HubSpotError(Exception):
    """Something went wrong that the customer should read in plain words."""


# ------------------------------------------------------------------ the app ---

def configured() -> bool:
    return bool(config.HUBSPOT_CLIENT_ID and config.HUBSPOT_CLIENT_SECRET)


def redirect_uri() -> str:
    return config.PUBLIC_URL.rstrip("/") + "/api/hubspot/callback"


def _sign(payload: str) -> str:
    mac = hmac.new(config.SESSION_SECRET.encode(), payload.encode(), hashlib.sha256)
    return base64.urlsafe_b64encode(mac.digest()).decode().rstrip("=")


def make_state(user_id: int) -> str:
    """Proof that this round trip started here, and recently.

    Without it anybody could hand the customer's browser a link that plants
    someone else's HubSpot on this installation.
    """
    body = json.dumps({"uid": user_id, "ts": int(time.time())}, separators=(",", ":"))
    encoded = base64.urlsafe_b64encode(body.encode()).decode().rstrip("=")
    return encoded + "." + _sign(encoded)


def read_state(raw: Optional[str]) -> Optional[int]:
    if not raw or "." not in raw:
        return None
    encoded, signature = raw.rsplit(".", 1)
    if not hmac.compare_digest(_sign(encoded), signature):
        return None
    try:
        padded = encoded + "=" * (-len(encoded) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded).decode())
    except (ValueError, TypeError):
        return None
    if int(time.time()) - int(data.get("ts") or 0) > STATE_MAX_AGE:
        return None
    return data.get("uid")


def authorize_url(state: str) -> str:
    from urllib.parse import urlencode
    return AUTHORIZE_URL + "?" + urlencode({
        "client_id": config.HUBSPOT_CLIENT_ID,
        "redirect_uri": redirect_uri(),
        "scope": " ".join(SCOPES),
        "state": state,
    })


# --------------------------------------------------------- what is stored ---

def _stored() -> dict:
    data = settings_store.get(SETTING_KEY)
    return data if isinstance(data, dict) else {}


def _save(data: dict) -> None:
    settings_store.put(SETTING_KEY, data)


def status() -> dict:
    """What a screen may know. Never the tokens."""
    data = _stored()
    return {
        "configured": configured(),
        "connected": bool(data.get("refresh_token")),
        "portal_id": data.get("portal_id"),
        "account": data.get("account"),
        "domain": data.get("domain"),
        "connected_at": data.get("connected_at"),
        "connected_by": data.get("connected_by"),
        "scopes": data.get("scopes") or [],
        "last_error": data.get("last_error"),
        "sync_error": data.get("sync_error"),
    }


def disconnect() -> None:
    """Forget the portal here. The customer can also pull the plug from their
    own side, under Connected Apps, and that is the one that really counts."""
    _save({})


# ------------------------------------------------------------------ tokens ---

def _token_request(payload: dict) -> dict:
    try:
        response = httpx.post(TOKEN_URL, data=payload, timeout=20.0, headers={
            "Content-Type": "application/x-www-form-urlencoded"})
    except httpx.HTTPError as error:
        raise HubSpotError("HubSpot could not be reached: " + type(error).__name__)
    if response.status_code >= 400:
        # HubSpot says what is wrong in a readable field; the rest of the body
        # is noise and may hold the secret we just sent.
        try:
            message = response.json().get("message") or ""
        except ValueError:
            message = ""
        raise HubSpotError(message[:200] or ("HubSpot refused the request ("
                                             + str(response.status_code) + ")"))
    return response.json()


def exchange(code: str, user_name: str) -> dict:
    """Turn the one-time code from the consent screen into a connection."""
    payload = _token_request({
        "grant_type": "authorization_code",
        "client_id": config.HUBSPOT_CLIENT_ID,
        "client_secret": config.HUBSPOT_CLIENT_SECRET,
        "redirect_uri": redirect_uri(),
        "code": code,
    })
    data = {
        "access_token": payload.get("access_token"),
        "refresh_token": payload.get("refresh_token"),
        "expires_at": time.time() + float(payload.get("expires_in") or 1800),
        "connected_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "connected_by": user_name,
        "scopes": SCOPES,
    }
    if not data["refresh_token"]:
        raise HubSpotError("HubSpot sent no refresh token, so the connection "
                           "would have died within the hour.")
    account = _account(data["access_token"])
    data.update(account)
    _save(data)
    return status()


def _refresh(data: dict) -> dict:
    payload = _token_request({
        "grant_type": "refresh_token",
        "client_id": config.HUBSPOT_CLIENT_ID,
        "client_secret": config.HUBSPOT_CLIENT_SECRET,
        "refresh_token": data["refresh_token"],
    })
    data = dict(data)
    data["access_token"] = payload.get("access_token")
    # HubSpot may hand back a new refresh token; keeping the old one would end
    # the connection the moment it rotates.
    data["refresh_token"] = payload.get("refresh_token") or data["refresh_token"]
    data["expires_at"] = time.time() + float(payload.get("expires_in") or 1800)
    data.pop("last_error", None)
    _save(data)
    return data


def access_token() -> str:
    """A token that is good right now, refreshed if it is about to go stale."""
    data = _stored()
    if not data.get("refresh_token"):
        raise HubSpotError("No HubSpot account is connected.")
    if (not data.get("access_token")
            or time.time() > float(data.get("expires_at") or 0) - REFRESH_MARGIN):
        try:
            data = _refresh(data)
        except HubSpotError as error:
            # Worth remembering: a refresh token that has been revoked inside
            # HubSpot fails here and nowhere else, and the screen should say so
            # rather than silently showing a connection that no longer works.
            broken = dict(data)
            broken["last_error"] = str(error)[:200]
            _save(broken)
            raise
    return data["access_token"]


def _account(token: str) -> dict:
    """Who we are connected to, for the screen."""
    try:
        response = httpx.get(ACCOUNT_URL, timeout=20.0,
                             headers={"Authorization": "Bearer " + token})
        if response.status_code >= 400:
            return {}
        payload = response.json()
    except (httpx.HTTPError, ValueError):
        return {}
    return {
        "portal_id": payload.get("portalId"),
        "account": payload.get("companyName") or payload.get("uiDomain"),
        "domain": payload.get("uiDomain"),
    }


def check() -> dict:
    """Ask HubSpot who we are, with the stored connection. The button that
    proves a connection is alive rather than merely stored."""
    token = access_token()
    account = _account(token)
    if not account:
        raise HubSpotError("The token is stored but HubSpot did not answer "
                           "with an account.")
    data = _stored()
    data.update(account)
    data.pop("last_error", None)
    _save(data)
    return status()
