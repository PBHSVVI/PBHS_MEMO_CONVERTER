from __future__ import annotations

import json
import hashlib
import subprocess
import tempfile
from dataclasses import replace
from pathlib import Path

import pytest

from engine.src.memo_engine import phase84c_cloudflare_composite_activation as activation
from engine.src.memo_engine import provider_fabric
from engine.tests.test_phase84c_cloudflare_composite import (
    TRANSCRIPT,
    _configure,
    _provider_body,
    _stage_s,
    _stage_v,
)


def _discovery() -> dict:
    return {
        "schema": activation.REPORT_SCHEMA,
        "discovery_only": True,
        "http_status": 200,
        "account_visible_model_count": 73,
        "vision_model": provider_fabric.CLOUDFLARE_COMPOSITE_VISION_MODEL,
        "vision_model_visible": True,
        "structurer_model": provider_fabric.CLOUDFLARE_PREFERRED_STRUCTURER_MODEL,
        "structurer_model_visible": True,
        "structurer_active": True,
        "structurer_free_only": True,
        "agreement_calls": 0,
        "inference_calls": 0,
    }


def test_stage_v_fixture_quality_requires_equation_labels_and_relation():
    expected = activation.synthetic_composite_fixture()["expected_evidence"]
    passed = activation.assess_stage_v_transcript(TRANSCRIPT, expected)
    partial = activation.assess_stage_v_transcript("MATH: 10/250 = 1/25", expected)
    assert passed["status"] == "pass"
    assert passed["unexpected_numbers"] == []
    assert partial["status"] == "partial"


def test_stage_v_fixture_quality_allows_visible_two_circle_cardinality():
    expected = activation.synthetic_composite_fixture()["expected_evidence"]
    transcript = TRANSCRIPT + "\nRELATION: 2 circles overlap."
    result = activation.assess_stage_v_transcript(transcript, expected)
    assert result["status"] == "pass"
    assert result["unexpected_numbers"] == []


def test_stage_v_cardinality_is_not_globally_allowed():
    expected = {
        **activation.synthetic_composite_fixture()["expected_evidence"],
        "visible_numeric_tokens": ["10", "250", "1", "25", "0.04", "4", "1.2", "3"],
        "spatial_cardinalities": [],
    }
    transcript = TRANSCRIPT + "\nRELATION: 2 circles overlap."
    result = activation.assess_stage_v_transcript(transcript, expected)
    assert result["status"] == "partial"
    assert result["unexpected_numbers"] == ["2"]


def test_discovery_intersects_visibility_and_current_production_allowlists(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setattr(activation, "list_account_models", lambda _account: ([
        {"id": provider_fabric.CLOUDFLARE_COMPOSITE_VISION_MODEL},
        {"id": provider_fabric.CLOUDFLARE_PREFERRED_STRUCTURER_MODEL},
        {"id": "@cf/example/preview-only"},
    ], 73, 200))
    result = activation.discover()
    assert result["vision_model"] == provider_fabric.CLOUDFLARE_COMPOSITE_VISION_MODEL
    assert result["structurer_model"] == provider_fabric.CLOUDFLARE_PREFERRED_STRUCTURER_MODEL
    assert result["agreement_calls"] == 0 and result["inference_calls"] == 0


def test_unusable_stage_v_stops_before_stage_s(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setattr(activation, "discover", _discovery)
    monkeypatch.setattr(
        provider_fabric,
        "cloudflare_stage_v_call",
        lambda *_args: {**_stage_v(), "transcript": "UNCERTAIN: unreadable"},
    )
    stage_s_calls = []
    monkeypatch.setattr(
        provider_fabric, "cloudflare_stage_s_call",
        lambda *_args: stage_s_calls.append(1),
    )
    report = activation.run()
    assert report["inference_calls"] == 1
    assert stage_s_calls == []
    assert report["stage_v"]["status"] in {"partial", "fail"}


def test_mocked_live_success_proves_both_stage_cache_and_failover(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setattr(activation, "discover", _discovery)
    calls = {"v": 0, "s": 0}

    def stage_v(*args):
        calls["v"] += 1
        return _stage_v(*args)

    def stage_s(*args):
        calls["s"] += 1
        return _stage_s(*args)

    monkeypatch.setattr(provider_fabric, "cloudflare_stage_v_call", stage_v)
    monkeypatch.setattr(provider_fabric, "cloudflare_stage_s_call", stage_s)
    report = activation.run()
    assert calls == {"v": 1, "s": 1}
    assert report["status"] == "passed"
    assert report["cache_replay"]["passed"] is True
    assert report["failover"]["passed"] is True
    assert report["inference_calls"] == 2
    assert report["grounding"] == {
        "status": "passed",
        "expected_content_path_count": 5,
        "supplied_grounding_path_count": 5,
        "valid_grounding_path_count": 5,
        "missing_paths": [],
        "unknown_paths": [],
        "duplicate_paths": [],
        "conflicting_duplicate_paths": [],
        "quote_validation": "passed",
        "numeric_grounding": "passed",
        "label_grounding": "passed",
        "relationship_grounding": "passed",
        "question_solution_protection": "passed",
    }
    assert report["provider_result"]["result_digest"]


def test_activation_source_has_no_agreement_request():
    source = Path(activation.__file__).read_text(encoding="utf-8")
    assert "accept_meta_terms" not in source
    assert ('"prompt"' + ': "agree"') not in source
    assert "previews.developers.cloudflare.com" not in source


def test_sanitized_report_does_not_contain_transcript_or_image(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setattr(activation, "discover", _discovery)
    monkeypatch.setattr(provider_fabric, "cloudflare_stage_v_call", _stage_v)
    monkeypatch.setattr(provider_fabric, "cloudflare_stage_s_call", _stage_s)
    serialized = json.dumps(activation.run(), sort_keys=True)
    assert TRANSCRIPT not in serialized
    assert "data:image" not in serialized


def test_private_stage_v_persistence_is_synthetic_only(tmp_path):
    fixture = activation.synthetic_composite_fixture()
    request = activation._request(fixture)
    request = replace(
        request, privacy_classification=provider_fabric.PRIVACY_SCHOOL_PRIVATE
    )
    with pytest.raises(RuntimeError, match="REQUIRES_SYNTHETIC_TEST"):
        activation.persist_synthetic_stage_v_checkpoint(
            tmp_path / "checkpoint.json",
            request=request,
            fixture=fixture,
            model=provider_fabric.CLOUDFLARE_COMPOSITE_VISION_MODEL,
            live=_stage_v(),
        )


def test_stage_v_checkpoint_survives_and_reuses_without_second_call(monkeypatch, tmp_path):
    _configure(monkeypatch)
    monkeypatch.setattr(activation, "discover", _discovery)
    path = tmp_path / "private-stage-v.json"
    monkeypatch.setenv("PHASE84C_STAGE_V_CHECKPOINT_PATH", str(path))
    calls = []

    def stage_v(*args):
        calls.append(1)
        return _stage_v(*args)

    monkeypatch.setattr(provider_fabric, "cloudflare_stage_v_call", stage_v)
    first = activation.run_stage_v()
    assert first["checkpoint_persisted"] is True
    assert first["checkpoint_readback_verified"] is True
    assert first["checkpoint_reused"] is False
    assert calls == [1]

    monkeypatch.setattr(
        provider_fabric,
        "cloudflare_stage_v_call",
        lambda *_args: pytest.fail("durable synthetic checkpoint must avoid inference"),
    )
    second = activation.run_stage_v()
    assert second["checkpoint_reused"] is True
    assert second["inference_calls"] == 0


def test_legacy_v2_stage_v_checkpoint_reuses_after_composite_v3_bump(
    monkeypatch, tmp_path
):
    _configure(monkeypatch)
    monkeypatch.setattr(activation, "discover", _discovery)
    path = tmp_path / "private-stage-v.json"
    monkeypatch.setenv("PHASE84C_STAGE_V_CHECKPOINT_PATH", str(path))
    monkeypatch.setenv("PHASE84C_REQUIRE_STAGE_V_REUSE", "true")
    fixture = activation.synthetic_composite_fixture()
    request = activation._request(fixture)
    activation.persist_synthetic_stage_v_checkpoint(
        path,
        request=request,
        fixture=fixture,
        model=provider_fabric.CLOUDFLARE_COMPOSITE_VISION_MODEL,
        live=_stage_v(),
    )
    artifact = json.loads(path.read_text(encoding="utf-8"))
    artifact["schema_version"] = "cloudflare-composite-v2"
    path.write_text(json.dumps(artifact), encoding="utf-8")
    loaded = activation.load_synthetic_stage_v_checkpoint(
        path,
        fixture=fixture,
        model=provider_fabric.CLOUDFLARE_COMPOSITE_VISION_MODEL,
    )
    assert loaded["stage_v_artifact_schema_version"] == "cloudflare-composite-v2"
    assert loaded["schema_version"] == "cloudflare-composite-v4"
    monkeypatch.setattr(
        provider_fabric,
        "cloudflare_stage_v_call",
        lambda *_args: pytest.fail("legacy durable checkpoint must avoid inference"),
    )

    report = activation.run_stage_v()

    assert report["checkpoint_reused"] is True
    assert report["inference_calls"] == 0


def test_stage_v_checkpoint_requires_all_identity_fields(monkeypatch, tmp_path):
    _configure(monkeypatch)
    monkeypatch.setattr(activation, "discover", _discovery)
    path = tmp_path / "private-stage-v.json"
    monkeypatch.setenv("PHASE84C_STAGE_V_CHECKPOINT_PATH", str(path))
    monkeypatch.setattr(provider_fabric, "cloudflare_stage_v_call", _stage_v)
    activation.run_stage_v()
    artifact = json.loads(path.read_text(encoding="utf-8"))
    artifact["fixture_id"] = "different-fixture"
    path.write_text(json.dumps(artifact), encoding="utf-8")
    with pytest.raises(RuntimeError, match="IDENTITY_MISMATCH"):
        activation.load_synthetic_stage_v_checkpoint(
            path,
            fixture=activation.synthetic_composite_fixture(),
            model=provider_fabric.CLOUDFLARE_COMPOSITE_VISION_MODEL,
        )


def test_authorized_cached_stage_s_proof_refuses_new_stage_v_call(monkeypatch, tmp_path):
    _configure(monkeypatch)
    monkeypatch.setattr(activation, "discover", _discovery)
    monkeypatch.setenv(
        "PHASE84C_STAGE_V_CHECKPOINT_PATH", str(tmp_path / "missing.json")
    )
    monkeypatch.setenv("PHASE84C_REQUIRE_STAGE_V_REUSE", "true")
    monkeypatch.setattr(
        provider_fabric,
        "cloudflare_stage_v_call",
        lambda *_args: pytest.fail("Stage V inference is not authorized"),
    )
    with pytest.raises(RuntimeError, match="STAGE_V_DURABLE_REUSE_FAILED"):
        activation.run_stage_v()


def test_private_stage_s_provider_body_artifact_is_synthetic_only():
    fixture = activation.synthetic_composite_fixture()
    request = activation._request(fixture)
    body = _provider_body()
    digest = hashlib.sha256(json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")).hexdigest()
    private_root = Path.cwd() / "provisioning-private"
    private_root.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=private_root) as directory:
        path = Path(directory) / "private-stage-s.json"
        artifact = activation.persist_synthetic_stage_s_provider_body(
            path,
            request=request,
            fixture_id=fixture["id"],
            model=provider_fabric.CLOUDFLARE_PREFERRED_STRUCTURER_MODEL,
            transcript_digest="synthetic-transcript-digest",
            provider_body=body,
            raw_result_digest=digest,
        )
        assert path.exists()
        assert subprocess.run(
            ["git", "check-ignore", "-q", str(path)],
            cwd=Path.cwd(), check=False,
        ).returncode == 0
        assert artifact["raw_provider_body_digest"] == digest
        assert artifact["raw_provider_body"] == body
        assert artifact["privacy_classification"] == provider_fabric.PRIVACY_SYNTHETIC_TEST
        serialized = json.dumps(artifact).lower()
        assert all(marker not in serialized for marker in (
            "authorization", "api_key", "sb_secret_", "service_role", "data:image"
        ))


def test_private_stage_s_provider_body_refuses_school_private(tmp_path):
    fixture = activation.synthetic_composite_fixture()
    request = replace(
        activation._request(fixture),
        privacy_classification=provider_fabric.PRIVACY_SCHOOL_PRIVATE,
    )
    body = _provider_body()
    digest = hashlib.sha256(json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")).hexdigest()
    with pytest.raises(RuntimeError, match="REQUIRES_SYNTHETIC_TEST"):
        activation.persist_synthetic_stage_s_provider_body(
            tmp_path / "must-not-exist.json",
            request=request,
            fixture_id=fixture["id"],
            model=provider_fabric.CLOUDFLARE_PREFERRED_STRUCTURER_MODEL,
            transcript_digest="synthetic-transcript-digest",
            provider_body=body,
            raw_result_digest=digest,
        )
    assert not (tmp_path / "must-not-exist.json").exists()


def test_synthetic_internal_failure_persists_private_body_but_sanitizes_report(
    monkeypatch, tmp_path
):
    _configure(monkeypatch)
    monkeypatch.setattr(activation, "discover", _discovery)
    monkeypatch.setattr(provider_fabric, "cloudflare_stage_v_call", _stage_v)
    body = _provider_body()
    rejected_value = "semantic_synonym_never_log"
    body["payload"]["evidence"][0]["kind"] = rejected_value
    raw_digest = hashlib.sha256(json.dumps(
        body, sort_keys=True, separators=(",", ":")
    ).encode()).hexdigest()
    monkeypatch.setattr(
        provider_fabric,
        "cloudflare_stage_s_call",
        lambda *_args: {
            **_stage_s(), "provider_body": body, "raw_result_digest": raw_digest,
        },
    )
    artifact_path = tmp_path / "private-stage-s.json"
    monkeypatch.setenv("PHASE84C_STAGE_S_PROVIDER_BODY_PATH", str(artifact_path))
    report = activation.run()
    assert report["status"] == "failed"
    assert report["stage_s"]["private_diagnostic_artifact_persisted"] is True
    assert report["stage_s"]["enum_normalization_attempted"] is True
    assert report["stage_s"]["enum_normalization_applied_count"] == 0
    assert rejected_value not in json.dumps(report)
    private = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert private["raw_provider_body_digest"] == raw_digest
    assert private["raw_provider_body"]["payload"]["evidence"][0]["kind"] == rejected_value
