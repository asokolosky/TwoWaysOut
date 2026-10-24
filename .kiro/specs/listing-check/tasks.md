# Implementation Plan

- [x] 1. Check form and route
  - [x] 1.1 `GET /check` form with labeled address, listing, and PDF fields; `?sample=1` prefill (`app/routers/check.py`, `app/templates/check.html`, `app/content/samples.py`)
    - _Requirements: 1.1, 1.2_
  - [x] 1.2 HTMX partial vs full page, and error rendering with 200 partial or 422 page (`_error`)
    - _Requirements: 1.3, 1.4, 1.5_
  - [x] 1.3 Truncate to 20,000 characters with a note; hard cap with a friendly, non-echoing error (`app/main.py::validation_error`)
    - _Requirements: 1.6, 1.7_
  - [x] 1.4 Escape listing text in the report (Jinja autoescape)
    - _Requirements: 1.8_

- [x] 2. In-memory lease PDF upload
  - [x] 2.1 `extract_text` with size, header, page, password, parse, and scan checks (`app/services/pdf_text.py`)
    - _Requirements: 2.1, 2.3, 2.4_
  - [x] 2.2 Chunked `_read_upload`, combine with pasted text, add the "not saved" note, keep pasted text on error
    - _Requirements: 2.1, 2.2, 2.7_
  - [x] 2.3 `LimitRequestSize` middleware for Content-Length and chunked bodies, and `spool_max_size` raised so uploads stay in memory (`app/main.py`)
    - _Requirements: 2.5, 2.6_

- [x] 3. Off-topic rejection
  - [x] 3.1 `looks_like_rental_text` keyword check before any AI call (`app/services/relevance.py`, `check_submit`, `analyze_listing`)
    - _Requirements: 3.1, 3.2_
  - [x] 3.2 `is_rental_document` first in the schema; `NotARentalDocument` on `false`; clear the form on rejection
    - _Requirements: 3.3, 3.4_
  - [x] 3.3 Prompt limits the AI to the fire-safety check and wraps the listing in `<listing>` tags
    - _Requirements: 3.5, 4.3_

- [x] 4. Claude structured analysis
  - [x] 4.1 `OUTPUT_SCHEMA` with source and relation enums; `_call_claude` with `output_config` and timeout (`app/services/analyzer.py`)
    - _Requirements: 4.1, 4.2, 8.7_
  - [x] 4.2 Use `extracted_address` for the lookup and mark it "(found in the listing)"
    - _Requirements: 4.4, 10.1_
  - [x] 4.3 "AI analysis" badge and "AI can make mistakes" note (`partials/report.html`)
    - _Requirements: 4.5_

- [x] 5. Validate AI output
  - [x] 5.1 `_clean_evidence` keeps only quotes found in the listing
    - _Requirements: 5.1_
  - [x] 5.2 `_text_ok` drops section numbers and safe claims; `LandlordQuestion` drops bad sources and guidance as "required_by"
    - _Requirements: 5.2, 5.3, 8.4_
  - [x] 5.3 Caps, dedupe, severity sort, and backfill from the rules report (`_build_report`)
    - _Requirements: 5.4, 5.5_

- [x] 6. AI failure fallback
  - [x] 6.1 Rules report with no notice when there's no API key (`app/services/ai_client.py`)
    - _Requirements: 6.1_
  - [x] 6.2 One retry on invalid output, no retry on API errors, `FALLBACK_NOTICE` on failure, reason-only log
    - _Requirements: 6.2, 6.3, 6.4, 11.3_

- [x] 7. Rule analyzer
  - [x] 7.1 Concern and mention rules per topic, evidence sentence, five topics in order (`app/services/rules_analyzer.py`)
    - _Requirements: 7.1, 7.2, 7.3_
  - [x] 7.2 `FLAG_TEXT` flags and question selection from `QUESTION_BANK` (`app/content/questions.py`)
    - _Requirements: 7.4_

- [x] 8. Sources and citations
  - [x] 8.1 The seven sources, including `nfpa_construction`, with `is_law`, names, and URLs (`app/content/sources.py`; `tests/test_sources_and_questions.py::test_exactly_the_seven_allowed_sources`)
    - _Requirements: 8.1, 8.2_
  - [x] 8.2 `RELATION_TEXT` and law-only `required_by` validator (`app/services/report_models.py`)
    - _Requirements: 8.3, 8.4_
  - [x] 8.3 Cited sources list with new-tab text, and per-topic "why" text with a source link (`partials/report.html`, `app/content/checklist.py`)
    - _Requirements: 8.5, 8.6_

- [x] 9. Report wording and disclaimer
  - [x] 9.1 `DISCLAIMER` in `app/content/copy.py`, Jinja global, included on every report via `partials/disclaimer.html`
    - _Requirements: 9.1_
  - [x] 9.2 "It can't tell you a unit is safe" note, no "safe" status, "verify in person" label, no-records card wording
    - _Requirements: 9.2, 9.3_
  - [x] 9.3 No em dashes or exclamation points in report UI text or the sample listing
    - _Requirements: 9.4_
  - [x] 9.4 "Report a problem here" link with the address
    - _Requirements: 9.5_

- [x] 10. Building history card
  - [x] 10.1 Lookup address order and `context_for_address` (rental building, area, or none; read-only DB) (`app/routers/check.py`, `app/services/boston.py`)
    - _Requirements: 10.1, 10.3, 10.4, 10.6_
  - [x] 10.2 `building_card.html` with records, permits, data sources, snapshot, and no owner names
    - _Requirements: 10.2, 10.6_
  - [x] 10.3 `questions_for_context` for rental buildings only, merged into cited sources (`app/services/building_questions.py`)
    - _Requirements: 10.5, 8.5_

- [x] 11. Privacy of listings and uploads
  - [x] 11.1 No disk, DB, or log writes of listing or PDF content in the check flow
    - _Requirements: 11.1, 11.4_
  - [x] 11.2 Access log disabled and SDK loggers capped at WARNING (`app/main.py`)
    - _Requirements: 11.2_
  - [x] 11.3 "Your text isn't saved" and "The file isn't saved" on the form
    - _Requirements: 11.5_

- [x] 12. Tests
  - [x] 12.1 Route, PDF, relevance, analyzer, rules, sources, Boston history, privacy, and final checks under `tests/`, all with fake AI and fixture data
    - _Requirements: 1.1, 2.6, 3.1, 5.2, 6.4, 7.3, 8.3, 9.1, 10.2, 11.2_

- [x] 13. Rate limit AI-backed checks
  - [x] 13.1 `get_check_limiter` dependency on `POST /check`; over the limit the check runs with the rules report and `RATE_LIMIT_NOTICE`; off-topic text never uses a slot; AI rejection refunds (`app/routers/check.py`)
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5_
  - [x] 13.2 `check_ai_per_hour` setting (default 20) and `tests/test_check_rate_limit.py`, including that the fake client isn't called past the limit
    - _Requirements: 12.1, 12.3, 12.4, 12.5_

- [x] 14. Fix the smoke alarm checklist "why" text
  - [x] 14.1 `app/content/checklist.py` `smoke_alarms` label is "Working smoke alarms, and carbon monoxide alarms where required" and its "why" text states only what the smoke alarm rules summary supports; the `heating` "why" text no longer claims tenants turn to space heaters
    - _Requirements: 8.8_
  - [x] 14.2 `tests/test_checklist_copy.py`, citation checker, and `.venv/bin/pytest -q` pass
    - _Requirements: 8.8_

- [x] 15. Attach nearby construction and area housing cards to the report
  - [x] 15.1 `_area_context` and `_report_context` pass `construction`, `construction_questions`, and `census`; `partials/report.html` includes both cards (details in `.kiro/specs/nearby-construction-and-census/tasks.md`)
    - _Requirements: 10.7, 10.8, 8.5_
