"""Engine and session plumbing."""

from sqlmodel import Session, SQLModel, create_engine

from . import config
from . import models  # noqa: F401  (import registers the tables on SQLModel.metadata)

config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    "sqlite:///" + str(config.DB_PATH),
    echo=False,
    connect_args={"check_same_thread": False},
)


def init_db():
    SQLModel.metadata.create_all(engine)


def get_session():
    with Session(engine) as session:
        yield session
