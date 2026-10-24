---
inclusion: always
---

# TwoWaysOut project rules

TwoWaysOut helps students check off-campus rentals for fire safety before signing a lease, and
gives towns a list of buildings ranked by reported problems. Solo hackathon project (Hackachusetts).

## Stack and commands

- Python 3.12 in `.venv` (system Python is 3.9; always use `.venv/bin/python`, `.venv/bin/pytest`).
- FastAPI + Jinja2 + HTMX + Tailwind (CDN, pinned with SRI), pandas, SQLite, Anthropic SDK.
- Pin exact versions in `requirements.txt` / `requirements-dev.txt`. Install with
  `uv pip install --python .venv/bin/python <pkg>==<version>`.
- Tests: `.venv/bin/pytest -q` (must pass before any task is done).
- Boston data: `.venv/bin/python -m scripts.fetch_boston` then `.venv/bin/python -m scripts.preprocess_boston`.
- Never start long-running servers with plain shell commands; use a background process and stop it after.

## Layout

- `app/` app code: `routers/`, `services/`, `content/` (fixed copy, sources, questions), `templates/`, `static/`.
- `scripts/` data pipeline (`fetch_boston.py`, `preprocess_boston.py`, `history.py`).
- `data/raw/` raw downloads (gitignored, contain PII). `data/boston.sqlite` read-only city data.
  `data/app.sqlite` tenant reports (gitignored).
- `tests/` pytest; fixtures in `tests/fixtures/`. Tests must never call the real Claude API, read
  `.env`, read the real Boston DB, or write the real app DB (see `tests/conftest.py` overrides).

## Privacy rules (non-negotiable)

1. Never read, store, display, or log these fields. Read raw CSVs with explicit `usecols` whitelists:
   - Property Assessment: `OWNER`, `MAIL_ADDRESSEE`, `MAIL_STREET_ADDRESS`, `MAIL_CITY`, `MAIL_STATE`, `MAIL_ZIP_CODE`
   - RentSmart: `owner`
   - Building violations: `contact_addr1`, `contact_addr2`, `contact_city`, `contact_state`, `contact_zip`
   - Building permits: `applicant`, `comments`
2. Building-level history is only stored and shown for likely rentals. Non-rentals and unmatched
   addresses get area-level (ZIP/ward) context only.
3. Tenant reports are anonymous: no name, email, phone, or account fields. Emails and phone numbers
   in descriptions are removed before saving. Client IPs are used only in memory for rate limiting
   and never stored or logged.
4. Uploaded lease PDFs and pasted listing text are processed in memory and never written to disk,
   a database, or logs. (Uploads up to the size limit must not spool to a temp file.)
5. Simulated tenant reports live only in the `simulated_reports` table, which has no address,
   parcel, SAM ID, or ZIP columns (ward + rental type + synthetic `sim_building` ID only). They are
   shown in their own clearly labeled "SIMULATED" section, never linked to a real building, and
   never affect the ranking of real buildings. Real ranking reads only `reports` with
   `is_simulated = 0`. User submissions are always `is_simulated = 0` in `reports`.
6. Secrets live only in `.env` (gitignored). Never print, log, or return secret values.
7. Don't send project data, listings, or reports to any third party except the Claude API for analysis.
   Data Commons (U.S. Census) data is fetched only at build time by `scripts/fetch_datacommons.py`
   for a fixed list of places; no student or tenant address is ever sent to it at runtime.
8. Nearby construction (Boston building permits) is shown only at block level ("100 block of Main
   St"), with work type, month issued, and rough distance. Never show the exact house number,
   applicant, owner, contractor, comments, or valuation, and never show the matched building's
   own parcel (that is building history and follows rule 2).

## Content rules

- Reports, questions, and checklists cite only these sources (`app/content/sources.py`), by name,
  never by section number: Massachusetts State Sanitary Code; Massachusetts carbon monoxide alarm
  rules; Massachusetts smoke alarm rules; Amherst Fire Department (Rental Property Overcrowding
  guidance); Massachusetts Department of Fire Services college fire safety; NFPA construction site
  fire safety fact sheet; NFPA college campus fire safety tips; and the verified off-campus fire
  safety pages of nearby colleges (`app/content/colleges.py`: UMass Amherst, Boston University,
  Tufts, MIT).
- The app isn't only for UMass students. College guidance comes from the college nearest the
  rental (or the one the student picks), and only for topics that college's page covers.
  Otherwise use the NFPA campus tips or state sources. Never show one college's advice for a
  rental near another. A college may be added only after its official off-campus fire safety
  page has been fetched and read.
- Approved data sources (shown as "Data from", never as rules): Analyze Boston datasets (SAM,
  Property Assessment, RentSmart, building violations, approved building permits), the Town of
  Amherst permit portal (link only, no bulk data), and Data Commons (U.S. Census American Community
  Survey). Boston's OpenContext MCP is not used by the app: it lets an AI query raw datasets live,
  which would bypass the column whitelists in privacy rule 1.
- Only the three state rules may be cited as "Required by". Others are "Recommended by"/"Based on guidance from".
- About page exception: the founder-story background (`app/content/background.py`) may cite news,
  government reports, and research outside the list above. Every number there must have a linked
  source that supports it as worded; reword a fact rather than show an unsourced number.
- Never say or imply a unit is safe, compliant, or up to code.
- Exact strings (from `app/content/copy.py`):
  - Every student report: "This is general information, not legal advice. Contact your local Board of Health to request an inspection."
  - Town dashboard: "Rankings reflect reported problems, not predicted fire risk"
- The app only analyzes rental listings and leases; off-topic input is rejected and the AI must
  never answer unrelated questions.

## Ranking rules

- Rankings come only from reports and official records. Building age, ZIP/neighborhood,
  demographics, Census/Data Commons data, and nearby construction are never ranking inputs
  (environmental justice data is outreach-only).
- Tenant score: severity × recency decay (90-day half-life). Severity: no second way out / no
  working smoke alarm = 5, blocked exit = 4, electrical = 4, heating = 3, other = 1
  (`app/content/report_categories.py`).
- A report can list several problems (checkboxes). It is scored once, at its most serious
  problem (`reports.category`); the others (`reports.extra_categories`) only feed hazard labels
  and filters, so checking every box can't inflate a building's rank.
- Official score: open fire-related violations × 3 + fire-related records in the last 12 months × 1, capped.
- Show score parts separately.

## Accessibility and style

- Semantic HTML, labels on every input, visible focus, ARIA live regions for HTMX updates,
  "opens in a new tab" text for external links. Plain, direct copy; no em dashes or exclamation points in UI text.
