"""Load a register extract into this app's database.

    python -m app.load_register be_register.csv --country BE --source "KBO 2026-08-12"

Belgium publishes its register as a four-gigabyte download rather than as a
query API, so its rows are prepared once and kept here. The extract is made by
a separate script that filters the download to the six industries; this reads
the result.

The load replaces the country rather than merging into it. A register file is a
snapshot of a whole country on one day, so a row that is no longer in the new
file is a company that has closed, and merging would keep selling to it.
"""

import csv
import sys
from typing import List

from sqlmodel import Session, delete, select

from .db import engine, init_db
from .models import RegisterCompany

BATCH = 2000
FIELDS = ("reg_id", "name", "nace", "segment", "zipcode", "city", "street",
          "email", "phone", "website")


def _rows(path: str, country: str, source: str) -> List[RegisterCompany]:
    out = []
    with open(path, encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            name = (row.get("name") or "").strip()
            reg_id = (row.get("reg_id") or "").strip()
            if not name or not reg_id:
                continue
            values = {key: ((row.get(key) or "").strip() or None) for key in FIELDS}
            values["reg_id"] = reg_id
            values["name"] = name[:300]
            values["segment"] = values["segment"] or "facility"
            out.append(RegisterCompany(country=country, source=source, **values))
    return out


def load(path: str, country: str, source: str) -> int:
    init_db()
    rows = _rows(path, country, source)
    if not rows:
        raise SystemExit("nothing to load from " + path)

    with Session(engine) as session:
        session.exec(delete(RegisterCompany).where(
            RegisterCompany.country == country))
        session.commit()
        for start in range(0, len(rows), BATCH):
            session.add_all(rows[start:start + BATCH])
            session.commit()
            print("  " + str(min(start + BATCH, len(rows))) + " / "
                  + str(len(rows)), flush=True)

        total = session.exec(select(RegisterCompany).where(
            RegisterCompany.country == country)).all()
    print("[register] " + country + ": " + str(len(total)) + " companies from "
          + source)
    return len(total)


def main(argv: List[str]) -> None:
    if not argv:
        raise SystemExit(__doc__)
    path = argv[0]
    country = "BE"
    source = "register extract"
    for index, arg in enumerate(argv):
        if arg == "--country" and index + 1 < len(argv):
            country = argv[index + 1].upper()
        if arg == "--source" and index + 1 < len(argv):
            source = argv[index + 1]
    load(path, country, source)


if __name__ == "__main__":
    main(sys.argv[1:])
