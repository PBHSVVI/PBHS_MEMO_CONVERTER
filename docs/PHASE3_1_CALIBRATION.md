# Phase 3.1 — Deterministic Structure Calibration

Phase 3.1 calibrates the deterministic parser against the controlled RAW and GOLD
Paper 1 benchmark pair before any AI-assisted semantic interpretation is introduced.

## Key improvements

- Understands both the two-column RAW memo layout and the four-column GDE-style GOLD layout.
- Separates question/working cells from marking cells and printed-allocation cells.
- Supports tick notation (`✓`, `✓✓`) as well as shorthand notation (`1M`, `1A`, `1CA`, etc.).
- Recognises compact shorthand such as `1Mlog`.
- Preserves parent headings such as `2.1` when `2.1.1` appears in the same row without
  treating the parent as a separate mark-bearing leaf.
- Partitions shared marking cells across multiple leaf questions when printed allocations
  make the partition deterministic.
- Treats explicit `OR` marking branches as alternatives rather than cumulative marks.
- Treats partial-credit patterns such as `2A ... correct / 1A ... correct` as a maximum,
  not a cumulative total.
- Rejects formula references such as `Sub into (1)` as printed mark allocations.
- Treats a parent as represented when descendants exist, preventing false "missing 7.2"
  warnings when `7.2.1` and `7.2.2` are present.
- Detects jammed identifiers such as `11.1.3Hence` without broadly matching formula numbers.

## Controlled benchmark results

Expected RAW Paper 1 result:

- review required
- 2 Red exceptions
- 5 Amber exceptions
- subtotal sum 146
- catches malformed `11.12.1`
- catches missing/unlabelled `2.2`
- catches probable missing `5.2`
- catches Question 10 major-number gap
- catches conflicting allocations at `5.1`
- catches mark arithmetic mismatch at `7.4`

Expected GOLD Paper 1 result:

- no exceptions
- subtotal sum 150
- deterministic structure gate passes
- semantic interpretation remains the next milestone

No external AI call is made.
