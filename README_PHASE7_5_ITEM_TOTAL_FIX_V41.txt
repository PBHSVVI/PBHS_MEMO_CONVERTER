PBHS Memo Converter — Phase 7.5 item-total recovery v4.1

Historical v4.1 patch instructions. Phase 7.5 hosted RAW acceptance completed
successfully on 2026-09-26; see README.md, "Phase 7.5 Accepted Baseline".
The 3-mark decision described below was later superseded by the conditional
2-mark scheme. Do not repeat these historical correction steps for the accepted job.

At the time of this patch, the live Question 11.1.1 exception had a pending typed correction "(3)".
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
