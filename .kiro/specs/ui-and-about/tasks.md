# Implementation Plan

- [x] 1. Build the shared base layout
  - [x] 1.1 `base.html` with `lang="en"`, viewport, `color-scheme`, title block, and description meta
    - _Requirements: 1.1_
  - [x] 1.2 Header with brand link and `nav aria-label="Main"` to `/check`, `/report`, `/town`, `/about`
    - _Requirements: 1.2_
  - [x] 1.3 Footer with the 911 note and the "does not replace a professional inspection" line
    - _Requirements: 1.3_
  - [x] 1.4 `main#main tabindex="-1"` content area
    - _Requirements: 1.4_

- [x] 2. Define the charcoal and ember theme in `app/static/styles.css`
  - [x] 2.1 CSS custom properties for surfaces, text, borders, ember accents, gradients, and status colors
    - _Requirements: 2.1_
  - [x] 2.2 Unlayered component classes that work without the Tailwind CDN
    - _Requirements: 2.2_
  - [x] 2.3 `.ember-text` gradient with solid and forced-colors fallbacks
    - _Requirements: 2.3, 2.4_
  - [x] 2.4 Ember gradient line under the header
    - _Requirements: 2.5_

- [x] 3. Build the floor plan icon
  - [x] 3.1 `partials/floorplan.html` macro with two exit paths and per-instance gradient ids
    - _Requirements: 3.1, 3.6_
  - [x] 3.2 Labeled (`role="img"`) or decorative (`aria-hidden`) output based on `label`
    - _Requirements: 3.2_
  - [x] 3.3 Header icon, unanimated, 2rem tall
    - _Requirements: 3.3_
  - [x] 3.4 Hero icon, animated and labeled, `w-28` / `md:w-36`
    - _Requirements: 3.4_
  - [x] 3.5 7s draw loop for both paths and arrows
    - _Requirements: 3.5_

- [x] 4. Build the landing page
  - [x] 4.1 `/` route and `index.html` hero with one `h1`
    - _Requirements: 4.1_
  - [x] 4.2 Student and town cards with `aria-hidden` arrow text
    - _Requirements: 4.2, 4.3_
  - [x] 4.3 `embers.js` canvas particles that pause when the tab is hidden
    - _Requirements: 4.4, 4.5_

- [x] 5. Add the smoke-clears loading state on `/check`
  - [x] 5.1 `smoke.js` adds and clears `is-loading`, and plays the reveal on swap
    - _Requirements: 5.1, 5.2, 5.3_
  - [x] 5.2 `hx-indicator="#analyzing"` and `hx-disabled-elt` on the submit button
    - _Requirements: 5.4_
  - [x] 5.3 Normal form POST without JavaScript
    - _Requirements: 5.5_

- [x] 6. Turn motion off for `prefers-reduced-motion`
  - [x] 6.1 Static, fully lit floor plan
    - _Requirements: 6.1_
  - [x] 6.2 Hidden ember canvas, and `embers.js` checks and listens to the media query
    - _Requirements: 6.2, 6.3_
  - [x] 6.3 Static smoke haze with no blur or reveal
    - _Requirements: 6.4_
  - [x] 6.4 No hover motion, plus the global `animation: none` and `transition: none` catch-all
    - _Requirements: 6.5_

- [x] 7. Meet the baseline accessibility rules
  - [x] 7.1 Skip link and visible `:focus-visible` and field focus styles
    - _Requirements: 7.1, 7.2_
  - [x] 7.2 Landmarks, `aria-labelledby` sections, one `h1`, no skipped levels
    - _Requirements: 7.3_
  - [x] 7.3 Labels on every control
    - _Requirements: 7.4_
  - [x] 7.4 New-tab links with `noopener noreferrer` and "(opens in a new tab)" text
    - _Requirements: 7.5_
  - [x] 7.5 `aria-live` on every HTMX target and `role="alert"` on errors
    - _Requirements: 7.6, 7.7_
  - [x] 7.6 `.sr-only` defined in `styles.css`
    - _Requirements: 7.8_
  - [x] 7.7 No em dashes or exclamation points in visible UI text
    - _Requirements: 7.9_

- [x] 8. Build the About page
  - [x] 8.1 `/about` route passing `SOURCES`, `DATA_SOURCES`, and `BACKGROUND`
    - _Requirements: 8.1_
  - [x] 8.2 Founder story naming Olympia Place in Amherst
    - _Requirements: 8.2_
  - [x] 8.3 Background facts in `app/content/background.py` with linked citations; partly sourced facts reworded so every number is sourced (About page exception, `.kiro/specs/task-10-finish/` task 2)
    - _Requirements: 8.3, 8.4_
  - [x] 8.4 Seven fire-safety sources, data sources note, limitations, ranking statement, and disclaimer
    - _Requirements: 8.5, 8.6, 8.7_
  - [x] 8.5 "Get started" navigation
    - _Requirements: 8.8_

- [x] 9. Add the `/health` endpoint
  - [x] 9.1 Return only `{"status": "ok"}`, with no configuration flags or secret values (`tests/test_pages.py::test_health_is_status_only`, `test_health_never_reveals_configuration_or_secrets`)
    - _Requirements: 9.1, 9.2_

- [x] 10. Lock down scripts and headers
  - [x] 10.1 Pin Tailwind and HTMX with SRI and `crossorigin="anonymous"` in `base.html`
    - _Requirements: 10.1_
  - [x] 10.2 `SecurityHeaders` middleware in `app/main.py`
    - _Requirements: 10.2, 10.3, 10.4_

- [x] 11. Cover the existing behavior with tests
  - [x] 11.1 `tests/test_pages.py`: landing, status-only health, exact strings, About source links
    - _Requirements: 1.1, 1.4, 4.2, 7.1, 8.3, 9.1, 9.2_
  - [x] 11.2 `tests/test_e2e.py`: page accessibility checks and About page content
    - _Requirements: 1.3, 3.2, 7.3, 7.4, 7.5, 7.6, 7.9, 8.1, 8.2, 8.5, 8.6, 8.7, 8.8_
  - [x] 11.3 `tests/test_final_checks.py`: security headers, text style, About links open safely
    - _Requirements: 7.5, 7.9, 8.3, 10.2, 10.3, 10.4_

- [x] 12. Fix the idle "Analyzing…" indicator for screen readers
  - [x] 12.1 `.htmx-indicator` uses `visibility: hidden` when idle and `.htmx-request` shows it (`app/static/styles.css`); `#analyzing` sits in a `role="status"` region (`app/templates/check.html`)
    - _Requirements: 5.4, 5.6, 7.6_
  - [x] 12.2 `tests/test_ui_hardening.py`: indicator hidden from assistive technology when idle, loading text in a status region
    - _Requirements: 5.4, 5.6_

- [x] 13. Add regression tests for scripts and motion
  - [x] 13.1 `tests/test_ui_hardening.py::test_cdn_scripts_are_pinned_with_sri`: exact versions, `integrity="sha384-..."`, and `crossorigin="anonymous"`
    - _Requirements: 10.1_
  - [x] 13.2 `tests/test_ui_hardening.py`: reduced-motion block covers every animation, and `embers.js` checks `matchMedia`
    - _Requirements: 6.1, 6.2, 6.4, 6.5_

- [ ] 14. Run a manual accessibility pass with assistive technology
  - Screen reader (VoiceOver), keyboard only, 200% zoom, and forced colors on `/`, `/about`, and `/check`. Record findings. Automated tests can't confirm WCAG conformance.
  - _Requirements: 7.1, 7.2, 7.3, 7.6, 2.4_

- [x]* 15. Optional: add a `Content-Security-Policy` header that allows the pinned jsDelivr scripts and the Tailwind browser build's runtime styles (`CONTENT_SECURITY_POLICY` in `app/main.py`, exact CDN file URLs in `script-src`; `tests/test_ui_hardening.py`). Browser confirmation is tracked in `.kiro/specs/platform-and-deploy/tasks.md` task 2.4.
  - _Requirements: 10.1, 10.5, 10.6_

- [x]* 16. Optional: remove or wire up the unused `app/templates/coming_soon.html` (deleted; `tests/test_ui_hardening.py::test_unused_coming_soon_template_is_gone`)
  - _Requirements: 1.1, 10.7_
