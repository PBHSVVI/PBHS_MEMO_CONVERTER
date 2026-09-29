# Structured question and memo-content corrections

This increment follows the formally accepted Phase 7.5 RAW baseline. It adds a
bounded way for a teacher to correct the actual question text, memo answer or
working during any active review. It does not alter the accepted baseline job.

## Review experience

Every discrepancy now shows:

- an always-available correction guide with examples for numbering, subtotals,
  additive marks and conditional marks;
- the existing free-form teacher-language input; and
- a structured content editor for the question number, corrected prompt,
  corrected memo answer or working, and an optional marking scheme.

The structured editor is the reliable route when source content itself is wrong.
It does not depend on punctuation or an AI response. The teacher sees the complete
replacement question, working and mark points before confirmation.

Ordinary teacher language remains deterministic-first. Commas, semicolons, `and`
and new lines can separate ordinary mark entries when each entry contains a count,
mark code and description. If a free-form instruction says that both content and
marks are wrong, the interpreter fails closed instead of applying only the marks;
the review page directs the teacher to the structured editor.

## Bounded correction operation

`replace_item_content` is an allowlisted correction operation. Its patch contains:

- one existing `target_id`;
- optional complete replacement `question_text`;
- replacement `solution_lines`;
- optional validated `mark_points`, total and calculation mode; and
- the active exception category and correction provenance.

At least one of question text or solution working is required. Question identifiers,
content sizes, mark codes, counts, descriptions and the optional computed mark total
are validated before the proposal can be confirmed and again during worker replay.
The operation never edits the uploaded source.

The browser submits structured content as the existing `typed` input kind together
with a versioned text envelope for immutable audit evidence. The Edge Function
constructs the closed proposal and moves it directly to `awaiting_confirmation`.
No database migration or new correction input kind is required.

## Replay, history and rendering

After confirmation, the overlay stores a `content_override` on the targeted
question. Canonical construction uses the teacher-confirmed prompt and working while
retaining the original source reference. If a replacement mark scheme is present,
canonical marking uses that scheme rather than the superseded source marking text.
DOCX and PDF rendering continue through the existing canonical and validation gates.

Content corrections use the `item_content` history domain. A newer content
correction supersedes older content for the same question. When it contains a
complete mark scheme, it also supersedes older mark-scheme and item-total decisions;
a later mark-only correction can still compose with the corrected content.

## Hosted acceptance

**ACCEPTED — Structured question and memo-content correction completed hosted
end-to-end validation successfully on 2026-09-29.**

Disposable job `e0055801-f512-4573-8389-2c084eb43fe2` used commit
`6bc1101837f2f0de3edf16a5ba5743cc7c2a4b7b` in
[Process Memo run 36533348435](https://github.com/PBHSVVI/PBHS_MEMO_CONVERTER/actions/runs/36533348435).
All **113 hosted tests passed** and the hosted worker completed.

Teacher correction `fa894ff6-1ed2-4d62-8351-18b394e5551e` replaced the prompt and
two memo-working lines for Question 11.2.1 and supplied an additive four-mark
scheme (`3M` calculation and `1A` answer). The correction was confirmed, effective,
applied under the `item_content` history domain, and recorded with zero application
issues.

The final job state was `complete / complete`, engine `phase7.5`, with zero active
review exceptions, canonical `render_ready`, validation passed, 11 major questions
and computed total 150. Nine confirmed corrections were effective and applied; none
were superseded and the correction audit had zero issues. DOCX and PDF preflights
passed, `phase6_render_complete` recorded total 150, and both output objects exist.

The DOCX is 148,902 bytes with 251/251 native math elements. The PDF is 371,699
bytes across 11 pages, with required glyphs present and fonts embedded. This hosted
acceptance records the content-correction increment; it does not replace or alter
the formally accepted Phase 7.5 RAW baseline.
