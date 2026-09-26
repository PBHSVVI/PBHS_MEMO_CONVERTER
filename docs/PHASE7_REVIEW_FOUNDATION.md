# Phase 7 — Responsive Review & Correction Foundation

## Parent discrepancy context increment

Review page version: **v4.3**.

The review UX follows this rule: **Show the cause, but always retain the parent
discrepancy context.** When an active child exception is the likely cause of a
`question_total_mismatch`, the child remains the correction target while the page
shows the parent question ID and its source/converter subtotals when those values
are available. The parent context is informational. It becomes a separate review
step only if it remains active after the child correction is confirmed and the
worker revalidates the memo.

The relationship is derived generically from hierarchical question identifiers;
there are no Question 11-specific rules. The focused immutable source evidence
remains beside the active child issue, and this feature adds no AI call.

This is a review UX increment after the formally accepted Phase 7.5 baseline. It
does not change that accepted status or any correction, audit, validation, or
rendering semantics.

## Scope of this slice

This release establishes the two-stage correction lifecycle required by the
controlled Interpretation Schema before confirmed corrections are allowed to
modify canonical/renderable data.

### Live database hardening

- fixes exception/job ownership checking in correction insertion;
- pending correction rows cannot contain a pre-populated proposed patch;
- browser UPDATE access to jobs, exceptions and corrections remains revoked;
- only one active pending correction may exist per exception;
- correction audit indexing is added.

### Authenticated correction endpoints

`submit-correction`
- supports suggestion, typed, photo and upload inputs;
- validates job + exception ownership and state;
- typed/suggestion input produces a safe show-back proposal;
- photo/upload input is stored as evidence and remains awaiting reinterpretation;
- no pending input is allowed to alter renderable data.

`confirm-correction`
- requires a server-produced/displayed proposed patch;
- confirms the correction and resolves the linked exception;
- records an audit event;
- never applies an unconfirmed correction.

`reject-correction`
- rejects a pending proposal;
- reopens the exception;
- returns the job to review.

All three functions require a valid user JWT.

## Responsive review lab

`web/phase7-review-lab.html` creates a fresh RAW conversion, fetches its actual
exceptions and private structure/canonical artifacts, presents evidence and
allowed correction routes, and exercises the show-back/confirm/reject lifecycle.

## Explicit boundary

This slice intentionally does **not** yet apply confirmed correction patches to
normalised/canonical data or resume rendering. That is the next Phase 7 slice.
The controlled invariant remains: confirmation permits application; it does not
mean the browser itself may mutate canonical data.
