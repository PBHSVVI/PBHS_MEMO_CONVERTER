# Phase 6 — Deterministic GDE Renderer

Status: implementation candidate ready for hosted acceptance.

## Contract

Phase 6 consumes only a Phase 5 canonical memo whose status is `render_ready` and
whose deterministic validator handoff is ready. AI is never called by the renderer.

The default profile is the frozen `PBHS_GDE_INTERNAL_V1` renderer profile from
GDE Mathematics Memo Rendering Specification v1.0.

## Outputs

A successful hosted render writes private job-scoped artifacts:

- `output/memo.docx`
- `output/memo.pdf`
- `internal/render_validation.json`

The DOCX is generated first. The PDF is exported from that exact DOCX using the
controlled LibreOffice engine.

## Implemented deterministic behaviour

- A4 portrait, 0.55 inch margins, 0.25 inch header/footer distance.
- Cover, notes page and body page sequence.
- Running `MATHEMATICS P1/26` / `P2/26` header and centred page field.
- Frozen four-column PBHS grid, fixed widths and 0.5 pt borders.
- Native editable OMML mathematics generated from validated canonical LaTeX.
- 10 pt native mathematics with 9 pt Times New Roman body text.
- U+2713 CHECK MARK marking annotations.
- Identical marking schemes shared by PRIMARY/OR alternatives render once; OR
  remains visible in the working column.
- Item `(n)`, question `[n]` and final `TOTAL: n` are renderer-owned arithmetic.
- Ordinary memo rows are protected from asymmetric cross-page cell splitting when
  their content fits within a conservative deterministic size threshold. Very
  large future rows remain splittable.
- Final question subtotal is kept with the TOTAL row.
- Source figures are copied from the authenticated source package and scaled
  proportionally.
- Page-count extent is populated by a two-pass pagination cycle and must stabilize.

## Preflight

DOCX preflight checks native math count, page settings, tick identity, replacement
characters and TOTAL presence.

PDF preflight checks openability, nonblank final page, replacement characters,
TOTAL, required memo glyph survival and embedded PDF fonts when `pdffonts` is
available.

A separate renderer qualification script exercises the complete required launch
glyph set plus representative native fractions, radicals, superscripts,
subscripts, Greek, geometry and half-open intervals:

`python engine/scripts/phase6_glyph_qualification.py --out-dir <dir>`

## Phase 5 fidelity corrections included

Renderer qualification exposed a canonical fidelity issue in mixed prose + Office
Math paragraphs: the previous normalizer could lose the original inline ordering.
Phase 6 therefore includes the corrected normalization/canonical assembly that
preserves text/math ordering before renderer handoff. The correction remains
subject to the same Phase 5 deterministic validation gates.

## Hosted terminal states

- Non-render-ready memo: `needs_review / phase5_canonicalized`, no renderer output.
- Render-ready memo with successful preflight: `complete / complete`,
  `engine_version=phase6.0`, no error code.
- Rendering failure: `failed_retryable / rendering_failed` plus a Red
  `rendering_failure` exception. A diagnostic DOCX is retained when available;
  an unqualified PDF is never released.
