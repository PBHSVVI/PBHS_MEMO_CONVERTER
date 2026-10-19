export function sourceHasDirectMarkAllocation(question) {
  if (!question || typeof question !== "object") return true;
  const points = Array.isArray(question.mark_points) ? question.mark_points : [];
  const hasPoint = points.some((point) => {
    if (!point || typeof point !== "object") return false;
    const count = Number(point.count);
    return Number.isFinite(count) ? count > 0 : true;
  });
  const printed = question.printed_marks == null ? 0 : Number(question.printed_marks);
  const computed = question.computed_shorthand_marks == null
    ? 0
    : Number(question.computed_shorthand_marks);
  return hasPoint || points.length > 0 || printed > 0 || computed > 0;
}

export function validateSourceRestoration({
  targetId,
  replacementId,
  printedMarks,
  markingText,
  supersedesCorrectionId,
  priorIsEffective,
  question,
}) {
  if (!supersedesCorrectionId) return { ok: false, error: "missing_predecessor" };
  if (!priorIsEffective) return { ok: false, error: "predecessor_not_effective" };
  if (!targetId || replacementId !== targetId) return { ok: false, error: "target_changed" };
  if (String(markingText ?? "").trim()) return { ok: false, error: "marking_scheme_not_blank" };
  if (!(printedMarks == null || printedMarks === "" || Number(printedMarks) === 0)) {
    return { ok: false, error: "total_not_blank_or_zero" };
  }
  if (sourceHasDirectMarkAllocation(question)) {
    return { ok: false, error: "source_has_direct_mark_allocation" };
  }
  return { ok: true, error: null };
}
