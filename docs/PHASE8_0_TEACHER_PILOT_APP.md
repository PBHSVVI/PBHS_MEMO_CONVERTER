# Phase 8.0 — Teacher Pilot Application Vertical Slice

## Status

**LOCALLY QUALIFIED — hosted teacher-pilot acceptance pending.**

The accepted Phase 7 baseline remains frozen. Phase 8.0 adds a teacher-facing
shell around that conversion and review system. A later teacher-pilot defect
increment makes three bounded corrections described below: real drag-and-drop,
source-defined document totals, and one purpose-specific atomic allocation-pairing
operation. Those changes do not revise the historical Phase 7 acceptance record.

Production project scope is restricted to Supabase project
`njrqiurqljwtuqrvguhj`.

## Purpose

The Phase 8.0 application supports the pilot path:

`SIGN IN → RECENT CONVERSIONS → UPLOAD → CONVERT → REVIEW IF REQUIRED → DOWNLOAD`

The application is intentionally small. It reuses the accepted Phase 7 review page
instead of duplicating that workflow in React.

## Frontend architecture

The source application lives in `web/` and uses React, Vite, Supabase JS and
Vitest. Runtime responsibilities are separated as follows:

- `src/App.jsx` owns authenticated application routing.
- `src/components/SignIn.jsx` handles email/password sign-in.
- `src/components/Dashboard.jsx` lists the signed-in teacher's recent jobs.
- `src/components/UploadMemo.jsx` validates and submits one source memo.
- `src/components/ConversionProgress.jsx` presents durable job progress, review,
  retry and download actions.
- `src/lib/jobContracts.js` contains supported source types and teacher-facing
  status/stage mappings.
- `src/lib/memoService.js` contains Supabase data, Storage and Edge Function calls.
- `src/lib/urls.js` constructs reviewed job and private output paths.

The production build target is `docs/teacher-app/` because the repository's live
GitHub Pages configuration publishes `main:/docs`. Vite uses the base path
`/PBHS_MEMO_CONVERTER/teacher-app/`. Existing `docs/phase7-5-review/` and
`docs/camera-handoff/` assets remain independent.

Only these browser environment variables are used:

- `VITE_SUPABASE_URL`
- `VITE_SUPABASE_PUBLISHABLE_KEY`

The client contains no Supabase secret/service-role key, GitHub token or AI key.

## Reused backend contracts

### Authentication

The app uses Supabase Auth email/password sign-in through
`auth.signInWithPassword`, restores the persisted session with `getSession`, and
tracks changes with `onAuthStateChange`. Sign-out uses `auth.signOut`.

Authentication identifies the caller. Authorization remains in Postgres and Storage
RLS; the frontend does not treat a URL job ID or a browser-side user comparison as
proof of ownership.

### Jobs and ownership

The browser may insert a `queued` row into `public.jobs` only when
`user_id = auth.uid()`. It may select only rows with the same owner. There is no
browser update policy for jobs.

The upload flow generates a UUID, creates a queued job with its source metadata,
uploads the source object, and invokes `dispatch-memo` with only that job UUID.
Worker and Edge Function code control all subsequent state changes.

### Private Storage

The `memo-files` bucket is private. Its live bucket contract allows at most 50 MB
and these source MIME types:

- `application/pdf`
- `application/vnd.openxmlformats-officedocument.wordprocessingml.document`
- `image/png`
- `image/jpeg`

The engine accepts `.pdf`, `.docx`, `.png`, `.jpg` and `.jpeg`, validates the actual
file signature, rejects empty or oversized input, and requires this path:

`{user_id}/{job_id}/source/{safe_filename}`

Authenticated users may insert or update only their own `source` and
`corrections` namespaces. They may select any object in their own first-path
namespace. Worker-generated `internal` and `output` objects therefore remain
readable to the owner but unwritable from the browser.

### Dispatch and hosted compute

`dispatch-memo` requires a valid user JWT. The function reads the requested job
through the caller's RLS scope, claims it with the admin client, and sends only
`job_id` to `process-memo.yml`.

Phase 8.0 closes the existing retry contract gap by allowing the same function to
claim either `queued` or `failed_retryable`. The claim still compares the current
database status, so concurrent or stale retry requests fail closed. A GitHub dispatch
failure restores the status from which the claim was made.

The bounded update was deployed on **2026-09-30** as `dispatch-memo` version 6 in
project `njrqiurqljwtuqrvguhj`, with JWT verification enabled.

### Progress and events

The app polls the selected `jobs` row every six seconds only while it is active.
This uses existing durable state and avoids speculative Realtime configuration.
The dashboard loads at most 20 recent jobs. RLS limits both queries to the current
teacher.

`job_events` remains the detailed audit source but is not exposed as the primary
teacher experience.

## Teacher status mapping

| Durable job state | Teacher-facing state |
| --- | --- |
| `created` | Uploading |
| `queued` | Queued |
| `dispatched` | Starting |
| `processing` | Converting |
| `needs_review` | Needs review |
| `correction_pending` | Needs review |
| `correction_confirmed` | Converting |
| `rendering` | Preparing files |
| `complete` | Ready |
| `failed_retryable` | Needs retry |
| `failed` | Failed |

Durable stages refine active progress into Upload received, Reading memo, Checking
structure and mathematics, Preparing review, Preparing final memo, and Creating
final memo. Internal phase numbers are not primary UI text.

## Upload sequence

1. Validate extension and size locally.
2. Generate a job UUID and safe source filename.
3. Insert the authenticated teacher's `queued` job.
4. Upload the source to the job's private `source` namespace with `upsert: false`.
5. Invoke authenticated `dispatch-memo` with `{ job_id }`.
6. Open the progress screen and poll durable state.

The browser never sends document bytes to GitHub. The worker downloads the source
from private Storage using its server credential.

## Review handoff

For `needs_review` and `correction_pending`, the progress screen links to:

`../phase7-5-review/?job_id={job_id}`

The accepted review page validates the UUID, restores the Supabase session, and
queries the selected job through RLS before displaying source evidence. The URL
selects a job; it does not grant access. Teachers no longer copy and paste UUIDs.

## Download security

Complete jobs expose Word and PDF buttons. The app calls authenticated private
Storage download for:

- `{user_id}/{job_id}/output/memo.docx`
- `{user_id}/{job_id}/output/memo.pdf`

The app creates only a short-lived local browser object URL for the returned blob.
It does not publish the bucket, create a permanent public URL, or use a service-role
credential.

## Failure handling

- Upload and dispatch errors are described in teacher language.
- `failed_retryable` preserves the same job and offers an authenticated retry
  through `dispatch-memo`.
- A failed initial GitHub dispatch is restored to `queued / dispatch_retry`; the
  teacher sees **Needs retry** and may invoke the same bounded retry path.
- `failed` is terminal in the pilot UI and instructs the teacher to retain the
  source and contact pilot support.
- Raw stack traces and server secrets are never shown.
- A bounded error code is available only in optional technical details.

## Teacher-pilot defect hardening - 2026-10-01

The first live teacher pilot exposed three bounded gaps. This increment addresses
them without changing the immutable source or manually editing live database rows.

### Upload drag-and-drop

The upload target now accepts one dropped PDF, DOCX, PNG or JPEG through the same
validation path as the file picker. Drag events prevent browser navigation, show an
active drop state, reject zero or multiple files, and remain disabled while upload
or dispatch is busy. Click-to-choose remains available and accessible.

### Source-defined assessment totals

Runtime validation no longer assumes that every assessment is worth 150 marks.
The last explicit source `TOTAL` is the observed document total; the canonical
computed total remains the sum of question subtotals, and the expected total is the
observed source total. Supported totals are bounded to 1-999. Missing source totals
remain missing and are never fabricated. A subtotal correction may be applied
sequentially; the document-level discrepancy remains active until the subtotal
ledger matches the observed source total.

The historical 150-mark RAW and teacher-language acceptance records remain
unchanged because they describe those specific benchmark memos.

### Atomic grouped allocation pairing

`question_allocation_pairing_ambiguous` now uses the dedicated
`resolve_question_allocation_pairing` operation. The review page displays every
question ID from the composite exception and requires a total and marking scheme
for each one. Teachers may use new lines or semicolons between mark entries and put
`OR` between alternative methods. The complete allocation is shown back before the
existing explicit confirmation step.

The Edge Function validates the exact ordered target set, bounded totals, mark
points, valid mark codes, reconciled totals, and maximum scoring across `OR`
branches. The engine repeats those payload checks and also requires one existing
leaf question per target and one shared source row. Validation completes for every
child before any structure is changed.
Missing, duplicate, reordered, extra, cross-row, or arithmetically inconsistent
input fails as a whole. Generic free text, AI interpretation, and single-item
content replacement cannot clear this grouped exception.

### Teacher-facing semantic conflicts

The semantic cross-check remains fail-closed. A manually entered shorthand code is
evidence rather than an automatic override: for example, an `A` marking point that
the semantic check reads as consistent accuracy still raises
`shorthand_semantic_conflict` for teacher review. High model confidence does not
choose either interpretation.

Review version 4.9 resolves the internal candidate ID to the actual question and
marking-point position. It presents the entered code and the automated interpretation
in teacher language, followed by explicit choices such as `Use CA — Consistent
accuracy` and `Keep A — Accuracy`. Candidate IDs, semantic enums, confidence and
provider routing appear only inside collapsed Technical details. The selected choice
is converted to a bounded `resolve_mark_semantic_conflict` patch, shown back in full,
and applied only after the existing confirmation step. A legacy pending raw-suggestion
attempt must be cancelled in the UI before these explicit choices are opened.

The review page now presents an actionable queue with Previous, Next and Skip for
now controls. Only active, non-dependent exceptions appear; parent subtotal and
document discrepancies continue to wait for their underlying causes. Skipping is
local navigation only and leaves the exception unresolved. Typed, content and
grouped-allocation drafts are retained per job and exception. A submitted pending
correction locks queue navigation until the teacher confirms or explicitly cancels
it, preventing concurrent correction attempts.

Multiple semantic conflicts for one question display both their marking-point
position and their progress within that question. If the automated semantic result
cannot map safely to a code, the page states that limitation and uses the bounded
ordinary FET Mathematics profile. General and non-geometry questions offer M, A,
CA and F. Explicit geometry context additionally offers S for Statement and R for
Reason; SR and S/R are accepted as aliases for one combined Statement + Reason mark in geometry. The source spelling remains available in the mark evidence.
SF and AO remain source-explicit only. S is never presented as substitution or simplification, and R
is never presented as rounding. Technical Mathematics and Mathematical Literacy
codes are outside this phase. The fallback uses the same structured correction,
readable show-back and explicit confirmation path; neither AI nor entered shorthand
selects a code automatically. Internal candidate IDs, enums, confidence and provider
details remain in collapsed Technical details.

This increment does not mutate live job or correction records. Existing pending attempts must be cancelled or rejected through the review UI before a replacement can be submitted.


## Phase 8.0 hosted pilot remediation — v4.9

This increment consolidates the teacher-pilot findings without changing the accepted
Phase 7.5, 7.6 or 7.7 contracts. Phase 8.0 remains pending hosted acceptance.

### Faster correction boundary

A submitted correction is still structurally validated and shown back before the
teacher can confirm it. Confirmation can now stage the correction and return to the
remaining review queue without launching the full memo worker. Each staged correction
keeps its own correction row, exception link and confirmation event. The teacher then
uses **Apply confirmed corrections and recheck memo** once for the staged set, or may
choose **Confirm, apply and recheck** when an immediate boundary is appropriate.

The confirmation function rejects two staged corrections with the same durable target
within the current review pass. No unconfirmed correction enters the overlay. The
existing correction overlay remains the deterministic batch dry-run and fails closed
if the confirmed set becomes inconsistent with the current source structure.

### Review ordering, skip and source focus

Actionable exceptions are sorted by numeric question segments and then by a stable
category rank. Dependency filtering runs first, so a parent subtotal remains waiting
behind its child causes. Skip remains browser-session state only and performs no
server mutation. It records a logical key made from category, affected question,
semantic candidate/mark index, or grouped target set; a recreated exception UUID
therefore stays deferred behind the other actionable items.

Focused evidence first uses the exact `source_block_index` from the current structure.
If provenance is unavailable, it uses a question label anchored at the start of a
cell, with numeric boundaries that distinguish Question 6 from an arbitrary 6 and
Question 3 from Question 3.1 or mark values. Queue navigation resets and rebuilds the
focus for every selected item.

### Question workspace and parent totals

The review page displays a question-level ledger for the selected major question.
Each child row shows its source printed marks when known, converter marks, marking
point count, active discrepancy and a direct review action. Confirmed staged child
changes contribute to an explicitly labelled projected subtotal while retaining
separate correction identities.

A parent total remains dependent while a specific child issue exists. When no child
cause is available, the parent screen shows source total, converter total and
Difference, and offers three bounded choices: use the deterministic child total when
the printed source subtotal is wrong, inspect/correct a child when the source subtotal
is correct, or defer the parent. The system never invents missing marks.

#### v4.9.1 suspicious-child repair hotfix

A parent subtotal can expose a structurally suspicious child even when the worker did
not create a separate child exception. The question workspace now makes a child
actionable when bounded deterministic signals are present, including a zero-mark row
inside a positive parent difference or a sequence such as `3.1`, `3.1.2`, `3.1.3`,
`3.1.4` with no `3.1.1`. Detection only offers inspection; it never renames or assigns
marks automatically. Healthy rows without an active exception remain read-only.

The teacher may correct the selected child's identifier, its complete marking scheme,
or both. The repair is anchored to the active parent subtotal exception, restricted to
one existing child within that major question, shown back before confirmation, and
stored as one auditable `replace_item_content` patch. Rename and mark changes validate
on a trial structure and commit atomically. When staged, the parent review stays open
and the ledger immediately recalculates the projected subtotal and remaining
difference. The normal batch revalidation remains responsible for resolving or
regenerating the parent discrepancy.

#### v4.9.2 complete question workspace hotfix

The active parent subtotal workspace is now authoritative for the whole major
question. Every detected child has an optional `Edit item` action with its current
identifier, safe printed/computed total and marking points prefilled. Warning language
is reserved for suspicious rows, so deterministic detection helps the teacher without
controlling which child may be corrected.

When the source subtotal remains above the projected child ledger, the workspace shows
`Possible missing or misnumbered subquestion` and offers `Add missing subquestion`.
The teacher must provide the child identifier, total and complete marking scheme; the
page never creates a child from arithmetic alone. Confirmation creates one auditable
`insert_missing_child_question` patch. It is restricted to the active parent, rejects
existing or staged identifiers, requires the marking scheme to equal the entered total,
and applies against a trial structure before committing atomically. A staged insertion
appears as its own ledger row and contributes immediately to the projected subtotal.

If malformed numbering prevents exact child focus, the review page derives a bounded
major-question region from known child provenance, the preceding subtotal/header and
the following question boundary. It labels this evidence `Question-level source region
— exact child alignment requires review` and does not include the preceding major
question as if it belonged to the active review.

#### v4.10 confirmed-change recovery and tick preservation

If a confirmed change cannot be applied, the teacher now sees the earlier instruction
in plain language and may edit it, withdraw it, or leave it for later. Editing creates
a new correction with `supersedes_correction_id`; withdrawal creates an auditable
no-op decision. The original confirmed row is never overwritten or deleted. Explicit
supersession works across an identifier amendment such as `6.1.1` to `6.1`, with the
history reason recorded as `teacher_amended_previous_change` or
`teacher_withdrew_previous_change`. No database migration is required because this
metadata lives in the existing structured patch.

The review page now presents one selected correction tool at a time, moves examples
and technical identifiers behind collapsed details, supports Enter in the sign-in
form, and allows the only queue item to be deferred without pretending its dependent
parent is resolved. An authenticated processing reload opens a dedicated status view
with real elapsed time. Recent recheck durations for the same job supply a broad ETA
range when available; otherwise the page says `Estimating…`, and exceeding the range
does not create a failure.

Mark parsing recognises Unicode check variants anywhere on a marking line. A run of
one, two, or three ticks contributes one, two, or three marks even when its semantic
type still needs review; a numeric shorthand on the same line prevents double-counting.
DOCX ingestion and normalization preserve verified Wingdings/Wingdings 2 and Segoe UI
Symbol check glyphs as `✓`, including their font and character code. Unknown `w:sym`
glyphs remain explicit unresolved symbol evidence rather than being guessed or dropped.
Full DBE Euclidean-reason lexicon integration remains a later, separate increment.

For the current pilot, open the v4.10 review URL, choose **Edit previous change** on
the failed `6.1.1` instruction, change only the identifier to `6.1`, review the
show-back, confirm it, then apply the saved changes and check again. The six-mark scheme
is prefilled and the historical `6.1.1` correction remains auditable.

### Semantic reuse and invalidation

Revalidation checks the current job's previous `internal/semantic.json` before looking
at other jobs with the same immutable source hash. The per-candidate cache identity is:
question ID, mark index, count, source shorthand, descriptor, source notation,
source semantic, question context, neighbouring marks, and whether the result was
deterministic. Exact matches reuse the whole semantic artifact. Partial matches reuse
only provider-valid green AI results at confidence 0.90 or higher; changed candidates
alone return to the provider. Older v4.8 records may warm the cache from the durable
mark identity, while new v4.9 records also compare context and neighbour fields.

A teacher-confirmed semantic decision changes the point notation to
`teacher_semantic_confirmed`, is resolved deterministically on later passes, and cannot
be replaced by an older AI cache entry. Source, mark structure, descriptor, context or
neighbour changes invalidate the affected candidate without invalidating unrelated
questions.

### Long-running processing

The review page no longer turns a ten-minute frontend timer into a processing failure.
It polls durable job state with bounded backoff, maps real stages to teacher-facing
phases, and after ten minutes says that processing is continuing and the page may be
closed. Reloading resumes from the live job state. Only durable `failed` or
`failed_retryable` state is presented as a worker failure.

### Ordinary Mathematics shorthand

General/non-geometry review remains bounded to M, A, CA and F. Geometry may add S,
R and one combined Statement + Reason mark. `SR`, `S-R` and `S/R` parse to the stable
`statement_reason` semantic and count as one mark, not separate S and R marks. SF and
AO remain source-explicit. Technical Mathematics and Mathematical Literacy meanings
remain outside scope.

### Pre-live support requirement

**Report a problem remains mandatory before general live use and is intentionally
deferred from this remediation.** It needs a durable support record and notification
path that preserve job, exception, correction, app version and state. Adding that
infrastructure was not necessary to make the current pilot review safe and faster.

## Explicit non-goals

Phase 8.0 does not include BUZA integration, billing, admin analytics, organisation
management, subscriptions, multi-school tenancy, notification systems, retention
management, a new AI provider, broad correction redesign, or a React rewrite of the
accepted review application.

## Local qualification

Automated frontend tests cover:

- signed-out and authenticated routing;
- durable job state and stage mapping;
- source validation;
- create → upload → dispatch sequencing with mocks;
- review URL handoff;
- complete/download state;
- retryable and terminal failures;
- private output path construction;
- reliance on RLS rather than frontend ownership trust;
- allowed browser environment variables and absence of server secrets; and
- the bounded server retry-state contract;
- valid, invalid, multiple-file and busy-state drag-and-drop behavior;
- source-defined totals at 40, 75, 100 and 150 marks without a fabricated fallback;
- sequential subtotal reconciliation against the observed source total; and
- atomic grouped allocation validation, `OR` scoring and composite safety.

The production Vite build is generated in `docs/teacher-app/`. The complete Phase 7
Python suite remains regression protection.

## Hosted and pilot acceptance still pending

Phase 8.0 is not hosted-accepted by this document. Acceptance still requires:

1. verify the Pages build at
   `https://pbhsvvi.github.io/PBHS_MEMO_CONVERTER/teacher-app/`;
2. sign in with a designated pilot teacher account;
3. run one new disposable PDF or DOCX through upload, dispatch and progress;
4. exercise either direct completion or the job-specific review handoff;
5. download and open both private outputs;
6. exercise the deployed version 6 retry path only when a safe natural
   `failed_retryable` or `queued / dispatch_retry` case exists;
7. confirm another authenticated user cannot read the pilot job or its objects; and
8. record the hosted run, final job state and teacher usability findings.

Do not reuse or modify the accepted Phase 7.5 RAW baseline for this pilot.
