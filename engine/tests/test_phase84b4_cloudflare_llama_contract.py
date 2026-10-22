from __future__ import annotations

import json
import hashlib
from dataclasses import replace

import pytest

from engine.src.memo_engine import phase84b4_cloudflare_llama_activation as activation
from engine.src.memo_engine import provider_fabric
from engine.src.memo_engine.ai_router import ProviderError
from engine.src.memo_engine.provider_fabric import (
    CLOUDFLARE_LLAMA_STRUCTURED_VISION_MODEL,
    PRIVACY_SCHOOL_PRIVATE,
    PRIVACY_SYNTHETIC_TEST,
    TASK_VISUAL_INTERPRETATION,
    ProviderResult,
    cloudflare_model_capabilities,
    eligible_providers,
)
from engine.tests.test_phase84a_provider_fabric import _normalized_result, _request, _spec


def _env() -> dict[str, str]:
    return {
        "CLOUDFLARE_ACCOUNT_ID": "configured",
        "CLOUDFLARE_AI_API_TOKEN": "configured",
        "CLOUDFLARE_ZERO_COST_CONFIRMED": "true",
    }


def _llama_spec():
    return replace(
        _spec("cloudflare", 0),
        model_id=CLOUDFLARE_LLAMA_STRUCTURED_VISION_MODEL,
        capabilities=cloudflare_model_capabilities(CLOUDFLARE_LLAMA_STRUCTURED_VISION_MODEL),
        credential_names=("CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_AI_API_TOKEN"),
        free_model_ids=provider_fabric.CLOUDFLARE_FREE_VISION_MODELS,
        zero_cost_confirmation_env="CLOUDFLARE_ZERO_COST_CONFIRMED",
    )


def _run(monkeypatch, response):
    calls = []

    def fake_post(url, headers, body, **kwargs):
        calls.append({"url": url, "headers": headers, "body": body, "kwargs": kwargs})
        return response, 5

    monkeypatch.setattr(provider_fabric, "_post_json", fake_post)
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "account")
    monkeypatch.setenv("CLOUDFLARE_AI_API_TOKEN", "secret-value")
    result = provider_fabric.cloudflare_visual_adapter(
        _request(PRIVACY_SYNTHETIC_TEST), _llama_spec(), None, 1, lambda: 0
    )
    return result, calls


def test_model_capabilities_distinguish_structured_visual_from_plain_vision():
    llama = cloudflare_model_capabilities(CLOUDFLARE_LLAMA_STRUCTURED_VISION_MODEL)
    gemma = cloudflare_model_capabilities("@cf/google/gemma-4-26b-a4b-it")
    qwen = cloudflare_model_capabilities("@cf/qwen/qwen3.8-27b")
    assert {"vision", "structured_json", "structured_visual", "free_only", "school_private"} <= llama
    assert "vision" in gemma and "structured_visual" not in gemma
    assert "vision" in qwen and "structured_visual" not in qwen


def test_only_llama_is_eligible_for_cloudflare_structured_visual():
    llama = _llama_spec()
    assert eligible_providers(
        {"cloudflare": llama},
        task_type=TASK_VISUAL_INTERPRETATION,
        privacy_classification=PRIVACY_SCHOOL_PRIVATE,
        env=_env(),
    ) == [llama]
    for model in ("@cf/google/gemma-4-26b-a4b-it", "@cf/qwen/qwen3.8-27b"):
        spec = replace(llama, model_id=model, capabilities=cloudflare_model_capabilities(model))
        assert eligible_providers(
            {"cloudflare": spec},
            task_type=TASK_VISUAL_INTERPRETATION,
            privacy_classification=PRIVACY_SCHOOL_PRIVATE,
            env=_env(),
        ) == []


def test_llama_uses_top_level_data_uri_raw_schema_and_nonstreaming(monkeypatch):
    result, calls = _run(monkeypatch, {
        "result": {"response": json.dumps(_normalized_result(1)), "usage": {"total_tokens": 9}},
        "success": True,
    })
    body = calls[0]["body"]
    request = _request(PRIVACY_SYNTHETIC_TEST)
    assert body["messages"] == [{"role": "user", "content": request.prompt}]
    assert body["image"].startswith("data:image/png;base64,")
    assert "secret-value" not in json.dumps(body)
    assert body["stream"] is False
    assert body["response_format"] == {
        "type": "json_schema", "json_schema": request.response_schema
    }
    assert result.status == "success"
    assert result.usage == {"total_tokens": 9}


@pytest.mark.parametrize("response_path", ["response", "choices"])
@pytest.mark.parametrize("decoded", [False, True])
def test_llama_native_response_variants_normalize(monkeypatch, response_path, decoded):
    content = _normalized_result(1) if decoded else json.dumps(_normalized_result(1))
    result_payload = {"usage": {"total_tokens": 11}}
    if response_path == "response":
        result_payload["response"] = content
    else:
        result_payload["choices"] = [{"message": {"content": content}}]
    result, _ = _run(monkeypatch, {"result": result_payload, "success": True})
    assert result.normalized_result == _normalized_result(1)
    assert result.usage["total_tokens"] == 11
    assert result.diagnostics["response_path"].startswith("result.")


@pytest.mark.parametrize("response", ["not-json", [], [1], 1, True, None])
def test_llama_malformed_or_nonobject_json_remains_invalid(monkeypatch, response):
    with pytest.raises(ProviderError) as caught:
        _run(monkeypatch, {"result": {"response": response}, "success": True})
    assert caught.value.code == "AI_PROVIDER_INVALID_RESPONSE"
    assert caught.value.category == "permanent_schema"


@pytest.mark.parametrize("message", ["JSON Mode couldn't be met", "JSON Mode could not be met"])
def test_documented_json_mode_unmet_fails_as_content_request(monkeypatch, message):
    with pytest.raises(ProviderError) as caught:
        _run(monkeypatch, {
            "result": None,
            "success": False,
            "errors": [{"code": 5004, "message": message}],
        })
    assert caught.value.code == "AI_PROVIDER_JSON_MODE_UNMET"
    assert caught.value.category == "content_request"
    assert caught.value.retryable is False


def test_mistral_remains_ineligible_for_school_private(monkeypatch):
    monkeypatch.setenv("MISTRAL_SCHOOL_PRIVATE_APPROVED", "false")
    monkeypatch.setenv("MEMO_CLOUDFLARE_VISION_MODEL", CLOUDFLARE_LLAMA_STRUCTURED_VISION_MODEL)
    mistral = provider_fabric.default_provider_registry()["mistral"]
    assert provider_fabric.provider_ineligibility_reason(
        mistral,
        task_type=TASK_VISUAL_INTERPRETATION,
        privacy_classification=PRIVACY_SCHOOL_PRIVATE,
        env={"MISTRAL_API_KEY": "configured", "MISTRAL_ZERO_COST_CONFIRMED": "true",
             "MISTRAL_SCHOOL_PRIVATE_APPROVED": "false"},
    ) == "model_unconfigured"


def test_non_llama_cloudflare_transport_remains_multimodal_content_parts(monkeypatch):
    calls = []

    def fake_post(url, headers, body, **kwargs):
        calls.append(body)
        return {"result": {"response": _normalized_result(1)}, "success": True}, 2

    monkeypatch.setattr(provider_fabric, "_post_json", fake_post)
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "account")
    monkeypatch.setenv("CLOUDFLARE_AI_API_TOKEN", "configured")
    provider_fabric.cloudflare_visual_adapter(
        _request(PRIVACY_SYNTHETIC_TEST),
        replace(_spec("cloudflare", 0), model_id="@cf/google/gemma-4-26b-a4b-it"),
        None, 1, lambda: 0,
    )
    assert "image" not in calls[0]
    assert calls[0]["messages"][0]["content"][1]["type"] == "image_url"


def test_terms_acceptance_is_one_bounded_agree_request(monkeypatch):
    calls = []

    def fake_post(url, headers, body, **kwargs):
        calls.append((url, headers, body, kwargs))
        return {"success": True, "result": {"response": "accepted"}}, 3

    monkeypatch.setattr(activation, "_post_json", fake_post)
    monkeypatch.setenv("CLOUDFLARE_AI_API_TOKEN", "configured")
    result = activation.accept_meta_terms("account")
    assert result == {
        "status": "accepted", "http_status": 200, "success": True, "provider_code": None
    }
    assert len(calls) == 1
    assert calls[0][2] == {"prompt": "agree"}
    assert calls[0][3]["max_rate_retries"] == 0
    assert calls[0][3]["max_transient_retries"] == 0


def test_invisible_llama_stops_before_terms_or_inference(monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "a" * 32)
    monkeypatch.setenv("CLOUDFLARE_AI_API_TOKEN", "configured")
    monkeypatch.setenv("CLOUDFLARE_ZERO_COST_CONFIRMED", "true")
    monkeypatch.setenv("MISTRAL_SCHOOL_PRIVATE_APPROVED", "false")
    monkeypatch.setattr(activation, "list_account_models", lambda _account: ([], 73, 200))
    calls = []
    monkeypatch.setattr(activation, "accept_meta_terms", lambda _account: calls.append("terms"))
    report = activation.run()
    assert report["visibility"]["visible"] is False
    assert report["run_path_requests"] == {"terms": 0, "synthetic_inference": 0, "total": 0}
    assert calls == []


def test_activation_success_persists_cache_and_proves_failover_without_second_call(monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "a" * 32)
    monkeypatch.setenv("CLOUDFLARE_AI_API_TOKEN", "configured")
    monkeypatch.setenv("CLOUDFLARE_ZERO_COST_CONFIRMED", "true")
    monkeypatch.setenv("MISTRAL_SCHOOL_PRIVATE_APPROVED", "false")
    monkeypatch.setattr(
        activation,
        "list_account_models",
        lambda _account: ([{"id": CLOUDFLARE_LLAMA_STRUCTURED_VISION_MODEL}], 73, 200),
    )
    monkeypatch.setattr(
        activation,
        "accept_meta_terms",
        lambda _account: {"status": "accepted", "http_status": 200, "success": True,
                          "provider_code": None},
    )
    calls = []
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

    def successful_adapter(request, spec, *_args):
        calls.append(request.crop_digest)
        return ProviderResult(
            provider_id="cloudflare", model_id=spec.model_id,
            task_type=request.task_type, status="success", normalized_result=normalized,
            request_attempt=1, latency_ms=4, usage={"total_tokens": 12}, quota={},
            result_digest=hashlib.sha256(json.dumps(normalized, sort_keys=True).encode()).hexdigest(),
            diagnostics={"response_path": "result.response"},
        )

    monkeypatch.setattr(activation, "cloudflare_visual_adapter", successful_adapter)
    report = activation.run()
    assert len(calls) == 1
    assert report["preflight"]["content_quality"] == "pass"
    assert report["cache_reuse"] == {
        "passed": True, "second_inference_calls": 0, "reused_success_count": 1
    }
    assert report["failover"] == {
        "passed": True, "selected_provider": "cloudflare", "extra_inference_calls": 0
    }
    assert report["run_path_requests"] == {"terms": 1, "synthetic_inference": 1, "total": 2}
