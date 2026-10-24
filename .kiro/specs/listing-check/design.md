# Design: Student listing and lease check

## Overview

`POST /check` turns pasted listing text or an uploaded lease PDF into a fire-safety report. Text
is checked for relevance first, then analyzed by Claude with a fixed JSON schema, or by the
keyword rule analyzer when there's no API key or the AI fails. Both analyzers return the same
`SafetyReport`. The route then looks up Boston records for the address and attaches a building
or area card. Nothing the student submits is stored.

## Architecture and data flow

```
GET /check  -> check.html (form; ?sample=1 prefills SAMPLE_LISTING)

POST /check (app/routers/check.py::check_submit)
  LimitRequestSize middleware (app/main.py)      body > 5 MB + 256 KB -> 413
  lease_pdf? -> _read_upload (64 KB chunks, stops past 5 MB)
             -> pdf_text.extract_text (in memory)   PdfError -> error partial/page
             -> prepend pasted text, add "Lease PDF read..." note
  empty?     -> error
  > 20,000 chars -> truncate, add note
  relevance.looks_like_rental_text   fail -> NOT_A_LISTING_MESSAGE (no slot used, no AI call)
  get_check_limiter: ai_client set?  allow(ip) -> use a slot; over limit -> ai_client = None
  analyzer.analyze_listing (thread pool)
     relevance.looks_like_rental_text   fail -> NotARentalDocument (no AI call)
     rules_analyzer.analyze             (always built; used as fallback and gap filler)
     client is None -> rules report
     _call_claude (up to 2 attempts) -> _build_report (validate, backfill)
     is_rental_document false -> NotARentalDocument
     failure -> rules report + FALLBACK_NOTICE
  NotARentalDocument after a used slot -> limiter.refund(ip)
  rate limited -> fallback_reason = RATE_LIMIT_NOTICE
  lookup address = form field or report.extracted_address or find_address_in_text
  boston.context_for_address (read-only DB) -> BuildingContext | None
  _area_context: construction.construction_context, census.census_context (read-only DB)
  _report_context: questions_for_context + construction_questions, cited sources
  HX-Request -> partials/report.html, else report_page.html
```

## Components

| Component | File | Role |
|---|---|---|
| Route | `app/routers/check.py` | Form, upload read, truncation, error rendering, AI rate limit, Boston lookup, construction and census context, template context |
| AI rate limit | `app/routers/check.py::get_check_limiter`, `app/services/rate_limit.py` | `RateLimiter(check_ai_per_hour, 3600)`, rebuilt when the setting changes; `RATE_LIMIT_NOTICE` |
| Request guard, spool setting, log settings | `app/main.py` | `LimitRequestSize`, `MultiPartParser.spool_max_size = MAX_REQUEST_BYTES`, access log off, SDK loggers at WARNING, `RequestValidationError` handler |
| PDF text | `app/services/pdf_text.py` | `extract_text(bytes)` with pypdf over `io.BytesIO`; limits 5 MB, 30 pages, 40 letters |
| Relevance | `app/services/relevance.py` | `looks_like_rental_text`: at least 2 distinct `HOUSING_TERMS`; `NOT_A_LISTING_MESSAGE` |
| AI analyzer | `app/services/analyzer.py` | `SYSTEM_PROMPT`, `OUTPUT_SCHEMA`, `_call_claude`, `_build_report`, `analyze_listing` |
| AI client | `app/services/ai_client.py` | `anthropic.Anthropic(max_retries=1)`, or `None` without a key |
| Settings | `app/config.py` | `anthropic_model`, `ai_timeout_seconds` (30), `check_ai_per_hour` (20) |
| Rule analyzer | `app/services/rules_analyzer.py` | `CONCERN_RULES`, `MENTION_RULES`, `FLAG_TEXT`, `_questions_for`, `MAX_LISTING_CHARS = 20_000` |
| Report models | `app/services/report_models.py` | `SafetyReport`, `ChecklistItem`, `Flag`, `LandlordQuestion` (law-only `required_by` validator), `RELATION_TEXT` |
| Building questions | `app/services/building_questions.py` | Questions from Boston history (records by category, year built, permits, heat type); `construction_questions` for nearby construction |
| Boston context | `app/services/boston.py` | `context_for_address`, `BuildingContext`, `DATA_SOURCES`; DB opened with `mode=ro` |
| Nearby construction, area housing | `app/services/construction.py`, `app/services/census.py` | See `.kiro/specs/nearby-construction-and-census/` |
| Sources | `app/content/sources.py` | The seven `Source` entries, `SOURCE_IDS`, `LEGAL_SOURCE_IDS` |
| Question bank | `app/content/questions.py` | 13 fixed `LandlordQuestion`s used by the rule analyzer |
| Checklist copy | `app/content/checklist.py` | `TOPICS`: label, "why" text, and one source per topic |
| Fixed copy | `app/content/copy.py` | `DISCLAIMER`, exposed as a Jinja global in `app/templating.py` |
| Sample | `app/content/samples.py` | `SAMPLE_LISTING` (fictional, no address) |
| Templates | `app/templates/check.html`, `report_page.html`, `partials/report.html`, `partials/building_card.html`, `partials/construction_card.html`, `partials/census_card.html`, `partials/check_error.html`, `partials/disclaimer.html` | Form, full and partial report, building, construction, and census cards, error, disclaimer |

### Building history attachment

`check_submit` calls `context_for_address(lookup_address, boston_db)`. It returns `None` for a
blank address, `kind="building"` with `BuildingHistory` only when the match `is_rental`,
`kind="area"` with ZIP or ward stats for non-rentals and unmatched Boston ZIPs, and `kind="none"`
outside Boston, when data is unavailable, or when history tables aren't loaded.
`_report_context` passes it as `ctx`, adds `questions_for_context(ctx, report.questions)` as
`building_questions`, and merges their source IDs into `cited_sources`. `partials/report.html`
includes `building_card.html` when `ctx` is set. Building questions are returned only for
`kind="building"`, and the CO question is skipped when the report already cites
`co_alarm_rules`.

### Construction and area housing attachment

`_area_context(lookup_address, boston, boston_db)` returns `construction_context(...)` (with the
Boston snapshot date) and `census_context(...)`. `_report_context` adds
`construction_questions(construction)` to the cited sources alongside building questions, and
passes `construction`, `construction_questions`, and `census` to the template.
`partials/report.html` includes `construction_card.html` and `census_card.html` after the
building card when each is set. Both read only local tables. Details, privacy rules, and tests
are in `.kiro/specs/nearby-construction-and-census/`.

### AI rate limit

`get_check_limiter` holds one process-wide `RateLimiter(settings.check_ai_per_hour, 3600)` and
rebuilds it if the setting changes. `check_submit` rejects off-topic text before touching the
limiter. Only when an AI client exists does it call `limiter.allow(client_ip)`. Over the limit it
sets `ai_client = None`, so `analyze_listing` returns the rules report, and the route sets
`fallback_reason = RATE_LIMIT_NOTICE` (shown with the "Basic analysis" badge). If the AI then
rejects the text as not a rental document, the slot is refunded. The IP is hashed under a
per-process salt inside the limiter and never stored or logged.

## Data models

From `app/services/report_models.py`:

- `Topic`: `smoke_alarms`, `two_ways_out`, `sprinklers`, `heating`, `electrical` (`TOPIC_ORDER`).
- `Status`: `mentioned`, `concern`, `not_mentioned`. There is no "safe" status.
- `ChecklistItem(topic, status, evidence <= 300)`.
- `Flag(topic, severity high|medium|low, message <= 400, evidence <= 300)`.
- `LandlordQuestion(topic, question <= 400, source_id: SourceId, relation)`. `citation` renders
  `RELATION_TEXT[relation] + cite_as`, for example "Required by the Massachusetts State Sanitary
  Code". The validator rejects `required_by` on a non-law source.
- `SafetyReport(analyzer ai|rules, checklist, flags, questions, fallback_reason, extracted_address)`.

`OUTPUT_SCHEMA` (`app/services/analyzer.py`) mirrors these with `additionalProperties: false`,
enums for topic, status, severity, `source_id` (`SOURCE_IDS`), and relation, and
`is_rental_document` as the first required field.

## Error handling

| Case | Behavior |
|---|---|
| Body over 5 MB + 256 KB | 413 "That upload is too large. The limit is 5 MB." (`LimitRequestSize`) |
| Field over hard cap | `TOO_LONG_MESSAGE`, values not echoed; 422 page or 200 partial |
| Bad PDF | `PdfError` message; pasted text kept on the no-JS page |
| Empty input | "Paste the listing or lease text, or upload a lease PDF." |
| Off-topic (keywords) | `NotARentalDocument` before any AI call; listing cleared |
| Off-topic (AI says `is_rental_document: false`) | Same message, no report |

### AI failure fallback (`analyze_listing`)

1. No client: return the rules report with no notice.
2. `_call_claude` raises `AIUnavailable` for an API exception, a `stop_reason` other than
   `end_turn` (refusal, `max_tokens`), invalid JSON, or the wrong shape.
3. Invalid output gets one retry. "API call failed" errors don't retry (the SDK already retries
   once). Any other exception stops immediately.
4. On failure: `log.warning` with the reason only, and the rules report with
   `fallback_reason = FALLBACK_NOTICE`, shown with `role="status"` and the "Basic analysis" badge.
5. On success, `_build_report` drops bad items (see Requirement 5) and backfills checklist
   entries and per-topic questions from the rules report, so a partly bad response still yields a
   full checklist.

## Privacy considerations

- PDFs: read in chunks into memory, parsed from `io.BytesIO`, `data` dropped in `finally`, upload
  closed. `MultiPartParser.spool_max_size` is raised to `MAX_REQUEST_BYTES` so uploads under the
  guard never roll over to a temp file.
- No DB writes in the check flow. The Boston DB is opened read-only.
- Logs: uvicorn access log disabled at import; `anthropic`, `httpx`, `httpx2`, `httpcore` at
  WARNING; `pdf_text` logs only the exception type; `analyzer` logs only the failure reason.
- Listing text goes only to the Claude API (rule 7). Rejected text isn't echoed back. The form
  says the text and file aren't saved.
- The "Report a problem here" link passes only the address to `/report`, not the listing.
- Building cards show only likely rentals and never owner names (steering rules 1 and 2).

## Testing strategy

All tests use `tests/conftest.py` overrides: no `.env`, `get_ai_client` returns `None` unless a
test injects `tests/fakes.py::FakeClient`, and the Boston DB points at a missing file or the
fixture DB. No test calls the real Claude API.

| File | Covers |
|---|---|
| `tests/test_check_routes.py` | Form, sample, HTMX vs full page, escaping, empty and long input, oversized input not echoed, AI wiring, fallback notice |
| `tests/test_pdf_upload.py` | PDF extraction and errors, empty-password PDFs, upload to report, 413, no spooling to disk (`SpooledTemporaryFile.rollover` spy) |
| `tests/test_relevance.py` | Keyword check, no AI call for off-topic text or PDFs, AI rejection, message wording |
| `tests/test_analyzer.py` | Request shape, schema enum, prompt sources, item filtering, backfill, retry and fallback paths, injection |
| `tests/test_rules_analyzer.py` | Five topics, concern and mention rules, never safe, unique sourced questions, truncation |
| `tests/test_sources_and_questions.py` | Exactly seven sources, no section numbers, citation wording, law-only `required_by` |
| `tests/test_boston_history.py` | Rental vs area vs none context, building questions, card rendering, never says safe |
| `tests/test_privacy_hardening.py` | Access log off, SDK loggers capped, chunked and Content-Length limits |
| `tests/test_final_checks.py` | Disclaimer on every report, no em dash or exclamation, sample listing, recipe rejected with no AI call |
| `tests/test_pages.py` | Exact fixed copy (`DISCLAIMER`) |
| `tests/test_check_rate_limit.py` | Fake AI not called past the limit, off-topic text uses no slot, AI rejection refunds, no AI client never counts, setting default and dependency |
| `tests/test_checklist_copy.py` | `smoke_alarms` "why" text sticks to the smoke alarm rules, on the model and on the rendered page |
| `tests/test_construction.py`, `tests/test_census.py` | Construction and area housing cards on the report (see the nearby-construction-and-census spec) |

Run `.venv/bin/pytest -q` and
`.venv/bin/python .kiro/skills/massachusetts-fire-safety-sources/scripts/check_citations.py`.

## Known gaps

None open. These earlier gaps are fixed:

1. `POST /check` had no rate limit, so anyone could drain the API budget. Fixed by
   `get_check_limiter` and `check_ai_per_hour` (Requirement 12).
2. The `smoke_alarms` checklist "why" text claimed a carbon monoxide requirement while linking
   only the smoke alarm rules. It now states only what the smoke alarm rules summary supports;
   CO is covered by the CO question citing the CO alarm rules (criterion 8.8). The label now
   reads "Working smoke alarms, and carbon monoxide alarms where required", and the `heating`
   "why" text no longer claims tenants turn to space heaters (`tests/test_checklist_copy.py`).
3. Criterion 8.1 now lists seven sources, including the NFPA construction fact sheet
   (`nfpa_construction`), used only for the nearby construction question.
4. The nearby construction and area housing (census) cards now attach to the report
   (criteria 10.7 and 10.8; see `.kiro/specs/nearby-construction-and-census/`).

Behind a proxy, the limit only works per client once `FORWARDED_ALLOW_IPS` is set; until then
all visitors share one limit (see `.kiro/specs/platform-and-deploy/`).
