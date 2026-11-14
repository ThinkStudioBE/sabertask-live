"""Cookie-session login.

A signed cookie carrying the user id, nothing else. No server-side session
store, so a restart leaves everybody still logged in.
"""

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Optional

from fastapi import Depends, HTTPException, Request
from sqlmodel import Session, select
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, RedirectResponse

from . import config
from .db import get_session
from .models import User

PUBLIC_PATHS = {
    "/login", "/api/login", "/api/logout", "/api/health",
    "/favicon.svg", "/sabertask.css", "/assets/sabertask-logo.png", "/robots.txt",
}
# Quote pages sit behind the login too. A real deployment would want them
# shareable with the customer; this one is reachable on a public URL and the
# documents name a real organisation, so there is no unauthenticated way in.
PUBLIC_PREFIXES = ("/assets/",)


# ------------------------------------------------------------------ passwords ---

def hash_password(password: str, salt: Optional[bytes] = None) -> str:
    if salt is None:
        salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 120_000)
    return "pbkdf2$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(digest).decode()


def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt_b64, digest_b64 = stored.split("$")
        salt = base64.b64decode(salt_b64)
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(hash_password(password, salt), stored)


# -------------------------------------------------------------------- cookie ---

def _sign(payload: str) -> str:
    mac = hmac.new(config.SESSION_SECRET.encode(), payload.encode(), hashlib.sha256)
    return base64.urlsafe_b64encode(mac.digest()).decode().rstrip("=")


def make_session_cookie(user_id: int) -> str:
    body = json.dumps({"uid": user_id, "ts": int(time.time())}, separators=(",", ":"))
    encoded = base64.urlsafe_b64encode(body.encode()).decode().rstrip("=")
    return encoded + "." + _sign(encoded)


def read_session_cookie(raw: Optional[str]) -> Optional[int]:
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
    if int(time.time()) - int(data.get("ts", 0)) > config.SESSION_MAX_AGE:
        return None
    return data.get("uid")


class AuthMiddleware(BaseHTTPMiddleware):
    """Everything is behind the login except the handful of paths above."""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path in PUBLIC_PATHS or path.startswith(PUBLIC_PREFIXES):
            return await call_next(request)

        uid = read_session_cookie(request.cookies.get(config.SESSION_COOKIE))
        if uid is None:
            if path.startswith("/api/"):
                return JSONResponse({"detail": "Not signed in"}, status_code=401)
            return RedirectResponse("/login", status_code=302)

        request.state.user_id = uid
        return await call_next(request)


def current_user(request: Request, session: Session = Depends(get_session)) -> User:
    uid = getattr(request.state, "user_id", None)
    if uid is None:
        raise HTTPException(status_code=401, detail="Not signed in")
    user = session.get(User, uid)
    if user is None or not user.active:
        raise HTTPException(status_code=401, detail="Not signed in")
    return user


def authenticate(session: Session, email: str, password: str) -> Optional[User]:
    user = session.exec(select(User).where(User.email == email.strip().lower())).first()
    if user is None or not user.active:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user
