# Requirements: Finish Task 10 (deploy hardening and review findings)

## Introduction

The final privacy review and tester pass for Task 10 left a few open findings. This spec closes
them without changing app behavior for students, tenants, or towns. All rules in
`.kiro/steering/project-rules.md` still apply. Nothing in this spec deploys or commits.

Findings covered: M1 (spoofable X-Forwarded-For), M2 (About page citations outside the fixed
report sources), L1 (demo cleanup missed `building_status`), L2 (`.gitignore` gap), L3
(`/health` detail), and L4 (scripts in the runtime image). The owner opted in to L3 and L4, so
they are no longer optional. Current behavior for all of these is also described in
`.kiro/specs/platform-and-deploy/`.

## Requirement 1: Trusted proxy addresses (M1)

**User story:** As the project owner, I want rate limits to use the real client IP, so a client
can't bypass them by sending a fake `X-Forwarded-For` header.

### Acceptance criteria

1.1 WHEN the container starts THE SYSTEM SHALL pass `--forwarded-allow-ips` from the
`FORWARDED_ALLOW_IPS` environment variable, defaulting to `127.0.0.1`.
1.2 WHEN `FORWARDED_ALLOW_IPS` is unset THE SYSTEM SHALL NOT trust forwarded headers from any
address other than `127.0.0.1`.
1.3 THE `render.yaml` blueprint SHALL declare `FORWARDED_ALLOW_IPS` with `sync: false`, because
Render doesn't publish its proxy range, and `docs/DEPLOY.md` SHALL explain how to find the range
from the service shell and that it must never be `*`.
1.4 WHEN the service is first deployed THE owner SHALL confirm the range and set
`FORWARDED_ALLOW_IPS` to the smallest private range that covers it.
1.5 THE SYSTEM SHALL CONTINUE TO run uvicorn with `--no-access-log` and `--proxy-headers`.
1.6 WHEN the deploy files tests run THE SYSTEM SHALL check that the entrypoint uses
`${FORWARDED_ALLOW_IPS:-127.0.0.1}` and doesn't hard-code `"*"`.

## Requirement 2: About page citations (M2)

**User story:** As the founder, I want the About page story to link the news and reports behind
its facts, while the fire-safety report stays limited to the fixed sources.

Resolution: the owner approved an About page exception. It is written into the steering file and
the sources skill, and the facts in `app/content/background.py` were reworded so every number
has a linked source that supports it as worded. Reports, questions, and checklists still cite
only the seven sources in `app/content/sources.py`.

### Acceptance criteria

2.1 THE `.kiro/steering/project-rules.md` content rules SHALL include an "About page exception":
the founder-story background in `app/content/background.py` may cite news, government reports,
and research outside the fixed source list.
2.2 THE `massachusetts-fire-safety-sources` skill SHALL state the same exception.
2.3 THE SYSTEM SHALL show every number in a background fact only when a linked source supports it
as worded. WHERE a number can't be sourced THE SYSTEM SHALL reword the fact instead of showing the
number.
2.4 THE three facts that were only partly sourced SHALL be reworded to match their sources: the
sprinkler figure now says 2023 (DFS 2023 summary); the July 2025 start date is replaced by the
sourced April 2024 vote to inspect every rental at least once every five years; and the "about
120 inspections a quarter" figure is removed.
2.5 THE `app/content/background.py` docstring SHALL record the founder's original wording and
what changed to match the sources.
2.6 WHEN the About page renders THE SYSTEM SHALL link at least one source for every background
fact, opening in a new tab with "(opens in a new tab)" text.

## Requirement 3: Demo cleanup (L1)

**User story:** As the presenter, I want one cleanup step that removes everything the live demo
created.

### Acceptance criteria

3.1 WHEN the presenter follows the DEMO.md cleanup THE SYSTEM SHALL delete demo rows from both
`reports` and `building_status` for `12 EXAMPLE ST`.
3.2 THE DEMO.md cleanup SHALL include a Python command that works inside the Docker image, which
has no `sqlite3` CLI.
3.3 THE cleanup SHALL NOT touch `simulated_reports` or any real building's rows.

## Requirement 4: Ignore local databases (L2)

4.1 THE `.gitignore` SHALL ignore `data/*.sqlite*` so no local database or sidecar file can be
committed.

## Requirement 5: Smaller exposure (L3, L4)

5.1 THE `/health` endpoint SHALL return only `{"status": "ok"}`.
5.2 THE runtime image SHALL copy only the scripts it runs at start (`scripts/__init__.py` and
`scripts/seed_reports.py`, which imports only `app/`).
