#!/bin/sh
# Container entrypoint: optionally seed simulated demo reports, then exec uvicorn.
#
# Runs from the project root (the parent of docker/), so `-m scripts.*` and `app.main` resolve
# and seed_reports finds data/boston.sqlite (app/db.py ROOT) both in the image (/app) and locally.
# Any arguments replace the default uvicorn command (e.g. `docker run IMAGE python -V`).
set -eu
cd "$(dirname "$0")/.."

# Local runs use the project venv (system Python lacks the deps); the image has no .venv.
if [ -z "${PYTHON:-}" ]; then
  if [ -x .venv/bin/python ]; then PYTHON=.venv/bin/python; else PYTHON=python; fi
fi
DB="${APP_DB_PATH:-/data/app.sqlite}"

if [ "${SEED_SIMULATED:-0}" = "1" ]; then
  # Seed only when the simulated table is missing or empty, so restarts keep existing data.
  count=$("$PYTHON" - "$DB" <<'PY'
import sqlite3, sys
try:
    con = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
    print(con.execute("SELECT COUNT(*) FROM simulated_reports").fetchone()[0])
except sqlite3.Error:
    print(0)
PY
)
  if [ "$count" = "0" ]; then
    echo "Seeding simulated demo reports"
    "$PYTHON" -m scripts.seed_reports --db "$DB"
  fi
fi

if [ "$#" -gt 0 ]; then
  exec "$@"
fi

# --no-access-log: request lines would pair client IPs with paths, which the privacy rules
# forbid logging. PORT is set by Render; defaults to 8000.
# --forwarded-allow-ips: only peers in FORWARDED_ALLOW_IPS (comma-separated IPs or CIDR ranges)
# may set X-Forwarded-For. Trusting every peer ("*") would let any client pick the IP the rate
# limiters see. The default trusts only localhost.
exec "$PYTHON" -m uvicorn app.main:app \
  --host 0.0.0.0 \
  --port "${PORT:-8000}" \
  --no-access-log \
  --proxy-headers \
  --forwarded-allow-ips="${FORWARDED_ALLOW_IPS:-127.0.0.1}"
