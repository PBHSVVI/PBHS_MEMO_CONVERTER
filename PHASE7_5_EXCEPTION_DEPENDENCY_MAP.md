# PBHS Memo Converter — Phase 7.5 Exception Dependency Map

Checkpoint: 22 September 2026

This patch deliberately corrects only cause-level RAW interpretation defects. Downstream subtotal and document-total mismatches remain deterministic symptoms and are not given generic edit operations.

| RAW finding | Classification | Controlled operation | Expected dependent effect |
|---|---|---|---|
| `unlabeled_mark_bearing_question` — 2.2 | Upstream numbering/segmentation defect | `promote_unlabeled_question` | Q2 computed subtotal rises 22 → 26; Q2 total mismatch disappears |
| `multiple_printed_allocations` — 5.1 | Upstream printed-allocation ambiguity | `set_printed_marks` constrained to one of the source allocations | Item observation becomes unambiguous; no direct Q5 subtotal patch |
| `possible_missing_question` — 5.2 | Upstream segmentation defect; marking-only source row | Phase 7.5 enrichment exposes `unlabeled_mark_bearing_question`; then `promote_unlabeled_question` | Q5 computed subtotal rises to 8; Q5 mismatch disappears |
| `mark_arithmetic_mismatch` / `item_total_mismatch` — 7.4 | Upstream mark-semantic ambiguity | `replace_mark_points` with explicit teacher-confirmed GDE mark scheme | Item becomes 4 marks; Q7 21 → 20; item and Q7 mismatches disappear |
| scored major `8` followed by `8.2` | Upstream numbering boundary defect | Phase 7.5 exposes `scored_major_precedes_subquestions`; teacher confirms `rename_question_identifier` 8 → 8.1 | Q8 receives the missing 3-mark item; its mismatch disappears |
| `major_question_gap` — first visible item 11.1.1 | Upstream missing major-question boundary | `insert_missing_major_question` for the unique scored unlabeled block between Q9 and Q11 | Creates Q10 = 5; Q9 remains its genuine 8 marks; Q10 subtotal binds correctly; major gap disappears |
| `item_total_mismatch` — 11.1.1 | Parser symptom, not teacher correction | Existing conditional-accuracy parser interprets “2A all three correct OR 1A two correct” as max 2 | Q11 reduces by 1 automatically; no correction operation exposed |
| `item_total_mismatch` — 11.2.1 | Upstream missing mark descriptors after numbering repair | `replace_mark_points` with explicit teacher-confirmed 4-mark scheme | Q11 gains 4 legitimate marks without inventing source mathematics |
| `subtotal_sum_unexpected` — document | Upstream observed-subtotal ledger defect: Q3 `[4]` not detected | `set_question_subtotal` only when the resulting observed subtotal ledger equals exactly 150 | Restores Q3 observed subtotal; removes document subtotal-ledger exception |
| `question_total_mismatch` Q2/Q5/Q7/Q8/Q9/Q11 and document total mismatches | Downstream symptoms | **No direct operation** | Recomputed after the cause-level fixes above |

Expected final computed question subtotals: **23, 26, 4, 14, 8, 13, 20, 13, 8, 5, 16 = 150**.

Safety constraints retained:

- no generic “edit anything” patch;
- no direct editing of dependent question/document totals;
- every correction remains show-back + explicit teacher confirmation;
- immutable source identifiers/evidence are preserved where numbering changes;
- Q11.2.1 mark descriptors may be teacher-supplied, but source mathematical working is not silently rewritten;
- rendering remains blocked until canonical invariants and open-review gates pass.
