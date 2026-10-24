# Requirements: App platform, security middleware, and deployment

## Introduction

This is a retroactive spec for the platform layer of TwoWaysOut: the FastAPI app object and its
middleware (`app/main.py`), settings (`app/config.py`), the app database (`app/db.py`), shared
templating (`app/templating.py`), pinned dependencies, test isolation (`tests/conftest.py`), the
Docker image and entrypoint, the Render blueprint, the deploy and demo docs, and the Kiro project
tooling under `.kiro/`. It describes what the code does today. All rules in
`.kiro/steering/project-rules.md` apply.

The Task 10 review findings (trusted proxy addresses, demo cleanup, `.gitignore`, `/health`, and
runtime scripts) are closed and are now described here as current behavior. The history of those
fixes is in `.kiro/specs/task-10-finish/`. Criteria marked "(open)" are not met yet; see
`tasks.md`. Most open items need a real browser, a real `docker build`, a live Render deploy, or
an owner decision.

## Requirement 1: Request size limit

**User story:** As the project owner, I want request bodies capped before they are read, so a
large upload can't fill memory or spill a lease to a temp file.

### Acceptance criteria

1.1 WHEN an HTTP request declares a `Content-Length` greater than `MAX_REQUEST_BYTES`
(`MAX_PDF_BYTES` of 5 MB plus 256 KB) THE SYSTEM SHALL respond 413 with "That upload is too
large. The limit is 5 MB." without passing the request to the app.
1.2 WHEN a request without `Content-Length` (chunked) streams more than `MAX_REQUEST_BYTES` THE
SYSTEM SHALL stop reading, discard any response the app tried to start, and respond 413.
1.3 WHEN a request body is within the limit THE SYSTEM SHALL pass it through unchanged.
1.4 THE SYSTEM SHALL set Starlette's `MultiPartParser.spool_max_size` to `MAX_REQUEST_BYTES` so
uploads up to the limit stay in memory and never roll over to a temp file.
1.5 WHERE the ASGI scope is not `http` THE SYSTEM SHALL pass it through without checks.

## Requirement 2: Security headers

**User story:** As the project owner, I want every response to carry basic security headers and a
content security policy, and town pages to stay out of caches and referrers.

### Acceptance criteria

2.1 WHEN any HTTP response starts THE SYSTEM SHALL set `X-Content-Type-Options: nosniff`,
`X-Frame-Options: DENY`, and `Content-Security-Policy` to `CONTENT_SECURITY_POLICY`.
2.2 THE `CONTENT_SECURITY_POLICY` SHALL be `default-src 'self'`; `script-src 'self'` followed by
the exact file URLs in `CDN_SCRIPTS` (the pinned `@tailwindcss/browser@4.3.3` and
`htmx.org@2.0.11` files on jsDelivr), not the whole CDN host; `style-src 'self' 'unsafe-inline'`;
`img-src 'self' data:`; `connect-src 'self'`; `object-src 'none'`; `base-uri 'self'`;
`form-action 'self'`; `frame-ancestors 'none'`. It SHALL NOT allow `'unsafe-inline'` or
`'unsafe-eval'` for scripts.
2.3 THE templates SHALL contain no inline `<script>` bodies, inline event-handler attributes,
`hx-on` attributes, `javascript:` URLs, or htmx `js:` expressions, so the policy needs no script
exceptions.
2.4 WHEN the path is `/town` or starts with `/town/` THE SYSTEM SHALL set `Cache-Control:
no-store`, `Pragma: no-cache`, and `Referrer-Policy: no-referrer`.
2.5 WHEN the path is not a town path and the response has no `Referrer-Policy` THE SYSTEM SHALL
set `Referrer-Policy: strict-origin-when-cross-origin`.
2.6 THE SYSTEM SHALL register the size-limit middleware before the header middleware, so the
header middleware wraps it and 413 responses also get the headers.
2.7 (open) WHEN the pages load in a real browser with the policy THE SYSTEM SHALL show no CSP
violations for the Tailwind browser build, htmx, `embers.js`, or `smoke.js`.
2.8 WHEN the base template renders THE external `<script src>` URLs SHALL be exactly the
`CDN_SCRIPTS` URLs, so the policy and the pinned script tags can't drift apart.

## Requirement 3: Validation errors never echo input

**User story:** As a student or tenant, I want a plain message when my input is too long, and I
don't want my text echoed back in an error.

### Acceptance criteria

3.1 WHEN a `RequestValidationError` occurs on an HTMX request (`HX-Request: true`) THE SYSTEM
SHALL return `partials/check_error.html` with "Some of what you entered is too long. Please
shorten it and try again." and status 200.
3.2 WHEN it occurs on a non-HTMX `/check` request THE SYSTEM SHALL render `check.html` with that
message, empty `address` and `listing`, and status 422.
3.3 WHEN it occurs on a non-HTMX `/report` request THE SYSTEM SHALL render the report form with
that message and status 422.
3.4 WHEN it occurs on any other path THE SYSTEM SHALL render `error.html` with that message and
status 422.
3.5 THE SYSTEM SHALL NOT include submitted values or FastAPI's default JSON `detail` in any of
these responses.

## Requirement 4: No request or SDK logging of user data

**User story:** As a tenant, I want my IP and the addresses I look up kept out of server logs.

### Acceptance criteria

4.1 WHEN `app.main` is imported THE SYSTEM SHALL clear the `uvicorn.access` logger's handlers,
stop it propagating, and disable it.
4.2 WHEN `app.main` is imported THE SYSTEM SHALL set the `anthropic`, `httpx`, `httpx2`, and
`httpcore` loggers to WARNING.
4.3 WHEN the container starts uvicorn THE SYSTEM SHALL pass `--no-access-log`.
4.4 THE SYSTEM SHALL disable the interactive API docs (`docs_url=None`, `redoc_url=None`).

## Requirement 5: Settings and secrets

**User story:** As the project owner, I want settings from environment variables, with secrets
kept out of the repo and the image, and the app still able to start without them.

### Acceptance criteria

5.1 THE SYSTEM SHALL load settings from environment variables or a local `.env` file, ignoring
unknown keys.
5.2 WHERE `ANTHROPIC_API_KEY`, `DASHBOARD_PASSWORD`, or `SESSION_SECRET` is unset THE SYSTEM
SHALL still start, with the features that need them degrading.
5.3 THE SYSTEM SHALL default `anthropic_model` to `claude-sonnet-5-5`, `ai_timeout_seconds` to
30, `app_db_path` to `data/app.sqlite`, `reports_per_hour` to 5, `check_ai_per_hour` to 20, and
`force_secure_cookies` to false.
5.4 THE SYSTEM SHALL cache one `Settings` instance per process through `get_settings`.
5.5 THE repository SHALL keep secrets only in `.env`, which `.gitignore` and `.dockerignore`
exclude, and SHALL ship `.env.example` with empty values.
5.6 WHEN `/health` is requested THE SYSTEM SHALL return only `{"status": "ok"}`, and SHALL NOT
say which features are configured or return any secret value.
5.7 THE optional `DATACOMMONS_API_KEY` SHALL be a build-time value only: it is never a runtime
setting, never read by `app/`, and never baked into an image layer.

## Requirement 6: App database

**User story:** As the project owner, I want the tenant reports database created and migrated
automatically, separate from the read-only Boston data.

### Acceptance criteria

6.1 THE SYSTEM SHALL create the `reports`, `simulated_reports`, `building_status`, and
`revoked_sessions` tables and their indexes with `CREATE TABLE IF NOT EXISTS`.
6.2 THE `simulated_reports` table SHALL have no address, parcel, SAM ID, or ZIP columns.
6.3 THE `reports.created_at` and `simulated_reports.created_at` defaults SHALL have day
precision only.
6.4 WHEN `app_db_path` is relative THE SYSTEM SHALL resolve it against the project root.
6.5 WHEN the app database is first requested in a process, or the file no longer exists, THE
SYSTEM SHALL create the parent directory and apply the schema.
6.6 WHEN an existing `reports` table lacks `extra_categories` THE SYSTEM SHALL add it, and SHALL
tolerate another process having added it first.
6.7 WHEN a connection is opened through `connect` THE SYSTEM SHALL use `sqlite3.Row` rows and
turn on foreign keys.

## Requirement 7: Shared templating

7.1 THE SYSTEM SHALL use one Jinja2 environment for all routers, with `DISCLAIMER` and
`RANKING_STATEMENT` from `app/content/copy.py` as globals.
7.2 THE base template SHALL load Tailwind and HTMX from pinned jsDelivr versions with subresource
integrity hashes and `crossorigin="anonymous"`.

## Requirement 8: Pinned dependencies

8.1 THE `requirements.txt` file SHALL pin every runtime dependency with `==` (fastapi, uvicorn,
jinja2, pydantic, pydantic-settings, python-multipart, pypdf, anthropic, pandas).
8.2 THE `requirements-dev.txt` file SHALL include `requirements.txt` and pin the test-only
dependencies (`pytest`, `httpx2`) with `==`.
8.3 THE final Docker image SHALL install only `requirements.txt`.

## Requirement 9: Test isolation

**User story:** As a developer, I want the test suite to run offline without touching my secrets
or real data.

### Acceptance criteria

9.1 WHEN a test uses the `client` fixture THE SYSTEM SHALL override `get_settings` with
`Settings(_env_file=None)` so `.env` is never read.
9.2 WHEN a test uses the `client` fixture THE SYSTEM SHALL override `get_ai_client` to return
`None`, so no real Claude call is possible.
9.3 WHEN a test uses the `client` fixture THE SYSTEM SHALL point `get_boston_db` at a
non-existent path under `tmp_path`, and `get_app_db` at a fresh database under `tmp_path`.
9.4 WHEN a test uses the `client` fixture THE SYSTEM SHALL give it a fresh report rate limiter
(5 per hour) and a fresh check rate limiter (20 per hour), and SHALL clear all dependency
overrides afterward.
9.5 WHERE a test needs Boston data THE SYSTEM SHALL build a fixture database
(`tests/fixtures/boston_db.py`) instead of reading `data/boston.sqlite`.
9.6 THE tests SHALL never call Data Commons or any other network service; the Data Commons
fetcher is tested with a fake opener.

## Requirement 10: Container image

**User story:** As the project owner, I want an image that carries the preprocessed Boston data
but never the raw downloads, secrets, or dev files.

### Acceptance criteria

10.1 THE `Dockerfile` SHALL use two `python:3.12-slim` stages: a builder that runs
`scripts/build_data.sh --python python`, deletes `data/raw` in the same `RUN`, and checks that
`data/boston.sqlite` exists; and a final runtime stage.
10.2 THE builder's data `RUN` SHALL mount the BuildKit secret `datacommons_api_key` and pass
`DATACOMMONS_API_KEY_FILE=/run/secrets/datacommons_api_key` to `scripts/build_data.sh`. WHEN that
file is non-empty THE script SHALL set `DATACOMMONS_API_KEY` only for the
`scripts.fetch_datacommons` command, so no other step sees the key. The key SHALL NOT appear in
any `ARG` or `ENV`, and the final stage SHALL NOT reference Data Commons at all.
10.3 THE final stage SHALL copy only `requirements.txt`, `app/`, `scripts/__init__.py`,
`scripts/seed_reports.py`, `samples/`, `docker/entrypoint.sh`, and `boston.sqlite` from the
builder. It SHALL NOT copy `data/raw`, `.env`, the rest of `scripts/`, or the whole build
context, and SHALL check that `data/raw` does not exist.
10.4 THE final stage SHALL set `APP_DB_PATH=/data/app.sqlite`, `FORCE_SECURE_COOKIES=true`,
`SEED_SIMULATED=0`, `PYTHONDONTWRITEBYTECODE=1`, and `PYTHONUNBUFFERED=1`, and SHALL NOT set any
secret in `ENV` or `ARG`.
10.5 THE final stage SHALL run as non-root user `app` (uid 10001), make `data/boston.sqlite`
read-only (0444), and declare `/data` as a volume owned by that user.
10.6 THE final stage SHALL expose port 8000 and run a `HEALTHCHECK` against `/health` on `PORT`.
10.7 THE `.dockerignore` file SHALL exclude `.env`, `.env.*` (except `.env.example`), `.git`,
`.venv`, `data/raw`, `data/*.sqlite*`, `.kiro`, `tests`, caches, bytecode, and a
`datacommons_api_key` file in the context root (where Render copies secret files).
10.8 (open) WHEN the image is built for real, once without and once with the
`datacommons_api_key` secret, THE build SHALL succeed, the image SHALL start and answer
`/health`, and only the keyed build SHALL produce a `census_zip` table.
10.9 WHERE `build_data.sh` runs without a key file THE script SHALL use `DATACOMMONS_API_KEY`
from the environment if set (local builds), and otherwise skip the Data Commons step. A failed
Data Commons fetch SHALL NOT fail the build.

## Requirement 11: Container entrypoint

11.1 WHEN `docker/entrypoint.sh` runs THE SYSTEM SHALL use `set -eu`, change to the project root,
and use `$PYTHON`, else `.venv/bin/python` if present, else `python`.
11.2 WHEN `SEED_SIMULATED=1` and the `simulated_reports` table is missing or empty THE SYSTEM
SHALL run `scripts.seed_reports --db "$DB"`, where `DB` is `APP_DB_PATH`, defaulting to
`/data/app.sqlite`.
11.3 WHILE checking the seed count THE SYSTEM SHALL open the database read-only, so the check
alone never creates a file.
11.4 WHEN arguments are passed THE SYSTEM SHALL exec them instead of uvicorn.
11.5 WHEN no arguments are passed THE SYSTEM SHALL exec uvicorn on `0.0.0.0:${PORT:-8000}` with
`--no-access-log`, `--proxy-headers`, and
`--forwarded-allow-ips="${FORWARDED_ALLOW_IPS:-127.0.0.1}"`, and SHALL NOT hard-code `"*"`.

## Requirement 12: Render blueprint

12.1 THE `render.yaml` file SHALL define a Docker web service on the `starter` plan with
`healthCheckPath: /health` and a 1 GB disk mounted at `/data`.
12.2 THE blueprint SHALL mark `ANTHROPIC_API_KEY`, `DASHBOARD_PASSWORD`, and
`FORWARDED_ALLOW_IPS` as `sync: false`, SHALL set `SESSION_SECRET` with `generateValue: true`,
and SHALL NOT contain a literal value for any secret.
12.3 THE blueprint SHALL set `APP_DB_PATH=/data/app.sqlite`, `FORCE_SECURE_COOKIES=true`, and
`SEED_SIMULATED=1`.
12.4 (open) WHEN the service is first deployed THE owner SHALL confirm the address range Render's
proxy connects from and set `FORWARDED_ALLOW_IPS` to the smallest private range that covers it,
never `*`.

## Requirement 13: Docs

13.1 THE `docs/DEPLOY.md` file SHALL cover building data locally, running the image locally,
the Data Commons BuildKit secret (local and as a Render secret file, never an env var), deploying
on Render, finding and setting `FORWARDED_ALLOW_IPS`, seeding simulated data, and privacy notes,
and every `python -m scripts.<name>` it mentions SHALL exist.
13.2 THE `DEMO.md` file SHALL use a made-up address (`12 Example St`) for the live report, SHALL
say never to submit a report for `41 Parker Hill Ave`, SHALL clean up demo rows from both
`reports` and `building_status` (with a `sqlite3` command and a Python command for the Docker
image), and every route and file path it mentions SHALL exist.
13.3 THE `README.md` file SHALL describe local setup with `.venv` and `--no-access-log`, the
proxy and logging privacy notes, and link to `docs/DEPLOY.md` and `DEMO.md`.
13.4 THE `.gitignore` file SHALL ignore `.env`, `.env.*` (except `.env.example`), `data/raw/`,
`data/*.sqlite*` (databases, `.tmp` builds, and journal, WAL, and shared-memory sidecars),
`.venv/`, and caches.
13.5 THE `README.md` file SHALL list the seven citation sources, including the NFPA
construction site fire safety fact sheet, and the approved data sources.

## Requirement 14: Kiro project tooling

14.1 THE `.kiro/steering/project-rules.md` file SHALL be included always and state the stack,
commands, layout, privacy rules 1 to 8, content rules (seven sources, approved data sources, the
About page exception), ranking, and accessibility rules.
14.2 THE `.kiro/agents/` folder SHALL define builder, data engineer, privacy reviewer
(read-only), tester (edits only `tests/`), and UI designer agents, each told to read the
steering file first and never read `.env`.
14.3 WHEN the agent is about to write, edit, move, or delete `.env`, `data/raw/`, a
`data/*.sqlite*` file, the steering file, `app/content/sources.py`, `app/content/copy.py`, the
`Dockerfile`, `render.yaml`, or `docker/entrypoint.sh` THE SYSTEM SHALL ask the user to confirm
(`guard_sensitive_paths.py` prints a `permissionDecision: "ask"`), without printing file
contents.
14.4 WHEN a file in `app/`, `tests/`, or `scripts/` ending in `.py`, `.html`, `.js`, or `.css`
is saved THE SYSTEM SHALL run `.venv/bin/pytest -q -x`.
14.5 WHEN a file in `app/content/`, `app/templates/`, or one of the analyzer or building
question services is saved THE SYSTEM SHALL run the citation checker.
14.6 WHEN a spec task completes THE SYSTEM SHALL prompt the agent to run the tests, a read-only
privacy review, and the citation checker when copy changed.
14.7 THE `massachusetts-fire-safety-sources` skill SHALL document the seven sources, citation
rules, the About page exception, and the approved data sources, and its `check_citations.py`
SHALL treat `nfpa_construction` as guidance and flag section-number citations, em dashes, safe or
compliant claims, and `required_by` on guidance sources, exiting 1 on any finding. The checker
SHALL skip symlinks, so a link inside a scanned folder can't make it read and print a file
outside the project.
14.8 THE project SHALL NOT configure Boston's OpenContext MCP for the app, because it would let an
AI query raw datasets live and bypass the column whitelists in privacy rule 1.
14.9 (open) WHERE the owner wants Data Commons exploration during development THE
`.kiro/settings/mcp.json` file SHALL configure the Data Commons MCP server for Kiro only, with
URL `https://api.datacommons.org/mcp` and header `X-API-Key: ${DATACOMMONS_API_KEY}`, and the
owner SHALL approve that environment variable in Kiro settings so the key is never written into
the file. The app never uses this server. Agents can't write `.kiro/settings/`, so the owner
adds it.
14.10 THE guard hook's description and reason text SHALL refer to "the fixed citation sources"
without a count, so they stay correct when the source list changes.

## Requirement 15: Source control

15.1 THE `.gitignore` rules in 5.5 and 13.4 SHALL keep `.env`, `data/raw/`, and every
`data/*.sqlite*` file out of any commit.
15.2 (open) WHEN the owner decides the project is ready THE owner SHALL make the first real
commit of the project. Today the history has only an "Initial commit" that adds one line to
`README.md`. Agents never commit on their own.
