const QUESTION_LINE_RE = /^\s*(\d{1,2}(?:\.\d{1,2}){0,2})\.?(?=\s|$|\t)/;
const QUESTION_HEADING_RE = /^\s*QUESTION\s+(\d{1,2})\b/i;
const JAMMED_QUESTION_RE = /^\s*(\d{1,2}\.\d{1,2}\.\d{1,2})(?=[A-Za-z])/;
const PAGE_LABEL_RE = /\bPage\s+(\d{1,3})\s+of\s+\d{1,3}\b/gi;
const PAREN_NUMBER_RE = /\((\d{1,2})\)/g;
const MARK_CODE_RE = /^(?:S\s*[\/-]?\s*R|CA|SF|AO|M|A|F|S|R)\b/i;
const MARK_DESCRIPTOR_RE = /^(?:isol|square|squar|fac|fact|rej|interval|bracket|shape|point|conclusion|simpl|formula|deriv|answer|ans|sub|equation|eqns|method|standard|value|geometric|arithmetic|condition|correct|common|ratio|sum|algebra|manip|swop|first|second|use|given|statement|reason|m=|c=)/i;

export function flattenImmutableSource(normalized) {
  const content = normalized?.content ?? {};
  if (!Array.isArray(content.units)) {
    return (content.pages ?? []).map((page) => ({
      source: String(page?.effective_text ?? ""), marking: "", allocation: "",
      cells: [String(page?.effective_text ?? "")], page: page?.page ?? null,
    }));
  }
  const blocks = [];
  for (const [unitIndex, unit] of content.units.entries()) {
    if (unit?.type === "paragraph") {
      const text = String(unit.text ?? "");
      if (text.trim()) blocks.push({ source: text, marking: "", allocation: "", cells: [text], unit_index: unitIndex });
      continue;
    }
    if (unit?.type !== "table") continue;
    for (const [rowIndex, row] of (unit.rows ?? []).entries()) {
      const cells = (row ?? []).map((cell) => String(cell?.text ?? ""));
      if (!cells.some((cell) => cell.trim())) continue;
      let source = "", marking = "", allocation = "";
      if (cells.length === 1) source = cells[0];
      else if (cells.length === 2) [source, marking, allocation] = [cells[0], cells[1], cells[1]];
      else if (cells.length === 3) [source, marking, allocation] = [cells.slice(0, 2).join("\n"), cells[2], cells[2]];
      else [source, marking, allocation] = [cells.slice(0, -2).join("\n"), cells.at(-2), cells.at(-1)];
      blocks.push({ source, marking, allocation, cells, unit_index: unitIndex, row_index: rowIndex });
    }
  }
  return blocks;
}

function lineRecords(text) {
  const records = [];
  let offset = 0;
  for (const line of String(text ?? "").split("\n")) {
    records.push({ line, offset });
    offset += line.length + 1;
  }
  return records;
}

export function immutableQuestionOccurrences(text) {
  const source = String(text ?? "");
  const records = lineRecords(source);
  const firstHeading = records.find((item) => QUESTION_HEADING_RE.test(item.line))?.offset ?? null;
  const instructionStart = records.find((item) => /^\s*INSTRUCTIONS?\s*:/i.test(item.line))?.offset ?? null;
  const found = [];
  for (const item of records) {
    const heading = item.line.match(QUESTION_HEADING_RE);
    if (heading) found.push({ offset: item.offset + item.line.search(/\S|$/), question_id: heading[1], is_heading: true, source_line: item.line.trim() });
    const jammed = item.line.match(JAMMED_QUESTION_RE);
    const question = item.line.match(QUESTION_LINE_RE);
    const match = jammed ?? question;
    if (!match) continue;
    const qid = match[1];
    if (!qid.includes(".")) {
      const tail = item.line.slice(match[0].length).trim();
      const hasLabelPeriod = match[0].includes(".");
      const childSupport = new RegExp(`^\\s*${qid.replace(".", "\\.")}\\.\\d{1,2}\\b`, "m").test(source);
      if ((firstHeading !== null && item.offset < firstHeading && instructionStart !== null && instructionStart < item.offset) ||
          !tail || /^[;,|]/.test(tail) || /^[\d.,;|+\-\s]+$/.test(tail) || (!hasLabelPeriod && !childSupport)) continue;
    }
    found.push({ offset: item.offset + item.line.search(/\S|$/), question_id: qid, is_heading: false, source_line: item.line.trim() });
  }
  found.sort((a, b) => a.offset - b.offset || a.question_id.split(".").length - b.question_id.split(".").length);
  return found.filter((item, index) => !found.slice(0, index).some((prior) => prior.offset === item.offset && prior.question_id === item.question_id));
}

function printedAllocations(text) {
  const values = [];
  for (const raw of String(text ?? "").split("\n")) {
    const line = raw.trim();
    if (!line) continue;
    PAREN_NUMBER_RE.lastIndex = 0;
    for (const match of line.matchAll(PAREN_NUMBER_RE)) {
      const before = line.slice(0, match.index).trim().toLowerCase();
      const after = line.slice((match.index ?? 0) + match[0].length).trim().toLowerCase();
      if (/\b(sub|into|equation|eqn|line|from)\s*$/.test(before)) continue;
      if (after && !after.startsWith("mark") && !/^(?:\(\d{1,2}\)\s*)+$/.test(after)) continue;
      values.push(Number(match[1]));
    }
  }
  return values;
}

function directMarkPointCounts(text) {
  const counts = [];
  for (const raw of String(text ?? "").split("\n")) {
    const line = raw.trim();
    if (!line) continue;
    const ticks = line.match(/[✓✔☑]+/);
    if (ticks) { counts.push(ticks[0].length); continue; }
    const spaced = line.match(/^\s*(\d+)\s+(.*)$/);
    const compact = line.match(/^\s*(\d+)([A-Za-z].*)$/);
    const count = Number((compact ?? spaced)?.[1]);
    const rest = String((compact ?? spaced)?.[2] ?? "").trim();
    const primaryAdded = Number.isInteger(count) && count > 0 && (MARK_CODE_RE.test(rest) || MARK_DESCRIPTOR_RE.test(rest));
    if (primaryAdded) counts.push(count);
    const inline = [...line.matchAll(/(?:^|[;|])\s*(\d+)\s*(?:S\s*[\/-]?\s*R|CA|SF|AO|M|A|F|S|R)\b/gi)];
    for (const match of inline.slice(primaryAdded ? 1 : 0)) counts.push(Number(match[1]));
  }
  return counts;
}

function sourcePageAt(text, offset, fallback = null) {
  let page = fallback == null ? null : Number(fallback);
  PAGE_LABEL_RE.lastIndex = 0;
  for (const match of String(text ?? "").matchAll(PAGE_LABEL_RE)) if ((match.index ?? 0) <= offset) page = Number(match[1]);
  return Number.isInteger(page) ? page : null;
}

export function immutableSourceStateForQuestionOccurrence(normalized, questionId, sourceBlockIndex) {
  const target = String(questionId ?? "");
  const index = Number(sourceBlockIndex);
  const blocks = flattenImmutableSource(normalized);
  if (!target || !Number.isInteger(index) || index < 0 || index >= blocks.length) return null;
  const block = blocks[index];
  const occurrences = immutableQuestionOccurrences(block.source);
  const targetOccurrences = occurrences.filter((item) => item.question_id === target);
  if (targetOccurrences.length !== 1) return null;
  const qids = [...new Set(occurrences.map((item) => item.question_id))];
  const leafIds = qids.filter((qid) => !qids.some((other) => other !== qid && other.startsWith(`${qid}.`)));
  const structuralParent = !leafIds.includes(target);
  const allocations = printedAllocations(block.allocation);
  const allocationById = new Map(qids.map((qid) => [qid, null]));
  if (leafIds.length > 0 && leafIds.length === allocations.length) leafIds.forEach((qid, position) => allocationById.set(qid, allocations[position]));
  else if (leafIds.length === 1 && allocations.length === 1) allocationById.set(leafIds[0], allocations[0]);
  const pointCounts = directMarkPointCounts(block.marking);
  const printedMarks = structuralParent ? null : allocationById.get(target) ?? null;
  const parsedPointTotal = !structuralParent && leafIds.length === 1 ? pointCounts.reduce((sum, count) => sum + count, 0) : 0;
  const computedMarks = Number(printedMarks) > 0 ? Number(printedMarks) : parsedPointTotal;
  const hasDirectMarks = !structuralParent && ((Number(printedMarks) > 0) || computedMarks > 0);
  const occurrence = targetOccurrences[0];
  return {
    question_id: target,
    source_block_index: index,
    source_page: sourcePageAt(block.source, occurrence.offset, block.page),
    printed_marks: printedMarks,
    computed_shorthand_marks: computedMarks || null,
    mark_points: computedMarks > 0 ? pointCounts.map((count) => ({ count })) : [],
    structural_parent: structuralParent,
    has_direct_marks: hasDirectMarks,
  };
}
