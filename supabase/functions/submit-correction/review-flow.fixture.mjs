import { createHash } from "node:crypto";
import { registerHooks } from "node:module";

// Run the real handlers with the network and Auth wrapper replaced by an
// in-memory owner-scoped store. No provider or Supabase credentials are used.
const hooks = registerHooks({
  resolve(specifier, context, next) {
    if (specifier.startsWith("jsr:")) return { url: "data:text/javascript,", shortCircuit: true };
    if (specifier === "npm:@supabase/server@^1") {
      return { url: "data:text/javascript,export const withSupabase = (_, handler) => handler", shortCircuit: true };
    }
    return next(specifier, context);
  },
});
const { default: submit } = await import("./index.ts");
const { default: confirm } = await import("../confirm-correction/index.ts");
hooks.deregister();

export const uuid = n => "e8600000-1000-4000-8000-" + String(n).padStart(12, "0");
export const jobId = uuid(1);
export const user = { id: uuid(2), email: "teacher@example.invalid" };
const start = "2026-11-28T09:00:00Z";
const criterion = (code, descriptor, solution_evidence_ids = []) => ({
  category: "proposed", count: 1, code, descriptor, solution_evidence_ids,
});
const question = (id, page, offset, printed_marks, source_line) => ({
  question_id: id, source_page: page, source_block_index: page - 2,
  source_character_offset: offset, source_heading_major: page === 5 ? "6" : "4",
  source_line, source_line_hash: createHash("sha256").update(source_line).digest("hex"),
  printed_marks, mark_points: [],
});
const review = (n, q, category, suggestions, message, status = "open") => ({
  id: uuid(n), job_id: jobId, user_id: user.id, category, affected_id: q.question_id, message,
  suggestions, level: "amber", status, created_at: start,
});
const hint = q => ({
  source_question_id: q.question_id, source_page: q.source_page, source_block_index: q.source_block_index,
  character_offset: q.source_character_offset, heading_question_id: q.source_heading_major,
});
const numbering = (n, q, status) => review(n, q, "question_parent_heading_mismatch",
  [hint(q)], "Check the printed numbering", status);
const marking = (n, q, decision, working, points, message) => review(n, q, "marking_interpretation_review",
  [{ ...hint(q), printed_total: q.printed_marks, guideline_verification: true, converted_working: working,
    guideline_provider_decision: decision, unconfirmed_criteria: points }], message);

export function makeFixture() {
  const probability = question("4.1.1", 3, 10, 4,
    "4.1.1 If ()25PA = ; ()13PB = and 𝑃(𝐴∪𝐵)=1315 , determine 𝑃(𝐴∩𝐵). (4)");
  const cards = question("4.2", 3, 80, 4, "4.2 A standard deck contains 52 cards.");
  const flags = question("4.1", 5, 100, 2, "4.1 Arrange five of eight flags. (2)");
  const parent = question("4.2", 5, 160, null, "4.2 Arrange the letters.");
  const first = question("4.2.1", 5, 200, 1, "4.2.1 With no restrictions. (1)");
  const second = question("4.2.2", 5, 240, 3, "4.2.2 With two letters together. (3)");
  const probabilityEx = marking(10, probability, "source_issue",
    [String.raw`P(A\cap B)=\frac{2}{5}+\frac{1}{3}-\frac{10}{15}=\frac{6+5-10}{15}=\frac{1}{15}`],
    [criterion("M", "Union formula"), criterion("M", "Substitute"), criterion("A", "Simplify"), criterion("A", "Answer")],
    "The memo working uses a different value from the printed question.");
  const cardsEx = marking(11, cards, null,
    ["P(A)=4/52", "P(B)=13/52", "P(A∩B)=1/52", "P(A)P(B)=1/52", "Conclude independence"],
    [criterion("A", "Find P(A)"), criterion("A", "Find P(B)"), criterion("A", "Find P(A∩B)"),
      criterion("A", "Establish equality and conclude independence", ["conclusion"]),
      { category: "ambiguous", count: null, allocation_quote: '"-1 if no conclusion"',
        allocation_evidence_ids: ["deduction"], solution_evidence_ids: ["conclusion"] }], "Confirm which occurrence owns this working.");
  const flagsEx = numbering(12, flags, "resolved");
  const parentEx = numbering(13, parent);
  const firstEx = numbering(14, first);
  const secondEx = numbering(15, second);
  const confirmation = { id: uuid(20), job_id: jobId, user_id: user.id, exception_id: flagsEx.id,
    confirmation_status: "confirmed", confirmed_at: start, applied_at: null,
    proposed_patch: { operation: "rename_question_identifier", category: flagsEx.category,
      affected_id: flags.question_id, target_id: "6.1", source_block_index: flags.source_block_index,
      source_locator: { source_question_id: flags.question_id, source_page: 5, parent_heading: "6",
        source_character_offset: flags.source_character_offset, source_line_hash: flags.source_line_hash,
        original_source_block_index: flags.source_block_index, schema_version: "1.0" },
    } };
  const job = { id: jobId, user_id: user.id, status: "needs_review", stage: "phase8_corrections_staged",
    started_at: start, attempt_count: 1, engine_version: "phase7.5", review_required: true,
    source_path: `${user.id}/${jobId}/source/synthetic.pdf`, source_filename: "Synthetic memo.pdf", source_mime: "application/pdf" };
  const rows = { jobs: [job], corrections: [confirmation], job_events: [],
    exceptions: [probabilityEx, cardsEx, flagsEx, parentEx, firstEx, secondEx] };
  const structure = { questions: [probability, cards, flags, parent, first, second] };
  const normalized = { content: { pages: [
    { page: 3, text: [probability.source_line, cards.source_line,
      "A is a king and B is a heart. Show whether the events are independent. (4)"].join("\n") },
    { page: 5, text: [flags, parent, first, second].map(q => q.source_line).join("\n") },
  ] } };
  return { rows, structure, normalized, probabilityEx, cardsEx, parentEx, flags, confirmation };
}

export function fixtureDatabase(fixture, owner) {
  return {
    from(table) {
      if (!Object.hasOwn(fixture.rows, table)) throw Error("Unexpected table " + table);
      const rows = fixture.rows[table];
      const filters = owner ? [row => row.user_id === owner] : [];
      let mutation, limit, order, head = false;
      const run = () => {
        if (mutation?.insert) {
          const row = { created_at: new Date().toISOString(), applied_at: null, ...mutation.insert };
          rows.push(row);
          return [row];
        }
        const selected = rows.filter(row => filters.every(filter => filter(row)));
        if (order) selected.sort(order);
        if (mutation?.update) for (const row of selected) Object.assign(row, mutation.update);
        return selected.slice(0, limit);
      };
      const api = {
        select(_columns, options) { head = options?.head; return api; },
        eq(key, value) { filters.push(row => row[key] === value); return api; },
        in(key, values) { filters.push(row => values.includes(row[key])); return api; },
        is(key, value) { filters.push(row => (row[key] ?? null) === value); return api; },
        gte(key, value) { filters.push(row => row[key] >= value); return api; },
        limit(value) { limit = value; return api; },
        order(key, { ascending = true } = {}) {
          order = (a, b) => String(a[key]).localeCompare(String(b[key])) * (ascending ? 1 : -1);
          return api;
        },
        insert(value) { mutation = { insert: value }; return api; },
        update(value) { mutation = { update: value }; return api; },
        async single() { return { data: structuredClone(run()[0] ?? null) }; },
        async maybeSingle() { return api.single(); },
        then(resolve) {
          const selected = run();
          resolve(head ? { count: selected.length } : { data: structuredClone(selected) });
        },
      };
      return api;
    },
    storage: { from: () => ({ async download(path) {
      const data = path.endsWith("/structure.json") ? fixture.structure : path.endsWith("/normalized.json") ? fixture.normalized : null;
      return data ? { data: new Blob([JSON.stringify(data)]) } : { error: new Error("Unknown fixture asset") };
    } }) },
  };
}

export function callEdge(fixture, name, body, owner = user.id) {
  const handler = { "submit-correction": submit, "confirm-correction": confirm }[name];
  if (!handler) throw Error("Unexpected fixture function " + name);
  return handler.fetch(new Request("http://fixture.invalid/" + name, { method: "POST", body: JSON.stringify(body) }),
    { supabase: fixtureDatabase(fixture, owner), supabaseAdmin: fixtureDatabase(fixture) });
}
