import { describe, expect, it } from "vitest";
import {
  filterPapers,
  formNumber,
  libraryPaper,
  ownerJobPaper,
  paperContext,
  paperIdentity,
  papersForScope,
  subjectScope,
  unclassifiedOwnerPapers,
} from "./paperWorkspace";

const user = { id: "teacher-1", email: "teacher@pbhs.example", app_metadata: { pbhs_display_name: "Teacher Example" } };

function job(changes = {}) {
  return {
    id: "job-1", user_id: user.id, status: "processing", stage: "structure",
    source_filename: "legacy-name.docx", created_at: "2026-10-01T08:00:00Z",
    updated_at: "2026-10-01T09:00:00Z",
    teacher_metadata: { values: { subject: "MATHEMATICS", exam_type: "CONTROL TEST", paper: "PAPER 1", grade_label: "FORM 3", year: 2026 } },
    ...changes,
  };
}

describe("department paper presentation model", () => {
  it("maps owner jobs and department summaries into the same safe fields", () => {
    const owner = ownerJobPaper(job(), user);
    const summary = libraryPaper({
      job_id: "job-2", owner_user_id: "teacher-2", owner_display_name: "Other Teacher",
      subject_scope: "mathematics", assessment_type: "CONTROL TEST", paper: "PAPER 2",
      grade_label: "FORM 3", year: 2026, workflow_bucket: "completed", status_source: "complete",
      updated_at: "2026-10-02T09:00:00Z", source_filename: "other.docx",
    });
    expect(owner).toMatchObject({ subject_scope: "mathematics", form: 3, workflow_bucket: "in_progress", source: "owner_job" });
    expect(summary).toMatchObject({ subject_scope: "mathematics", form: 3, workflow_bucket: "completed", source: "department_summary" });
    expect(paperIdentity(owner)).toBe("CONTROL TEST · PAPER 1");
    expect(paperContext(owner)).toEqual(["FORM 3", 2026]);
  });

  it("filters explicitly by subject, workflow, form and owner", () => {
    const papers = [
      ownerJobPaper(job(), user),
      ownerJobPaper(job({ id: "job-2", status: "complete" }), user),
      ownerJobPaper(job({ id: "job-3", teacher_metadata: { values: { subject: "FS MATHEMATICS", grade_label: "FORM 3" } } }), user),
      ownerJobPaper(job({ id: "job-4", user_id: "teacher-2" }), user),
    ];
    expect(filterPapers(papers, { department: "mathematics", workState: "in_progress", scope: "my", form: 3, ownerId: user.id }).map((paper) => paper.job_id)).toEqual(["job-1"]);
    expect(filterPapers(papers, { department: "fs_mathematics", workState: "in_progress", scope: "my", form: 3, ownerId: user.id }).map((paper) => paper.job_id)).toEqual(["job-3"]);
  });

  it("keeps missing metadata neutral and preserves legacy owner work separately", () => {
    const legacy = ownerJobPaper(job({ teacher_metadata: { values: {} } }), user);
    expect(legacy).toMatchObject({ subject_scope: null, form: null });
    expect(paperIdentity(legacy)).toBe("legacy-name.docx");
    expect(unclassifiedOwnerPapers([legacy], { ownerId: user.id, workState: "in_progress" })).toEqual([legacy]);
  });

  it("uses deterministic ordinary form labels without inventing missing values", () => {
    expect(subjectScope(" FS Mathematics ")).toBe("fs_mathematics");
    expect(subjectScope("Technical Mathematics")).toBeNull();
    expect(formNumber("Form 5")).toBe(5);
    expect(formNumber("Grade 12")).toBe(5);
    expect(formNumber("Senior form")).toBeNull();
  });

  it("uses only owner jobs for My papers and summary rows for All papers", () => {
    const owner = ownerJobPaper(job(), user);
    const rows = [{ job_id: "other", owner_user_id: "teacher-2", subject_scope: "mathematics", grade_label: "FORM 3", workflow_bucket: "in_progress", status_source: "processing" }];
    expect(papersForScope({ scope: "my", ownerPapers: [owner], libraryRows: rows, ownerId: user.id })).toEqual([owner]);
    expect(papersForScope({ scope: "all", ownerPapers: [owner], libraryRows: rows, ownerId: user.id })[0]).toMatchObject({ job_id: "other", source: "department_summary" });
  });
});
