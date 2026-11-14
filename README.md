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

A brief in plain words becomes real companies: Claude reads the brief once per search and
says which industries, countries and cities to look in, Nominatim turns each city into a
bounding box, and Overpass returns the businesses inside it carrying that industry's tags.
Name, address, website and phone come from the map. Without an `ANTHROPIC_API_KEY` the
brief is read with keywords instead, so the tab still works.

**A search returns at most 100 leads.** The cap is `config.LEAD_HARD_CAP`, deliberately not
an environment variable and not a setting, so it cannot be raised from a dashboard or a
deployment by accident. It is enforced twice: `out tags center 100` in the Overpass query
itself, so a volunteer server is never asked to do work that gets thrown away, and again
as a clamp in the search endpoint in case a mirror ignores it.

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

## Everything else

Funnel, seats-per-role-tier MRR in DKK, quotes, clients, reports, CSV import and export,
cold mail: unchanged from the demo, including the industry colour and name on every row.
See that project's README for the value model and the funnel.

**Cache-bust gotcha:** `index.html` loads `app.js?v=N` and `sabertask.css?v=N`. Bump `N`
after editing either, or the browser serves the old file. Currently `v=12`.
