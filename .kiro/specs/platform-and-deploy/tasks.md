# Implementation Plan

- [x] 1. Request size limit
  - [x] 1.1 `LimitRequestSize` for Content-Length and chunked bodies, dropping app output after the limit (`app/main.py`)
    - _Requirements: 1.1, 1.2, 1.3, 1.5_
  - [x] 1.2 Raise `MultiPartParser.spool_max_size` to `MAX_REQUEST_BYTES`
    - _Requirements: 1.4_

- [x] 2. Security headers
  - [x] 2.1 `SecurityHeaders` with nosniff, DENY, and town no-store, no-cache, no-referrer
    - _Requirements: 2.1, 2.4, 2.5_
  - [x] 2.2 Middleware order so 413 responses get headers
    - _Requirements: 2.6_
  - [x] 2.3 `CONTENT_SECURITY_POLICY` on every response with `script-src` limited to the exact `CDN_SCRIPTS` URLs, matching the rendered script tags, and templates free of inline scripts and handlers (`tests/test_ui_hardening.py`, `tests/test_round2_csp.py`)
    - _Requirements: 2.1, 2.2, 2.3, 2.8_
  - [ ] 2.4 Load `/`, `/check` (including a report swap), `/about`, and `/town` in a real browser and confirm the console shows no CSP violations
    - _Requirements: 2.7_

- [x] 3. Validation errors that never echo input (`app/main.py::validation_error`)
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

- [x] 4. Logging off for requests and SDKs
  - [x] 4.1 Disable `uvicorn.access` at import and cap SDK loggers at WARNING
    - _Requirements: 4.1, 4.2_
  - [x] 4.2 `--no-access-log` in the entrypoint; API docs disabled
    - _Requirements: 4.3, 4.4_

- [x] 5. Settings and secrets
  - [x] 5.1 `Settings` with optional secrets and defaults, including `check_ai_per_hour = 20` (`app/config.py`)
    - _Requirements: 5.1, 5.2, 5.3, 5.4_
  - [x] 5.2 `.env` ignored by git and Docker; `.env.example` shipped
    - _Requirements: 5.5_
  - [x] 5.3 `/health` returns only `{"status": "ok"}` (`tests/test_pages.py`)
    - _Requirements: 5.6_
  - [x] 5.4 Data Commons key used only at build time; no runtime calls (`tests/test_census.py::test_no_runtime_datacommons_calls`)
    - _Requirements: 5.7_

- [x] 6. App database (`app/db.py`)
  - [x] 6.1 Schema for `reports`, `simulated_reports`, `building_status`, `revoked_sessions`
    - _Requirements: 6.1, 6.2, 6.3_
  - [x] 6.2 Path resolution, once-per-process init, re-init after deletion, `extra_categories` migration
    - _Requirements: 6.4, 6.5, 6.6, 6.7_

- [x] 7. Shared templating and pinned CDN scripts
  - _Requirements: 7.1, 7.2_

- [x] 8. Pinned dependencies in `requirements.txt` and `requirements-dev.txt`
  - _Requirements: 8.1, 8.2, 8.3_

- [x] 9. Test isolation (`tests/conftest.py`)
  - [x] 9.1 Overrides for settings, AI client, Boston DB, app DB, report limiter, and check limiter
    - _Requirements: 9.1, 9.2, 9.3, 9.4_
  - [x] 9.2 Fixture Boston DB and fake Data Commons opener
    - _Requirements: 9.5, 9.6_

- [x] 10. Container image
  - [x] 10.1 Multi-stage `Dockerfile`, raw data deleted in the builder layer
    - _Requirements: 10.1_
  - [x] 10.2 BuildKit secret `datacommons_api_key` mounted only in the data `RUN`, passed as `DATACOMMONS_API_KEY_FILE`; `build_data.sh` sets the key only for `scripts.fetch_datacommons`; never `ARG` or `ENV` (`tests/test_deploy_files.py::test_datacommons_key_is_a_build_secret_only`)
    - _Requirements: 10.2, 10.9, 5.7_
  - [x] 10.3 Runtime copies only `app/`, `scripts/__init__.py`, `scripts/seed_reports.py`, `samples/`, the entrypoint, and `boston.sqlite`
    - _Requirements: 10.3_
  - [x] 10.4 Runtime env, non-root user, read-only city DB, `/data` volume, health check
    - _Requirements: 10.4, 10.5, 10.6_
  - [x] 10.5 `.dockerignore` including `data/*.sqlite*` and `datacommons_api_key`
    - _Requirements: 10.7_
  - [ ] 10.6 Run a real `docker build` without the secret and with it; start each image, check `/health`, and check that only the keyed build has `census_zip`
    - _Requirements: 10.8_

- [x] 11. Container entrypoint (`docker/entrypoint.sh`)
  - [x] 11.1 Interpreter choice, read-only seed check, seeding into `APP_DB_PATH`
    - _Requirements: 11.1, 11.2, 11.3_
  - [x] 11.2 Exec arguments or uvicorn with `--forwarded-allow-ips="${FORWARDED_ALLOW_IPS:-127.0.0.1}"`
    - _Requirements: 11.4, 11.5_

- [x] 12. Render blueprint
  - [x] 12.1 Service, disk, health check, env vars, `FORWARDED_ALLOW_IPS` as `sync: false`
    - _Requirements: 12.1, 12.2, 12.3_
  - [ ] 12.2 After the first deploy, confirm Render's proxy range with the `docs/DEPLOY.md` command, set `FORWARDED_ALLOW_IPS`, redeploy, and check the range stays stable
    - _Requirements: 12.4_

- [x] 13. Docs
  - [x] 13.1 `docs/DEPLOY.md` with the Data Commons secret, proxy section, and privacy notes
    - _Requirements: 13.1_
  - [x] 13.2 `DEMO.md` with made-up address and cleanup of both tables (`tests/test_final_checks.py`)
    - _Requirements: 13.2_
  - [x] 13.3 `README.md` setup and privacy notes; `.gitignore` with `data/*.sqlite*`
    - _Requirements: 13.3, 13.4_
  - [x] 13.4 `README.md` Sources section lists the seven sources, including the NFPA construction site fire safety fact sheet, and the approved data sources
    - _Requirements: 13.5_

- [ ] 14. Kiro tooling
  - [x] 14.1 Steering file with rules 1 to 8, seven sources, data sources, About page exception
    - _Requirements: 14.1_
  - [x] 14.2 Five agents that read the steering file first and never read `.env`
    - _Requirements: 14.2_
  - [x] 14.3 Guard, tests-on-save, citations-on-save, and after-task hooks
    - _Requirements: 14.3, 14.4, 14.5, 14.6_
  - [x] 14.4 Sources skill with seven sources and the About page exception; checker treats `nfpa_construction` as guidance and skips symlinks
    - _Requirements: 14.7_
  - [x] 14.5 No Boston OpenContext MCP configured
    - _Requirements: 14.8_
  - [ ] 14.6 Owner adds the Data Commons MCP server to `.kiro/settings/mcp.json` for development use only (URL `https://api.datacommons.org/mcp`, header `X-API-Key: ${DATACOMMONS_API_KEY}`), then approves `DATACOMMONS_API_KEY` in Kiro settings. Agents can't write that folder.
    - _Requirements: 14.9_
  - [x] 14.7 Guard hook description and `guard_sensitive_paths.py` reason text say "the fixed citation sources" with no count
    - _Requirements: 14.10_

- [ ] 15. Source control
  - [x] 15.1 `.gitignore` keeps `.env`, `data/raw/`, and `data/*.sqlite*` out of commits (`tests/test_deploy_files.py::test_gitignore_covers_every_sqlite_file`)
    - _Requirements: 15.1_
  - [ ] 15.2 Owner makes the first real commit of the project (owner's call; agents don't commit)
    - _Requirements: 15.2_
