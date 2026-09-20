# Phase 7 — Responsive Review & Correction Foundation

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
