# Phase 8.5A coordinate contract and saved-evidence revalidation

The OpenAI visual prompt declares crop-relative unit-interval `[left, top, right,
bottom]` bounds, measured from the top-left corner. The original adapter passed
these directly to ownership code expecting crop pixels. Crops with page offsets
therefore classified genuine solution observations as contextual margin content.

`visual_coordinates.py` converts the explicitly identified OpenAI contract to
crop pixels using the original raster width and height. Page mapping then uses
the crop rectangle's dimensions and offsets. Both evidence and mark changes use
this path. Invalid, reversed, non-finite, out-of-range or ambiguous coordinates
fail closed. Missing OpenAI geometry cannot establish ownership. No numerical
magnitude heuristic determines units. Groq and Cloudflare keep their existing
pixel/render-scale convention and the existing cross-question checks remain.

Private coordinate provenance retains the original structured provider response,
its digest, original bounds, raster dimensions and contract version. The result
digest remains the digest of the original provider interpretation. Replaying a
tagged response checks it against the original and never scales it twice.

## Authorised same-job operation

The ordinary Teacher App retry does not accept `needs_review` at canonicalization.
For the owner-authorised Phase 8.5A continuation, dispatch **Process Memo** on
`main` with the existing pilot job ID and `operation=revalidate_coordinates`.
The existing workflow permissions, secrets and per-job concurrency group apply.
This operator action is limited to the approved PBHS project and pilot source;
it does not broaden the public retry endpoint or create a second job.

Before claiming the job, the worker requires its expected review state, zero
teacher corrections, complete 21-region coverage, fifteen Luna responses and
the six approved free-provider checkpoints. It verifies the immutable source,
regenerated crop hashes and privately stored crop bytes. It then saves exact
copies of all eight previous internal artifacts plus job, exception, correction
and event history under an immutable `internal/revisions/phase85a-<run>-<attempt>`
prefix. The claim compares status, stage and `updated_at`; an intervening teacher
correction aborts before processing. Lifecycle events record the workflow run,
actor, archive and coordinate contract.

Legacy Luna checkpoints retain the original observation fields, bounds and
`model_normalized_math`, but not the complete raw Responses API envelope. Replay
explicitly labels reconstruction from these saved observations; it does not
claim to recreate the lost transport envelope or replace the original run digest.
The original checkpoints, including defective derived decisions, remain archived.
Only the Luna observations' derived coordinates and associations are rebuilt.
The six established Groq/Cloudflare runs and observations are preserved.

The normal pipeline then rebuilds structure, semantic interpretation, canonical
validation and the review generation. No visual provider is invoked; semantic
calls, if required, retain the shared included-credit ledger. Existing exception
publication supersedes prior unresolved rows only after a new generation exists.
It never fabricates corrections or reconciles totals to an expected number.
Rendering still requires normal validation eligibility.

## Qualification

`test_phase85a_coordinates.py` exercises nonzero crop origins, raster aspect
ratios, crop/page mapping, actual margin content, cross-anchor rejection, missing
and invalid geometry, mark changes, mixed checkpoints and repeat replay. The
downstream synthetic regression requires evidence fusion, source marking-point
acceptance and mathematical checks; a contradictory working line blocks handoff
even when its marks balance. All fixtures are synthetic and offline.

Coordinate correctness does not establish recognition correctness. Source
comparison and genuine mathematical contradictions remain review requirements;
this repair contains no Amanda-specific answer substitutions. Luna, Standard,
low reasoning, `store=false`, the existing $2 cumulative ledger and all provider
and protected-job boundaries remain unchanged.
