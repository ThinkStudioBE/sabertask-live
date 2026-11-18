# Sabertask Sales (live)

The same sales platform as the Sabertask demo, pointed at real companies. It ships with
no prospects: the pipeline starts empty and fills up by running searches against
OpenStreetMap.

> Its twin, `~/sabertask-demo`, is the one with the invented pipeline, and it stays that
> way. Nothing in this repository should ever grow a fictional record: a made-up company
> or a made-up contact person here is indistinguishable, a week later, from a found one.

## Running it

```bash
/usr/bin/python3 -m pip install --user -r backend/requirements.txt
./start.sh          # http://127.0.0.1:8600
```

`make reset` deletes `backend/sabertask-live.db`, prospects and all. The next start
re-creates the accounts and nothing else.

### Accounts

Password for all of them: `Sabertask2026!` (override with `SABERTASK_PASSWORD`).

| Account | Desk |
|---|---|
| `sabertask@think-studio.com` | Owner, sees every industry |
| `cleaning@sabertask.local` | Cleaning, window cleaning |
| `facility@sabertask.local` | Facility management, municipal and public |
| `green@sabertask.local` | Landscaping, winter services |

They are desks rather than people on purpose. Rename one to the colleague who runs it and
the routing follows: `User.segments` is what `routing.py` reads, and every company, lead
and deal in those industries is assigned to that desk automatically.

## Leads

A brief in plain words becomes real companies. Claude reads the brief once per search and
says which industries, countries and cities to look in. Without an `ANTHROPIC_API_KEY` the
brief is read with keywords instead, so the tab still works.

Then the country decides where to look. Two sources, never mixed for one country, and the
result says which answered.

**The official business register, where the country has one.** Every company is in it by
law, filed under what it actually does, which is exactly what the map misses in these
industries: a cleaning firm works in other people's buildings and has no shopfront for
anybody to map. Measured in Antwerp, same two industries: register 37 facility companies
against the map's 1, and 256 cleaning companies against 13.

| | register | how |
|---|---|---|
| BE | KBO | published as a 4 GB download, filtered and loaded ahead of time |
| NO | Enhetsregisteret | live JSON API, no key, and it carries employee counts |
| FI | PRH / YTJ | live JSON API, no key |
| DK | CVR | adapter built, switched off: free, but granted by email after a signed declaration. See `docs/cvr-ansoegning.md` |
| SE | — | Bolagsverket does not register industry codes at all |
| NL | — | the KVK API cannot search by activity, only name, street and place |
| US / CA | — | no national register with activity codes |

Denmark is the one country here with a register the app cannot reach yet. Erhvervsstyrelsen
grants access to the CVR Elasticsearch endpoint by email, free, after a signed declaration about
advertisement-protected companies, and the published turnaround is around three weeks. The
adapter is written and tested against the published field names but never against a real
response, because the endpoint answers 401 without credentials. It stays switched off until
`CVR_USER` and `CVR_PASSWORD` are both set: `has_register("DK")` reads those two variables, so
until then Denmark searches the map and the Settings tab says so rather than promising a register
it cannot use. The application, ready to sign and send, is in `docs/cvr-ansoegning.md`.

Two things in that adapter are worth knowing before the credentials land. Denmark's DB07 codes
subdivide further than Norway's or Finland's, so window cleaning is `812210` on its own rather
than the whole of 81.22, and property management is `683210` and not the owners' associations
next to it in `683220`. And CVR-loven § 19 means an advertisement-protected company may not be
used for direct marketing, so the adapter drops those rows, drops rows whose flag it cannot read,
and refuses to run at all if CVR ever answers without the flag. A legal limit is a filter in the
code, not a line in a policy.

**The open map, for the rest.** Nominatim turns each city into a bounding box and Overpass
returns the businesses inside it carrying that industry's tags. A country whose register
cannot be reached falls back here rather than reporting that it has no companies in it.

Belgium's rows are prepared by `backend/tools/extract_kbo.py` and loaded with
`python -m app.load_register`. The extract is where four rules are enforced once instead of
at every search: enterprises not establishments, active only, legal entities only (a
one-person business is filed as a natural person, whose address is their home), and
impersonal mailboxes only.

The six industries, and the words the search looks for, come from sabertask.com's own
"Target industries" pages rather than from guesswork. `config.SEGMENTS` carries each one's
profile and the pain Sabertask names for it, the app shows both beside the industry, and
the prompt that reads a brief is built from them. Five of the six can be checked against
the site; `municipal` cannot, and says so where it is defined.

**A search returns at most 50 leads per country**, counted over every industry in it, so the
total grows with the number of countries picked. The cap is `config.LEAD_CAP_PER_COUNTRY`,
deliberately not an environment variable and not a setting, so it cannot be raised from a
dashboard or a deployment by accident. On the map path it is enforced twice: in the
Overpass query itself, so a volunteer server is never asked to do work that gets thrown
away, and again as a clamp in the search endpoint in case a mirror ignores it.

Leads sit apart from the pipeline until somebody adds one. Adding creates the company and
a deal at `lead`, routed to the desk that owns its industry, and carries the published
mailbox across as the company's contact.

### No invented people

The contact a lead brings in is a role, "Main contact", with the address and number the
company publishes. No personal names are invented anywhere, in the seed or in the search,
and nothing is sent automatically: cold mail is drafted, read by a person and sent from
their own mailbox.

### Mirrors, and why there is a curl fallback

Overpass is run by volunteers. Mirrors are tried in order and the first that answers wins.
Two things that cost a day each if you meet them cold:

- **A transport error does not mean the server is down.** macOS system Python 3.9.6 is
  linked against LibreSSL 2.8.3, which has no TLS 1.3, so hosts that require it refuse the
  handshake while `curl` on the same machine gets through. Every mirror is therefore
  retried through a `curl` subprocess before it is written off.
- **Overpass answers a query it could not run with HTTP 200 and an empty list**, with the
  reason in `remark`. Unread, that is indistinguishable from "this city has nothing".

`overpass.osm.ch` is last in the list and carries a Swiss extract rather than the planet.
It is there because it is reachable from hosts the big mirrors refuse, which makes it the
one instance that can prove the pipeline end to end when the others are blocked.

Set `OVERPASS_URLS` to a comma-separated list to override the mirrors.

## The funnel

Lead, Contacted, **Engaged**, Demo booked, Scoping, Trial, Proposal, Won, with Lost and
Nurture off the board. The stages, their odds and the next step each one brings are all in
`config.STAGES` and `config.STAGE_NEXT_STEP`, so adding one is a single edit.

Engaged is the stage between the mail and the meeting. Somebody opens the mail, clicks
through to sabertask.com, reads the page for their industry, maybe opens the booking form,
and then does not book. Filed under Contacted that person is indistinguishable from
somebody who never reacted at all, and they are not the same: they are the warmest thing in
the pipeline short of a booked demo, and the window to ring them is short. The stage brings
a two-day next step for that reason, where Contacted gets three.

It is a stage rather than a flag because of the question it answers. The Reports funnel now
shows two percentages per row: the share of everything that ever reached Lead, and the
share of whatever reached the stage directly above. The second one is the point. Engaged to
Demo booked is the conversion worth watching, and in a funnel measured only from the top it
is invisible.

## The four seat tiers

Sabertask's price list has four cards, all billed per user per month: Worker, Worker with
planning, Admin, and Enterprise. A deal carries a seat count per tier and MRR is their sum,
so the value is always recurring and every screen quotes the same figure.

Enterprise is the one the catalogue cannot price. Their page prints "Custom" where the
others print an amount, so its rate here is 0 and the rep types what was negotiated, on the
deal itself. Until they do, those seats are worth nothing in the forecast, which is a quiet
way to read low. So the deal says it out loud: the seat line reads "price still to agree"
instead of showing a zero, the deal carries `rate_missing`, and the drawer puts the rate box
and a warning right under the monthly figure. On a quote the same line prints "On request"
rather than 0 kr, because that document goes to a customer.

A deal is an Enterprise deal exactly when it has Enterprise seats on it: `plan` is derived
at write time, never picked from a dropdown, so the label on a quote cannot disagree with
the seats on it.

Adding a fifth tier means adding it to `config.SEAT_TIERS` and adding two columns to `Deal`
and `Quote`. Nothing else: the seat maths, the modal, the drawer and the quote page all
loop over `config.SEAT_KEYS`.

## Schema changes

`create_all` makes missing tables and never touches an existing one, so a new field on a
model that already has rows behind it would deploy as a 500 on every read. `db.py` closes
that at startup: it compares the models to the live tables and adds the columns that are
missing, on SQLite and Postgres alike. Additive only. It adds columns and never drops,
renames, retypes or backfills, and it stops with an error rather than guess at a type it
does not know. A real change of shape is still a migration somebody writes by hand.

## Everything else

Funnel, quotes, clients, reports, CSV import and export, cold mail: unchanged from the
demo, including the industry colour and name on every row. See that project's README for
the value model and the funnel.

**Cache-bust gotcha:** `index.html` loads `app.js?v=N` and `sabertask.css?v=N`. Bump `N`
after editing either, or the browser serves the old file. `login.html` carries its own
copy of the stylesheet link, so bump that one too. Currently `v=18`.
