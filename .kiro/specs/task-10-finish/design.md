# Design: Finish Task 10

## Overview

These are small, isolated changes to deploy files, docs, steering, and one content file. No
routes, services, ranking, or data pipeline logic changed. The `guard-sensitive-files` hook asks
for confirmation before edits to `docker/entrypoint.sh`, `render.yaml`, `Dockerfile`, and the
steering file. That's expected.

Status: all code and doc changes are done and tested. The only open item is confirming Render's
proxy range on a live deploy. A real `docker build` is tracked in
`.kiro/specs/platform-and-deploy/`.

## 1. Trusted proxy addresses

**Before:** `docker/entrypoint.sh` ran uvicorn with `--forwarded-allow-ips="*"`, so any client
could set `X-Forwarded-For` and pick the key the rate limiters in `app/services/rate_limit.py`
use.

**Now:**

```sh
exec "$PYTHON" -m uvicorn app.main:app \
  --host 0.0.0.0 \
  --port "${PORT:-8000}" \
  --no-access-log \
  --proxy-headers \
  --forwarded-allow-ips="${FORWARDED_ALLOW_IPS:-127.0.0.1}"
```

- uvicorn 0.31.0 and later accept CIDR ranges; the project pins 0.54.0.
- Render doesn't publish its proxy range, so `render.yaml` declares `FORWARDED_ALLOW_IPS` with
  `sync: false`. `docs/DEPLOY.md` explains the shared-limit effect while it's unset and gives a
  shell command that lists the proxy peers connected to the app port.
- The Dockerfile comment and DEPLOY.md describe the new flag.
- `tests/test_deploy_files.py::test_forwarded_ips_never_trust_every_peer` checks the entrypoint.

Open: confirm the range on a live deploy and set the value.

## 2. About page citations

The owner approved the exception.

- `.kiro/steering/project-rules.md` content rules: "About page exception: the founder-story
  background (`app/content/background.py`) may cite news, government reports, and research
  outside the list above. Every number there must have a linked source that supports it as
  worded; reword a fact rather than show an unsourced number."
- `.kiro/skills/massachusetts-fire-safety-sources/SKILL.md` repeats it.
- `app/content/background.py` facts were reworded so every number is sourced:
  - Smoke alarms: "working smoke alarms were confirmed at only about 35% of fatal fire scenes"
    (DFS, March 2025). Sprinklers: "In 2023, none of the homes where people died in fires had
    sprinklers" (DFS 2023 summary), since no 2024 figure was found.
  - Amherst inspections: self-certification and complaint-only inspections (Gazette, December
    2023), then the April 2024 vote to inspect every rental at least once every five years
    (Gazette and Amherst Indy). The unsourced July 2025 start date was dropped.
  - Rental count: "about 1,300 rental properties with more than 5,000 units" (Gazette, December
    2023: 1,258 and 5,134). The unsourced "about 120 inspections a quarter" was removed.
- The docstring lists the founder's original wording and each change.

## 3. Demo cleanup

DEMO.md now deletes from both tables:

```sh
sqlite3 data/app.sqlite "DELETE FROM reports WHERE address_key LIKE '12 EXAMPLE ST%'; DELETE FROM building_status WHERE building_key LIKE '12 EXAMPLE ST%';"
```

plus a `docker exec ... python -c` version for the image, which has no `sqlite3` CLI.
`tests/test_final_checks.py::test_demo_cleanup_removes_demo_report_and_status` runs the cleanup
against a temp database and checks that other rows survive.

## 4. .gitignore

One `data/*.sqlite*` line replaces the separate database, `.tmp`, and sidecar lines.

## 5. Smaller exposure

- `/health` (`app/routers/pages.py`) returns `{"status": "ok"}`. DEMO.md and DEPLOY.md explain
  how to confirm the AI (`/check?sample=1` has no "Basic analysis" badge) and the dashboard
  (`/town/login` shows the sign-in form).
- The runtime stage copies `scripts/__init__.py` and `scripts/seed_reports.py` only.

## Testing

- `.venv/bin/pytest -q` passes (768 tests at the time of this update).
- Citation checker: `.venv/bin/python .kiro/skills/massachusetts-fire-safety-sources/scripts/check_citations.py`.
- Not done: `docker build` and a live Render deploy.
