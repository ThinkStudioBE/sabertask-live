"""Engine and session plumbing.

Two stores, one codebase. With `DATABASE_URL` set the app runs on Postgres;
without it, on a SQLite file. That is not a convenience: this build collects
real companies, and the host it is going to has an ephemeral filesystem, so the
database has to live somewhere a restart cannot reach.

SQLModel does the talking either way, so nothing above this module knows which
one it is on.
"""

import os

from sqlalchemy import inspect, text
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


# Column types this app actually uses, spelled for each store. Anything outside
# the map stops the migration rather than guessing at a type.
_SQL_TYPE = {
    "INTEGER": {"sqlite": "INTEGER", "postgres": "INTEGER"},
    "BIGINT": {"sqlite": "INTEGER", "postgres": "BIGINT"},
    "FLOAT": {"sqlite": "REAL", "postgres": "DOUBLE PRECISION"},
    "BOOLEAN": {"sqlite": "INTEGER", "postgres": "BOOLEAN"},
    "VARCHAR": {"sqlite": "TEXT", "postgres": "TEXT"},
    "TEXT": {"sqlite": "TEXT", "postgres": "TEXT"},
    "DATE": {"sqlite": "DATE", "postgres": "DATE"},
    "DATETIME": {"sqlite": "DATETIME", "postgres": "TIMESTAMP"},
    "TIMESTAMP": {"sqlite": "DATETIME", "postgres": "TIMESTAMP"},
}


def _add_missing_columns():
    """Add columns the models have and the live tables do not.

    `create_all` creates missing tables and never touches an existing one, so a
    new field on a model that already has rows behind it would deploy as a 500
    on every read. This closes that, additively and only that: it adds columns,
    never drops, renames, retypes or backfills. A real change of shape is still
    a migration somebody writes by hand.
    """
    inspector = inspect(engine)
    live = set(inspector.get_table_names())
    added = []
    with engine.begin() as connection:
        for table in SQLModel.metadata.sorted_tables:
            if table.name not in live:
                continue
            have = {column["name"] for column in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in have or column.primary_key:
                    continue
                family = type(column.type).__name__.upper()
                spec = _SQL_TYPE.get(family)
                if spec is None:
                    raise RuntimeError(
                        "No SQL type known for %s.%s (%s): add it to _SQL_TYPE "
                        "or migrate that column by hand"
                        % (table.name, column.name, family))
                kind = spec["postgres" if ON_POSTGRES else "sqlite"]
                default = ""
                if column.default is not None and not callable(
                        getattr(column.default, "arg", None)):
                    value = getattr(column.default, "arg", None)
                    if isinstance(value, bool):
                        default = " DEFAULT " + ("TRUE" if value else "FALSE")
                    elif isinstance(value, (int, float)):
                        default = " DEFAULT " + str(value)
                    elif isinstance(value, str):
                        default = " DEFAULT '" + value.replace("'", "''") + "'"
                connection.execute(text(
                    'ALTER TABLE "%s" ADD COLUMN "%s" %s%s'
                    % (table.name, column.name, kind, default)))
                added.append(table.name + "." + column.name)
    if added:
        print("db: added missing columns: " + ", ".join(added))


def init_db():
    SQLModel.metadata.create_all(engine)
    _add_missing_columns()


def get_session():
    with Session(engine) as session:
        yield session
