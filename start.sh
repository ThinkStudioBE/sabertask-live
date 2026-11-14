#!/usr/bin/env bash
# Run the Sabertask sales demo on http://127.0.0.1:8600
set -e
cd "$(dirname "$0")"
exec /usr/bin/python3 -m uvicorn app.main:app --app-dir backend \
  --host 127.0.0.1 --port "${PORT:-8600}" --reload
