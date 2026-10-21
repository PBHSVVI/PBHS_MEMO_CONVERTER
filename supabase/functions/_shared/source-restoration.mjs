export function sourceHasDirectMarkAllocation(immutableSource) {
  if (!immutableSource || typeof immutableSource !== "object") return true;
  if (typeof immutableSource.has_direct_marks === "boolean") return immutableSource.has_direct_marks;
  const points = Array.isArray(immutableSource.mark_points) ? immutableSource.mark_points : [];
  const hasPoint = points.some((point) => {
    if (!point || typeof point !== "object") return false;
    const count = Number(point.count);
    return Number.isFinite(count) ? count > 0 : true;
  });
  const printed = immutableSource.printed_marks == null ? 0 : Number(immutableSource.printed_marks);
  const computed = immutableSource.computed_shorthand_marks == null
    ? 0
    : Number(immutableSource.computed_shorthand_marks);
  return hasPoint || points.length > 0 || printed > 0 || computed > 0;
}

export function correctionPredecessorMatchesSource({
  prior,
  targetId,
  questionSourceIndex,
  matchingOccurrenceCount,
}) {
  if (!prior || prior.confirmation_status !== "confirmed") return false;
  const patch = prior.proposed_patch && typeof prior.proposed_patch === "object"
    ? prior.proposed_patch
    : null;
  if (!patch || patch.operation !== "replace_item_content") return false;
  if (String(patch.target_id ?? patch.affected_id ?? "") !== String(targetId ?? "")) return false;
  if (patch.source_block_index == null) return Number(matchingOccurrenceCount) === 1;
  const priorSourceIndex = Number(patch.source_block_index);
  return Number.isInteger(priorSourceIndex) && priorSourceIndex === Number(questionSourceIndex);
}

export function validateSourceRestoration({
  targetId,
  replacementId,
  printedMarks,
  markingText,
  supersedesCorrectionId,
  priorIsEffective,
  immutableSource,
}) {
  if (!supersedesCorrectionId) return { ok: false, error: "missing_predecessor" };
  if (!priorIsEffective) return { ok: false, error: "predecessor_not_effective" };
  if (!targetId || replacementId !== targetId) return { ok: false, error: "target_changed" };
  if (String(markingText ?? "").trim()) return { ok: false, error: "marking_scheme_not_blank" };
  if (!(printedMarks == null || printedMarks === "" || Number(printedMarks) === 0)) {
    return { ok: false, error: "total_not_blank_or_zero" };
  }
  if (!immutableSource || String(immutableSource.question_id ?? "") !== String(targetId ?? "")) {
    return { ok: false, error: "immutable_source_unavailable" };
  }
  if (sourceHasDirectMarkAllocation(immutableSource)) {
    return { ok: false, error: "source_has_direct_mark_allocation" };
  }
  return { ok: true, error: null };
}
