# Design: UI design, accessibility, and About page

## Overview

The UI is server-rendered Jinja2 on FastAPI, with HTMX for partial updates and Tailwind (browser
CDN build) for layout utilities. Colors, components, motion, and reduced-motion rules live in one
stylesheet. Two small scripts add decoration (embers) and a loading transition (smoke). Without
JavaScript, every form still posts normally and every page still reads in order.

This spec is retroactive. It records what exists. The About page citation decision (M2) was
resolved by the owner's "About page exception" (`.kiro/specs/task-10-finish/` Requirement 2).
`/health` now returns only `{"status": "ok"}`.

## Visual system

Defined in `app/static/styles.css` `:root`:

- Charcoal surfaces, darkest to lightest: `--charcoal-950` page `#141210`, `--charcoal-900`
  header and footer, `--charcoal-800` cards and panels, `--charcoal-700` inputs and raised panels,
  `--charcoal-600` dividers.
- Warm text: `--text`, `--text-muted`, `--text-subtle`.
- Borders: `--border-soft` (decorative), `--border-field` (inputs; the CSS comment says 3:1
  against surfaces).
- Ember accents: `--ember-1` to `--ember-3` (orange to red), `--ember-deep-*` for the primary
  button so white text sits on a darker gradient, `--ember-link` for links and the focus ring.
  `--ember-gradient` (90deg) and `--ember-gradient-deep` (135deg).
- Status colors for concern, missing, mentioned, AI, and note, plus flag severity borders.

`base.html` sets `<meta name="color-scheme" content="dark">` and `theme-color` `#141210`.

Component classes are unlayered so they beat Tailwind's layered utilities and still apply if the
CDN fails: `.panel`, `.panel-raised`, `.card`, `.btn-primary`, `.btn-secondary`, `.field`,
`.field-file`, `.choice`, `.alert`, `.note-danger`, `.note-disclaimer`, `.badge*`, `.pill*`,
`.flag*`, `.data-table`, `.cta-panel`, `.hero`, `.sr-only`, `.hp`. `.ember-text` uses
`background-clip: text` with a solid `--ember-1` fallback and a `forced-colors: active` override.
The header has a 2px ember gradient line from `.site-header::after`.

Contrast ratios appear in CSS comments (for example `.btn-secondary` and `.badge-sim`). No test
measures them.

## Components

| Component | File | Notes |
| --- | --- | --- |
| Base layout | `app/templates/base.html` | Pinned CDN scripts with SRI, skip link, header with brand and `nav aria-label="Main"`, `main#main tabindex="-1"`, footer with the 911 note. `head_scripts` block for page scripts. |
| Floor plan macro | `app/templates/partials/floorplan.html` | `floorplan(id, animated=true, label="", class="")`. `viewBox="0 0 220 160"`. Two paths with `pathLength="1"` so the dash animation is length-independent. Gradient id is `{{ id }}-ember`. |
| Landing | `app/templates/index.html` | Hero `section aria-labelledby="hero-heading"`, ember canvas, hero icon in `mx-auto w-28 max-w-full md:w-36` (grid column `9rem`), two `.card` links. Loads `embers.js` with `defer`. |
| About | `app/templates/about.html` | Sections: Why it exists, Background (panel), What it does (two nested `section`s with `h3`), Fire-safety sources, Data sources, Limitations, disclaimer include, Get started `nav`. |
| Background facts | `app/content/background.py` | `Citation` and `BackgroundFact` frozen dataclasses. `BACKGROUND` holds six facts, each with at least one linked source and a comment saying what the source supports. Facts that were only partly sourced were reworded: sprinklers now cite 2023 data, the unsourced July 2025 start date became the sourced April 2024 inspection vote, and "about 120 inspections a quarter" was removed. The docstring records the founder's original wording and each change. |
| Disclaimer | `app/templates/partials/disclaimer.html` | `aside role="note"` with `DISCLAIMER` from `app/content/copy.py`. |
| Error pages | `app/templates/error.html`, `partials/check_error.html` | Error text in `p role="alert"`. |
| Page routes | `app/routers/pages.py` | `/` renders `index.html`. `/about` passes `sources` (all seven `SOURCES` values), `data_sources` (`DATA_SOURCES`), and `background` (`BACKGROUND`). `/health` returns only `{"status": "ok"}`. |
| Template globals | `app/templating.py` | `DISCLAIMER` and `RANKING_STATEMENT` available in every template. |
| Embers | `app/static/embers.js` | Canvas particles: 12, 20, or 32 by width; DPR capped at 2; additive blending; 150ms debounced resize. |
| Smoke | `app/static/smoke.js` | Listens for `htmx:beforeRequest`, `htmx:afterSwap`, and `htmx:afterRequest` on the `/check` form only. |

### Floor plan sizing

- Header: `floorplan("fp-brand", animated=false, class="brand-icon")`. `.brand .brand-icon.floorplan`
  sets `height: 2rem; width: auto; aspect-ratio: 220 / 160`. The extra class beats the general
  `.floorplan { width: 100% }` rule. Decorative, since the "TwoWaysOut" text names the link.
- Hero: `floorplan("fp-hero", animated=true, label="Floor plan showing two ways out of a
  bedroom")` inside `w-28` / `md:w-36`.

## Motion and reduced motion

Animations:

- Floor plan (`.floorplan.is-animated`): 7s `ease-in-out` loop. Path 1 draws from 0 to 25%,
  arrow 1 appears at 22 to 28%. Path 2 draws from 35 to 55%, arrow 2 at 52 to 58%. Both fade out
  from 85 to 100%.
- Embers: `requestAnimationFrame` loop, frame time capped at 50ms. Starts only if reduced motion is
  off and the tab is visible. `visibilitychange` and the media query `change` event call `sync()`,
  which stops, starts, or clears.
- Smoke: `.report-stage.is-loading` shows `.smoke` (two blurred radial-gradient layers drifting on
  9s and 12s loops) and blurs `#report`. On swap, `#report.smoke-reveal` runs a 0.7s un-blur. The
  class is removed on `animationend`. Failed requests clear `is-loading` with no reveal.
- Cards lift 2px on hover. Buttons shift 1px on press. `.htmx-indicator` fades in over 0.2s.
  Idle, it is `opacity: 0; visibility: hidden` (visibility switches after the fade), so it
  leaves the accessibility tree. `#analyzing` sits inside `p role="status"` in `check.html`.

`@media (prefers-reduced-motion: reduce)` in `styles.css`:

- Floor plan: `animation: none`, `stroke-dashoffset: 0`, `opacity: 1`, so both exits show lit.
- Embers: `.embers { display: none; }`. `embers.js` also checks `matchMedia` and never starts.
- Smoke: no drift, transition, blur, or reveal. A static haze still marks the loading state.
- Card and button transitions and transforms off.
- Catch-all: `*, *::before, *::after { animation: none !important; transition: none !important;
  scroll-behavior: auto !important; }`.

## Accessibility approach

- Landmarks: `header`, `nav aria-label="Main"`, `main`, `footer`. Sections use `aria-labelledby`
  pointing at their heading. The About page "Get started" links are a second labeled `nav`.
- Skip link: `.skip-link` sits at `top: -3rem` and moves to `0.5rem` on focus. `main` has
  `tabindex="-1"` so focus lands there, and `main:focus-visible` has no outline.
- Focus: global `:focus-visible` is a 3px `--ember-link` outline, 2px offset. `.field` adds an
  ember border on focus. `.table-scroll` has its own focus outline.
- Labels: `check.html` uses `<label for>` plus `aria-describedby` help text on every input.
- New-tab links: every `target="_blank"` link in `about.html`, `partials/report.html`, and
  `report_thanks.html` has `rel="noopener noreferrer"` and an `.sr-only` "(opens in a new tab)".
- Live regions: `#report` on `/check`, `#town-results` on `/town`, and `#building-status` are
  `aria-live="polite"`. Errors use `role="alert"`. Report fallback notes use `role="status"`.
- SVG: labeled (`role="img"` and `aria-label`) or hidden (`aria-hidden="true"`,
  `focusable="false"`).
- Decorative layers (`canvas.embers`, `.smoke`, card arrow text) are `aria-hidden="true"`.
- UI copy avoids em dashes and exclamation points.

Automated tests check structure only. Full WCAG validation needs manual testing with assistive
technology (screen readers, keyboard only, zoom, forced colors) and an expert review. That has not
been done and is listed as an open task.

## Security headers

`SecurityHeaders` in `app/main.py` is pure ASGI middleware added after `LimitRequestSize`, so it
wraps it and 413 responses get headers too. It applies to every HTTP response, including
`/static`:

- All responses: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`.
- Non-town paths: `Referrer-Policy: strict-origin-when-cross-origin` unless a response already set
  one.
- `/town` and `/town/...`: `Referrer-Policy: no-referrer`, `Cache-Control: no-store`,
  `Pragma: no-cache`.

- All responses: `Content-Security-Policy` (`CONTENT_SECURITY_POLICY` in `app/main.py`):
  `default-src 'self'`; `script-src 'self'` plus the two exact jsDelivr file URLs in
  `CDN_SCRIPTS` (`.../@tailwindcss/browser@4.3.3/dist/index.global.js` and
  `.../htmx.org@2.0.11/dist/htmx.min.js`), not the whole CDN host; `style-src 'self'
  'unsafe-inline'`; `img-src 'self' data:`; `connect-src 'self'`; `object-src 'none'`;
  `base-uri 'self'`; `form-action 'self'`; `frame-ancestors 'none'`.

Scripts need no inline exception: templates have no inline `<script>` bodies, event-handler
attributes, `hx-on`, or `javascript:` URLs. `style-src` allows inline styles because the Tailwind
browser build and htmx inject `<style>` at runtime. CDN scripts are also protected by SRI hashes
in `base.html`. FastAPI's `/docs` and `/redoc` are disabled (`docs_url=None, redoc_url=None`).
The policy is checked by tests but hasn't been loaded in a real browser yet (tracked in
`.kiro/specs/platform-and-deploy/tasks.md` task 2.4).

The unused `app/templates/coming_soon.html` was deleted.

## Known gaps

1. No manual accessibility pass with assistive technology has been recorded. This includes
   hearing the new `role="status"` loading announcement with a screen reader.
2. The About page "Data sources" section names only the Analyze Boston datasets. The census card
   and the Amherst permit portal link carry their own "Data from" lines on the report, but the
   About page doesn't list Data Commons or the Amherst portal yet (tracked in
   `.kiro/specs/nearby-construction-and-census/tasks.md`).

Fixed since the first version of this spec:
- The idle indicator uses `visibility: hidden` until `.htmx-request` shows it, and sits in a
  `role="status"` region in `check.html` (`tests/test_ui_hardening.py`).
- CDN script pinning (exact versions, SRI, `crossorigin`) and the reduced-motion rules have
  regression tests.
- A `Content-Security-Policy` header is sent from `app/main.py`, with the exact CDN file URLs in
  `script-src`.
- `coming_soon.html` was deleted.
- `/health` returns only `{"status": "ok"}`.
- `index.html` loads `embers.js` with a relative URL.
- Every background fact in `app/content/background.py` has sources that support its numbers as
  worded. An Olympia Place fact (the November 2025 fire started at a construction site next door)
  was added, and partly sourced facts were reworded.

## Testing strategy

Run `.venv/bin/pytest -q`. Tests use the overrides in `tests/conftest.py` and never call Claude,
read `.env`, or touch the real databases.

- `tests/test_ui_hardening.py`: idle indicator hidden from assistive technology, loading text in
  a status region, CDN scripts pinned with SRI and `crossorigin`, reduced-motion block covers
  every animation, `embers.js` checks `matchMedia`, CSP on every response and its directives, no
  inline scripts or handlers, `coming_soon.html` gone, relative static URLs.
- `tests/test_pages.py`: landing links to `/check` and `/town`, `lang="en"`, skip link, `id="main"`;
  `/health` is status only and reveals no configuration or secrets; exact disclaimer and ranking strings; every background fact
  has an `https://` source linked on `/about`, with enough "(opens in a new tab)" text.
- `tests/test_e2e.py` `_assert_page_accessible` (run on `/`, `/check`, `/check?sample=1`,
  `/report`, `/about`, `/town/login`, and signed-in town pages): `lang="en"`, one `h1`, first
  heading `h1`, no skipped levels, skip link, every visible control labeled, new-tab links have
  sr-only text and `noopener`, buttons have text, every SVG labeled or hidden, every `hx-target` is
  an `aria-live` region, 911 footer note. `test_about_page_content` checks the founder story, all
  sources, data note, ranking statement, disclaimer, Get started links, and no em dashes or exclamation points.
- `tests/test_final_checks.py`: security headers on `/`, `/check`, `/report`, `/about` and on town
  pages; no em dashes or exclamation points in visible text across rendered pages; disclaimer and ranking
  statement placement; About background facts shown verbatim with `target="_blank"`,
  `noopener noreferrer`, and exact "(opens in a new tab)" text per source link.

Visual details (colors, sizes, animation timing) are not covered by automated tests, and the
reduced-motion tests check the CSS and script text, not rendered behavior. They were checked by reading the code for this spec, not in a browser.
