const QUESTION = /^\d{1,2}(?:\.\d{1,2}){0,2}$/;

export function numberingMembers(patch) {
  if (patch?.operation === "rename_question_family") return patch.numbering_members ?? [];
  return patch?.operation === "rename_question_identifier" ? [patch] : [];
}

export function numberingContext(exception) {
  const source = exception?.suggestions?.[0];
  if (exception?.category !== "question_parent_heading_mismatch" ||
      !QUESTION.test(source?.source_question_id ?? "") ||
      !/^\d{1,2}$/.test(source?.heading_question_id ?? "") ||
      !Number.isInteger(source?.source_page) || !Number.isInteger(source?.source_block_index) ||
      !Number.isInteger(source?.character_offset) || exception.affected_id !== source.source_question_id) return null;
  return { printed: source.source_question_id, heading: String(source.heading_question_id),
    page: source.source_page, block: source.source_block_index, offset: source.character_offset };
}

export function familyNumberingSelection(anchor, exceptions, questions, requested) {
  const root = numberingContext(anchor);
  if (!root || !Array.isArray(requested) || !requested.length || requested.length > 30) return null;
  const expected = exceptions.flatMap(row => {
    const s = numberingContext(row);
    return s && s.heading === root.heading && s.page === root.page && s.block === root.block &&
      s.printed.split(".")[0] === root.printed.split(".")[0] ? [{ row, source: s }] : [];
  });
  if (expected.length !== requested.length || !expected.some(item => item.row.id === anchor.id)) return null;
  const selections = [];
  for (const {row, source} of expected) {
    const mapped = requested.filter(item => item?.exception_id === row.id);
    const target = String(mapped[0]?.target_id ?? "");
    const matches = questions.filter(q => q?.question_id === source.printed && q.source_page === source.page &&
      q.source_block_index === source.block && q.source_character_offset === source.offset &&
      String(q.source_heading_major) === source.heading);
    if (mapped.length !== 1 || matches.length !== 1 || !QUESTION.test(target) ||
        target.split(".")[0] !== source.heading || target.split(".").length !== source.printed.split(".").length ||
        questions.some(q => q?.question_id === target) || selections.some(item => item.target === target)) return null;
    selections.push({ exceptionId: row.id, source, target, question: matches[0] });
  }
  // If the parent is part of this change, its children must stay below it.
  if (selections.some(child => selections.some(parent =>
    child.source.printed.startsWith(parent.source.printed + ".") && !child.target.startsWith(parent.target + ".")))) return null;
  return selections;
}

export function matchingNumberingMember(patch, currentId, targetId, sourceBlock) {
  const matches = numberingMembers(patch).filter(item => item.affected_id === currentId &&
    item.target_id === targetId && item.source_block_index === sourceBlock && item.source_locator);
  return matches.length === 1 ? matches[0] : null;
}

export function numberingConflict(patch, other) {
  const left = numberingMembers(patch), right = numberingMembers(other);
  return left.some(a => right.some(b => a.target_id === b.target_id ||
    (a.affected_id === b.affected_id && (a.source_block_index == null || b.source_block_index == null ||
      a.source_block_index === b.source_block_index))));
}
