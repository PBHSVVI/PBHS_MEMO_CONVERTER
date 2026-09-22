PBHS Memo Converter — Phase 7.5 item-total recovery v4.1

The live Question 11.1.1 exception already has a pending typed correction "(3)".
That earlier correction was dispatched for reinterpretation but came back unresolved.
A second typed attempt such as "award 3 marks" is therefore rejected because the
backend correctly allows only one pending correction per exception.

This fix keeps that safeguard and instead:
- teaches item_total_mismatch to understand "(3)", "3 marks", "award 3 marks", and "use 3 marks";
- adds a bounded set_item_total_override operation;
- requires the teacher total to equal the already-computed mark-scheme total;
- makes Review v4.1 automatically retry a saved unresolved correction using the current engine;
- shows the teacher item total explicitly before confirmation.

Upload this ZIP to the repository root, preserving folders.

Then run:
Actions -> Apply Phase 7.5 Item Total Fix -> Run workflow

After it succeeds, reopen:
https://pbhsvvi.github.io/PBHS_MEMO_CONVERTER/phase7-5-review/?v=4.1

The existing pending "(3)" correction should be retried automatically and should
show back:
set_item_total_override
Teacher item total: 3 marks

Confirm only if that matches the intended correction.
