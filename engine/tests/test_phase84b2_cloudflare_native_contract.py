import json
from dataclasses import replace

import pytest

from engine.src.memo_engine import provider_fabric
from engine.src.memo_engine.ai_router import ProviderError
from engine.src.memo_engine.provider_fabric import PRIVACY_SYNTHETIC_TEST
from engine.tests.test_phase84a_provider_fabric import _normalized_result, _request, _spec


def _native_payload(response, *, usage=None):
    return {
        "result": {"response": response, "usage": usage or {}},
        "success": True,
        "errors": [],
        "messages": [],
    }


def _run_cloudflare(monkeypatch, payload):
    calls = []

    def fake_post(url, headers, body, **_kwargs):
        calls.append((url, headers, body))
        return payload, 7

    monkeypatch.setattr(provider_fabric, "_post_json", fake_post)
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "account")
    monkeypatch.setenv("CLOUDFLARE_AI_API_TOKEN", "token")
    request = _request(PRIVACY_SYNTHETIC_TEST)
    result = provider_fabric.cloudflare_visual_adapter(
        request,
        replace(_spec("cloudflare", 0), model_id="@cf/google/gemma-4-26b-a4b-it"),
        None,
        1,
        lambda: 0,
    )
    return result, calls, request


def test_cloudflare_sends_native_schema_and_keeps_multimodal_data_uri(monkeypatch):
    result, calls, request = _run_cloudflare(
        monkeypatch, _native_payload(json.dumps(_normalized_result(1)))
    )
    body = calls[0][2]
    assert body["response_format"] == {
        "type": "json_schema",
        "json_schema": request.response_schema,
    }
    assert "name" not in body["response_format"]["json_schema"]
    assert "strict" not in body["response_format"]["json_schema"]
    assert body["messages"][0]["content"][0] == {"type": "text", "text": request.prompt}
    image_part = body["messages"][0]["content"][1]
    assert image_part["type"] == "image_url"
    assert image_part["image_url"]["url"].startswith("data:image/png;base64,")
    assert result.normalized_result == _normalized_result(1)


def test_cloudflare_native_string_response_and_usage_normalize(monkeypatch):
    result, _, _ = _run_cloudflare(
        monkeypatch,
        _native_payload(json.dumps(_normalized_result(1)), usage={"total_tokens": 19}),
    )
    assert result.status == "success"
    assert result.normalized_result == _normalized_result(1)
    assert result.usage == {"total_tokens": 19}
    assert result.diagnostics == {
        "provider_success": True,
        "result_exists": True,
        "result_keys": ["response", "usage"],
        "response_type": "str",
        "response_path": "result.response",
        "normalization_stage": "complete",
    }


def test_cloudflare_native_object_response_normalizes(monkeypatch):
    result, _, _ = _run_cloudflare(monkeypatch, _native_payload(_normalized_result(1)))
    assert result.normalized_result == _normalized_result(1)


def test_cloudflare_observed_native_envelope_with_choices_normalizes(monkeypatch):
    payload = {
        "result": {
            "id": "safe-id",
            "object": "chat.completion",
            "created": 1,
            "model": "@cf/google/gemma-4-26b-a4b-it",
            "choices": [{
                "message": {"content": json.dumps(_normalized_result(1))},
            }],
            "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
        },
        "success": True,
        "errors": [],
        "messages": [],
    }
    result, _, _ = _run_cloudflare(monkeypatch, payload)
    assert result.normalized_result == _normalized_result(1)
    assert result.usage["total_tokens"] == 18
    assert result.diagnostics["response_path"] == "result.choices[0].message.content"
    assert result.diagnostics["response_type"] == "str"


@pytest.mark.parametrize("response", ["not-json", [], [1], 3, True, None])
def test_cloudflare_invalid_or_nonobject_response_is_rejected(monkeypatch, response):
    with pytest.raises(ProviderError) as caught:
        _run_cloudflare(monkeypatch, _native_payload(response))
    assert caught.value.code == "AI_PROVIDER_INVALID_RESPONSE"
    assert caught.value.category == "permanent_schema"


def test_cloudflare_success_false_maps_to_provider_error(monkeypatch):
    payload = {
        "result": None,
        "success": False,
        "errors": [{"code": 3030, "message": "Model unavailable"}],
        "messages": [],
    }
    with pytest.raises(ProviderError) as caught:
        _run_cloudflare(monkeypatch, payload)
    assert caught.value.code == "AI_PROVIDER_CLOUDFLARE_ERROR"
    assert caught.value.category == "permanent_provider"
    assert caught.value.provider_code == 3030
    assert caught.value.provider_message == "Model unavailable"
    assert caught.value.diagnostics == {
        "provider_success": False,
        "result_exists": False,
        "result_keys": [],
        "response_type": None,
        "response_path": None,
        "normalization_stage": "cloudflare_native_envelope",
    }


def test_openai_shaped_groq_and_mistral_parsing_is_unchanged(monkeypatch):
    calls = []

    def fake_post(url, headers, body, **_kwargs):
        calls.append(body)
        return {
            "choices": [{"message": {"content": json.dumps(_normalized_result(1))}}],
            "usage": {"total_tokens": 5},
        }, 4

    monkeypatch.setattr(provider_fabric, "_post_json", fake_post)
    monkeypatch.setenv("GROQ_API_KEY", "token")
    monkeypatch.setenv("MISTRAL_API_KEY", "token")
    request = _request(PRIVACY_SYNTHETIC_TEST)
    groq = provider_fabric.groq_visual_adapter(request, _spec("groq", 0), None, 1, lambda: 0)
    mistral = provider_fabric.mistral_visual_adapter(request, _spec("mistral", 0), None, 1, lambda: 0)
    assert groq.normalized_result == _normalized_result(1)
    assert mistral.normalized_result == _normalized_result(1)
    assert calls[0]["response_format"]["json_schema"]["strict"] is True
    assert calls[1]["response_format"]["json_schema"]["strict"] is True
