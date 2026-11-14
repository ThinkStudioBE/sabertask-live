.PHONY: run reset install

install:
	/usr/bin/python3 -m pip install --user -r backend/requirements.txt

run:
	./start.sh

reset:
	rm -f backend/sabertask-live.db
	@echo "Database wiped, prospects and all. The next run re-creates the accounts only."
