.PHONY: run reset install register

install:
	/usr/bin/python3 -m pip install --user -r backend/requirements.txt

run:
	./start.sh

reset:
	rm -f backend/sabertask-live.db
	@echo "Database wiped, prospects and all. The next run re-creates the accounts only."

register:
	@# Loads the Belgian register into whatever database DATABASE_URL points at,
	@# or the local SQLite file when it is unset. Replaces Belgium, does not merge.
	cd backend && /usr/bin/python3 -m app.load_register data/be_register.csv \
		--country BE --source "KBO 2026-08-12"
