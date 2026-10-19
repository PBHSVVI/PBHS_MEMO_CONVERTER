from __future__ import annotations

import copy
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from engine.src.memo_engine.corrections import apply_confirmed_corrections
from engine.src.memo_engine.visual_evidence import (
    classify_visual_review_unit,
    ensure_visual_evidence_ids,
    extract_visual_evidence,
    fuse_visual_evidence,
    legacy_visual_evidence_id,
    validate_visual_response,
)
from engine.tests.test_phase8_visual_association import _correction, _observation, _patch, _structure, _visual

ROOT = Path(__file__).resolve().parents[2]
PAGE = ROOT / "docs" / "phase7-5-review" / "index.html"
SHARED = ROOT / "supabase" / "functions" / "_shared" / "visual-evidence.mjs"


def _runaway_items() -> list[dict]:
    readings = ["6.4.2", "4.2"] + [f"4.2.{index}" for index in range(1, 39)]
    return [_observation(index, reading, asset="internal/visual/regions/page-0005-q4_2_1.png") for index, reading in enumerate(readings)]


def test_legacy_identity_is_stable_preserves_modern_ids_and_does_not_collide():
    first = _observation(1, "x = 2")
    second = _observation(2, "x = 3")
    first.pop("evidence_id")
    second.pop("evidence_id")
    expected = legacy_visual_evidence_id(first, 0)
    ensure_visual_evidence_ids([first, second])
    assert first["evidence_id"] == expected
    assert first["evidence_id"] != second["evidence_id"]
    assert legacy_visual_evidence_id(first, 0) == expected
    modern = {**first, "evidence_id": "modern-stored-id"}
    ensure_visual_evidence_ids([modern])
    assert modern["evidence_id"] == "modern-stored-id"


def test_python_browser_and_edge_shared_module_derive_same_legacy_id():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js required")
    item = _observation(1, "x = 2")
    item.pop("evidence_id")
    item["source_page_bbox"] = [110.0, 220.5, 130.0, 240.0]
    expected = legacy_visual_evidence_id(item, 0)
    edge_run = subprocess.run(
        [node, "--input-type=module", "-e", f"import {{legacyVisualEvidenceId}} from {json.dumps(SHARED.as_uri())}; console.log(await legacyVisualEvidenceId(JSON.parse(process.argv[1]),0));", json.dumps(item)],
        check=True, capture_output=True, text=True,
    )
    source = PAGE.read_text(encoding="utf-8")
    section = re.search(r"// BEGIN VISUAL ASSOCIATION REVIEW MODEL\s*(.*?)\s*// END VISUAL ASSOCIATION REVIEW MODEL", source, re.S).group(1)
    browser_run = subprocess.run(
        [node, "--input-type=module", "-e", section + "\nconsole.log(await legacyVisualEvidenceId(JSON.parse(process.argv[1]),0));", json.dumps(item)],
        check=True, capture_output=True, text=True,
    )
    assert edge_run.stdout.strip() == expected
    assert browser_run.stdout.strip() == expected


def test_live_style_cap_sequence_is_runaway_and_cap_warning_is_recorded():
    items = _runaway_items()
    model = classify_visual_review_unit(items)
    assert model["classification"] == "runaway_model_output"
    assert model["cap_hit"] is True
    assert model["warnings"] == ["VISUAL_EVIDENCE_ITEM_CAP_REACHED"]
    assert model["probable_printed_identifier_count"] == 40
    assert model["sequential_identifier_run"] >= 38

    response = {
        "schema_version": "1.0", "page": 5, "visual_content_present": True,
        "evidence": [{
            "question_ref": "4.2.1", "kind": "answer_working", "transcription": item["transcription"],
            "normalized_math": item["transcription"], "confidence": .97, "source": "visual_overlay", "bbox": [1, 1, 2, 2],
        } for item in items],
        "mark_changes": [], "warnings": [],
    }
    normalized = {"source": {"sha256": "sha"}, "content": {"kind": "pdf", "pages": [{"page": 5, "visual_inspection_required": True}]}}
    region = {"page": 5, "question_refs": ["4.2.1"], "bbox": [0, 0, 100, 100], "render_bbox": [0, 0, 100, 100], "owned_bbox": [0, 0, 100, 100], "asset_path": "internal/visual/regions/page-0005-q4_2_1.png", "image_bytes": b"x", "mime_type": "image/png", "printed_text": "4.2.1", "region_index": 1}
    import engine.src.memo_engine.visual_evidence as ve
    original = ve._render_regions
    ve._render_regions = lambda *_: [region]
    try:
        record, _ = extract_visual_evidence(b"pdf", normalized, runner=lambda *_: response)
    finally:
        ve._render_regions = original
    assert any(warning["code"] == "VISUAL_EVIDENCE_ITEM_CAP_REACHED" for warning in record["warnings"])


def test_unrelated_multi_kind_crop_is_mixed_without_being_runaway():
    items = [
        {**_observation(1, "x = 2"), "kind": "answer"},
        {**_observation(2, "✓"), "kind": "tick"},
        {**_observation(3, "check graph"), "kind": "teacher_comment"},
        {**_observation(4, "x = 2"), "kind": "answer"},
    ]
    assert classify_visual_review_unit(items)["classification"] == "mixed"


def test_runaway_requires_explicit_subset_but_reject_covers_whole_region():
    visual = _visual(_runaway_items())
    fused = fuse_visual_evidence(_structure(), visual)
    unit = fused["exceptions"][0]["suggestions"][0]
    assert unit["unit_classification"] == "runaway_model_output"

    partial = _patch(unit, "REASSIGN", "6.3")
    partial.update({
        "selection_mode": "explicit_subset",
        "unit_classification": "runaway_model_output",
        "review_unit_evidence_ids": unit["evidence_ids"],
        "evidence_ids": unit["distinct_observations"][0]["evidence_ids"],
    })
    selected_unit = fuse_visual_evidence(_structure(), _visual([copy.deepcopy(visual["evidence"][0])]))["exceptions"][0]["suggestions"][0]
    partial["source_page_bboxes"] = selected_unit["source_page_bboxes"]
    partial["original_claimed_question_refs"] = selected_unit["claimed_question_refs"]
    result, applied, issues = apply_confirmed_corrections(fused, {}, [_correction(partial)], visual)
    assert issues == [] and applied[0]["selected_evidence_count"] == 1
    target = next(q for q in result["questions"] if q["question_id"] == "6.3")
    assert len(target["visual_evidence"]) == 1
    assert len(visual["evidence"]) == 40

    blind = _patch(unit, "ACCEPT", "6.2")
    blind.update({"selection_mode": "whole_unit", "unit_classification": "runaway_model_output", "review_unit_evidence_ids": unit["evidence_ids"]})
    _, applied, issues = apply_confirmed_corrections(fused, {}, [_correction(blind)], visual)
    assert applied == [] and issues[0]["category"] == "correction_evidence_unresolved"

    reject = _patch(unit, "REJECT", None)
    reject.update({"selection_mode": "whole_unit", "unit_classification": "runaway_model_output", "review_unit_evidence_ids": unit["evidence_ids"]})
    _, applied, issues = apply_confirmed_corrections(fused, {}, [_correction(reject)], visual)
    assert issues == [] and applied[0]["decision"] == "REJECT"

    # Existing confirmed v4.12 whole-unit decisions have no selection metadata;
    # they remain replayable and auditable without rewriting proposed_patch.
    legacy = _patch(unit, "ACCEPT", "6.2")
    legacy_result, applied, issues = apply_confirmed_corrections(fused, {}, [_correction(legacy)], visual)
    assert issues == [] and applied[0]["selection_mode"] == "legacy_whole_unit"
    legacy_target = next(q for q in legacy_result["questions"] if q["question_id"] == "6.2")
    assert len(legacy_target["visual_evidence"]) == 40


def test_cross_crop_missing_duplicate_and_empty_selected_ids_fail_closed():
    cross_crop = _observation(99, "x = 2", asset="internal/visual/regions/page-0003-q4_1.png")
    visual = _visual([*_runaway_items(), cross_crop])
    fused = fuse_visual_evidence(_structure(), visual)
    unit = fused["exceptions"][0]["suggestions"][0]
    base = _patch(unit, "REASSIGN", "6.3")
    base.update({"selection_mode": "explicit_subset", "unit_classification": "runaway_model_output", "review_unit_evidence_ids": unit["evidence_ids"]})
    for ids in ([], ["missing"], [cross_crop["evidence_id"]], [unit["evidence_ids"][0], unit["evidence_ids"][0]]):
        patch = {**base, "evidence_ids": ids}
        _, applied, issues = apply_confirmed_corrections(fused, {}, [_correction(patch)], visual)
        assert applied == [] and issues[0]["category"] == "correction_evidence_unresolved"


def test_probable_question_identifier_does_not_become_solution_but_numeric_math_does():
    def response(text: str) -> dict:
        return {
            "schema_version": "1.0", "page": 5, "visual_content_present": True,
            "evidence": [{
                "question_ref": "4.2.1", "kind": "answer", "transcription": text,
                "normalized_math": text, "confidence": .97,
                "source": "visual_overlay", "bbox": [10, 10, 20, 20],
            }],
            "mark_changes": [], "warnings": [],
        }

    region = {
        "page": 5, "question_refs": ["4.2.1"], "bbox": [0, 0, 100, 100],
        "render_bbox": [0, 0, 100, 100], "owned_bbox": [0, 0, 100, 100],
        "asset_path": "internal/visual/regions/page-0005-q4_2_1.png",
        "printed_text": "Question 4.2.1", "render_scale": 1,
    }
    printed = validate_visual_response(response("4.2.1"), region)["evidence"][0]
    numeric_math = validate_visual_response(response("4.2"), region)["evidence"][0]
    assert printed["effective"] is False
    assert printed["evidence_status"] == "printed_source_rediscovery"
    assert numeric_math["effective"] is True
