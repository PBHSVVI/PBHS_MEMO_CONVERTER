import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

function sourceFiles(directory) {
  return fs.readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const target = path.join(directory, entry.name);
    return entry.isDirectory() ? sourceFiles(target) : [target];
  });
}

describe("client security boundary", () => {
  it("contains only the two approved public browser environment variables", () => {
    const source = sourceFiles(path.resolve("src"))
      .filter((file) => /\.(js|jsx)$/.test(file) && !/\.test\.(js|jsx)$/.test(file))
      .map((file) => fs.readFileSync(file, "utf8"))
      .join("\n");

    const variables = [...source.matchAll(/import\.meta\.env\.(VITE_[A-Z0-9_]+)/g)].map((match) => match[1]);
    expect(new Set(variables)).toEqual(new Set([
      "VITE_SUPABASE_URL",
      "VITE_SUPABASE_PUBLISHABLE_KEY",
    ]));
    expect(source).not.toMatch(/service[_-]?role/i);
    expect(source).not.toMatch(/SUPABASE_SECRET|GITHUB_TOKEN|GROQ_API_KEY/);
  });

  it("keeps ownership enforcement in RLS rather than a browser-only owner comparison", () => {
    const service = fs.readFileSync(path.resolve("src/lib/memoService.js"), "utf8");
    expect(service).not.toContain('.eq("user_id"');
    expect(service).toContain('.from("jobs")');
    expect(service).toContain('.from("memo-files")');
  });

  it("keeps the retry transition bounded to queued and failed_retryable server states", () => {
    const edge = fs.readFileSync(path.resolve("../supabase/functions/dispatch-memo/index.ts"), "utf8");
    const policy = fs.readFileSync(path.resolve("../supabase/functions/_shared/teacher-metadata.ts"), "utf8");
    expect(policy).toContain('job.status === "queued" || job.status === "failed_retryable"');
    expect(policy).toContain('job.status === "needs_review" && job.stage === "phase8_1b_metadata_review"');
    expect(edge).toContain('.eq("status", claimedFromStatus)');
    expect(edge).toContain('.eq("stage", claimedFromStage)');
  });
});
