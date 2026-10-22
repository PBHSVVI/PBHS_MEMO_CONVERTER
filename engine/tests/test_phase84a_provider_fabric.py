from __future__ import annotations

import hashlib
import json
from dataclasses import replace

import pytest

from engine.src.memo_engine.ai_router import ProviderError
from engine.src.memo_engine import provider_fabric, visual_evidence
from engine.src.memo_engine.provider_fabric import (
    FREE_ONLY_PLAN_MODE,
    PRIVACY_SCHOOL_PRIVATE,
    PRIVACY_SYNTHETIC_TEST,
    TASK_VISUAL_INTERPRETATION,
    ProviderFabric,
    ProviderPoolExhausted,
    ProviderResult,
    ProviderSpec,
    ProviderTaskRequest,
    eligible_providers,
)


def _spec(
    provider_id: str,
    priority: int,
    *,
    school_private: bool = True,
    privacy_env: str | None = None,
    requires_paid: bool = False,
    automatic_overage: bool = False,
    enabled: bool = True,
) -> ProviderSpec:
    return ProviderSpec(
        provider_id=provider_id,
        model_id=f"{provider_id}-vision-free",
        capabilities=frozenset({"vision", "structured_json", "structured_visual"}),
        credential_names=(f"{provider_id.upper()}_KEY",),
        priority=priority,
        school_private_allowed=school_private,
        requires_explicit_privacy_approval=privacy_env is not None,
        privacy_approval_env=privacy_env,
        plan_mode=FREE_ONLY_PLAN_MODE,
        requires_paid_plan=requires_paid,
        automatic_overage_possible=automatic_overage,
        enabled=enabled,
    )


def _request(privacy: str = PRIVACY_SCHOOL_PRIVATE, region: int = 1) -> ProviderTaskRequest:
    crop = f"crop-{region}".encode()
    return ProviderTaskRequest(
        task_type=TASK_VISUAL_INTERPRETATION,
        region_id=f"region-{region}",
        current_question_owner=f"{region}.1",
        source_question=f"{region}.1",
        source_page=region,
        source_digest="source",
        crop_digest=hashlib.sha256(crop).hexdigest(),
        crop_bytes=crop,
        crop_mime_type="image/png",
        interpretation_schema_version="1.0",
        task_prompt_version="visual-evidence-v1",
        privacy_classification=privacy,
        prompt="Return structured evidence.",
        response_schema={"type": "object"},
    )


def _normalized_result(page: int) -> dict:
    return {
        "schema_version": "1.0",
        "page": page,
        "visual_content_present": False,
        "evidence": [],
        "mark_changes": [],
        "warnings": [],
    }


def _success(request: ProviderTaskRequest, spec: ProviderSpec) -> ProviderResult:
    normalized = _normalized_result(request.source_page)
    return ProviderResult(
        provider_id=spec.provider_id,
        model_id=spec.model_id,
        task_type=request.task_type,
        status="success",
        normalized_result=normalized,
        request_attempt=1,
        latency_ms=5,
        usage={"total_tokens": 20},
        quota={"remaining_requests": 10},
        result_digest=hashlib.sha256(
            json.dumps(normalized, sort_keys=True).encode()
        ).hexdigest(),
    )


def _env(*providers: str, mistral_approved: bool = False) -> dict[str, str]:
    values = {f"{provider.upper()}_KEY": "configured" for provider in providers}
    if mistral_approved:
        values["MISTRAL_PRIVATE_APPROVED"] = "true"
    return values


def _regions(count: int) -> list[dict]:
    return [
        {
            "page": index + 1,
            "question_refs": [f"{index + 1}.1"],
            "printed_text": "",
            "image_bytes": f"crop-{index + 1}".encode(),
            "mime_type": "image/png",
            "asset_path": f"internal/visual/regions/region-{index + 1}.png",
        }
        for index in range(count)
    ]


def _normalized() -> dict:
    return {
        "job_id": "fabric-job",
        "source": {"sha256": "source"},
        "content": {"pages": [{"visual_inspection_required": True}]},
    }


def test_21_regions_fail_over_from_groq_to_cloudflare_without_review_flood(monkeypatch):
    monkeypatch.setattr(visual_evidence, "_render_regions", lambda *_: _regions(21))
    registry = {"groq": _spec("groq", 0), "cloudflare": _spec("cloudflare", 1)}
    calls = {"groq": [], "cloudflare": []}

    def groq(request, spec, *_args):
        calls["groq"].append(request.region_id)
        if request.region_id == "internal/visual/regions/region-2.png":
            raise ProviderError(
                "AI_PROVIDER_RATE_LIMITED", "capacity", retry_after_seconds=120,
                category="transient_capacity", http_status=429,
            )
        return _success(request, spec)

    def cloudflare(request, spec, *_args):
        calls["cloudflare"].append(request.region_id)
        return _success(request, spec)

    fabric = ProviderFabric(
        registry=registry,
        adapters={"groq": groq, "cloudflare": cloudflare},
        env=_env("groq", "cloudflare"),
    )
    record, _ = visual_evidence.extract_visual_evidence(
        b"source", _normalized(), provider_fabric=fabric
    )
    fused = visual_evidence.fuse_visual_evidence(
        {"questions": [], "exceptions": [], "summary": {}}, record
    )

    assert calls["groq"] == [
        "internal/visual/regions/region-1.png",
        "internal/visual/regions/region-2.png",
    ]
    assert len(calls["cloudflare"]) == 20
    assert record["summary"]["success_count"] == 21
    assert record["summary"]["infrastructure_deferred"] is False
    assert fused["exceptions"] == []
    assert {run["provider"] for run in record["runs"]} == {"groq", "cloudflare"}


def test_cloudflare_exhaustion_defers_when_mistral_private_is_not_approved(monkeypatch):
    monkeypatch.setattr(visual_evidence, "_render_regions", lambda *_: _regions(6))
    registry = {
        "groq": _spec("groq", 0),
        "cloudflare": _spec("cloudflare", 1),
        "mistral": _spec(
            "mistral", 2, school_private=False, privacy_env="MISTRAL_PRIVATE_APPROVED"
        ),
    }
    cf_calls = []

    def groq(*_args):
        raise ProviderError("AI_PROVIDER_RATE_LIMITED", "capacity", category="transient_capacity")

    def cloudflare(request, spec, *_args):
        cf_calls.append(request.region_id)
        if len(cf_calls) == 4:
            raise ProviderError(
                "AI_PROVIDER_RATE_LIMITED", "capacity", retry_after_seconds=60,
                category="transient_capacity",
            )
        return _success(request, spec)

    fabric = ProviderFabric(
        registry=registry,
        adapters={"groq": groq, "cloudflare": cloudflare},
        env=_env("groq", "cloudflare", "mistral"),
    )
    record, _ = visual_evidence.extract_visual_evidence(
        b"source", _normalized(), provider_fabric=fabric
    )
    assert record["summary"]["success_count"] == 3
    assert record["summary"]["unprocessed_count"] == 3
    assert record["summary"]["infrastructure_deferred"] is True
    assert any(
        item["provider"] == "mistral" and item["decision"] == "privacy_ineligible"
        for item in record["provider_attempts"]
    )
    assert record["warnings"] == []


def test_mistral_is_synthetic_fallback_through_normalized_contract():
    registry = {
        "groq": _spec("groq", 0),
        "cloudflare": _spec("cloudflare", 1),
        "mistral": _spec("mistral", 2, school_private=False),
    }

    def unavailable(*_args):
        raise ProviderError("AI_PROVIDER_NETWORK_ERROR", "offline", category="transient_capacity")

    fabric = ProviderFabric(
        registry=registry,
        adapters={
            "groq": unavailable,
            "cloudflare": unavailable,
            "mistral": lambda request, spec, *_args: _success(request, spec),
        },
        env=_env("groq", "cloudflare", "mistral"),
    )
    result = fabric.route(_request(PRIVACY_SYNTHETIC_TEST), deadline_monotonic=100, remaining_requests=1)
    assert result.provider_id == "mistral"
    assert result.normalized_result == _normalized_result(1)
    assert [item["provider"] for item in result.route_attempts] == [
        "groq", "cloudflare", "mistral"
    ]


def test_mistral_school_private_is_blocked_without_explicit_approval():
    spec = _spec(
        "mistral", 0, school_private=False, privacy_env="MISTRAL_PRIVATE_APPROVED"
    )
    calls = []
    fabric = ProviderFabric(
        registry={"mistral": spec},
        adapters={"mistral": lambda *_args: calls.append(True)},
        env=_env("mistral"),
    )
    with pytest.raises(ProviderPoolExhausted) as caught:
        fabric.route(_request(), deadline_monotonic=100, remaining_requests=1)
    assert calls == []
    assert caught.value.attempts[0]["decision"] == "privacy_ineligible"


def test_mistral_school_private_can_be_explicitly_approved():
    spec = _spec(
        "mistral", 0, school_private=False, privacy_env="MISTRAL_PRIVATE_APPROVED"
    )
    fabric = ProviderFabric(
        registry={"mistral": spec},
        adapters={"mistral": lambda request, provider, *_args: _success(request, provider)},
        env=_env("mistral", mistral_approved=True),
    )
    assert fabric.route(_request(), deadline_monotonic=100, remaining_requests=1).provider_id == "mistral"


def test_no_eligible_provider_defers_without_call():
    calls = []
    fabric = ProviderFabric(
        registry={"groq": _spec("groq", 0, enabled=False)},
        adapters={"groq": lambda *_args: calls.append(True)},
        env=_env("groq"),
    )
    with pytest.raises(ProviderPoolExhausted):
        fabric.route(_request(), deadline_monotonic=100, remaining_requests=1)
    assert calls == []


def test_content_error_does_not_shop_other_providers():
    registry = {"groq": _spec("groq", 0), "cloudflare": _spec("cloudflare", 1)}
    cloudflare_calls = []

    def unread(*_args):
        raise ProviderError(
            "AI_PROVIDER_REQUEST_REJECTED", "unread", retryable=False,
            category="content_request", http_status=400,
        )

    fabric = ProviderFabric(
        registry=registry,
        adapters={"groq": unread, "cloudflare": lambda *_args: cloudflare_calls.append(True)},
        env=_env("groq", "cloudflare"),
    )
    with pytest.raises(ProviderError) as caught:
        fabric.route(_request(), deadline_monotonic=100, remaining_requests=1)
    assert caught.value.category == "content_request"
    assert cloudflare_calls == []


def test_auth_failure_opens_only_groq_circuit_and_cloudflare_succeeds():
    registry = {"groq": _spec("groq", 0), "cloudflare": _spec("cloudflare", 1)}

    def auth(*_args):
        raise ProviderError(
            "AI_PROVIDER_AUTH_CONFIGURATION_FAILED", "invalid", retryable=False,
            category="auth_configuration", http_status=401,
        )

    fabric = ProviderFabric(
        registry=registry,
        adapters={
            "groq": auth,
            "cloudflare": lambda request, spec, *_args: _success(request, spec),
        },
        env=_env("groq", "cloudflare"),
    )
    result = fabric.route(_request(), deadline_monotonic=100, remaining_requests=1)
    assert result.provider_id == "cloudflare"
    assert fabric.circuits["groq"].category == "auth_configuration"
    assert "invalid" not in str(result.route_attempts)


def test_known_exhausted_free_quota_skips_provider_on_next_region():
    registry = {"groq": _spec("groq", 0), "cloudflare": _spec("cloudflare", 1)}
    calls = {"groq": 0, "cloudflare": 0}

    def groq(request, spec, *_args):
        calls["groq"] += 1
        result = _success(request, spec)
        result.quota = {"remaining_requests": 0, "reset_requests_seconds": 90}
        return result

    def cloudflare(request, spec, *_args):
        calls["cloudflare"] += 1
        return _success(request, spec)

    fabric = ProviderFabric(
        registry=registry,
        adapters={"groq": groq, "cloudflare": cloudflare},
        env=_env("groq", "cloudflare"),
    )
    assert fabric.route(_request(region=1), deadline_monotonic=100, remaining_requests=2).provider_id == "groq"
    second = fabric.route(_request(region=2), deadline_monotonic=100, remaining_requests=1)
    assert second.provider_id == "cloudflare"
    assert calls == {"groq": 1, "cloudflare": 1}
    assert second.route_attempts[0]["decision"] == "circuit_open"


def test_cross_provider_checkpoint_reuses_first_nine_regions(monkeypatch):
    monkeypatch.setattr(visual_evidence, "_render_regions", lambda *_: _regions(12))
    registry = {"groq": _spec("groq", 0), "cloudflare": _spec("cloudflare", 1)}
    first_counts = {"groq": 0, "cloudflare": 0}

    def groq_first(request, spec, *_args):
        first_counts["groq"] += 1
        if first_counts["groq"] > 4:
            raise ProviderError("AI_PROVIDER_RATE_LIMITED", "capacity", category="transient_capacity")
        return _success(request, spec)

    def cloudflare_first(request, spec, *_args):
        first_counts["cloudflare"] += 1
        if first_counts["cloudflare"] > 5:
            raise ProviderError("AI_PROVIDER_RATE_LIMITED", "capacity", category="transient_capacity")
        return _success(request, spec)

    first, _ = visual_evidence.extract_visual_evidence(
        b"source", _normalized(),
        provider_fabric=ProviderFabric(
            registry=registry,
            adapters={"groq": groq_first, "cloudflare": cloudflare_first},
            env=_env("groq", "cloudflare"),
        ),
    )
    second_calls = []

    def second_adapter(request, spec, *_args):
        second_calls.append(request.region_id)
        return _success(request, spec)

    second, _ = visual_evidence.extract_visual_evidence(
        b"source", _normalized(), checkpoint_record=first,
        provider_fabric=ProviderFabric(
            registry=registry,
            adapters={"groq": second_adapter, "cloudflare": second_adapter},
            env=_env("groq", "cloudflare"),
        ),
    )
    assert first["summary"]["success_count"] == 9
    assert second_calls == [
        "internal/visual/regions/region-10.png",
        "internal/visual/regions/region-11.png",
        "internal/visual/regions/region-12.png",
    ]
    assert second["summary"]["reused_success_count"] == 9
    assert second["summary"]["success_count"] == 12


@pytest.mark.parametrize("field", ["requires_paid_plan", "automatic_overage_possible"])
def test_zero_cost_policy_excludes_billable_provider(field):
    kwargs = {"requires_paid": field == "requires_paid_plan", "automatic_overage": field == "automatic_overage_possible"}
    spec = _spec("paid", 0, **kwargs)
    assert eligible_providers(
        {"paid": spec}, task_type=TASK_VISUAL_INTERPRETATION,
        privacy_classification=PRIVACY_SYNTHETIC_TEST,
        env=_env("paid"),
    ) == []


def test_privacy_policy_allows_synthetic_and_denies_school_private():
    spec = _spec("synthetic", 0, school_private=False)
    assert eligible_providers(
        {"synthetic": spec}, task_type=TASK_VISUAL_INTERPRETATION,
        privacy_classification=PRIVACY_SYNTHETIC_TEST, env=_env("synthetic"),
    ) == [spec]
    assert eligible_providers(
        {"synthetic": spec}, task_type=TASK_VISUAL_INTERPRETATION,
        privacy_classification=PRIVACY_SCHOOL_PRIVATE, env=_env("synthetic"),
    ) == []


def test_zero_cost_confirmation_flag_is_required_when_registry_declares_it():
    spec = replace(
        _spec("free", 0), zero_cost_confirmation_env="FREE_ZERO_COST_CONFIRMED"
    )
    env = _env("free")
    assert eligible_providers(
        {"free": spec}, task_type=TASK_VISUAL_INTERPRETATION,
        privacy_classification=PRIVACY_SYNTHETIC_TEST, env=env,
    ) == []
    env["FREE_ZERO_COST_CONFIRMED"] = "true"
    assert eligible_providers(
        {"free": spec}, task_type=TASK_VISUAL_INTERPRETATION,
        privacy_classification=PRIVACY_SYNTHETIC_TEST, env=env,
    ) == [spec]


def test_default_mistral_adapter_requires_an_explicit_current_model(monkeypatch):
    monkeypatch.delenv("MEMO_MISTRAL_VISION_MODEL", raising=False)
    monkeypatch.setenv("MISTRAL_API_KEY", "configured-in-test")
    monkeypatch.setenv("MISTRAL_ZERO_COST_CONFIRMED", "true")
    spec = provider_fabric.default_provider_registry()["mistral"]
    assert provider_fabric.provider_ineligibility_reason(
        spec,
        task_type=TASK_VISUAL_INTERPRETATION,
        privacy_classification=PRIVACY_SYNTHETIC_TEST,
    ) == "model_unconfigured"


def test_cloudflare_and_mistral_adapters_use_direct_zero_cost_contracts(monkeypatch):
    calls = []

    def fake_post(url, headers, body, **_kwargs):
        calls.append((url, headers, body))
        if "cloudflare.com" in url:
            return {
                "result": {
                    "response": json.dumps(_normalized_result(1)),
                    "usage": {"total_tokens": 5},
                },
                "success": True,
                "errors": [],
            }, 4
        return {
            "choices": [{"message": {"content": json.dumps(_normalized_result(1))}}],
            "usage": {"total_tokens": 5},
        }, 4

    monkeypatch.setattr(provider_fabric, "_post_json", fake_post)
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "account")
    monkeypatch.setenv("CLOUDFLARE_AI_API_TOKEN", "token")
    monkeypatch.setenv("MISTRAL_API_KEY", "token")
    request = _request(PRIVACY_SYNTHETIC_TEST)
    cloudflare = provider_fabric.cloudflare_visual_adapter(
        request,
        replace(_spec("cloudflare", 0), model_id="@cf/qwen/qwen3.8-27b"),
        None,
        1,
        lambda: 0,
    )
    mistral = provider_fabric.mistral_visual_adapter(
        request, _spec("mistral", 0), None, 1, lambda: 0
    )
    assert cloudflare.normalized_result == _normalized_result(1)
    assert mistral.normalized_result == _normalized_result(1)
    assert "/accounts/account/ai/run/@cf/qwen/qwen3.8-27b" in calls[0][0]
    assert "gateway" not in calls[0][0].lower()
    assert "model" not in calls[0][2]
    assert calls[0][2]["response_format"] == {
        "type": "json_schema",
        "json_schema": request.response_schema,
    }
    assert calls[1][0] == "https://api.mistral.ai/v1/chat/completions"
    assert calls[1][2]["service_tier"] == "standard_only"
    assert "Bearer token" not in json.dumps([call[2] for call in calls])
