# Requirements: UI design, accessibility, and About page

## Introduction

This is a retroactive spec. It describes what TwoWaysOut already does for its shared layout,
visual theme, motion, accessibility, landing page, About page, and the security headers that
apply to those pages. Every criterion below was checked against the code at the paths listed in
`design.md`. All rules in `.kiro/steering/project-rules.md` still apply.

Out of scope: the content of student reports, the town dashboard logic, ranking, and the data
pipeline. Those pages reuse this layout and theme but have their own behavior.

The About page citation question (finding M2) is resolved: the owner approved the "About page
exception" in the steering file, and the background facts were reworded so every number is
sourced (`.kiro/specs/task-10-finish/` Requirement 2). The idle loading indicator, script and
motion regression tests, the content security policy, and the unused `coming_soon.html` cleanup
are also done. The only open item is a manual pass with assistive technology.

## Requirement 1: Shared page layout

**User story:** As a student or town user, I want every page to share the same header, navigation,
and footer, so I can always find the main sections and the emergency note.

### Acceptance criteria

1.1 WHEN any full page renders THE SYSTEM SHALL use `base.html` with `<html lang="en">`, a
viewport meta tag, `color-scheme: dark`, a page title block, and a description meta tag.
1.2 WHEN any full page renders THE SYSTEM SHALL show a header with the TwoWaysOut brand link to
`/` and a `<nav aria-label="Main">` list linking to `/check`, `/report`, `/town`, and `/about`.
1.3 WHEN any full page renders THE SYSTEM SHALL show a footer that includes "In an emergency, call
911." and says the project does not replace a professional inspection.
1.4 WHEN any full page renders THE SYSTEM SHALL place page content in `<main id="main"
tabindex="-1">`.

## Requirement 2: Visual theme

**User story:** As a visitor, I want a warm, consistent look that stays readable, so the app feels
calm and trustworthy while being about fire.

### Acceptance criteria

2.1 THE SYSTEM SHALL define the theme as CSS custom properties in `app/static/styles.css`:
charcoal surfaces, warm text colors, field borders, ember accents, an ember gradient, and status
colors.
2.2 THE SYSTEM SHALL define its component classes (panels, cards, buttons, fields, alerts, badges,
pills, flags, tables) as unlayered CSS, so they override Tailwind utilities and still style the
page if the Tailwind CDN fails to load.
2.3 WHEN large heading text uses `.ember-text` THE SYSTEM SHALL fill it with the ember gradient,
with a solid color fallback.
2.4 WHILE the browser is in forced-colors mode THE SYSTEM SHALL render `.ember-text` in the
current text color with no gradient background.
2.5 THE SYSTEM SHALL draw a thin ember gradient line under the site header.

## Requirement 3: Floor plan icon

**User story:** As a visitor, I want a simple picture of "two ways out", so the name and the core
safety idea are clear at a glance.

### Acceptance criteria

3.1 THE SYSTEM SHALL provide one SVG macro, `floorplan(id, animated, label, class)`, that draws a
bedroom with two exit paths: one through the bedroom door and front door, one through the window.
3.2 WHEN the macro is called with a `label` THE SYSTEM SHALL render the SVG with `role="img"` and
that `aria-label`; WHEN called without one THE SYSTEM SHALL render it with `aria-hidden="true"`
and `focusable="false"`.
3.3 WHEN the header renders THE SYSTEM SHALL show the icon unanimated and decorative, sized to a
height of 2rem next to the wordmark.
3.4 WHEN the landing hero renders THE SYSTEM SHALL show the icon animated, labeled "Floor plan
showing two ways out of a bedroom", in a container of `w-28` that grows to `md:w-36`.
3.5 WHEN `animated` is true THE SYSTEM SHALL draw exit path 1, then exit path 2, each followed by
its arrow, on a 7 second loop.
3.6 THE SYSTEM SHALL give each icon instance a unique gradient id prefix so two icons on one page
don't share ids.

## Requirement 4: Landing page

**User story:** As a first-time visitor, I want to see what the app does and pick my path, student
or town, right away.

### Acceptance criteria

4.1 WHEN a visitor requests `/` THE SYSTEM SHALL render `index.html` with one `h1` hero heading,
a short description, and the hero floor plan icon.
4.2 WHEN a visitor requests `/` THE SYSTEM SHALL show two cards linking to `/check` ("Check a
rental") and `/town` ("For towns"), each with an `h2` and a short description.
4.3 WHEN a card renders THE SYSTEM SHALL mark its arrow call-to-action text `aria-hidden="true"`
so the link name comes from the card heading and description.
4.4 WHEN a visitor requests `/` THE SYSTEM SHALL draw decorative ember particles on a canvas
marked `aria-hidden="true"` behind the hero, with no pointer events.
4.5 WHILE the browser tab is hidden THE SYSTEM SHALL pause the ember animation.

## Requirement 5: Smoke-clears loading state

**User story:** As a student waiting for a report, I want a clear sign that the check is running,
and a calm reveal when it is ready.

### Acceptance criteria

5.1 WHEN the `/check` form sends its HTMX request THE SYSTEM SHALL add `is-loading` to the report
stage, show the smoke layer, and blur the previous report.
5.2 WHEN the report is swapped into `#report` THE SYSTEM SHALL remove `is-loading` and play a
short un-blur reveal on the report.
5.3 IF the request fails, times out, or is aborted THEN THE SYSTEM SHALL remove `is-loading`
without the reveal.
5.4 WHILE an HTMX request is in flight THE SYSTEM SHALL show the "Analyzing… this can take up to
30 seconds." indicator and disable the submit button.
5.5 WHERE JavaScript is not available THE SYSTEM SHALL submit the form as a normal POST, and none
of the smoke behavior runs.
5.6 WHILE no request is in flight THE SYSTEM SHALL hide the indicator with `visibility: hidden`
(not only `opacity: 0`), so assistive technology doesn't read it, and the indicator SHALL sit
inside a `role="status"` element so the start of loading is announced.

## Requirement 6: Reduced motion

**User story:** As a visitor who is sensitive to motion, I want animations off when my system asks
for reduced motion.

### Acceptance criteria

6.1 WHILE `prefers-reduced-motion: reduce` matches THE SYSTEM SHALL show the floor plan with both
exit paths and arrows fully drawn and no animation.
6.2 WHILE `prefers-reduced-motion: reduce` matches THE SYSTEM SHALL hide the ember canvas with
CSS, and `embers.js` SHALL not start drawing.
6.3 WHEN the reduced-motion setting changes while the landing page is open THE SYSTEM SHALL stop
or start the ember animation to match, clearing the canvas when it stops.
6.4 WHILE `prefers-reduced-motion: reduce` matches THE SYSTEM SHALL show a static smoke haze while
loading, with no drift, blur, fade, or reveal animation.
6.5 WHILE `prefers-reduced-motion: reduce` matches THE SYSTEM SHALL turn off card and button hover
motion and SHALL set `animation: none` and `transition: none` on every element and
pseudo-element.

## Requirement 7: Accessibility

**User story:** As a keyboard or screen reader user, I want to reach and understand every part of
the page.

### Acceptance criteria

7.1 WHEN any full page renders THE SYSTEM SHALL provide a "Skip to main content" link to `#main`
that is off-screen until focused.
7.2 WHEN an element receives keyboard focus THE SYSTEM SHALL show a 3px ember outline with a 2px
offset, and form fields SHALL show a 3px outline and an ember border.
7.3 THE SYSTEM SHALL use semantic landmarks and sections labeled by their headings
(`aria-labelledby`), with exactly one `h1` per page and no skipped heading levels.
7.4 THE SYSTEM SHALL give every visible form control a label, by `<label for>`, wrapping label,
`aria-label`, or `aria-labelledby`.
7.5 WHEN a link opens in a new tab THE SYSTEM SHALL use `target="_blank"` with
`rel="noopener noreferrer"` and include the screen-reader text "(opens in a new tab)".
7.6 WHEN an element is an HTMX target THE SYSTEM SHALL make the target an `aria-live` region.
7.7 WHEN an error message is shown THE SYSTEM SHALL render it with `role="alert"`.
7.8 THE SYSTEM SHALL define `.sr-only` in `styles.css` so screen-reader-only text stays hidden
visually without the Tailwind CDN.
7.9 THE SYSTEM SHALL keep visible UI text free of em dashes and exclamation points.

## Requirement 8: About page

**User story:** As a visitor, I want to know why TwoWaysOut exists, what it does, what it relies
on, and what it can't do.

### Acceptance criteria

8.1 WHEN a visitor requests `/about` THE SYSTEM SHALL render `about.html` with sections for why it
exists, background, what it does, fire-safety sources, data sources, and limitations.
8.2 WHEN the "Why it exists" section renders THE SYSTEM SHALL state that the founder's apartment
building, Olympia Place in Amherst, burned down last fall.
8.3 WHEN the Background section renders THE SYSTEM SHALL show each fact from
`app/content/background.py` `BACKGROUND` verbatim, followed by a "Source:" line that links each of
its citations. Under the About page exception these may be news, government reports, or research
outside the fixed report sources.
8.4 THE SYSTEM SHALL show a number in a background fact only when a linked source supports it as
worded. WHERE a number can't be sourced THE SYSTEM SHALL reword the fact rather than show it, and
each fact SHALL have a code comment naming what its sources say. The `background.py` docstring
SHALL record the founder's original wording and what changed. Every fact in `BACKGROUND`,
including the Olympia Place fact (the November 2025 fire started at a construction site next
door), SHALL have sources that support each of its numbers, and partly sourced facts SHALL be
reworded to what the sources support.
8.5 WHEN the fire-safety sources section renders THE SYSTEM SHALL list the seven sources from
`app/content/sources.py` by name and say reports cite only these sources.
8.6 WHEN the data sources section renders THE SYSTEM SHALL name the Boston datasets from
`app/services/boston.py` `DATA_SOURCES` and state that owner names and mailing addresses are never
read.
8.7 WHEN the Limitations section renders THE SYSTEM SHALL say the app is not an inspection and
can't tell a user a unit is safe, and SHALL show the exact ranking statement and the exact
disclaimer from `app/content/copy.py`.
8.8 WHEN the About page renders THE SYSTEM SHALL end with a "Get started" navigation to `/check`,
`/report`, and `/town`.

## Requirement 9: Health endpoint

**User story:** As the deployer, I want a liveness check that reveals nothing about the
configuration.

### Acceptance criteria

9.1 WHEN a client requests `/health` THE SYSTEM SHALL return only the JSON `{"status": "ok"}`.
9.2 THE SYSTEM SHALL NOT return any secret value, and SHALL NOT say whether the AI or the
dashboard is configured, from `/health`.

## Requirement 10: Third-party scripts and security headers

**User story:** As the project owner, I want pages to load only pinned, verified scripts and send
basic security headers.

### Acceptance criteria

10.1 WHEN any full page renders THE SYSTEM SHALL load Tailwind (`@tailwindcss/browser@4.3.3`) and
HTMX (`htmx.org@2.0.11`) from jsDelivr with exact versions, `integrity` SRI hashes, and
`crossorigin="anonymous"`.
10.2 WHEN any response is sent THE SYSTEM SHALL include `X-Content-Type-Options: nosniff` and
`X-Frame-Options: DENY`.
10.3 WHEN a response for a path outside `/town` has no `Referrer-Policy` THE SYSTEM SHALL set
`Referrer-Policy: strict-origin-when-cross-origin`.
10.4 WHEN a response is for `/town` or a path under `/town/` THE SYSTEM SHALL instead set
`Referrer-Policy: no-referrer`, `Cache-Control: no-store`, and `Pragma: no-cache`.
10.5 WHEN any response is sent THE SYSTEM SHALL include the `Content-Security-Policy` from
`app/main.py`, which allows scripts only from this site and the two exact pinned jsDelivr file
URLs (not the whole `https://cdn.jsdelivr.net` host), allows
inline styles (the Tailwind browser build and htmx inject `<style>` at runtime), and blocks
objects, framing, and foreign form targets.
10.6 THE templates SHALL contain no inline scripts, event-handler attributes, `hx-on`,
`javascript:` URLs, or htmx `js:` expressions.
10.7 THE `app/templates/` folder SHALL contain no unused templates (`coming_soon.html` was
removed).
