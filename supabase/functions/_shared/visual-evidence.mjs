const QUESTION_ID_RE = /^\d{1,2}(?:\.\d{1,2}){0,2}$/;

export function normalizedVisualText(item) {
  if (item && "level" in item && "visual_value" in item) {
    return JSON.stringify([item.level ?? null, item.printed_value ?? null, item.visual_value ?? null]);
  }
  return String(item?.normalized_math ?? item?.transcription ?? "").replace(/\s+/g, " ").trim().toLowerCase();
}

export async function legacyVisualEvidenceId(item, index) {
  const payload = {
    bbox: item?.source_page_bbox ?? item?.bbox ?? null,
    index,
    kind: item?.kind ?? null,
    page: item?.page ?? null,
    question_ref: item?.question_ref ?? null,
    rendered_asset_ref: item?.rendered_asset_ref ?? null,
    text: normalizedVisualText(item),
  };
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(JSON.stringify(payload)));
  return [...new Uint8Array(digest)].map((value) => value.toString(16).padStart(2, "0")).join("").slice(0, 16);
}

export async function ensureVisualEvidenceIds(items) {
  return Promise.all((Array.isArray(items) ? items : []).map(async (item, index) => item?.evidence_id
    ? item
    : { ...item, evidence_id: await legacyVisualEvidenceId(item, index) }));
}

export function probablePrintedIdentifier(item) {
  const value = String(item?.normalized_math ?? item?.transcription ?? "").replace(/\s+/g, "").replace(/\.$/, "");
  return QUESTION_ID_RE.test(value);
}

export function longestSequentialIdentifierRun(items) {
  const groups = new Map();
  for (const item of items) {
    const value = String(item?.normalized_math ?? item?.transcription ?? "").replace(/\s+/g, "").replace(/\.$/, "");
    const parts = value.split(".");
    if (parts.length < 2 || parts.some((part) => !/^\d+$/.test(part))) continue;
    const prefix = parts.slice(0, -1).join(".");
    if (!groups.has(prefix)) groups.set(prefix, new Set());
    groups.get(prefix).add(Number(parts.at(-1)));
  }
  let longest = 0;
  for (const values of groups.values()) {
    let current = 0, previous = null;
    for (const value of [...values].sort((a, b) => a - b)) {
      current = previous !== null && value === previous + 1 ? current + 1 : 1;
      longest = Math.max(longest, current);
      previous = value;
    }
  }
  return longest;
}

export function classifyVisualReviewUnit(items) {
  const count = items.length;
  const distinct = new Set(items.map((item) => `${String(item?.kind ?? "mark_change")}|${normalizedVisualText(item)}`)).size;
  const identifierCount = items.filter(probablePrintedIdentifier).length;
  const ratio = count ? identifierCount / count : 0;
  const sequence = longestSequentialIdentifierRun(items);
  const capHit = count === 40;
  const kinds = new Set(items.map((item) => String(item?.kind ?? "mark_change"))).size;
  if ((capHit && (ratio >= 0.5 || sequence >= 5)) || (count >= 25 && ratio >= 0.7 && sequence >= 5)) return "runaway_model_output";
  if (count >= 4 && distinct >= 3 && (ratio >= 0.5 || kinds >= 3)) return "mixed";
  return "normal";
}