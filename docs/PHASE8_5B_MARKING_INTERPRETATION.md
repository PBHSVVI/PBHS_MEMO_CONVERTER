# Phase 8.5B source-backed marking interpretation

The accepted visual pipeline populated observations and solution segments but
never created `question.mark_points`. The semantic planner correctly iterated
only existing points, so a handwritten memo without typed shorthand produced
no semantic candidates. Page-level PDF blocks also hid item allocations from
the marking-column parser. Neither issue authorises counting approval ticks.

## Source inventory before implementation

The controlled memo contains blue solutions, red ticks and braces, printed item
totals and question subtotals. There is no complete typed or handwritten marking
scheme for most questions. Explicit notes include CA, substitution/conclusion
annotations, an answer qualification and a conditional deduction. Individual
ticks have no universally stated value. These findings were reported before
implementing the bridge; private source images and observations were retained.

## Interpretation boundary

`marking_interpretation.py` runs after visual fusion and before semantic
classification. It extracts each local printed allocation using the parsed
source occurrence boundaries. Existing typed marking points are preserved.
Evidence attaches to its question and source page, including same-numbered
questions on different pages; structural parents retain their children.

Positive explicit marking instructions can be extracted deterministically.
When Luna interprets a question packet, its closed output schema restricts
references to the supplied owned evidence IDs. Accepted criteria require a
quoted positive allocation, readable solution evidence, unique placement and
matching shorthand where present. A tick alone, a printed total, a conditional
deduction or model confidence cannot establish an accepted allocation.

Ambiguous criteria and proposed DBE/GDE criteria remain separately identified,
unconfirmed and outside canonical mark totals. Their semantics are classified
on a separate draft structure and their bands remain amber. Alternative schemes
use their maximum rather than their sum. Duplicate criteria and allocations
exceeding the source total cannot manufacture accepted marks. Source references,
allocation evidence IDs and corresponding solution evidence IDs are retained.

The teacher review displays drafts as unconfirmed. **Prepare editable marking
draft** fills the existing Content editor locally. It does not submit, confirm,
or write a correction. Existing review/show-back/confirmation gates still apply.
Source-backed figures are preserved; preparing marks does not replace a figure
with transcribed labels or generated text.

## Recognition and mathematics

The distinct Phase 8.5B operation retains all original 21 visual runs, source
crops, coordinate provenance and the preceding coordinate-revalidation history.
Only documented inadequate regions are reinterpreted. The paired lower-family
crop reuses existing source pixels and explicitly bounds two visible question
labels; other labels and margin geometry remain rejected. Original observations
remain in the archived generation and recognition revision history. New raw
structured responses and usage are checkpointed privately after each request.

The numeric checker now understands LaTeX spacing in factorial products and
adjacent factorial factors. It retains bounded token, nesting and factorial
limits and performs no unrestricted symbolic evaluation. Genuine contradictions
remain in source working and become red review issues. Unsupported notation is
reported as not checked and requires review for interpreted items. Structural
confidence cannot make an unconfirmed marking interpretation green.

## Authorised lifecycle

Dispatch **Process Memo**, `operation=revalidate_marking`, on main for the
existing authorised pilot. This is a separate operation; the Phase 8.5A one-time
guard is unchanged. Project, source SHA, hosted workflow, review state and zero
teacher corrections are checked. Exact previous artifacts and audit rows are
archived under `internal/revisions/phase85b-<run>-<attempt>` before an optimistic
claim. The original coordinate archive remains untouched. New review exceptions
are published through the normal generation replacement path.

All Luna requests use the existing low/Standard/store-false adapter and shared
private $2 ledger. No models, paid fallbacks, protected jobs or provider routes
are enabled by this change. School-private artifacts remain private; comparison
answers are not inserted into inference prompts or interpretation code.
