# TwoWaysOut

Fire-safety checks for off-campus rentals. Students paste a listing or lease and get a
fire-safety report with landlord questions. Towns get a ranked list of buildings based on
reported problems.

Rankings reflect reported problems, not predicted fire risk.

## Run locally

Requires Python 3.12. With [uv](https://docs.astral.sh/uv/):

```sh
uv venv --python 3.12 .venv
source .venv/bin/activate
uv pip install -r requirements-dev.txt
cp .env.example .env   # then fill in values (all optional for local review)
uvicorn app.main:app --reload --no-access-log
```

Open http://127.0.0.1:8000.

Privacy notes for running it:

- Access logging is off. The app disables uvicorn's access logger at import, and
  `--no-access-log` keeps it off at the server level too, so client IPs and URLs (which can
  include an address) are never logged.
- Behind a reverse proxy, add `--proxy-headers` (and `--forwarded-allow-ips` for your proxy)
  so rate limiting sees the real client IP. The IP is only hashed in memory, never stored.
- Don't set `ANTHROPIC_LOG` to `debug` in production. SDK debug logs can include listing and
  lease text. The app keeps the `anthropic`, `httpx`, and `httpcore` loggers at WARNING.

## Test

```sh
pytest
```

Tests use a fake Claude client and never call the real API.

## Boston data

```sh
python -m scripts.fetch_boston sam assessment   # ~200 MB into data/raw/ (gitignored)
python -m scripts.preprocess_boston             # builds data/boston.sqlite (~1 min)
python -m scripts.lookup "182 London St 02128"  # try a lookup
```

- Addresses come from Boston's SAM address list; building details from Property Assessment FY2026.
- Owner names and mailing addresses are never read from the raw files.
- "Rental" means likely rented, based on assessment data: 2+ family homes, apartment
  buildings, and mixed residential/commercial buildings, plus single-family homes and condos
  that aren't owner-occupied. Condo units are rolled up to the building.
- Matching checks the exact street and number range, then the street without a suffix. It asks
  for a ZIP instead of guessing when a street exists in several neighborhoods. On 2,000 real
  RentSmart addresses, 99.6% matched and 99.3% landed on the same parcel the city recorded.
  Fuzzy (typo-tolerant) matching was left out; the 2-hour time box wasn't needed.

### Building history (Task 6)

```sh
python -m scripts.fetch_boston rentsmart violations permits   # ~330 MB more
python -m scripts.preprocess_boston                           # adds history tables
```

- Fire-related records come from RentSmart (inspector-cited housing violations and resident
  complaints, about the last 5 years) and ISD Building and Property Violations (with open/closed
  status). Each is tagged as smoke/CO alarms, exits, fire protection, heating, or electrical
  (`app/services/fire_categories.py`). Trash, rodent, utility-billing, and other records that
  aren't about fire safety are dropped.
- Permits for fire alarms, sprinklers, and electrical work are shown as context. A permit means
  work was approved, not finished or inspected.
- Building history is only stored and shown for likely rentals. Other matched addresses, and
  unmatched Boston addresses with a ZIP, get neighborhood counts for the past 12 months instead.
- RentSmart `owner`, violation `contact_*` fields, and permit `applicant` and `comments` are
  never read. Regulation section numbers are removed from displayed descriptions.
- If the address field is empty, the report uses an address found in the listing.

## Off-topic protection

TwoWaysOut only analyzes rental listings and leases. Text without enough housing terms is
rejected before any AI call. Claude also decides whether the text is a rental document and
returns no report if it isn't, and it's told never to answer questions or follow requests in
the text.

## Lease PDF upload

On `/check`, students can upload a lease PDF (up to 5 MB and 30 pages) instead of, or along
with, pasted text. Text is extracted in memory with pypdf; the file is never written to disk or
saved. Scanned (image-only) PDFs get a message asking for pasted text.
`samples/sample_lease.pdf` is a fictional lease for demos.

## AI analysis

Set `ANTHROPIC_API_KEY` in `.env` to turn on Claude analysis. Without it, or if the API call
fails, the app uses the rule-based analyzer and the report says "Basic analysis".

Try it from the command line:

```sh
python -m scripts.try_ai              # sample listing
python -m scripts.try_ai listing.txt  # your own text
```

## Town dashboard
`/town` lists real buildings ranked by tenant reports and Boston's fire-related records, with
tenant, official, and total scores shown separately, plus an inspection status for each building
(open, scheduled, inspected). Simulated demo reports are shown in their own labeled section and
never mix with the real ranking.

The dashboard stays closed (it shows a setup page) until both of these are set in `.env`:
```sh
DASHBOARD_PASSWORD=choose-a-shared-password
SESSION_SECRET=paste-a-random-string-of-at-least-32-characters
```
Generate `SESSION_SECRET` with:
```sh
python -c "import secrets; print(secrets.token_urlsafe(48))"
```
Sign-in sets a signed, HttpOnly, SameSite=Lax session cookie scoped to `/town` that expires
after 8 hours (Secure when served over HTTPS). Five wrong passwords from one IP within 15
minutes block sign-in for that IP until the window passes. Changing `SESSION_SECRET` signs
everyone out. Signing out also revokes the session on the server, so a copied cookie stops
working. Dashboard pages are sent with `Cache-Control: no-store` and `Referrer-Policy: no-referrer`.

Run the dashboard behind TLS. If a reverse proxy terminates TLS, start uvicorn with
`--proxy-headers --forwarded-allow-ips=<your proxy's IP>` so the app sees HTTPS (and the real
client IP), or set `FORCE_SECURE_COOKIES=true` to always mark the session cookie Secure.

## About page

`/about` explains why TwoWaysOut exists, the background facts with links to their sources, what
it does for students and towns, the fire-safety sources, where the data comes from (owner
names are never read), and its limitations.

## Deploy and demo

- Deploy: see [docs/DEPLOY.md](docs/DEPLOY.md).
- Demo: see [DEMO.md](DEMO.md).

## Project layout

```
app/
  main.py          FastAPI app
  config.py        settings from env / .env
  db.py            tenant report database (data/app.sqlite)
  templating.py    shared Jinja2 setup
  content/         fixed copy, the allowed sources, checklist text, landlord question bank,
                   report categories, About page background, sample listing
  routers/         check.py = student report, report.py = tenant reports,
                   town.py = town dashboard, pages.py = landing, about, health
  services/        report schema, rule-based and Claude analyzers, relevance check, PDF text,
                   Boston address matching and building history, fire categories, building
                   questions, tenant report saving, ranking, inspection status, town auth,
                   rate limiting
  templates/       Jinja2 templates and HTMX partials
  static/          CSS and small decorative scripts (embers, smoke)
scripts/           Boston data download and preprocessing (fetch_boston, preprocess_boston,
                   history, build_data.sh), simulated report seeding, and CLI tools
                   (lookup, rank, try_ai)
data/              raw downloads (gitignored), boston.sqlite (city data), app.sqlite (reports)
tests/             pytest suite with fixtures; never calls the real Claude API
```

## Sources

Reports cite only these seven sources, by name (see `app/content/sources.py`):

1. Massachusetts State Sanitary Code
2. Massachusetts carbon monoxide alarm rules
3. Massachusetts smoke alarm rules
4. UMass Off-Campus Student Life
5. Amherst Fire Department (Rental Property Overcrowding guidance)
6. Massachusetts Department of Fire Services college fire safety
7. NFPA construction site fire safety fact sheet (nearby construction only)

Only the three state rules can be cited as "Required by". The others are guidance.

Data comes from Analyze Boston (addresses, property assessment, RentSmart, building violations,
approved building permits) and, optionally, Data Commons (U.S. Census American Community Survey,
fetched at build time). Amherst permits are linked, not downloaded. The About page background
cites news and government reports for its statistics.
