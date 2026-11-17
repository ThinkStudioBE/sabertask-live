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
from .auth import hash_password, verify_password
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


def sync_passwords():
    """Keep the desk accounts on whatever APP_PASSWORD currently says.

    This app has one shared password and the login page prints it, so the
    environment variable is the truth and the stored hash is a copy of it. The
    accounts are seeded once, which means changing the variable afterwards
    otherwise changes the hint on the screen and nothing else: the page then
    advertises a password that does not work, which is worse than no hint.

    Only the seeded desks, and only when the current password does not already
    verify, so this is a no-op on every boot but the one after a change.
    """
    emails = {spec["email"] for spec in DESKS}
    with Session(engine) as session:
        changed = 0
        for user in session.exec(select(User)).all():
            if user.email not in emails:
                continue
            if verify_password(config.APP_PASSWORD, user.password_hash):
                continue
            user.password_hash = hash_password(config.APP_PASSWORD)
            session.add(user)
            changed += 1
        if changed:
            session.commit()
            print("[seed] password updated on " + str(changed) + " account(s)")
