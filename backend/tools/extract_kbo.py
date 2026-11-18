"""Turn the Belgian KBO open-data download into a file this app can load.

    python3 tools/extract_kbo.py ~/kbo be_register.csv
    python3 -m app.load_register be_register.csv --country BE --source "KBO 2026-08-12"

The download is eight CSV files and four gigabytes, nearly all of it other
people's industries. What comes out is about fourteen thousand rows: the active
legal entities whose main activity is one of the six Sabertask sells into, with
their address and whatever impersonal mailbox the register holds.

Why a register at all, when the app can already search the map: measured in
Antwerp, for the same two industries, the register has 37 facility companies
against the map's 1, and 256 cleaning companies against 13. A cleaning firm
works in other people's buildings, so it has no shopfront for anybody to map.

Four rules are enforced here rather than at search time, because a filter that
runs once cannot be forgotten later:

1. Enterprises, never establishments. An establishment number starts with a 2
   and belongs to a company already in the list.
2. Active only.
3. Legal entities only. A one-person business is filed as a natural person: the
   name is their surname, the address is where they live and the mailbox is
   their private one. That is a private individual at home, not a prospect.
4. Impersonal mailboxes only. A legal entity can still publish a colleague's
   address. The company stays on the list; the named address does not.

An address is looked up on the enterprise first and on its establishments
second, which is the difference between 38% of these companies having a place
and 98% of them having one.
"""

import collections
import csv
import os
import re
import sys

csv.field_size_limit(min(sys.maxsize, 2 ** 31 - 1))

SECTORS = {
    "81100": "facility",
    "81210": "cleaning",
    "81220": "window",
    "81290": "winter",
    "81300": "landscaping",
    "84114": "municipal",
}

FIELDS = ["reg_id", "name", "nace", "segment", "zipcode", "city", "street",
          "email", "phone", "website"]

# A mailbox at a webmail provider is somebody's personal inbox that happens to
# be used for work. A company publishes one on its own domain.
WEBMAIL = {
    "gmail.com", "googlemail.com", "hotmail.com", "hotmail.be", "hotmail.fr",
    "outlook.com", "outlook.be", "live.com", "live.be", "live.fr", "msn.com",
    "yahoo.com", "yahoo.fr", "yahoo.co.uk", "icloud.com", "me.com", "mac.com",
    "telenet.be", "skynet.be", "proximus.be", "scarlet.be", "voo.be",
    "belgacom.net", "base.be", "pandora.be", "aol.com", "gmx.com", "gmx.net",
    "protonmail.com", "proton.me", "zoho.com", "mail.com", "orange.fr",
    "wanadoo.fr", "free.fr", "laposte.net", "numericable.be", "edpnet.be",
}

# Words that make a mailbox a department or a function rather than a person. A
# function title counts: it is a role somebody holds this year and the mailbox
# outlives whoever is reading it.
ROLES = {
    "info", "infos", "information", "contact", "contacts", "mail", "email",
    "post", "office", "bureau", "kantoor", "admin", "administratie",
    "administration", "algemeen", "general", "hello", "hallo", "welcome",
    "onthaal", "receptie", "reception", "accueil", "balie", "onthaalbalie",
    "secretariaat", "secretariat", "secretaire", "secretaris", "secretary",
    "sales", "verkoop", "commercial", "commerce", "service", "services",
    "support", "helpdesk", "help", "desk", "klantendienst", "customerservice",
    "customer", "klanten", "boekhouding", "accounting", "facturatie",
    "facturation", "invoice", "invoices", "finance", "finances", "hr", "hrm",
    "jobs", "job", "vacature", "werken", "team", "planning", "werf", "offerte",
    "offertes", "quote", "order", "orders", "bestelling", "shop", "winkel",
    "communicatie", "communication", "press", "pers", "direction", "directie",
    "directeur", "management", "gemeente", "commune", "stad", "ville",
    "bestuur", "burgerzaken", "officiel", "officieel", "onderhoud",
    "schoonmaak", "cleaning", "tuin", "groen", "garden", "facility", "beheer",
    "contactus", "mailbox", "inbox", "company", "firma", "greffe", "griffie",
    "mairie", "gemeentehuis", "dienst", "diensten", "college", "burgemeester",
    "schepen", "financieeldirecteur", "algemeendirecteur", "ocmw", "raad",
    "beleid", "technischedienst", "milieu", "openbarewerken",
}


def impersonal(address):
    """Is this a mailbox of the organisation rather than of a person?"""
    local = address.rpartition("@")[0].strip().lower()
    domain = address.rpartition("@")[2].strip().lower()
    if not local or not domain:
        return False
    if domain in WEBMAIL:
        return False
    words = [word for word in re.split(r"[^a-z]+", local) if word]
    if not words:
        return False
    if any(word in ROLES for word in words):
        return True
    # A mailbox named after the organisation itself is the organisation's own:
    # evere@evere.brussels is the town hall.
    label = domain.partition(".")[0]
    if local.replace("-", "") == label.replace("-", ""):
        return True
    joined = "".join(words)
    return any(joined.startswith(role) for role in ROLES if len(role) > 3)


def _read(base, name):
    path = os.path.join(base, name)
    if not os.path.exists(path):
        raise SystemExit("missing " + path)
    handle = open(path, encoding="utf-8", errors="replace", newline="")
    return handle, csv.DictReader(handle)


def extract(base, out_path):
    print("1/6 activities (the big one)...", flush=True)
    nace = {}
    handle, reader = _read(base, "activity.csv")
    with handle:
        for row in reader:
            if row.get("Classification") != "MAIN":
                continue
            code = (row.get("NaceCode") or "").strip()
            if code not in SECTORS:
                continue
            number = (row.get("EntityNumber") or "").strip()
            if number and not number.startswith("2"):
                nace.setdefault(number, code)
    print("   in these industries: " + str(len(nace)), flush=True)

    print("2/6 status and entity type...", flush=True)
    want = set()
    handle, reader = _read(base, "enterprise.csv")
    with handle:
        for row in reader:
            number = (row.get("EnterpriseNumber") or "").strip()
            if number not in nace:
                continue
            if (row.get("Status") or "").strip() != "AC":
                continue
            if (row.get("TypeOfEnterprise") or "").strip() != "2":
                continue        # natural person, not a company
            want.add(number)
    print("   active legal entities: " + str(len(want)), flush=True)
    if not want:
        raise SystemExit("nothing matched; is this the KBO full extract?")

    print("3/6 names...", flush=True)
    names = {}
    handle, reader = _read(base, "denomination.csv")
    with handle:
        for row in reader:
            number = (row.get("EntityNumber") or "").strip()
            if number not in want:
                continue
            value = (row.get("Denomination") or "").strip()
            if not value:
                continue
            # 001 is the registered name, 003 the trading name. The registered
            # name identifies the legal entity, so it wins.
            if (row.get("TypeOfDenomination") or "").strip() == "001":
                names[number] = value
            else:
                names.setdefault(number, value)

    print("4/6 establishments, to find the rest of the addresses...", flush=True)
    owner = {}
    handle, reader = _read(base, "establishment.csv")
    with handle:
        for row in reader:
            enterprise = (row.get("EnterpriseNumber") or "").strip()
            if enterprise in want:
                owner[(row.get("EstablishmentNumber") or "").strip()] = enterprise

    print("5/6 addresses...", flush=True)
    place = {}
    handle, reader = _read(base, "address.csv")
    with handle:
        for row in reader:
            number = (row.get("EntityNumber") or "").strip()
            target = number if number in want else owner.get(number)
            if not target:
                continue
            if (row.get("DateStrikingOff") or "").strip():
                continue
            # The company's own address wins over one of its establishments.
            own = number in want
            if target in place and not (own and not place[target]["own"]):
                continue
            street = (row.get("StreetNL") or row.get("StreetFR") or "").strip()
            house = (row.get("HouseNumber") or "").strip()
            place[target] = {
                "own": own,
                "zipcode": (row.get("Zipcode") or "").strip(),
                "city": (row.get("MunicipalityNL") or row.get("MunicipalityFR") or "").strip(),
                "street": (street + " " + house).strip(),
            }

    print("6/6 contact details...", flush=True)
    details = collections.defaultdict(dict)
    handle, reader = _read(base, "contact.csv")
    with handle:
        for row in reader:
            number = (row.get("EntityNumber") or "").strip()
            target = number if number in want else owner.get(number)
            if not target:
                continue
            field = {"EMAIL": "email", "TEL": "phone",
                     "WEB": "website"}.get((row.get("ContactType") or "").strip())
            value = (row.get("Value") or "").strip()
            if field and value and field not in details[target]:
                details[target][field] = value

    written = 0
    per_sector = collections.Counter()
    dropped_mail = 0
    with open(out_path, "w", encoding="utf-8", newline="") as out:
        writer = csv.DictWriter(out, fieldnames=FIELDS)
        writer.writeheader()
        for number in sorted(want):
            name = names.get(number)
            if not name:
                continue     # no name in the register is not a lead
            where = place.get(number) or {}
            found = details.get(number) or {}
            email = found.get("email", "")
            if email and not impersonal(email):
                email = ""
                dropped_mail += 1
            code = nace[number]
            writer.writerow({
                "reg_id": number, "name": name[:300], "nace": code,
                "segment": SECTORS[code],
                "zipcode": where.get("zipcode", ""), "city": where.get("city", ""),
                "street": where.get("street", ""),
                "email": email, "phone": found.get("phone", ""),
                "website": found.get("website", ""),
            })
            written += 1
            per_sector[SECTORS[code]] += 1

    print("--- " + str(written) + " companies -> " + out_path)
    for segment, count in per_sector.most_common():
        print("    %-12s %6d" % (segment, count))
    print("    mailboxes dropped as personal: " + str(dropped_mail))


if __name__ == "__main__":
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    extract(os.path.expanduser(sys.argv[1]), os.path.expanduser(sys.argv[2]))
