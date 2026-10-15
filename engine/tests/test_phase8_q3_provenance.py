from __future__ import annotations

import copy

import fitz

from engine.src.memo_engine.canonical import build_canonical_memo
from engine.src.memo_engine.structure import extract_structure
from engine.src.memo_engine.visual_evidence import (
    _question_regions,
    fuse_visual_evidence,
    validate_visual_response,
)


Q3_PAGE_1 = """QUESTION 3
The table contains values 1 2 3 4 5 6 7 8 9 10.
T 38 39 43 26 32 39 9 31 41 17
P 39 37 43 24 33 34 14 29 35 21
3.1 Find the regression equation. (3)
"""

Q3_PAGE_2 = """3.2 Estimate the practical result. (2)
3.3 Is the estimate valid? (2)
[7]
QUESTION 4
4.1 Continue with probability. (9)
[9]
TOTAL: 16
"""


def _normalized() -> dict:
    return {
        "job_id": "public-safe-q3-hybrid",
        "source": {"sha256": "synthetic", "detected_kind": "pdf"},
        "content": {
            "kind": "pdf",
            "pages": [
                {"page": 1, "effective_text": Q3_PAGE_1},
                {"page": 2, "effective_text": Q3_PAGE_2},
            ],
        },
    }


def _response(*, question_ref: str, transcription: str, bbox: list[int], kind: str = "answer_working", mark_changes=None) -> dict:
    return {
        "schema_version": "1.0",
        "page": 1,
        "visual_content_present": True,
        "evidence": [{
            "question_ref": question_ref,
            "kind": kind,
            "transcription": transcription,
            "normalized_math": None,
            "confidence": 0.95,
            "source": "visual_overlay",
            "bbox": bbox,
        }],
        "mark_changes": mark_changes or [],
        "warnings": [],
    }


def _region(owner: str = "3.2") -> dict:
    return {
        "page": 1,
        "question_refs": [owner],
        "bbox": [0.0, 80.0, 595.0, 224.0],
        "render_bbox": [0.0, 80.0, 595.0, 224.0],
        "owned_bbox": [0.0, 100.0, 595.0, 200.0],
        "render_scale": 2.0,
        "asset_path": "internal/visual/regions/page-0001-q3_2.png",
        "printed_text": "3.2 Estimate the practical result. (2)\n3.3 Is the estimate valid? (2)\n[7]",
    }


def _q3_structure() -> dict:
    return {
        "questions": [
            {"question_id": "3.2", "source_block_index": 0, "mark_points": []},
            {"question_id": "3.3", "source_block_index": 0, "mark_points": []},
        ],
        "exceptions": [],
        "summary": {},
    }


def test_amanda_shaped_hybrid_owns_bracketed_subtotals_by_source_order():
    structure = extract_structure(_normalized())
    subtotals = structure["subtotals"]

    assert [(item["value"], item["after_question"]) for item in subtotals] == [
        (7, "3.3"),
        (9, "4.1"),
    ]
    assert all(
        item["source_provenance"]["kind"] == "explicit_bracketed_subtotal"
        for item in subtotals
    )
    assert not any(item["value"] == 9 and item["after_question"].startswith("3") for item in subtotals)


def test_q3_source_subtotal_and_teacher_confirmed_children_canonicalize_to_seven():
    normalized = _normalized()
    structure = extract_structure(normalized)
    for question in structure["questions"]:
        qid = question["question_id"]
        if qid not in {"3.1", "3.2", "3.3"}:
            continue
        marks = {"3.1": 3, "3.2": 2, "3.3": 2}[qid]
        question.update({
            "printed_marks": marks,
            "computed_shorthand_marks": marks,
            "mark_calculation_mode": "additive",
            "mark_points": [{
                "count": marks,
                "code": "A",
                "semantic": "accuracy",
                "descriptor": f"Confirmed Question {qid} marking point",
                "source": f"{marks}A Confirmed Question {qid} marking point",
            }],
        })

    canonical, _, _ = build_canonical_memo(
        {"id": "public-safe-q3-hybrid", "source_filename": "fixture.pdf", "source_mime": "application/pdf"},
        {"source": {"sha256": "synthetic", "detected_mime": "application/pdf"}},
        normalized,
        structure,
        {"exceptions": [], "interpreter_runs": [], "deterministic_results": [], "ai_results": []},
        b"",
    )

    q3 = next(question for question in canonical["questions"] if question["number"] == "3")
    assert q3["subtotal"] == {"observed": 7, "computed": 7, "status": "match"}
    assert [item["number"] for item in q3["items"]] == ["3.1", "3.2", "3.3"]


def test_question_crop_keeps_context_but_ends_ownership_before_next_anchor():
    document = fitz.open()
    page = document.new_page(width=595, height=842)
    page.insert_text((60, 100), "3.2 Estimate the practical result. (2)", fontsize=12)
    page.insert_text((60, 200), "3.3 Is the estimate valid?", fontsize=12)
    page.insert_text((500, 200), "(2)", fontsize=12)

    regions = _question_regions(page)
    q32 = next(item for item in regions if item["question_refs"] == ["3.2"])
    q33_mark = page.search_for("(2)")[-1]
    document.close()

    assert q32["bbox"][3] > q32["owned_bbox"][3]
    assert q33_mark.y0 >= q32["owned_bbox"][3]
    assert q33_mark.y0 < q32["bbox"][3]


def test_cross_anchor_claim_from_q32_crop_is_not_fused_into_q33():
    validated = validate_visual_response(
        _response(question_ref="3.3", transcription="visible next-item tick", bbox=[120, 250, 180, 290], kind="marking_note"),
        _region(),
    )
    item = validated["evidence"][0]
    assert item["effective"] is False
    assert item["evidence_status"] == "cross_anchor_mismatch"
    assert item["owned_question_ref"] == "3.2"

    structure = fuse_visual_evidence(_q3_structure(), validated)
    q33 = next(question for question in structure["questions"] if question["question_id"] == "3.3")
    assert "visual_evidence" not in q33
    assert any(
        issue["category"] == "visual_evidence_association_uncertain"
        and issue["affected_id"] == "3.2"
        for issue in structure["exceptions"]
    )


def test_printed_allocation_rediscovery_is_non_effective_but_real_amendment_reviews():
    response = _response(question_ref="3.2", transcription="(2)", bbox=[100, 100, 150, 130])
    response["mark_changes"] = [{
        "question_ref": "3.2", "level": "item", "printed_value": 2,
        "visual_value": 2, "confidence": 0.96, "requires_confirmation": True,
        "bbox": [900, 100, 980, 140],
    }]
    validated = validate_visual_response(response, _region())
    assert validated["evidence"][0]["effective"] is False
    assert validated["evidence"][0]["evidence_status"] == "printed_source_rediscovery"
    assert validated["mark_changes"][0]["effective"] is False
    assert not any(
        issue["category"] == "visual_mark_change_review"
        for issue in fuse_visual_evidence(_q3_structure(), validated)["exceptions"]
    )

    changed = copy.deepcopy(response)
    changed["evidence"] = []
    changed["mark_changes"][0]["visual_value"] = 3
    validated_change = validate_visual_response(changed, _region())
    assert validated_change["mark_changes"][0]["effective"] is True
    assert any(
        issue["category"] == "visual_mark_change_review"
        for issue in fuse_visual_evidence(_q3_structure(), validated_change)["exceptions"]
    )


def test_overlapping_crops_retain_two_provenance_rows_but_one_effective_item():
    first = {
        "question_ref": "3.3", "kind": "marking_note", "transcription": "✓",
        "normalized_math": None, "confidence": 0.95, "page": 1,
        "bbox": [700, 235, 760, 275], "source_page_bbox": [350, 190, 380, 210],
        "rendered_asset_ref": "internal/visual/regions/page-0001-q3_2.png",
    }
    second = {
        **first,
        "bbox": [80, 40, 140, 80], "source_page_bbox": [352, 191, 382, 211],
        "rendered_asset_ref": "internal/visual/regions/page-0001-q3_3.png",
    }
    visual = {"evidence": [first, second], "mark_changes": [], "warnings": []}
    structure = fuse_visual_evidence(_q3_structure(), visual)
    q33 = next(question for question in structure["questions"] if question["question_id"] == "3.3")

    assert len(visual["evidence"]) == 2
    assert sum(item["effective"] for item in visual["evidence"]) == 1
    assert len(q33["visual_evidence"]) == 1
    assert len(q33["visual_evidence"][0]["duplicate_provenance"]) == 1
    assert structure["summary"]["visual_evidence_effective_count"] == 1
