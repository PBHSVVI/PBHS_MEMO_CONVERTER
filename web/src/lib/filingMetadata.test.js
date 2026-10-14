import { describe, expect, it } from "vitest";
import {
  allowedYears,
  initialFilingDraft,
  outputDownloadName,
  sanitizeDisplayName,
  serializeFilingMetadata,
  suggestedDisplayName,
  validateFilingDraft,
} from "./filingMetadata";

const now = new Date("2026-10-14T00:00:00Z");
const base = { subject_scope: "mathematics", form: 4, assessment_type: "class_test", term: 4, year: 2026, assessment_number: 2, paper: "", duration_value: 45, duration_unit: "minutes" };

describe("department filing metadata", () => {
  it("uses a dynamic next/current/previous-ten year range", () => {
    expect(allowedYears(now)).toEqual([2027, 2026, 2025, 2024, 2023, 2022, 2021, 2020, 2019, 2018, 2017, 2016]);
    expect(initialFilingDraft({}, now).year).toBe(2026);
  });

  it.each([
    [{ ...base }, "Form 4 Class Test 2 Term 4 2026"],
    [{ ...base, form: 3, assessment_type: "standardised_test", assessment_number: 1, term: 2 }, "Form 3 Standardised Test 1 Term 2 2026"],
    [{ ...base, form: 5, assessment_type: "examination", assessment_number: "", paper: 2 }, "Form 5 Examination Paper 2 Term 4 2026"],
    [{ ...base, form: 2, assessment_type: "investigation", assessment_number: "", term: 3 }, "Form 2 Investigation Term 3 2026"],
  ])("generates the expected friendly name", (draft, expected) => {
    expect(suggestedDisplayName(draft)).toBe(expected);
    expect(suggestedDisplayName(draft)).not.toContain("N/A");
  });

  it("enforces conditional assessment number and paper rules", () => {
    expect(validateFilingDraft({ ...base, assessment_number: "" }, "Name", now).errors).toHaveProperty("assessment_number");
    expect(validateFilingDraft({ ...base, paper: 2 }, "Name", now).errors).toHaveProperty("paper");
    expect(validateFilingDraft({ ...base, assessment_type: "examination", assessment_number: 3, paper: 2 }, "Name", now).errors).toHaveProperty("assessment_number");
    expect(validateFilingDraft({ ...base, assessment_type: "examination", assessment_number: "", paper: "" }, "Name", now).errors).toHaveProperty("paper");
  });

  it("preserves duration units and never invents minutes for periods", () => {
    expect(serializeFilingMetadata(base, now).duration).toEqual({ value: 45, unit: "minutes", duration_minutes: 45 });
    expect(serializeFilingMetadata({ ...base, duration_value: 1.5, duration_unit: "hours" }, now).duration).toEqual({ value: 1.5, unit: "hours", duration_minutes: 90 });
    expect(serializeFilingMetadata({ ...base, duration_value: 2, duration_unit: "periods" }, now).duration).toEqual({ value: 2, unit: "periods", duration_minutes: null });
    expect(validateFilingDraft({ ...base, duration_value: 1.5, duration_unit: "periods" }, "Name", now).errors).toHaveProperty("duration_value");
    expect(validateFilingDraft({ ...base, duration_value: 0 }, "Name", now).errors).toHaveProperty("duration_value");
  });

  it("sanitizes names and provides safe friendly and legacy download filenames", () => {
    expect(sanitizeDisplayName("  ../Form 4: Test<script>  ")).toBe(". Form 4 Test script");
    expect(outputDownloadName({ display_name: "Form 4 Test", source_filename: "raw.pdf" }, "docx")).toBe("Form 4 Test - GDE Memo.docx");
    expect(outputDownloadName({ source_filename: "legacy memo.pdf" }, "pdf")).toBe("legacy memo - GDE Memo.pdf");
  });
});
