PBHS Memo Converter — Phase 7.5 Review UX v4

Replace/add:
  docs/phase7-5-review/index.html

v4 fixes issues found during the live RAW acceptance review:
- dynamic resume from live exceptions instead of a fixed 8-step queue;
- dependent question subtotal mismatches are held back while a more specific item cause is open;
- focused evidence section is shown by default instead of the whole memo;
- yellow markers are explicitly context only;
- red discrepancy arrow/callout points to the actual decision point;
- gap-type numbering issues point between neighbouring anchors;
- reviewer chooses correction method before submission:
    * accept any server-provided suggestion;
    * type correction / mark scheme / LaTeX;
    * take/choose a photo;
    * upload an image/PDF/DOC/DOCX;
- typed/image/file evidence is reinterpreted and shown back before confirmation;
- pause/resume remains server-state based;
- full memo remains available as an optional context toggle.

The current live RAW job is expected to resume on the remaining Question 11.1.1 item-total mismatch, while the dependent Question 11 subtotal mismatch is held back automatically.
