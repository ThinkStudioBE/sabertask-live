"""Sabertask Sales: FastAPI serving the JSON API and the SPA."""

from fastapi import Depends, FastAPI, Request
from fastapi.responses import (
    FileResponse, HTMLResponse, JSONResponse, RedirectResponse,
)
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlmodel import Session

from . import config
from .auth import AuthMiddleware, authenticate, make_session_cookie
from .db import get_session, init_db
from .api import (
    clients, companies, deals, leads, mail, meta, quotes, reports, settings,
    tasks, transfer,
)
from .seed import seed_if_empty, sync_passwords
from .serializers import user_dict

app = FastAPI(title=config.APP_NAME, docs_url=None, redoc_url=None)


@app.middleware("http")
async def no_cache_spa(request: Request, call_next):
    """The frontend has no build step, so a cached app.js is a stale app."""
    response = await call_next(request)
    path = request.url.path
    if path == "/" or path.endswith((".html", ".js", ".css")):
        response.headers["Cache-Control"] = "no-store, must-revalidate"
    return response


app.add_middleware(AuthMiddleware)


@app.on_event("startup")
def startup():
    init_db()
    seed_if_empty()
    sync_passwords()


@app.get("/api/health")
def health():
    """Also says which store it is on.

    Worth the two words: on a host with an ephemeral filesystem, a missing
    DATABASE_URL is not an error anywhere. The app starts, seeds itself, works
    all afternoon and loses the pipeline at the first restart. The only way to
    catch that is to ask it, from outside, what it is writing to."""
    from .db import ON_POSTGRES
    return {"ok": True, "app": config.APP_NAME,
            "store": "postgres" if ON_POSTGRES else "sqlite (not durable here)"}


class LoginIn(BaseModel):
    email: str
    password: str


@app.post("/api/login")
def login(payload: LoginIn, session: Session = Depends(get_session)):
    user = authenticate(session, payload.email, payload.password)
    if user is None:
        return JSONResponse({"detail": "Wrong email or password"}, status_code=401)
    response = JSONResponse({"ok": True, "user": user_dict(user)})
    response.set_cookie(
        config.SESSION_COOKIE, make_session_cookie(user.id),
        max_age=config.SESSION_MAX_AGE, httponly=True, samesite="lax",
        secure=config.SESSION_SECURE, path="/",
    )
    return response


@app.post("/api/logout")
def logout():
    response = JSONResponse({"ok": True})
    response.delete_cookie(config.SESSION_COOKIE, path="/")
    return response


app.include_router(meta.router)
app.include_router(deals.router)
app.include_router(companies.router)
app.include_router(tasks.router)
app.include_router(clients.router)
app.include_router(leads.router)
app.include_router(mail.router)
app.include_router(quotes.router)
app.include_router(reports.router)
app.include_router(settings.router)
app.include_router(transfer.router)


@app.get("/login", response_class=HTMLResponse)
def login_page():
    """Rendered rather than served raw, so the password shown on the page is the
    one the server actually accepts. Deployments override it with an env var,
    and a hint that says otherwise is worse than no hint."""
    html = (config.FRONTEND_DIR / "login.html").read_text()
    return HTMLResponse(html.replace("{{APP_PASSWORD}}", config.APP_PASSWORD))


@app.get("/login.html")
def login_page_alias():
    """The file is a template now, so nobody should reach it through the static
    mount and read an unsubstituted placeholder."""
    return RedirectResponse("/login", status_code=308)


@app.get("/")
def index():
    return FileResponse(config.FRONTEND_DIR / "index.html")


# Mounted last, so the routes above win on the paths they claim.
app.mount("/", StaticFiles(directory=str(config.FRONTEND_DIR), html=True), name="static")
