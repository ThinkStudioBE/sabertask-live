# Register extracts

`be_register.csv` is the Belgian KBO register filtered to the six industries this app
sells into: 18,906 active legal entities with their address and whatever impersonal
mailbox the register publishes. It is committed because the thing it was made from is a
four-gigabyte download, so without it the only way to rebuild this list is to fetch that
download again.

Load it:

    cd backend && python -m app.load_register data/be_register.csv \
        --country BE --source "KBO 2026-08-12"

The load replaces Belgium rather than merging into it, because a register file is a
snapshot of a whole country on one day: a row that is gone from a newer file is a company
that has closed.

Refresh it from a new download with `tools/extract_kbo.py`, which is also where the four
filters live (enterprises not establishments, active only, legal entities only, impersonal
mailboxes only) and why each one is there.

Norway and Finland are not in here. Their registers answer live, so their rows are never
stale and never stored.
