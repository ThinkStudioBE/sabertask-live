"""First-run accounts. No prospects.

This app runs on real companies, so it ships with none: the pipeline starts
empty and is filled by running searches. The only thing seeded is the set of
accounts, and those are desks rather than people. Inventing colleagues would
put fictional names on real records, and once a name is in the data nobody
downstream can tell which ones were made up.

Rename a desk to the colleague who runs it and the routing follows.
"""

from sqlmodel import Session, select

from . import config
from .auth import hash_password
from .db import engine
from .models import User

# One account per industry desk plus one that sees the whole floor. `segments`
# is what routing.py reads: every company and every lead in those industries is
# assigned to that desk automatically.
DESKS = [
    {
        "name": "Sabertask", "email": "sabertask@think-studio.com",
        "title": "Owner", "role": "manager", "segments": "",
        "color": "#2a3140", "initials": "ST",
    },
    {
        "name": "Cleaning desk", "email": "cleaning@sabertask.local",
        "title": "Cleaning and window cleaning", "role": "rep",
        "segments": "cleaning,window", "color": "#4f7aa0", "initials": "CL",
    },
    {
        "name": "Facility desk", "email": "facility@sabertask.local",
        "title": "Facility management and public sector", "role": "rep",
        "segments": "facility,municipal", "color": "#7d6c9c", "initials": "FM",
    },
    {
        "name": "Green desk", "email": "green@sabertask.local",
        "title": "Landscaping and winter services", "role": "rep",
        "segments": "landscaping,winter", "color": "#5d8a5a", "initials": "GR",
    },
]


def seed_if_empty():
    with Session(engine) as session:
        if session.exec(select(User)).first() is not None:
            return

        for spec in DESKS:
            session.add(User(
                name=spec["name"], email=spec["email"],
                password_hash=hash_password(config.APP_PASSWORD),
                title=spec["title"], role=spec["role"],
                segments=spec["segments"] or None, color=spec["color"],
                initials=spec["initials"],
            ))
        session.commit()

        print("[seed] " + str(len(DESKS)) + " accounts, no prospects. "
              "Sign in as " + DESKS[0]["email"] + " and run a search.")
