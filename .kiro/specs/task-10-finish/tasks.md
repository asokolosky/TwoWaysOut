# Implementation Plan

- [x] 0. Remove exclamation points from the sample listing
  - `app/content/samples.py`: "walk to campus." and "these go fast."
  - Fixes `test_prefilled_sample_listing_has_no_em_dash_or_exclamation`

- [ ] 1. Make trusted proxy addresses configurable
  - [x] 1.1 Use `${FORWARDED_ALLOW_IPS:-127.0.0.1}` in `docker/entrypoint.sh`
    - _Requirements: 1.1, 1.2, 1.5_
  - [x] 1.2 Confirm uvicorn CIDR support (0.31.0 and later; pinned 0.54.0) and add `FORWARDED_ALLOW_IPS` to `render.yaml` as `sync: false`
    - _Requirements: 1.3_
  - [x] 1.3 Update the Dockerfile comment and the "Client IPs behind a proxy" section of `docs/DEPLOY.md`
    - _Requirements: 1.3_
  - [x] 1.4 `tests/test_deploy_files.py::test_forwarded_ips_never_trust_every_peer` checks the new flag and that `"*"` isn't hard-coded
    - _Requirements: 1.6_
  - [ ] 1.5 On a live Render deploy, confirm the proxy range and set `FORWARDED_ALLOW_IPS` (tracked as task 12.2 in `.kiro/specs/platform-and-deploy/tasks.md`)
    - _Requirements: 1.4_

- [x] 2. Resolve About page citations (owner approved the exception)
  - [x] 2.1 Owner decision: approve the About page exception; reword facts that can't be sourced
    - _Requirements: 2.1, 2.3_
  - [x] 2.2 Add the "About page exception" to `.kiro/steering/project-rules.md` and the sources skill
    - _Requirements: 2.1, 2.2_
  - [x] 2.3 Reword the 2024 sprinkler, July 2025 start, and 120-inspections facts in `app/content/background.py` so every number is sourced
    - _Requirements: 2.3, 2.4_
  - [x] 2.4 Rewrite the `background.py` docstring with the original wording and what changed
    - _Requirements: 2.5_
  - [x] 2.5 Tests: `tests/test_pages.py::test_about_background_facts_each_have_a_linked_source` and `tests/test_final_checks.py::test_about_background_facts_verbatim_and_sources_open_safely`
    - _Requirements: 2.6_

- [x] 3. Complete the demo cleanup
  - [x] 3.1 Add the `building_status` delete and the Docker Python command to DEMO.md
    - _Requirements: 3.1, 3.2, 3.3_
  - [x] 3.2 `tests/test_final_checks.py::test_demo_cleanup_removes_demo_report_and_status`
    - _Requirements: 3.1, 3.3_

- [x] 4. Ignore all local SQLite files with `data/*.sqlite*` in `.gitignore` (`tests/test_deploy_files.py::test_gitignore_covers_every_sqlite_file`)
  - _Requirements: 4.1_

- [x] 5. Reduce exposure (owner opted in)
  - [x] 5.1 Return only `{"status": "ok"}` from `/health` (`tests/test_pages.py::test_health_is_status_only`); DEMO.md and DEPLOY.md updated to match
    - _Requirements: 5.1_
  - [x] 5.2 Copy only `scripts/__init__.py` and `scripts/seed_reports.py` into the runtime image (`tests/test_deploy_files.py::test_final_stage_copies_only_startup_scripts`)
    - _Requirements: 5.2_
  - Note: a real `docker build` and start, which also exercises seeding, is general deploy verification and is tracked as task 10.6 in `.kiro/specs/platform-and-deploy/tasks.md`.
