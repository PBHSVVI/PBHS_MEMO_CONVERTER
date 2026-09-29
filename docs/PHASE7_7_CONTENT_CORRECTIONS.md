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

## Qualification boundary

Local regressions cover the structured envelope, strict target and content
validation, atomic mark application, broader-content fail-closed behaviour,
correction show-back, source-reference preservation, and review-page availability.
A disposable hosted job should be used for end-to-end acceptance before this
increment is described as hosted-accepted.
