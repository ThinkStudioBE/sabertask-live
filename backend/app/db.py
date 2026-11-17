"""Engine and session plumbing.

Two stores, one codebase. With `DATABASE_URL` set the app runs on Postgres;
without it, on a SQLite file. That is not a convenience: this build collects
real companies, and the host it is going to has an ephemeral filesystem, so the
database has to live somewhere a restart cannot reach.

SQLModel does the talking either way, so nothing above this module knows which
one it is on.
"""

import os

from sqlmodel import Session, SQLModel, create_engine

from . import config
from . import models  # noqa: F401  (import registers the tables on SQLModel.metadata)


def _url() -> str:
    raw = (os.getenv("DATABASE_URL") or "").strip()
    if not raw:
        config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        return "sqlite:///" + str(config.DB_PATH)
    # Hosts hand out the historical `postgres://` prefix and psycopg wants to be
    # named explicitly, or SQLAlchemy reaches for psycopg2, which is not here.
    if raw.startswith("postgres://"):
        raw = "postgresql://" + raw[len("postgres://"):]
    if raw.startswith("postgresql://"):
        raw = "postgresql+psycopg://" + raw[len("postgresql://"):]
    return raw


URL = _url()
ON_POSTGRES = URL.startswith("postgresql")

engine = create_engine(
    URL,
    echo=False,
    # A managed Postgres closes idle connections, and a pooled one that was
    # closed at the far end fails the next request rather than the one that
    # went away. Checking it out costs a round trip and saves that.
    **({"pool_pre_ping": True, "pool_recycle": 280}
       if ON_POSTGRES else {"connect_args": {"check_same_thread": False}})
)


def init_db():
    SQLModel.metadata.create_all(engine)


def get_session():
    with Session(engine) as session:
        yield session
