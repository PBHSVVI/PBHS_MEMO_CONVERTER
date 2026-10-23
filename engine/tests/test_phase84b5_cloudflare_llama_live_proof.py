from __future__ import annotations

import hashlib
import json

from engine.src.memo_engine import phase84b5_cloudflare_llama_live_proof as proof
from engine.src.memo_engine.provider_fabric import ProviderResult


def _configure(monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "a" * 32)
    monkeypatch.setenv("CLOUDFLARE_AI_API_TOKEN", "configured")
    monkeypatch.setenv("CLOUDFLARE_ZERO_COST_CONFIRMED", "true")
    monkeypatch.setenv("MISTRAL_SCHOOL_PRIVATE_APPROVED", "false")


def _success(request, spec, *_args):
    normalized = {
        "schema_version": "1.0",
        "page": 1,
        "visual_content_present": True,
        "evidence": [{
            "question_ref": "1.2",
            "kind": "answer_working",
            "transcription": "10/250 = 1/25 = 0.04 = 4%",
            "normalized_math": "10/250 = 1/25 = 0.04 = 4%",
            "confidence": 0.99,
            "source": "visual_overlay",
            "bbox": None,
        }],
        "mark_changes": [],
        "warnings": [],
    }
    return ProviderResult(
        provider_id="cloudflare", model_id=spec.model_id,
        task_type=request.task_type, status="success", normalized_result=normalized,
        request_attempt=1, latency_ms=4, usage={"total_tokens": 12}, quota={},
        result_digest=hashlib.sha256(json.dumps(normalized, sort_keys=True).encode()).hexdigest(),
        diagnostics={
            "provider_success": True, "result_exists": True,
            "result_keys": ["response", "usage"], "response_type": "str",
            "response_path": "result.response", "normalization_stage": "complete",
        },
    )


def test_proof_has_no_agreement_path_and_reuses_one_live_result(monkeypatch):
    _configure(monkeypatch)
    calls = []

    def counted(*args):
        calls.append(1)
        return _success(*args)

    monkeypatch.setattr(proof, "cloudflare_visual_adapter", counted)
    report = proof.run()
    assert report["agreement_calls"] == 0
    assert report["inference_calls"] == 1
    assert len(calls) == 1
    assert report["preflight"]["content_quality"] == "pass"
    assert report["checkpoint"]["persisted"] is True
    assert report["cache_reuse"] == {
        "passed": True, "second_inference_calls": 0, "reused_success_count": 1
    }
    assert report["failover"] == {
        "passed": True, "selected_provider": "cloudflare", "extra_inference_calls": 0
    }


def test_failure_stops_after_single_inference(monkeypatch):
    _configure(monkeypatch)
    calls = []

    def fail(*_args):
        calls.append(1)
        raise RuntimeError("synthetic failure")

    monkeypatch.setattr(proof, "cloudflare_visual_adapter", fail)
    report = proof.run()
    assert report["agreement_calls"] == 0
    assert report["inference_calls"] == 1
    assert len(calls) == 1
    assert report["preflight"]["status"] == "failed"
    assert report["cache_reuse"] is None


def test_source_contains_no_agreement_request():
    source = proof.Path(proof.__file__).read_text(encoding="utf-8")
    forbidden = '"prompt"' + ': "agree"'
    assert forbidden not in source
    assert "accept_meta_terms" not in source
