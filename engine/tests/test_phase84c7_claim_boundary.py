from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from engine.src.memo_engine import phase84c_cloudflare_composite_activation as activation
from engine.src.memo_engine import provider_fabric, visual_evidence
from engine.src.memo_engine.ai_router import ProviderError
from engine.tests.test_phase84c_cloudflare_composite import _request


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "phase84c7_captured_synthetic_activation.json"
EXPECTED_RAW_DIGEST = "fb20d8ab21b9dacda3140609d636c7c06d7a40b9d32f8c2384acb6eb5d24d41f"
EXPECTED_STAGE_V_DIGEST = "b0779e3015ffedd734170e5ab56c6c137486fffe473f95394bd0e984bc104387"


def _fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _synthetic_request():
    return replace(_request(), privacy_classification=provider_fabric.PRIVACY_SYNTHETIC_TEST)


def _replay():
    fixture = _fixture()
    return provider_fabric.replay_cloudflare_composite_provider_body(
        _synthetic_request(),
        fixture["provider_body"],
        fixture["transcript"],
        raw_result_digest=fixture["raw_provider_body_digest"],
    )


def _validated_replay() -> dict:
    result = _replay()
    return visual_evidence.validate_visual_response(
        {
            **result.normalized_result,
            "provider": "cloudflare",
            "model": result.model_id,
        },
        activation._region(activation.synthetic_composite_fixture()),
    )


def test_captured_synthetic_fixture_has_verified_private_artifact_identity():
    fixture = _fixture()
    assert fixture["provenance"] == "captured synthetic activation shape"
    assert fixture["privacy_classification"] == "synthetic_test"
    assert fixture["raw_provider_body_digest"] == EXPECTED_RAW_DIGEST
    assert fixture["stage_v_transcript_digest"] == EXPECTED_STAGE_V_DIGEST
    assert hashlib.sha256(fixture["transcript"].encode()).hexdigest() == EXPECTED_STAGE_V_DIGEST
    assert provider_fabric._canonical_json_digest(fixture["provider_body"]) == EXPECTED_RAW_DIGEST


def test_old_contract_failure_ladder_reproduces_unknown_and_missing_coverage():
    ladder = provider_fabric.cloudflare_captured_body_failure_ladder(
        _fixture()["provider_body"]
    )
    assert ladder["raw_populated_leaf_count"] == 60
    assert ladder["raw_content_bearing_count"] == 40
    assert ladder["raw_supplied_grounding_count"] == 7
    assert ladder["unknown_paths"] == [
        "/payload/mark_changes/0/prinited_value"
    ]
    assert len(ladder["missing_after_unknown_path_ignored"]) == 34
    assert len(ladder["missing_after_unique_pointer_repair"]) == 33
    assert len(ladder["unavailable_bbox_paths"]) == 24
    assert len(ladder["model_question_ref_paths_with_q_prefix"]) == 6
    assert ladder["no_op_mark_change_count"] == 1


def test_claim_boundary_reduces_grounding_to_actual_transcription_claims():
    fixture = _fixture()
    prepared, audit = provider_fabric.prepare_cloudflare_composite_provider_body(
        fixture["provider_body"], _synthetic_request()
    )
    assert audit == {
        "version": "cloudflare-composite-claim-boundary-v1",
        "grounding_policy_version": "cloudflare-grounding-policy-v3",
        "pointer_normalization_version": "cloudflare-grounding-pointer-normalizer-v1",
        "pointer_normalization_applied": [],
        "unsupported_model_bbox_discarded_count": 6,
        "model_question_ref_discarded_count": 6,
        "model_normalized_math_discarded_count": 5,
        "no_op_mark_changes_discarded_count": 1,
        "raw_populated_leaf_count": 60,
        "raw_content_bearing_count": 40,
        "raw_supplied_grounding_count": 7,
        "sanitized_populated_leaf_count": 23,
        "sanitized_content_bearing_count": 5,
        "sanitized_supplied_grounding_count": 5,
        "accepted_grounding_count": 5,
        "removed_or_application_derived_grounding_count": 2,
        "missing_grounding_count": 0,
        "unknown_grounding_count": 0,
    }
    assert all(
        row["path"].endswith("/transcription") for row in prepared["grounding"]
    )


def test_non_null_model_bboxes_are_discarded_before_production():
    prepared, audit = provider_fabric.prepare_cloudflare_composite_provider_body(
        _fixture()["provider_body"], _synthetic_request()
    )
    assert audit["unsupported_model_bbox_discarded_count"] == 6
    assert all(item["bbox"] is None for item in prepared["payload"]["evidence"])
    assert all(item["source_page_bbox"] is None for item in _validated_replay()["evidence"])


def test_q_prefixed_model_refs_are_replaced_by_deterministic_anchor_ownership():
    prepared, _audit = provider_fabric.prepare_cloudflare_composite_provider_body(
        _fixture()["provider_body"], _synthetic_request()
    )
    assert all(item["question_ref"] is None for item in prepared["payload"]["evidence"])
    validated = _validated_replay()
    assert {item["owned_question_ref"] for item in validated["evidence"]} == {"1.2"}
    assert {item["association_status"] for item in validated["evidence"]} == {"owned"}


def test_model_cannot_reassign_anchored_content_to_neighbor_question():
    body = copy.deepcopy(_fixture()["provider_body"])
    for item in body["payload"]["evidence"]:
        item["question_ref"] = "9.9"
    fixture = _fixture()
    result = provider_fabric.replay_cloudflare_composite_provider_body(
        _synthetic_request(), body, fixture["transcript"]
    )
    validated = visual_evidence.validate_visual_response(
        {**result.normalized_result, "provider": "cloudflare", "model": result.model_id},
        activation._region(activation.synthetic_composite_fixture()),
    )
    assert {item["owned_question_ref"] for item in validated["evidence"]} == {"1.2"}
    assert all(item["question_ref"] is None for item in validated["evidence"])


def test_model_normalized_math_is_not_a_second_composite_claim():
    result = _replay()
    assert all(item["normalized_math"] is None for item in result.normalized_result["evidence"])
    assert result.diagnostics["claim_boundary"]["model_normalized_math_discarded_count"] == 5


def test_visual_content_present_is_derived_from_surviving_content():
    body = copy.deepcopy(_fixture()["provider_body"])
    body["payload"]["visual_content_present"] = False
    prepared, _audit = provider_fabric.prepare_cloudflare_composite_provider_body(
        body, _synthetic_request()
    )
    assert prepared["payload"]["visual_content_present"] is True
    body["payload"]["evidence"] = []
    body["payload"]["mark_changes"] = []
    prepared, _audit = provider_fabric.prepare_cloudflare_composite_provider_body(
        body, _synthetic_request()
    )
    assert prepared["payload"]["visual_content_present"] is False


def test_zero_delta_mark_change_and_diagram_number_do_not_survive():
    result = _replay()
    assert result.normalized_result["mark_changes"] == []
    assert result.diagnostics["claim_boundary"]["no_op_mark_changes_discarded_count"] == 1
    assert any("3" in item["transcription"] for item in result.normalized_result["evidence"])


def test_actual_differing_mark_change_still_requires_complete_grounding():
    fixture = _fixture()
    body = copy.deepcopy(fixture["provider_body"])
    body["payload"]["mark_changes"][0]["printed_value"] = 2
    with pytest.raises(ProviderError) as caught:
        provider_fabric.replay_cloudflare_composite_provider_body(
            _synthetic_request(), body, fixture["transcript"]
        )
    assert caught.value.code == "AI_PROVIDER_GROUNDING_UNSUPPORTED_NUMBER"
    assert caught.value.diagnostics["grounding_path"] == "/payload/mark_changes/0/printed_value"


def test_unique_final_leaf_typo_repairs_under_exact_parent_and_index():
    body = copy.deepcopy(_fixture()["provider_body"])
    normalized, audit = provider_fabric.normalize_cloudflare_grounding_pointers(body)
    assert audit["applied"] == [{
        "original_schema_path": "/payload/mark_changes/0/prinited_value",
        "canonical_schema_path": "/payload/mark_changes/0/printed_value",
    }]
    assert any(
        row["path"] == "/payload/mark_changes/0/printed_value"
        for row in normalized["grounding"]
    )


@pytest.mark.parametrize("path", [
    "/payload/mark_changes/1/prinited_value",
    "/payload/evidence/0/prinited_value",
    "/payload/mark_changes/0/prnted_vlue",
    "/payload/mark_changes/0/original_value",
])
def test_pointer_normalizer_refuses_wrong_index_parent_two_edits_and_synonym(path):
    body = copy.deepcopy(_fixture()["provider_body"])
    row = next(
        item for item in body["grounding"]
        if item["path"] == "/payload/mark_changes/0/prinited_value"
    )
    row["path"] = path
    normalized, audit = provider_fabric.normalize_cloudflare_grounding_pointers(body)
    assert audit["applied"] == []
    assert any(item["path"] == path for item in normalized["grounding"])


def test_pointer_normalizer_refuses_ambiguous_one_edit_leaf():
    body = {
        "payload": {"object": {"printed": 1, "painted": 2}},
        "grounding": [{"path": "/payload/object/pinted", "evidence_quote": "synthetic"}],
    }
    normalized, audit = provider_fabric.normalize_cloudflare_grounding_pointers(body)
    assert audit["applied"] == []
    assert normalized == body


def test_application_owned_paths_do_not_require_grounding_but_future_fields_do():
    result = _replay()
    requirements = provider_fabric.enumerate_cloudflare_content_paths(
        result.normalized_result
    )
    assert "/payload/visual_content_present" not in requirements
    assert not any("/bbox/" in path for path in requirements)
    assert not any(path.endswith("/question_ref") for path in requirements)
    payload = copy.deepcopy(result.normalized_result)
    payload["future_claim"] = "synthetic"
    assert "/payload/future_claim" in provider_fabric.enumerate_cloudflare_content_paths(payload)


def test_five_captured_transcription_grounding_rows_remain_byte_identical():
    fixture = _fixture()
    original = [
        row for row in fixture["provider_body"]["grounding"]
        if row["path"].endswith("/transcription")
    ]
    prepared, _audit = provider_fabric.prepare_cloudflare_composite_provider_body(
        fixture["provider_body"], _synthetic_request()
    )
    assert len(original) == 5
    assert prepared["grounding"] == original


def test_captured_replay_passes_all_grounding_and_production_gates():
    result = _replay()
    assert result.status == "success"
    assert result.diagnostics["grounding_status"] == "passed"
    assert result.result_digest
    validated = _validated_replay()
    assert len(validated["evidence"]) == 5
    assert not validated["mark_changes"]
    assert any(item["kind"] == "diagram_entry" for item in validated["evidence"])
    assert all(item["rendered_asset_ref"] for item in validated["evidence"])


def test_replay_provenance_retains_both_stage_and_assembled_digests():
    result = _replay()
    assert result.diagnostics["vision_transcript_digest"] == EXPECTED_STAGE_V_DIGEST
    assert result.diagnostics["structurer_raw_result_digest"] == EXPECTED_RAW_DIGEST
    assert result.diagnostics["assembled_wrapper_digest"]
    checkpoint = result.diagnostics["_private_composite_checkpoint"]
    assert checkpoint["schema_version"] == "cloudflare-composite-v3"
    assert checkpoint["final"]["result_digest"] == result.result_digest


def test_offline_replay_makes_no_provider_call(monkeypatch):
    monkeypatch.setattr(
        provider_fabric, "cloudflare_stage_v_call",
        lambda *_args, **_kwargs: pytest.fail("Stage V network call forbidden"),
    )
    monkeypatch.setattr(
        provider_fabric, "cloudflare_stage_s_call",
        lambda *_args, **_kwargs: pytest.fail("Stage S network call forbidden"),
    )
    assert _replay().status == "success"
