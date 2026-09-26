PBHS Memo Converter — Phase 7.5 Review v4.2

Historical v4.2 patch instructions. Phase 7.5 hosted RAW acceptance completed
successfully on 2026-09-26; see README.md, "Phase 7.5 Accepted Baseline".
The instructions below record the recovery sequence at that time, not a pending
action for the accepted job.

Live issue at the time of this patch:
  2A for 3 correct answers; 1A for 2 correct answers.

This is conditional partial-credit logic, so the item is worth a maximum of
2 marks. The two thresholds must NOT be added as 2 + 1 = 3.

v4.2:
- treats correction_mark_total_invalid as a real review category;
- preserves conditional_accuracy calculation mode through correction overlays;
- makes canonical generation use the maximum threshold and carry lower thresholds
  as partial-credit rules;
- adds Retry interpretation, Edit / resubmit, Cancel correction attempt, and
  Edit / resubmit from show-back;
- unresolved interpretation no longer dead-ends with only an error message.

Upload/extract into the repo root, preserving folders.

Then run:
  GitHub -> Actions -> Apply Phase 7.5 Conditional Scoring Fix -> Run workflow

When green, reopen:
  https://pbhsvvi.github.io/PBHS_MEMO_CONVERTER/phase7-5-review/?v=4.2

The currently saved correction should retry automatically. Expected show-back:
  replace_mark_points
  Expected total: 2

Confirm only if that matches the intended marking rule.

NOTE:
The broader free-form AI teacher-intent interpreter is deliberately NOT bundled
into this emergency fix. This patch gets the live conditional-marking case and
recovery UX correct first. The general interpreter should be added as a separately
tested layer after this acceptance run.
