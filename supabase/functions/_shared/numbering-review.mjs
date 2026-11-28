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

export function questionMatchesNumberingSource(question, source, target = source.printed) {
  return question && (question.question_id === source.printed || question.question_id === target)
    && (question.source_question_id ?? question.question_id) === source.printed
    && question.source_page === source.page && question.source_block_index === source.block
    && question.source_character_offset === source.offset && String(question.source_heading_major) === source.heading;
}

export function familyNumberingSelection(anchor, exceptions, questions, requested, confirmed = []) {
  const root = numberingContext(anchor);
  const fail = (error, question_id) => ({ error, question_id });
  if (!root || !Array.isArray(requested) || !requested.length || requested.length > 30) {
    return fail("invalid_numbering_family");
  }
  const inFamily = (s) => s && s.heading === root.heading && s.page === root.page && s.block === root.block
    && String(s.printed).split(".")[0] === root.printed.split(".")[0];
  const replaced = new Set(confirmed.map(row => row.proposed_patch?.supersedes_correction_id));
  const saved = confirmed.filter(row => !replaced.has(row.id)).flatMap(row =>
    numberingMembers(row.proposed_patch).flatMap(member => {
      const locator = member.source_locator;
      const source = { printed: member.affected_id, page: locator?.source_page, block: member.source_block_index,
        offset: locator?.source_character_offset, heading: String(locator?.parent_heading ?? "") };
      return inFamily(source) ? [{ source, target: member.target_id, locator }] : [];
    }));
  const sameSource = (a, b) => a.printed === b.printed && a.offset === b.offset;
  const expected = exceptions.flatMap(row => {
    const s = numberingContext(row);
    return inFamily(s) && !saved.some(item => sameSource(item.source, s)) ? [{ row, source: s }] : [];
  }).sort((a, b) => a.source.offset - b.source.offset);
  if (expected.length !== requested.length || !expected.some(item => item.row.id === anchor.id)) {
    return fail("numbering_family_incomplete");
  }
  const selections = [];
  for (const {row, source} of expected) {
    const mapped = requested.filter(item => item?.exception_id === row.id);
    const target = String(mapped[0]?.target_id ?? "");
    if (mapped.length !== 1) return fail("numbering_family_incomplete");
    const matches = questions.filter(q => questionMatchesNumberingSource(q, source));
    if (matches.length !== 1) return fail("numbering_family_source_changed", source.printed);
    selections.push({ exceptionId: row.id, source, target, question: matches[0] });
  }
  for (const item of saved) {
    const matches = questions.filter(q => questionMatchesNumberingSource(q, item.source, item.target));
    if (matches.length !== 1 || (matches[0].source_line_hash && matches[0].source_line_hash !== item.locator.source_line_hash)) {
      return fail("numbering_family_source_changed", item.source.printed);
    }
    item.question = matches[0];
  }
  const family = [...selections, ...saved];
  for (const item of family) {
    const { target, source } = item;
    if (!QUESTION.test(target ?? "") || target.split(".")[0] !== root.heading ||
        target.split(".").length !== source.printed.split(".").length) {
      return fail("numbering_family_invalid_target", source.printed);
    }
    if (family.some(other => other !== item && (other.target === target || sameSource(other.source, source))) ||
        questions.some(q => q !== item.question && q.question_id === target)) {
      return fail("numbering_identifier_conflict", target);
    }
    const printedParent = source.printed.split(".").slice(0, -1).join(".");
    const parent = family.find(other => other.source.printed === printedParent);
    if (parent && !target.startsWith(parent.target + ".")) {
      return fail("numbering_family_invalid_parent", target);
    }
  }
  return { selections };
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
