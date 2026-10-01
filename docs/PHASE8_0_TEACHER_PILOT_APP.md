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

This increment does not mutate live job or correction records. Existing pending attempts must be cancelled or rejected through the review UI before a replacement can be submitted.

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
