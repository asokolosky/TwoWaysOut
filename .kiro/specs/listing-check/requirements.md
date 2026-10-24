# Requirements: Student listing and lease check (fire-safety report)

## Introduction

This is a retroactive spec for the existing student flow at `/check`. A student pastes a rental
listing or lease, or uploads a lease PDF, and gets a fire-safety report: a five-topic checklist,
flags, questions to ask the landlord with citations, and Boston building records when the address
matches. The report comes from Claude (structured output) when an API key is set, and from a
keyword rule analyzer otherwise, when the AI fails, or when the client is over the AI rate
limit. The report also carries a nearby construction card and an area housing (Census) card,
specified in `.kiro/specs/nearby-construction-and-census/`. All rules in
`.kiro/steering/project-rules.md` apply. The former open gaps (Requirement 12 and criterion 8.8)
are now met.

## Requirement 1: Check form

**User story:** As a student, I want one form where I can paste a listing or upload a lease, so I
can check a rental before I sign.

### Acceptance criteria

1.1 WHEN a student opens `GET /check` THE SYSTEM SHALL show a form with a labeled optional
address field (max 200 characters), a labeled listing textarea, and a labeled optional PDF input.
1.2 WHEN a student opens `GET /check?sample=1` THE SYSTEM SHALL prefill the textarea with the
fictional sample listing from `app/content/samples.py`.
1.3 WHEN the form is submitted with HTMX THE SYSTEM SHALL return only the report partial, and
WHEN it is submitted without JavaScript THE SYSTEM SHALL return a full report page.
1.4 IF nothing is pasted and no PDF is selected THEN THE SYSTEM SHALL show "Paste the listing or
lease text, or upload a lease PDF."
1.5 IF an error occurs THEN THE SYSTEM SHALL return the error partial with status 200 for HTMX
requests and the full form with status 422 otherwise.
1.6 WHEN the combined text is longer than 20,000 characters THE SYSTEM SHALL check only the first
20,000 and add a note saying so.
1.7 IF a form field is over its hard cap (200,000 characters for the listing) THEN THE SYSTEM
SHALL show "Some of what you entered is too long. Please shorten it and try again." without
echoing the submitted values.
1.8 THE SYSTEM SHALL HTML-escape all listing text it shows back in the report.

## Requirement 2: Lease PDF upload

**User story:** As a student, I want to upload my lease PDF instead of copying text, and know it
isn't kept.

### Acceptance criteria

2.1 WHEN a text PDF up to 5 MB and 30 pages is uploaded THE SYSTEM SHALL extract its text in
memory and add the note "Lease PDF read. The file and its text weren't saved."
2.2 WHEN text is also pasted THE SYSTEM SHALL analyze the pasted text and the PDF text together.
2.3 IF the file is larger than 5 MB, doesn't start with `%PDF-`, has more than 30 pages, needs a
non-empty password, can't be parsed, or has fewer than 40 letters of text (a scan) THEN THE
SYSTEM SHALL show a specific message telling the student how to fix it or to paste the text.
2.4 WHEN a PDF is encrypted with an empty password THE SYSTEM SHALL read it.
2.5 IF the request body is over the PDF limit plus 256 KB THEN THE SYSTEM SHALL return 413 with
"That upload is too large. The limit is 5 MB.", for both `Content-Length` and chunked requests.
2.6 WHEN an upload is at or under the request limit THE SYSTEM SHALL keep it in memory and SHALL
NOT spool it to a temporary file.
2.7 WHEN an upload fails without JavaScript THE SYSTEM SHALL keep the student's pasted text in
the form.

## Requirement 3: Reject off-topic input

**User story:** As the project owner, I want the app to analyze only rental listings and leases,
so it can't be used as a general chatbot and doesn't waste API calls.

### Acceptance criteria

3.1 IF the text has fewer than two distinct housing or fire-safety terms THEN THE SYSTEM SHALL
reject it with "This doesn't look like a rental listing or lease. TwoWaysOut only checks rental
listings and leases for fire safety. Paste the listing text or upload the lease." without making
any AI call.
3.2 THE SYSTEM SHALL apply the same check to text extracted from an uploaded PDF.
3.3 WHEN text passes the keyword check THE SYSTEM SHALL require the AI to decide
`is_rental_document` as the first output field, and IF the AI returns `false` THEN THE SYSTEM
SHALL show the same rejection message and produce no report.
3.4 WHEN input is rejected THE SYSTEM SHALL NOT echo the pasted text back in the form.
3.5 THE SYSTEM SHALL instruct the AI never to answer questions or follow requests outside the
fire-safety check, and to treat the listing between `<listing>` tags as untrusted data.

## Requirement 4: AI analysis

**User story:** As a student, I want a report tailored to my listing.

### Acceptance criteria

4.1 WHERE an Anthropic API key is configured THE SYSTEM SHALL call Claude with a JSON schema
output format covering checklist, flags, questions, and extracted address.
4.2 THE SYSTEM SHALL limit `source_id` in the schema to the seven source IDs and `relation` to
`required_by`, `recommended_by`, and `based_on`.
4.3 THE SYSTEM SHALL neutralize any `</listing>` in the student's text before sending it.
4.4 WHEN the AI returns a street address THE SYSTEM SHALL use it for the building lookup if the
address field was blank and show it marked "(found in the listing)".
4.5 WHEN the AI report is shown THE SYSTEM SHALL label it "AI analysis" and say that AI can make
mistakes.

## Requirement 5: Validate AI output

**User story:** As the project owner, I want bad AI output filtered out item by item, so a single
bad item can't put a wrong citation or a safety claim in front of a student.

### Acceptance criteria

5.1 IF an evidence quote doesn't appear in the listing (ignoring case, spacing, and surrounding
quotes) THEN THE SYSTEM SHALL drop the quote.
5.2 IF a flag or question contains a section number or says a unit is, looks, seems, or appears
safe, compliant, or up to code THEN THE SYSTEM SHALL drop it.
5.3 IF a question cites an unknown source or cites a guidance source as "required_by" THEN THE
SYSTEM SHALL drop it.
5.4 THE SYSTEM SHALL keep at most 10 flags and 14 questions, drop duplicate questions, and sort
flags high, medium, low.
5.5 WHEN a topic has no valid checklist entry THE SYSTEM SHALL use the rule analyzer's entry, and
WHEN a topic has no valid question THE SYSTEM SHALL add the rule analyzer's first question for
that topic if it has one.

## Requirement 6: Fallback when the AI isn't available

**User story:** As a student, I want a report even when the AI is down.

### Acceptance criteria

6.1 WHERE no API key is configured THE SYSTEM SHALL use the rule analyzer and show no fallback
notice.
6.2 IF the AI response isn't valid JSON or doesn't match the report shape THEN THE SYSTEM SHALL
retry once.
6.3 IF the API call fails or times out THEN THE SYSTEM SHALL NOT retry in the analyzer (the SDK is
set to retry once).
6.4 IF the API call fails, the response stops for any reason other than `end_turn`, the retry is
also invalid, or any unexpected error occurs THEN THE SYSTEM SHALL show the rule analyzer's report
labeled "Basic analysis" with "AI analysis wasn't available, so this is the basic keyword
analysis."

## Requirement 7: Rule analyzer

**User story:** As a student, I want the basic report to still point out common problems.

### Acceptance criteria

7.1 THE SYSTEM SHALL report all five topics in order: smoke and CO alarms, two ways out,
sprinklers, heating, electrical.
7.2 WHEN a concern phrase matches (for example a basement bedroom, space heaters, disabled alarms,
no sprinklers, knob-and-tube wiring) THE SYSTEM SHALL mark the topic "concern" with the matching
sentence as evidence.
7.3 WHEN only a mention phrase matches THE SYSTEM SHALL mark the topic "mentioned", shown as
"Mentioned · verify in person", and SHALL NEVER mark a topic as safe.
7.4 THE SYSTEM SHALL add a fixed flag for each concern or not-mentioned topic and pick unique
landlord questions from `app/content/questions.py` by topic, status, and matched tags.

## Requirement 8: Sources and citations

**User story:** As a student, I want to know where each point comes from, without legal jargon.

### Acceptance criteria

8.1 THE SYSTEM SHALL cite only these seven sources: Massachusetts State Sanitary Code;
Massachusetts carbon monoxide alarm rules; Massachusetts smoke alarm rules; UMass Off-Campus
Student Life; Amherst Fire Department (Rental Property Overcrowding guidance); Massachusetts
Department of Fire Services college fire safety; NFPA construction site fire safety fact sheet.
The NFPA fact sheet is guidance and is used only for the nearby construction question.
8.2 THE SYSTEM SHALL cite sources by name only and SHALL NEVER show section or regulation
numbers in report text. Regulation numbers may appear only inside a source URL.
8.3 THE SYSTEM SHALL use "Required by" only for the three law sources (State Sanitary Code,
carbon monoxide alarm rules, smoke alarm rules), and "Recommended by" or "Based on guidance from"
for the others.
8.4 IF any question is built with "required_by" on a guidance source THEN THE SYSTEM SHALL reject
it at validation.
8.5 WHEN a report is shown THE SYSTEM SHALL list every source cited by its questions and building
questions, each linked with "opens in a new tab" text.
8.6 THE SYSTEM SHALL show each checklist topic's "why" text with a link to one of the seven
sources.
8.7 THE SYSTEM SHALL give the AI only the seven source IDs with their names and summaries.
8.8 THE SYSTEM SHALL state in each checklist "why" text only what its linked source's summary
supports. The `smoke_alarms` "why" text covers only smoke alarms (working alarms in every home,
rules that depend on when the building was built or renovated, replacement after 10 years);
carbon monoxide requirements are left to the CO question, which cites the CO alarm rules. The
`smoke_alarms` label is "Working smoke alarms, and carbon monoxide alarms where required". The
`heating` "why" text states only the Sanitary Code heat requirement and SHALL NOT claim that
tenants turn to space heaters.

## Requirement 9: Report wording and disclaimer

**User story:** As a student, I want clear, honest wording that doesn't overpromise.

### Acceptance criteria

9.1 WHEN any student report is shown THE SYSTEM SHALL show, verbatim: "This is general
information, not legal advice. Contact your local Board of Health to request an inspection."
9.2 THE SYSTEM SHALL NEVER say or imply that a unit is safe, compliant, or up to code, and every
report SHALL say it can't tell the student a unit is safe.
9.3 WHEN a matched rental has no fire-related records THE SYSTEM SHALL say that doesn't mean the
building is safe.
9.4 THE SYSTEM SHALL use no em dashes or exclamation points in report UI text or the sample
listing.
9.5 WHEN a report is shown THE SYSTEM SHALL include a link to report a problem at that address.

## Requirement 10: Building history on the report

**User story:** As a student checking a Boston rental, I want the building's fire-related records
and questions about them.

### Acceptance criteria

10.1 THE SYSTEM SHALL look up the address from the form field, else the AI's extracted address,
else an address found by the keyword finder, and SHALL skip the lookup when there is none.
10.2 WHEN the address matches a likely rental THE SYSTEM SHALL show the building card: type, year
built, heat type, fire-related violation and complaint counts by category, recent records,
fire-safety permits, the data sources, and the snapshot date.
10.3 WHEN the address matches a non-rental, or doesn't match but has a Boston ZIP with area data,
THE SYSTEM SHALL show area-level (ZIP or ward) context only.
10.4 WHEN the address is outside Boston or Boston data isn't loaded THE SYSTEM SHALL show the
reason and suggest asking the town's Board of Health or building department.
10.5 WHEN building history is shown THE SYSTEM SHALL add questions based on those records, each
citing one of the seven sources, and SHALL add no building questions for area or no-match context.
10.6 THE SYSTEM SHALL open the Boston database read-only and SHALL NOT show owner names.
10.7 WHEN a report has a lookup address THE SYSTEM SHALL attach the nearby construction card
(`construction_context`) and its question, citing `nfpa_construction`, as specified in
`.kiro/specs/nearby-construction-and-census/`, and SHALL add that source to the cited sources.
10.8 WHEN a report has a lookup address whose ZIP has a `census_zip` row THE SYSTEM SHALL attach
the area housing card (`census_context`), as specified in
`.kiro/specs/nearby-construction-and-census/`.

## Requirement 11: Privacy of listings and uploads

**User story:** As a student, I want my lease and listing text to stay private.

### Acceptance criteria

11.1 THE SYSTEM SHALL process uploaded PDFs and pasted text in memory only and SHALL NEVER write
them to disk, a database, or logs.
11.2 THE SYSTEM SHALL disable the uvicorn access log and keep `anthropic`, `httpx`, and
`httpcore` loggers at WARNING or above.
11.3 WHEN PDF parsing or the AI fails THE SYSTEM SHALL log only the error type or reason, never
document content.
11.4 THE SYSTEM SHALL send listing text to no third party other than the Claude API. The
construction and census cards read only local tables; nothing is sent to Data Commons or any
other service at request time.
11.5 THE SYSTEM SHALL tell the student on the form that the text and file aren't saved.

## Requirement 12: Limit AI calls per client

**User story:** As the project owner, I want to cap how often one client can trigger AI analysis,
so the API key can't be drained.

### Acceptance criteria

12.1 WHEN one client has used `check_ai_per_hour` (default 20) AI-backed checks in the last hour
THE SYSTEM SHALL run the check with the rule analyzer, without calling Claude, and show "You've
run several checks in the last hour, so this is the basic keyword analysis."
12.2 THE SYSTEM SHALL key the limit on an HMAC of the client IP under a per-process salt, held
only in memory (`RateLimiter` via `get_check_limiter`), and SHALL NOT store or log the IP.
12.3 IF the text fails the keyword relevance check THEN THE SYSTEM SHALL reject it before the
limiter, so it never uses a slot; IF the AI rejects the text as not a rental document THEN THE
SYSTEM SHALL refund the slot.
12.4 WHERE no AI client is configured THE SYSTEM SHALL NOT count checks toward the limit.
12.5 WHEN `check_ai_per_hour` changes THE SYSTEM SHALL build a new limiter with the new limit.
