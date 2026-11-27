"""Project verified question-local results without replacing the source or its audit."""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

import pymupdf

from .math_notation import normalize_visual_math
from .openai_credit import BUCKET, PILOT_JOB


# The dedicated pilot operation may read only the privately inspected results.
TRIAL_RUN = "45982815290"
ARTIFACTS = {
    2: "863f33f28160e631f16096b8a7d6fa9f1223c6c36fc210df867b486a91eda14b",
    3: "b294d0ef3e65806f3fa9bb52b5e5e6c5d54b893f690da86ef74aebdc776d9d07",
    4: "42362fb2cf828f38a67420238bcbcaa10cb9d01c4331823d28b40d7a003b8284",
}
CHECKS = {"fidelity", "mathematics", "criterion_links", "allocation", "explicit_instructions", "ownership", "figure"}


def load_trial(db: Any, job: dict, source: bytes) -> list[dict]:
    if job["id"] != PILOT_JOB:
        raise ValueError("Reference replay is limited to the authorised pilot")
    prefix = f"{job['user_id']}/{job['id']}/internal/trials/phase85e-{TRIAL_RUN}"
    results = []
    with pymupdf.open(stream=source, filetype="pdf") as pdf:
        for sample, expected in ARTIFACTS.items():
            blob = db.download_object(BUCKET, f"{prefix}/{sample}-comparison.json")
            if hashlib.sha256(blob).hexdigest() != expected:
                raise ValueError("An inspected reference result changed")
            entry = json.loads(blob)
            page = pdf[entry["page"] - 1]
            box = pymupdf.Rect(entry["source_rectangle"])
            raster = page.get_pixmap(matrix=pymupdf.Matrix(3.5, 3.5), clip=box, alpha=False)
            if hashlib.sha256(raster.tobytes("png")).hexdigest() != entry["crop_sha256"]:
                raise ValueError("The reference result crop differs from the original source")
            results.append({**entry, "artifact_digest": expected})
    return results


def _validated_awards(draft: dict, printed: int) -> list[tuple[dict, list[int]]]:
    working = draft["working"]
    if not working or any(row["alternative"] != 0 for row in working):
        raise ValueError("Reference replay requires one complete source method")
    seen = set()
    awards = []
    for point in draft["criteria"]:
        links = point["links"]
        identities = {(point["code"], link) for link in links}
        if (type(point["marks"]) is not int or point["marks"] < 1 or
                point["code"] not in {"A", "M"} or not point["descriptor"].strip() or not links or
                len(identities) != len(links) or seen & identities or
                any(type(link) is not int or not 0 <= link < len(working) for link in links)):
            raise ValueError("Reference marking links or awards are invalid")
        seen.update(identities)
        awards.append((point, links))
    if type(printed) is not int or printed < 1 or sum(p["marks"] for p, _ in awards) != printed:
        raise ValueError("Reference awards disagree with the original item allocation")
    return awards


def _set_working(question: dict, entry: dict, ids: list[str], ref: str) -> None:
    segments = []
    page_ref = {"file_id": "source_1", "page": entry["page"]}
    for order, (line, identifier) in enumerate(zip(entry["draft"]["working"], ids, strict=True)):
        if line["kind"] != "math":
            raise ValueError("Reference working replay requires independently verified mathematics")
        latex, issue = normalize_visual_math(line["latex"])
        if not latex or issue or "$" in latex:
            raise ValueError("Reference working failed the notation check")
        segments.append({"text": latex, "canonical_latex": latex, "raw_transcription": line["source_text"],
                         "source_ref": page_ref, "rendered_asset_ref": ref, "confidence": 1.0,
                         "evidence_order": order, "interpretation_evidence_id": identifier,
                         "verification_id": entry["artifact_digest"]})
    question["visual_solution_segments"] = segments


def _diagram_additions(question: dict, entry: dict, ids: list[str], awards: list, figure: dict) -> list:
    """Preserve existing awards and append only distinct entries on the original image."""
    old = question["mark_points"]
    by_id = {row["evidence_id"]: row for row in question.get("visual_evidence", [])}
    figures = set(figure["visual_evidence_ids"])
    reserved = set()
    for point in old:
        refs = point.get("solution_evidence_ids", [])
        if (point.get("notation") != "constructed_verified" or point["count"] != 1 or len(refs) != 1
                or refs[0] not in figures or refs[0] not in by_id):
            raise ValueError("Existing diagram awards cannot be uniquely preserved")
        value = str(by_id[refs[0]].get("normalized_math") or "").strip()
        if not re.fullmatch(r"\d+", value) or value in reserved:
            raise ValueError("Existing diagram values cannot be uniquely preserved")
        reserved.add(value)
    values = set()
    additions = []
    for point, links in awards:
        if point["marks"] != 1 or len(links) != 1:
            raise ValueError("Diagram awards must identify distinct entries")
        index, = links
        value = entry["draft"]["working"][index]["latex"]
        if not isinstance(value, str) or not re.fullmatch(r"\d+", value) or value in values:
            raise ValueError("Reference diagram values cannot be uniquely mapped")
        values.add(value)
        if value not in reserved:
            additions.append((point, links))
    if not reserved <= values or len(old) + len(additions) != entry["printed_allocation"]:
        raise ValueError("Reference diagram would alter an existing award")
    figure["visual_evidence_ids"] = [*figure["visual_evidence_ids"],
                                      *(ids[links[0]] for _, links in additions)]
    return additions


def apply_reference_results(structure: dict, entries: list[dict]) -> dict:
    totals = {"verified_questions": 0, "added_marking_points": 0, "source_issues_with_verified_working": 0,
              "verified_working_pending_ownership": 0}
    for entry in entries:
        draft, qa = entry["draft"], entry["independent_verification"]
        if set(qa["checks"]) != CHECKS or not all(value is True for value in qa["checks"].values()) or (
                qa["decision"] not in {"accept", "source_issue"}) or draft["issue"] != "none":
            raise ValueError("Reference result did not pass independent component checks")
        qid, page = entry["printed_label"], entry["page"]
        question, = [q for q in structure["questions"] if q["question_id"] == qid and q["source_page"] == page]
        if question["printed_marks"] != entry["printed_allocation"]:
            raise ValueError("Reference result no longer matches the original item")
        if any(point.get("teacher_correction_id") for point in question["mark_points"]):
            raise ValueError("Reference replay cannot replace teacher marking")
        awards = _validated_awards(draft, question["printed_marks"])
        ids = [f"reference_{entry['artifact_digest'][:16]}_{index}" for index in range(len(draft["working"]))]
        offset = question.get("source_block_index")
        def same_review(row):
            return row["affected_id"] == qid and any(s.get("source_page") == page
                   and s.get("source_block_index") == offset for s in row.get("suggestions", []))
        review, = [row for row in structure["exceptions"] if row["category"] == "marking_interpretation_review" and same_review(row)]
        ref = review["suggestions"][0]["rendered_asset_ref"]
        question["reference_verification"] = {"run": TRIAL_RUN, "artifact_sha256": entry["artifact_digest"],
                                              "crop_sha256": entry["crop_sha256"], "decision": qa["decision"],
                                              "marker_notes": draft["marker_notes"]}
        ownership = [row for row in structure["exceptions"] if row["category"] == "question_parent_heading_mismatch"
                     and same_review(row)]
        if ownership:
            # This occurrence may share a printed path with a different
            # question's children. Keep the verified working, but wait
            # for the existing numbering decision before scoring it.
            question["reference_verification"]["pending_marks"] = question["printed_marks"]
            review["message"] = "The working and marking were verified. Confirm the question numbering before counting these marks."
            for suggestion in review["suggestions"]:
                suggestion["converted_working"] = [line["source_text"] for line in draft["working"]]
                suggestion["depends_on_source_numbering"] = True
            for row in ownership:
                for suggestion in row["suggestions"]:
                    suggestion["verified_working"] = [line["source_text"] for line in draft["working"]]
            totals["verified_working_pending_ownership"] += 1
            continue
        if all(line["kind"] == "diagram_entry" for line in draft["working"]):
            figure, = [g for g in question.get("spatial_visual_groups", []) if g["reliable"]]
            if qa["decision"] != "accept":
                raise ValueError("Reference figure requires complete independent verification")
            awards = _diagram_additions(question, entry, ids, awards, figure)
            ref = figure["rendered_asset_ref"]
        else:
            if question["mark_points"]:
                raise ValueError("Reference working would replace already admitted awards")
            _set_working(question, entry, ids, ref)
        if qa["decision"] == "source_issue":
            finding = qa["finding"].partition("However, ")[2].split(";", 1)[0].strip()
            review["message"] = (finding.rstrip(".") + ". Confirm the intended wording."
                                 if finding else "Confirm the source wording highlighted by the independent check.")
            for suggestion in review["suggestions"]:
                suggestion["converted_working"] = [line["source_text"] for line in draft["working"]]
            totals["source_issues_with_verified_working"] += 1
            continue
        added = []
        for count, (award, links) in enumerate(awards):
            point = {"category": "proposed", "criterion_id": f"{entry['artifact_digest'][:20]}_{count}",
                     "count": award["marks"], "code": award["code"], "descriptor": award["descriptor"],
                     "solution_evidence_ids": [ids[index] for index in links], "alternative": 0,
                     "source_refs": [{"file_id": "source_1", "page": page}], "notation": "constructed_verified",
                     "verification_id": entry["artifact_digest"]}
            added.append(point)
        question["mark_points"].extend(added)
        question["computed_shorthand_marks"] = sum(point["count"] for point in question["mark_points"])
        interpretation = question["marking_interpretation"]
        interpretation.setdefault("constructed", []).extend(added)
        interpretation["unconfirmed"] = []
        interpretation["verification"] = {"id": entry["artifact_digest"], "status": "verified"}
        structure["exceptions"].remove(review)
        structure["exceptions"] = [row for row in structure["exceptions"] if not (
            row["affected_id"] == qid and row["category"] == "visual_evidence_uncertain"
            and row.get("suggestions") and all(s.get("rendered_asset_ref") == ref for s in row["suggestions"]))]
        totals["verified_questions"] += 1
        totals["added_marking_points"] += len(added)
    return totals
