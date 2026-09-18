# Phase 5 — Canonical Mathematics + Controlled Interpretation Schema

Phase 5 converts the accepted Phase 3.1 structure layer and Phase 4 semantic layer into the renderer-independent controlled memo model described by **GDE Mathematics Memo Interpretation Schema v1.0**.

## Contract status

The explanatory Google Doc is the controlled baseline. It references a machine-readable companion file named `gde_memo_interpretation_schema_v1.0.json`, but that normative JSON file has not been located in Drive. Phase 5 therefore implements the named fields and deterministic cross-object invariants without inventing a replacement and calling it the original normative JSON Schema.

## New private artifacts

- `internal/canonical.json`
- `internal/validation.json`

The existing private artifacts remain:

- `internal/ingestion.json`
- `internal/normalized.json`
- `internal/structure.json`
- `internal/semantic.json`

## Canonical mathematics

For DOCX input, Office Math (OMML) is converted deterministically into the approved LaTeX interchange subset. The converter supports the structures exercised by the controlled Paper 1 benchmarks, including runs, superscripts/subscripts, fractions, radicals, delimiters, functions, limits, n-ary operators and accents/bars.

Every canonical math block carries:

- `source_text`
- `canonical_latex`
- `presentation_mathml` (optional, currently null)
- `plain_text`
- `display_mode`
- source provenance
- confidence/warnings

Unsupported commands, malformed OMML, empty mathematics and unbalanced canonical LaTeX fail closed.

## Source provenance and figures

DOCX source references preserve a one-based page plus structural anchors:

- top-level unit index
- row index
- cell index
- paragraph index

Embedded media are resolved from DOCX relationships into stable assets with SHA-256 provenance. Figure blocks refer to those stable asset IDs.

## Hierarchy and alternatives

The canonical model separates:

- major questions
- recursive items
- solution alternatives (`PRIMARY`, `OR`, `ALTERNATIVE`, `NOTE_ONLY`)
- content blocks
- marking points

Alternative solution paths compete and are never added together.

A marking-column `OR` that represents a lower-mark partial-credit rule is **not** automatically turned into a second mathematical solution. Phase 5 distinguishes source-side solution alternatives from marking-side conditional credit rules.

## Mark links and CA

Marking points receive stable IDs and semantic types from Phase 4. Marks link to canonical solution blocks. Consistent-accuracy evidence remains explicit, and source wording such as `CA from 11.2.1` becomes a dependency on the corresponding earlier canonical item where possible.

## Deterministic validator

The Phase 5 validator implements the controlled cross-object invariants:

- `ID_UNIQUE`
- `REF_RESOLVES`
- `NUMBER_TREE`
- `LEAF_SOLUTION`
- `ALT_MAX`
- `MARK_DESCRIPTOR`
- `MARK_LINK`
- `ITEM_TOTAL`
- `QUESTION_TOTAL`
- `DOCUMENT_TOTAL`
- `CA_DEPENDENCY`
- `CORRECTION_CONFIRMED`
- `NO_OPEN_RED`
- `NO_PENDING_REVIEW`
- `MATH_PARSE`
- `ASSET_RESOLVES`

A memo can become `render_ready` only when all core validation gates pass and no unresolved Amber/Red exception remains.

## Semantic result cache

Phase 5 reuses a previous semantic result only when all of the following hold:

1. the prior job belongs to the same authenticated user;
2. the source SHA-256 is identical;
3. the prior job reached a reusable semantic/canonical milestone;
4. the exact semantic candidate signature still matches, including candidate ID, question ID, mark index, count, shorthand and descriptor.

A cache hit copies the semantic result into the new job namespace, resets `job_id`, clears provider-run records for the new job and emits `phase4_semantic_cache_hit`. No provider call is made for the reused semantic stage.

## Controlled local regression — Paper 1

### RAW benchmark

- Office Math expressions: 260
- OMML → canonical LaTeX failures: 0
- Phase 3.1 structural exceptions: 7
- Phase 5 canonical status: `blocked`
- canonical computed marks: 134
- deterministic validation: not passed
- Phase 5 validation issues: 9
- source contradictions remain reviewable; no balancing or silent repair is attempted

### GOLD moderated benchmark

- Office Math expressions: 222
- OMML → canonical LaTeX failures: 0
- Phase 3.1 structural exceptions: 0
- Phase 5 canonical status: `render_ready`
- observed / computed / expected total: 150 / 150 / 150
- deterministic validation: passed
- Phase 5 validation issues: 0

## Hosted milestone states

If review is required:

- `status = needs_review`
- `stage = phase5_canonicalized`
- `error_code = PHASE5_REVIEW_REQUIRED`

If the canonical memo is renderer-ready:

- `status = failed_retryable`
- `stage = phase5_render_ready`
- `error_code = PHASE5_RENDERER_NOT_YET_CONNECTED`

The second state is an intentional controlled stop. Phase 5 does not claim that a DOCX/PDF has been produced.
