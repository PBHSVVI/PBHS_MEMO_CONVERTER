import { describe, expect, it } from "vitest";
import {
  normalizeMetadataDraft,
  uploadMetadataFromDashboard,
  validateTeacherMetadata,
} from "./documentMetadata";

describe("teacher document metadata", () => {
  it("serializes the controlled Form 4 option to the backend contract", () => {
    const metadata = normalizeMetadataDraft({ grade_label: "FORM 4" });
    expect(metadata.values.grade_label).toBe("FORM 4");
    expect(validateTeacherMetadata(metadata)).toEqual({ valid: true, errors: {} });
  });

  it("omits a blank Form and rejects arbitrary grade text", () => {
    expect(normalizeMetadataDraft({ grade_label: "" }).values).not.toHaveProperty("grade_label");
    expect(validateTeacherMetadata(normalizeMetadataDraft({ grade_label: "a long teacher note" }))).toMatchObject({
      valid: false,
      errors: { grade_label: expect.any(String) },
    });
  });

  it("rejects invalid years and durations while accepting blank optional fields", () => {
    expect(validateTeacherMetadata(normalizeMetadataDraft({ year: "1999" })).errors).toHaveProperty("year");
    expect(validateTeacherMetadata(normalizeMetadataDraft({ duration_value: "0", duration_unit: "minutes" })).errors).toHaveProperty("duration_minutes");
    expect(validateTeacherMetadata(normalizeMetadataDraft({ duration_value: "1.5", duration_unit: "minutes" })).errors).toHaveProperty("duration_minutes");
    expect(validateTeacherMetadata(normalizeMetadataDraft({}))).toEqual({ valid: true, errors: {} });
  });

  it("converts safe dashboard context into editable upload defaults", () => {
    expect(uploadMetadataFromDashboard({ department: "mathematics", form: 4 }).values).toEqual({
      subject: "MATHEMATICS",
      grade_label: "FORM 4",
    });
  });
});
