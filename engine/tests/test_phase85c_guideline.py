from __future__ import annotations

import copy
import hashlib
from types import SimpleNamespace

import pytest

from engine.src.memo_engine.canonical import build_canonical_memo
from engine.src.memo_engine.guideline_verification import CHECKS, _eligible_scheme, verify_guideline
from engine.src.memo_engine.marking_interpretation import interpret_marking
from engine.src.memo_engine.semantic import interpret_semantics
from engine.src.memo_engine.openai_credit import PBHS_URL, reconcile_ledger
from engine.src.memo_engine.visual_evidence import fuse_visual_evidence
from engine.tests.test_phase85b_marking import criterion, fixture, responder


CROP = b"immutable fixture crop"


def inputs(points=None):
    structure, normalized, visual = fixture()
    asset = visual["evidence"][0]["rendered_asset_ref"]
    visual["assets"] = [{"path": asset, "sha256": hashlib.sha256(CROP).hexdigest(), "mime_type": "image/png"}]
    fuse_visual_evidence(structure, visual)
    structure, _ = interpret_marking(
        structure, normalized, visual, interpreter=responder(points if points is not None else [
            {**criterion(code="M"), "descriptor": "correct method"}, criterion(code="A"),
        ]),
    )
    return structure, normalized, visual


def verify(packet, crop, mime):
    assert crop == CROP and mime == "image/png"
    return SimpleNamespace(value={
        "decision": "verified", "checks": {name: True for name in CHECKS},
        "selected_ids": [criterion["criterion_id"] for criterion in packet["criteria"] if criterion["category"] != "ambiguous"],
        "ambiguities_resolved": True, "reason": "", "readings": [], "criteria": [], "figure_bounds": [],
    })


def test_source_verified_constructed_marks_reach_the_normal_canonical_handoff():
    structure, normalized, visual = inputs()
    audit = verify_guideline(structure, normalized, visual, load_crop=lambda _: CROP, verifier=verify)
    assert audit["summary"]["constructed_marking_points"] == 2
    assert not structure["exceptions"]
    semantic = interpret_semantics(structure)
    canonical, validation, _ = build_canonical_memo(
        {"id": normalized["job_id"], "source_filename": "fixture.pdf", "source_mime": "application/pdf"},
        {"source": {"sha256": "synthetic", "detected_kind": "pdf", "detected_mime": "application/pdf", "size_bytes": 1}},
        normalized, structure, semantic, b"%PDF-synthetic",
    )
    item = canonical["questions"][0]["items"][0]
    points = item["alternatives"][0]["marking_points"]
    assert len(points) == 2 and all(p["marking_provenance"]["origin"] == "constructed_verified" for p in points)
    assert all("source_marking" not in p and p["applies_to_block_ids"] for p in points)
    assert canonical["totals"]["computed"] == 2
    assert validation["mathematical_consistency"]["checked_expression_count"] == 1
    assert validation["handoff_ready"] and canonical["status"] == "render_ready"


def test_explicit_source_point_is_preserved_distinct_from_verified_construction():
    structure, normalized, visual = inputs([
        criterion("explicit", code="M", quote="1M method", allocation=["e1"]), criterion(code="A"),
    ])
    original = copy.deepcopy(structure["questions"][0]["mark_points"][0])
    verify_guideline(structure, normalized, visual, load_crop=lambda _: CROP, verifier=verify)
    assert structure["questions"][0]["mark_points"][0] == original
    assert structure["questions"][0]["mark_points"][1]["notation"] == "constructed_verified"


def test_converter_repair_has_a_second_source_check_and_preserves_raw_evidence():
    structure, normalized, visual = inputs()
    old = copy.deepcopy(visual)
    calls = []

    def independent(packet, crop, mime):
        result = verify(packet, crop, mime)
        calls.append(packet["observations"][0]["transcription"])
        if len(calls) == 1:
            result.value.update(decision="repairable", readings=[{
                "evidence_id": "e0", "transcription": "2 + 3 = 5", "normalized_math": "2+3=5",
            }])
        return result

    audit = verify_guideline(structure, normalized, visual, load_crop=lambda _: CROP, verifier=independent)
    assert calls == ["2+3=5", "2 + 3 = 5"]
    assert audit["summary"]["repaired_readings"] == 1 and visual == old


@pytest.mark.parametrize("mode", ["source_issue", "missing_check", "unknown_id", "wrong_total", "bad_crop"])
def test_verification_never_releases_genuine_or_unsupported_marking(mode):
    structure, normalized, visual = inputs([criterion(count=3)] if mode == "wrong_total" else None)

    def independent(packet, crop, mime):
        result = verify(packet, crop, mime)
        if mode == "source_issue":
            result.value.update(decision="source_issue", reason="Written source equality conflicts.")
        if mode == "missing_check":
            result.value["checks"]["explicit_instructions"] = False
        if mode == "unknown_id":
            result.value["selected_ids"][0] = "unknown"
        return result

    if mode == "bad_crop":
        with pytest.raises(ValueError, match="crop digest"):
            verify_guideline(structure, normalized, visual, load_crop=lambda _: b"different", verifier=independent)
        return
    verify_guideline(structure, normalized, visual, load_crop=lambda _: CROP, verifier=independent)
    assert not structure["questions"][0]["mark_points"]
    assert len(structure["exceptions"]) == 1


def test_verified_draft_reuses_exact_audit_without_provider_io():
    structure, normalized, visual = inputs()
    second = copy.deepcopy(structure)
    cached = verify_guideline(structure, normalized, visual, load_crop=lambda _: CROP, verifier=verify)
    reuse = verify_guideline(second, normalized, visual, load_crop=lambda _: pytest.fail("unnecessary source I/O"),
                             verifier=None, cached=cached)
    assert second == structure
    assert "verification_calls" not in reuse["summary"]


def test_alternatives_use_the_printed_maximum_with_branch_local_step_links():
    question = {"printed_marks": 1, "visual_solution_segments": [
        {"text": "2+3=5", "interpretation_evidence_id": "e0"},
        {"text": "OR"}, {"text": "3+2=5", "interpretation_evidence_id": "e1"},
    ]}
    primary = criterion(steps=["e0"])
    alternative = {**criterion(steps=["e1"]), "alternative": 1}
    assert _eligible_scheme(question, [primary, alternative], {"e0", "e1"})
    assert not _eligible_scheme(question, [primary, {**alternative, "solution_evidence_ids": ["e0"]}], {"e0", "e1"})
    assert not _eligible_scheme(question, [primary, primary, alternative], {"e0", "e1"})


def test_credit_reconciliation_keeps_uncertain_requests_reserved():
    class Store:
        base = PBHS_URL
        objects = {
            "002-reservation.json": {"stage": "marking", "request_ceiling_nusd": 50000},
            "002-receipt.json": {"usage": {"estimated_cost_nusd": 20000}, "charged_budget_nusd": 22000},
            "003-reservation.json": {"stage": "guideline_verify", "request_ceiling_nusd": 60000},
        }

        def _request_json(self, method, path, **kwargs):
            assert method == "POST" and path == "/storage/v1/object/list/memo-files"
            return [{"name": name} for name in self.objects]

        def download_json(self, _bucket, path):
            return self.objects[path.rsplit("/", 1)[1]]

    report = reconcile_ledger(Store())
    assert report["reservations"] == 2 and report["uncertain_charges"] == 1
    assert report["priced_nusd"] == 20000 and report["accounted_upper_nusd"] == 82000
    assert report["available_worker_slots"] == 96
