from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import replace
from pathlib import Path

import pytest

from engine.src.memo_engine import phase84c_cloudflare_composite_activation as activation
from engine.src.memo_engine import provider_fabric, visual_evidence
from engine.src.memo_engine.ai_router import ProviderError
from engine.tests.test_phase84c_cloudflare_composite import _configure


FIXTURE_PATH = (
    Path(__file__).parent
    / "fixtures"
    / "phase84c9_captured_synthetic_live_response.json"
)
STAGE_V_DIGEST = "b0779e3015ffedd734170e5ab56c6c137486fffe473f95394bd0e984bc104387"
STAGE_S_DIGEST = "346d03614a263d46975534851afa851f7884ab3da674367a678d0f0f6b0e5074"
RELATION = "Venn diagram with two overlapping circles"


def _fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _request(checkpoint=None):
    return replace(
        activation._request(activation.synthetic_composite_fixture()),
        provider_checkpoint=checkpoint,
    )


def _replay(body=None, transcript=None):
    fixture = _fixture()
    return provider_fabric.replay_cloudflare_composite_provider_body(
        _request(),
        body or fixture["stage_s_provider_body"],
        transcript or fixture["stage_v_transcript"],
        raw_result_digest=fixture["stage_s_raw_provider_body_digest"],
    )


def _validated(result=None):
    result = result or _replay()
    return visual_evidence.validate_visual_response(
        {**result.normalized_result, "provider": "cloudflare", "model": result.model_id},
        activation._region(activation.synthetic_composite_fixture()),
    )


def _sidecar(result=None):
    result = result or _replay()
    return result.diagnostics["_private_composite_checkpoint"][
        "stage_v_relation_preservation"
    ]


def _quality(result=None):
    result = result or _replay()
    validated = _validated(result)
    evidence = " ".join(str(item.get("transcription") or "") for item in validated["evidence"])
    quality = activation.assess_preserved_composite_content(
        evidence,
        _sidecar(result),
        activation.synthetic_composite_fixture()["expected_evidence"],
    )
    quality["diagram_entry_present"] = any(
        item.get("kind") == "diagram_entry" for item in validated["evidence"]
    )
    quality["status"] = (
        "pass" if quality["status"] == "pass" and quality["diagram_entry_present"]
        else "partial"
    )
    return quality


def _forbid_calls(monkeypatch):
    monkeypatch.setattr(
        provider_fabric,
        "cloudflare_stage_v_call",
        lambda *_args, **_kwargs: pytest.fail("Stage V inference is forbidden"),
    )
    monkeypatch.setattr(
        provider_fabric,
        "cloudflare_stage_s_call",
        lambda *_args, **_kwargs: pytest.fail("Stage S inference is forbidden"),
    )


def test_captured_live_fixture_digests_and_synthetic_provenance():
    fixture = _fixture()
    assert fixture["provenance"] == "captured synthetic activation response"
    assert fixture["privacy_classification"] == "synthetic_test"
    assert hashlib.sha256(fixture["stage_v_transcript"].encode()).hexdigest() == STAGE_V_DIGEST
    assert provider_fabric._canonical_json_digest(
        fixture["stage_s_provider_body"]
    ) == STAGE_S_DIGEST


def test_exact_relation_is_preserved_when_captured_stage_s_omits_it():
    sidecar = _sidecar()
    assert sidecar["version"] == "cloudflare-stage-v-relation-preservation-v1"
    assert sidecar["relation_count"] == 1
    assert sidecar["preserved_count"] == 1
    assert sidecar["represented_by_stage_s_count"] == 0
    assert sidecar["relations"][0]["text"] == RELATION
    assert sidecar["relations"][0]["representation"] == "preserved_stage_v_sidecar"


def test_captured_live_response_reaches_content_pass_after_preservation():
    quality = _quality()
    assert quality["status"] == "pass"
    assert all(quality["recovered"].values())
    assert quality["unexpected_numbers"] == []


def test_stage_s_raw_body_remains_byte_equivalent_and_no_inference(monkeypatch):
    fixture = _fixture()
    before = provider_fabric._canonical_json_digest(fixture["stage_s_provider_body"])
    _forbid_calls(monkeypatch)
    result = _replay()
    after = provider_fabric._canonical_json_digest(fixture["stage_s_provider_body"])
    assert before == after == STAGE_S_DIGEST
    assert result.status == "success"


def test_relation_provenance_is_stage_v_without_invented_semantic_metadata():
    record = _sidecar()["relations"][0]
    assert record["source_stage"] == "stage_v"
    assert record["model"] == provider_fabric.CLOUDFLARE_COMPOSITE_VISION_MODEL
    assert record["transcript_digest"] == STAGE_V_DIGEST
    assert record["policy_version"] == "cloudflare-stage-v-relation-preservation-v1"
    assert record["source_digest"] == _request().source_digest
    assert record["crop_digest"] == _request().crop_digest
    assert "confidence" not in record
    assert "bbox" not in record
    assert "normalized_math" not in record


def test_only_exact_relation_prefix_is_preserved():
    transcript = "QUESTION: Q1.2\nMATH: 1\nTEXT: note\nLABEL: A\nrelation: lower\nRELATION: kept"
    request = _request()
    sidecar = provider_fabric.preserve_cloudflare_stage_v_relations(
        {
            "status": "success",
            "model": provider_fabric.CLOUDFLARE_COMPOSITE_VISION_MODEL,
            "source_digest": request.source_digest,
            "crop_digest": request.crop_digest,
            "prompt_version": provider_fabric.CLOUDFLARE_COMPOSITE_PROMPT_VERSION,
            "transcript": transcript,
            "transcript_digest": hashlib.sha256(transcript.encode()).hexdigest(),
        },
        {"grounding": []},
        {"evidence": []},
        request,
        provider_fabric.CLOUDFLARE_COMPOSITE_VISION_MODEL,
    )
    assert [item["text"] for item in sidecar["relations"]] == ["kept"]


def test_empty_relation_is_ignored_safely():
    transcript = "RELATION:   \nTEXT: synthetic"
    request = _request()
    sidecar = provider_fabric.preserve_cloudflare_stage_v_relations(
        {
            "status": "success",
            "model": provider_fabric.CLOUDFLARE_COMPOSITE_VISION_MODEL,
            "source_digest": request.source_digest,
            "crop_digest": request.crop_digest,
            "prompt_version": provider_fabric.CLOUDFLARE_COMPOSITE_PROMPT_VERSION,
            "transcript": transcript,
            "transcript_digest": hashlib.sha256(transcript.encode()).hexdigest(),
        },
        {"grounding": []},
        {"evidence": []},
        request,
        provider_fabric.CLOUDFLARE_COMPOSITE_VISION_MODEL,
    )
    assert sidecar["relation_count"] == 0
    assert sidecar["empty_relation_count"] == 1


def test_exact_stage_s_grounded_relation_does_not_duplicate_production_evidence():
    fixture = _fixture()
    body = copy.deepcopy(fixture["stage_s_provider_body"])
    before_count = len(body["payload"]["evidence"])
    template = copy.deepcopy(body["payload"]["evidence"][0])
    template.update({
        "kind": "diagram_entry",
        "transcription": f"RELATION: {RELATION}",
        "normalized_math": None,
        "bbox": None,
        "question_ref": None,
    })
    body["payload"]["evidence"].append(template)
    body["grounding"].append({
        "path": f"/payload/evidence/{before_count}/transcription",
        "evidence_quote": f"RELATION: {RELATION}",
    })
    result = _replay(body=body)
    sidecar = _sidecar(result)
    assert sidecar["represented_by_stage_s_count"] == 1
    assert sidecar["preserved_count"] == 0
    assert len(result.normalized_result["evidence"]) == before_count + 1


def test_explicit_stage_s_relation_contradiction_fails_closed():
    request = _request()
    transcript = _fixture()["stage_v_transcript"]
    stage_v = {
        "status": "success",
        "model": provider_fabric.CLOUDFLARE_COMPOSITE_VISION_MODEL,
        "source_digest": request.source_digest,
        "crop_digest": request.crop_digest,
        "prompt_version": provider_fabric.CLOUDFLARE_COMPOSITE_PROMPT_VERSION,
        "transcript": transcript,
        "transcript_digest": STAGE_V_DIGEST,
    }
    payload = {"evidence": [{"transcription": "Two disjoint circles"}]}
    wrapper = {"grounding": [{
        "path": "/payload/evidence/0/transcription",
        "evidence_quote": "Two disjoint circles",
    }]}
    with pytest.raises(ProviderError, match="conflicts") as caught:
        provider_fabric.preserve_cloudflare_stage_v_relations(
            stage_v,
            wrapper,
            payload,
            request,
            provider_fabric.CLOUDFLARE_COMPOSITE_VISION_MODEL,
        )
    assert caught.value.code == "AI_PROVIDER_STAGE_V_RELATION_CONFLICT"


@pytest.mark.parametrize("field", ["source_digest", "crop_digest", "transcript_digest"])
def test_relation_cannot_cross_source_crop_or_transcript_identity(field):
    request = _request()
    transcript = _fixture()["stage_v_transcript"]
    stage_v = {
        "status": "success",
        "model": provider_fabric.CLOUDFLARE_COMPOSITE_VISION_MODEL,
        "source_digest": request.source_digest,
        "crop_digest": request.crop_digest,
        "prompt_version": provider_fabric.CLOUDFLARE_COMPOSITE_PROMPT_VERSION,
        "transcript": transcript,
        "transcript_digest": STAGE_V_DIGEST,
    }
    stage_v[field] = "different"
    with pytest.raises(ProviderError) as caught:
        provider_fabric.preserve_cloudflare_stage_v_relations(
            stage_v, {"grounding": []}, {"evidence": []}, request,
            provider_fabric.CLOUDFLARE_COMPOSITE_VISION_MODEL,
        )
    assert caught.value.code == "AI_PROVIDER_STAGE_V_RELATION_IDENTITY_INVALID"


def test_production_schema_and_slices_remain_green():
    result = _replay()
    validated = _validated(result)
    quality = _quality(result)
    assert result.diagnostics["grounding_status"] == "passed"
    assert quality["status"] == "pass"
    assert any(item["kind"] == "diagram_entry" for item in validated["evidence"])
    assert all(item["source_page_bbox"] is None for item in validated["evidence"])
    assert all(item["rendered_asset_ref"] for item in validated["evidence"])
    assert validated["mark_changes"] == []


def test_provider_result_is_v4_and_has_distinct_relation_provenance():
    result = _replay()
    checkpoint = result.diagnostics["_private_composite_checkpoint"]
    assert result.status == "success" and result.result_digest
    assert checkpoint["schema_version"] == "cloudflare-composite-v4"
    assert checkpoint["final"]["result_digest"] == result.result_digest
    assert checkpoint["final"]["relation_preservation_digest"]
    assert result.diagnostics["relation_preservation_version"] == (
        "cloudflare-stage-v-relation-preservation-v1"
    )
    assert result.diagnostics["preserved_stage_v_relation_count"] == 1


def test_stage_s_cache_reuses_across_downstream_v4_bump(monkeypatch):
    _configure(monkeypatch)
    first = _replay()
    checkpoint = copy.deepcopy(first.diagnostics["_private_composite_checkpoint"])
    checkpoint["schema_version"] = "cloudflare-composite-v3"
    checkpoint["final"] = {"status": "partial", "result_digest": "old-partial"}
    _forbid_calls(monkeypatch)
    request = _request(checkpoint)
    result = provider_fabric.cloudflare_composite_visual_adapter(
        request,
        provider_fabric.default_provider_registry()["cloudflare"],
        None,
        1,
        lambda: 0,
    )
    updated = result.diagnostics["_private_composite_checkpoint"]
    assert result.diagnostics["stage_v_cache_hit"] is True
    assert result.diagnostics["stage_s_cache_hit"] is True
    assert updated["schema_version"] == "cloudflare-composite-v4"
    assert updated["final"]["status"] == "success"
    assert updated["final"]["result_digest"] != "old-partial"


def test_exact_cache_replay_uses_zero_provider_calls_and_same_digest(monkeypatch):
    _configure(monkeypatch)
    first = _replay()
    _forbid_calls(monkeypatch)
    replayed = provider_fabric.cloudflare_composite_visual_adapter(
        _request(first.diagnostics["_private_composite_checkpoint"]),
        provider_fabric.default_provider_registry()["cloudflare"],
        None,
        1,
        lambda: 0,
    )
    assert replayed.result_digest == first.result_digest
    assert replayed.diagnostics["stage_v_cache_hit"] is True
    assert replayed.diagnostics["stage_s_cache_hit"] is True


def test_groq_unavailable_routes_to_cached_cloudflare_without_provider_calls(monkeypatch):
    _configure(monkeypatch)
    first = _replay()
    _forbid_calls(monkeypatch)
    request = _request(first.diagnostics["_private_composite_checkpoint"])
    registry = provider_fabric.default_provider_registry()
    groq = replace(registry["groq"], enabled=True, priority=0)
    cloudflare = replace(registry["cloudflare"], enabled=True, priority=1)

    def unavailable(*_args, **_kwargs):
        raise ProviderError(
            "AI_PROVIDER_TEST_UNAVAILABLE",
            "Synthetic Groq unavailable.",
            category="transient_capacity",
        )

    routed = provider_fabric.ProviderFabric(
        registry={"groq": groq, "cloudflare": cloudflare},
        adapters={
            "groq": unavailable,
            "cloudflare": provider_fabric.cloudflare_composite_visual_adapter,
        },
        env={
            "GROQ_API_KEY": "synthetic-unavailable",
            "GROQ_ZERO_COST_CONFIRMED": "true",
            "CLOUDFLARE_ACCOUNT_ID": "a" * 32,
            "CLOUDFLARE_AI_API_TOKEN": "configured",
            "CLOUDFLARE_ZERO_COST_CONFIRMED": "true",
        },
    ).route(request, deadline_monotonic=None, remaining_requests=1)
    assert routed.provider_id == "cloudflare"
    assert routed.result_digest == first.result_digest
    assert any(
        item["provider"] == "groq" and item["status"] == "failed"
        for item in routed.route_attempts
    )


def test_fixture_contains_no_secret_or_production_markers():
    serialized = FIXTURE_PATH.read_text(encoding="utf-8")
    assert not re.search(
        r"authorization|bearer\s|api[_-]?key|account[_-]?id|sb_secret_|service_role|signed[_-]?url|data:image",
        serialized,
        re.I,
    )
