# Design: App platform, security middleware, and deployment

## Overview

TwoWaysOut is one FastAPI process. `app/main.py` builds the app, adds two pure ASGI middlewares,
installs a validation error handler, turns off request logging, mounts `/static`, and includes
four routers (`pages`, `check`, `report`, `town`). Settings come from the environment. Two
SQLite files back it: `data/boston.sqlite` (read-only city data built offline) and the app
database (`APP_DB_PATH`, tenant reports and town state). The same image runs locally and on
Render.

## Request path

```
client -> Render proxy (TLS) -> uvicorn --proxy-headers --forwarded-allow-ips=$FORWARDED_ALLOW_IPS
  SecurityHeaders            adds nosniff, DENY, CSP; town paths: no-store, no-cache, no-referrer
    LimitRequestSize         413 on Content-Length or streamed bytes > MAX_REQUEST_BYTES
      FastAPI app
        RequestValidationError -> friendly, non-echoing error (partial 200 or page 422)
        /static, pages, check, report, town routers
```

`app.add_middleware` wraps outward, so registering `LimitRequestSize` first and
`SecurityHeaders` second puts the header middleware outside. Its 413 responses get the headers.

## Components

| Component | File | Notes |
|---|---|---|
| Size guard | `app/main.py::LimitRequestSize` | Checks `Content-Length`, then counts received bytes; raises `_BodyTooLarge` inside `receive`, swallows app output after the limit, sends its own 413. `MultiPartParser.spool_max_size = MAX_REQUEST_BYTES`. |
| Headers | `app/main.py::SecurityHeaders`, `CONTENT_SECURITY_POLICY` | See "Content security policy" below. |
| Validation handler | `app/main.py::validation_error` | `TOO_LONG_MESSAGE`; HTMX gets `partials/check_error.html` with 200 (htmx skips 4xx swaps); `/check` and `/report` get their forms with 422; other paths `error.html`. |
| Logging | `app/main.py` (import time) | `uvicorn.access` handlers cleared, not propagated, disabled. `anthropic`, `httpx`, `httpx2`, `httpcore` at WARNING. |
| Settings | `app/config.py` | `Settings(BaseSettings)`, `env_file=".env"`, `extra="ignore"`; `get_settings` is `lru_cache`d. |
| App DB | `app/db.py` | `SCHEMA`, `init_db` (schema plus additive `extra_categories` migration), `connect`, `get_app_db` (schema once per path per process, again if the file vanished). |
| Templates | `app/templating.py` | One `Jinja2Templates`, globals `DISCLAIMER`, `RANKING_STATEMENT`. |
| Health | `app/routers/pages.py::health` | Returns `{"status": "ok"}` only. |
| Test isolation | `tests/conftest.py` | `client` fixture overrides settings, AI client, Boston DB, app DB, report limiter, and check limiter. |
| Image | `Dockerfile` | Builder and runtime stages (below). |
| Entrypoint | `docker/entrypoint.sh` | Optional seeding, then `exec` uvicorn or the given command. |
| Blueprint | `render.yaml` | Docker web service, starter plan, disk at `/data`. |
| Docs | `docs/DEPLOY.md`, `DEMO.md`, `README.md` | Deploy steps, demo script and cleanup, local setup. |

### Content security policy

```
default-src 'self';
script-src 'self'
  https://cdn.jsdelivr.net/npm/@tailwindcss/browser@4.3.3/dist/index.global.js
  https://cdn.jsdelivr.net/npm/htmx.org@2.0.11/dist/htmx.min.js;
style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none';
base-uri 'self'; form-action 'self'; frame-ancestors 'none'
```

- Scripts: only this origin (`embers.js`, `smoke.js`) and the two exact file URLs in
  `app/main.py::CDN_SCRIPTS`, not the whole jsDelivr host. `base.html` loads those same URLs with
  SRI hashes. `tests/test_ui_hardening.py::test_csp_directives` checks that the rendered
  `<script src>` URLs equal `CDN_SCRIPTS`, so bumping a version in one place fails the tests
  until the other matches.
- No inline scripts. `tests/test_ui_hardening.py` scans every template for inline `<script>`
  bodies, `on*=` handlers, `hx-on`, `javascript:`, and htmx `js:` expressions.
- `style-src 'unsafe-inline'` is needed because the Tailwind browser build and htmx inject
  `<style>` elements at runtime.
- Owned static URLs are relative (`/static/styles.css`), so pages behind an untrusted proxy don't
  get `http://` asset URLs on an `https://` page.
- The policy is tested header by header but has not been loaded in a real browser yet.

### App database schema (`app/db.py`)

- `reports`: address input and key, display address, parcel, SAM ID, ward, ZIP, `category`,
  `extra_categories`, redacted `description`, `observed_date`, day-precision `created_at`,
  `is_simulated` (CHECK 0 or 1), `status` (CHECK open, scheduled, inspected). No identity or IP
  columns.
- `simulated_reports`: `sim_building`, ward, rental type, category, fictional description,
  dates. No address, parcel, SAM ID, or ZIP.
- `building_status`: `building_key`, `status`, `updated_on` (day). Workflow only.
- `revoked_sessions`: random `nonce`, `expires_at` (Unix seconds).

## Container image

```
builder (python:3.12-slim, /build)
  pip install -r requirements.txt
  COPY scripts/ app/                     preprocessing imports app.services.address_normalize
  RUN --mount=type=secret,id=datacommons_api_key
      DATACOMMONS_API_KEY_FILE=/run/secrets/datacommons_api_key \
        bash scripts/build_data.sh --python python
      rm -rf data/raw                    same layer, so raw CSVs never persist
      test -f data/boston.sqlite

final (python:3.12-slim, /app)
  ENV APP_DB_PATH=/data/app.sqlite FORCE_SECURE_COOKIES=true SEED_SIMULATED=0 ...
  useradd app (uid 10001)
  pip install -r requirements.txt        never requirements-dev.txt
  COPY app/ ; scripts/__init__.py scripts/seed_reports.py ; samples/ ; docker/entrypoint.sh
  COPY --from=builder data/boston.sqlite
  chmod 0444 boston.sqlite; test ! -e data/raw; /data owned by app
  USER app; VOLUME /data; EXPOSE 8000; HEALTHCHECK /health on $PORT
  CMD /app/docker/entrypoint.sh
```

The Data Commons key is a BuildKit secret, never an `ARG` or `ENV`, so it isn't in image history.
The `RUN` passes only the secret's file path. `build_data.sh` checks that the file is non-empty
and then sets `DATACOMMONS_API_KEY` as a prefix on the single `scripts.fetch_datacommons`
command, so `fetch_boston` and `preprocess_boston` never see it. A failed fetch prints a message
without the key and the build continues. Local runs without a key file fall back to
`DATACOMMONS_API_KEY` in the environment. Without any key the step is skipped and the image has
no `census_zip` table.
On Render the key is a secret file named `datacommons_api_key`; Render mounts secret files as
build secrets with the file name as the ID, and also copies them into the context root, which
`.dockerignore` excludes.

The runtime image copies only the two `scripts/` files start-up needs. `seed_reports.py` imports
only `app/`. The rest of the pipeline stays in the builder.

## Entrypoint and proxies

`docker/entrypoint.sh` runs from the project root so `-m scripts.*` and `app.main` resolve in the
image and locally. It seeds only when `SEED_SIMULATED=1` and a read-only count of
`simulated_reports` is 0 (a missing file or table counts as 0). With no arguments it execs:

```
python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --no-access-log \
  --proxy-headers --forwarded-allow-ips="${FORWARDED_ALLOW_IPS:-127.0.0.1}"
```

uvicorn takes the client IP from `X-Forwarded-For` only when the peer is in
`FORWARDED_ALLOW_IPS`. The pinned uvicorn 0.54.0 accepts CIDR ranges (0.31.0 and later). The rate
limiters key on `request.client.host`, so trusting `*` would let any client choose its own key.
Render doesn't publish its proxy range, so `render.yaml` leaves the value to the owner
(`sync: false`). Until it's set, all visitors share one report limit, one check limit, and one
login limit. `docs/DEPLOY.md` gives a one-line `/proc/net/tcp` command to list the proxy peers
from the Render shell.

## Docs

- `docs/DEPLOY.md`: local data build, local Docker run, Data Commons secret (local and Render),
  Render blueprint steps, how to confirm the AI and dashboard without `/health` flags, client IPs
  behind a proxy, persistent disk notes, seeding, privacy notes.
- `DEMO.md`: pre-demo checklist (`/health` returns `{"status": "ok"}`), 3-minute script, made-up
  `12 Example St` for the live report, never report `41 Parker Hill Ave`, cleanup of `reports`
  and `building_status` with `sqlite3` or a Docker-safe Python one-liner, fallbacks.
- `README.md`: local setup, privacy notes, Boston data, AI, town dashboard, layout, sources. Its
  Sources section lists the seven citation sources and the approved data sources.
- `.gitignore`: `.env`, `.env.*` except `.env.example`, `data/raw/`, `data/*.sqlite*`, `.venv/`,
  caches. The git history has only a one-line "Initial commit"; the first real commit is the
  owner's call.

## Kiro tooling

| Item | Path | Behavior |
|---|---|---|
| Steering | `.kiro/steering/project-rules.md` | `inclusion: always`. Stack, layout, privacy rules 1 to 8, content rules, ranking rules, accessibility. |
| Agents | `.kiro/agents/twowaysout-{builder,data-engineer,privacy-reviewer,tester,ui-designer}.md` | Each reads the steering file first and never reads `.env`. Privacy reviewer has `read` only. Tester edits only `tests/`. |
| Guard hook | `.kiro/hooks/guard-sensitive-files.json`, `hooks/scripts/guard_sensitive_paths.py` | `PreToolUse` on write, replace, append, delete, relocate. Finds path keys in the tool input; prints `permissionDecision: "ask"` for sensitive paths. Reason text says "the fixed citation sources" with no count. Stdlib only, never prints contents. |
| Tests on save | `.kiro/hooks/run-tests-on-save.json` | `PostFileSave` on `app/`, `tests/`, `scripts/` `.py/.html/.js/.css`; `pytest -q -x`. |
| Citations on save | `.kiro/hooks/check-citations-on-save.json` | `PostFileSave` on `app/content/`, `app/templates/`, analyzers, `building_questions.py`. |
| After task | `.kiro/hooks/privacy-review-after-task.json` | `PostTaskExec` agent prompt: tests, read-only privacy review, citation check. |
| Sources skill | `.kiro/skills/massachusetts-fire-safety-sources/` | `SKILL.md` lists the seven sources, which to use per topic, the About page exception, data sources, and verification notes. `scripts/check_citations.py` (`GUIDANCE_IDS` includes `nfpa_construction`; skips symlinks so a link can't make it read and print an outside file). |

MCP servers: Boston's OpenContext MCP is deliberately not used, at runtime or for building data,
because it queries raw datasets live and would skip the `usecols` whitelists. The Data Commons
MCP could help the owner explore variables during development. It is Kiro-only and not
configured yet: `.kiro/settings/` doesn't exist and agents can't write it. The owner adds:

```json
{
  "mcpServers": {
    "datacommons": {
      "url": "https://api.datacommons.org/mcp",
      "headers": { "X-API-Key": "${DATACOMMONS_API_KEY}" }
    }
  }
}
```

then approves `DATACOMMONS_API_KEY` in Kiro settings so the key is read from the environment and
never written into the file.

## Error handling

| Case | Behavior |
|---|---|
| Body too large | 413 plain text, with security headers |
| Over-length field | `TOO_LONG_MESSAGE`, values never echoed |
| Missing secrets | App starts; AI falls back to rules, dashboard shows its setup page |
| App DB deleted while running | Schema re-applied on the next request |
| Concurrent migration | `duplicate column` error ignored |
| No Data Commons key at build | Step skipped; no `census_zip`; census card never shows |
| Data Commons request fails at build | Script exits 1 without the key in the message; `build_data.sh` continues |

## Testing strategy

| File | Covers |
|---|---|
| `tests/test_privacy_hardening.py` | Access log off, SDK loggers, Content-Length and chunked limits |
| `tests/test_final_checks.py` | Security headers on public and town pages, DEMO.md and DEPLOY.md references, demo cleanup |
| `tests/test_ui_hardening.py` | CSP on every response and its directives, `script-src` equal to `CDN_SCRIPTS` and to the rendered script tags, no inline scripts, pinned SRI scripts, relative static URLs |
| `tests/test_round2_csp.py` | CSP on GET pages, check results, check errors, and 404s |
| `tests/test_pages.py` | `/health` is status only and reveals no configuration |
| `tests/test_deploy_files.py` | Final stage copies, raw data deleted, startup scripts only, Data Commons build secret, `.gitignore`, runtime env, no baked secrets, non-root, `.dockerignore`, Render secrets, `build_data.sh`, entrypoint flags and seeding guard, forwarded IPs never `*` |
| `tests/test_check_rate_limit.py` | `check_ai_per_hour` default and dependency |
| `tests/test_census.py` | Fetcher with a fake opener, no runtime Data Commons calls |

No test runs `docker build`, deploys, or loads pages in a browser. Run `.venv/bin/pytest -q`
(768 passed at the time of this update) and the citation checker (passed, 36 files).
