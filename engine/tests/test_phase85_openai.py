from __future__ import annotations

import io
import json
import threading
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from email.message import Message
from pathlib import Path

import pytest
from PIL import Image

from engine.src.memo_engine import openai_adapter, provider_fabric, visual_evidence
from engine.src.memo_engine.ai_router import ProviderError
from engine.src.memo_engine.openai_credit import (
    MODEL, PBHS_URL, PILOT_JOB, SLOT_CEILING_NUSD, SLOT_COUNT, CreditLedger,
)
from engine.src.memo_engine.provider_fabric import ProviderTaskRequest


def _env() -> dict[str, str]:
    return {
        "OPENAI_API_KEY": "synthetic-only",
        "MEMO_OPENAI_ENABLED": "true",
        "MEMO_OPENAI_INCLUDED_CREDIT_CONFIRMED": "true",
        "MEMO_OPENAI_SCHOOL_PRIVATE_APPROVED": "true",
        "MEMO_OPENAI_ORGANIZATION": "org-test",
        "MEMO_OPENAI_PROJECT": "proj_test",
        "MEMO_JOB_ID": PILOT_JOB,
        "SUPABASE_URL": PBHS_URL,
        "GROQ_API_KEY": "synthetic-only",
        "GROQ_PLAN_MODE": "free_only",
        "GROQ_ZERO_COST_CONFIRMED": "true",
        "MEMO_CLOUDFLARE_COMPOSITE_VISUAL_ENABLED": "true",
        "MEMO_CLOUDFLARE_VISION_MODEL": provider_fabric.CLOUDFLARE_COMPOSITE_VISION_MODEL,
        "MEMO_CLOUDFLARE_STRUCTURER_MODEL": provider_fabric.CLOUDFLARE_PREFERRED_STRUCTURER_MODEL,
        "CLOUDFLARE_ZERO_COST_CONFIRMED": "true",
        "CLOUDFLARE_WORKERS_AI_PLAN_MODE": "free_only",
        "CLOUDFLARE_AI_API_TOKEN": "synthetic-only",
        "CLOUDFLARE_ACCOUNT_ID": "synthetic-only",
        "MISTRAL_SCHOOL_PRIVATE_APPROVED": "false",
    }


class InMemoryPrivateStorage:
    base = PBHS_URL

    def __init__(self) -> None:
        self.objects = {}
        self.lock = threading.Lock()

    def upload_json(self, _bucket, path, value, *, upsert):
        assert not upsert
        with self.lock:
            if path in self.objects:
                raise RuntimeError("duplicate reservation") from urllib.error.HTTPError(
                    "https://example.invalid", 409, "conflict", {}, None,
                )
            self.objects[path] = value


def _request() -> ProviderTaskRequest:
    buffer = io.BytesIO()
    Image.new("RGB", (128, 64), "white").save(buffer, format="PNG")
    return ProviderTaskRequest(
        task_type="visual_interpretation", region_id="synthetic.png", current_question_owner="1.1",
        source_question="1.1", source_page=1, source_digest="fixture", crop_digest="fixture",
        crop_bytes=buffer.getvalue(), crop_mime_type="image/png", interpretation_schema_version="1.0",
        task_prompt_version="test", privacy_classification="synthetic_test", prompt="synthetic maths only",
        response_schema=visual_evidence._vision_schema(1),
    )


def _result_body() -> dict:
    value = {
        "schema_version": "1.0", "page": 1, "visual_content_present": True, "warnings": [], "mark_changes": [],
        "evidence": [{"question_ref": "1.1", "kind": "answer_working", "transcription": "1+2=3",
                      "normalized_math": "1+2=3", "confidence": .95, "source": "visual_overlay", "bbox": None}],
    }
    return {"model": MODEL, "service_tier": "default", "status": "completed",
            "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(value)}]}],
            "usage": {"input_tokens": 1000, "output_tokens": 250,
                      "input_tokens_details": {"cached_tokens": 200, "cache_write_tokens": 300, "image_tokens": 125},
                      "output_tokens_details": {"reasoning_tokens": 180}}}


class ApiResponse(io.BytesIO):
    headers = Message()


def _visual(interpreter, request=None):
    spec = provider_fabric.default_provider_registry(_env())["openai"]
    return interpreter.visual(request or _request(), spec, None, 1, lambda: 0)


def test_private_route_requires_policy_scope_and_org_project_binding():
    env = _env()
    spec = provider_fabric.default_provider_registry(env)["openai"]
    assert provider_fabric.validate_production_provider_configuration(env)["effective_school_private_route"] == [
        "openai", "groq", "cloudflare", "defer",
    ]
    for alternative in ({"MEMO_JOB_ID": "historical-job"}, {"MEMO_OPENAI_PROJECT": ""},
                        {"MEMO_OPENAI_SCHOOL_PRIVATE_APPROVED": "false"}, {"MEMO_OPENAI_INCLUDED_CREDIT_CONFIRMED": "false"},
                        {"MEMO_PRIVACY_MODE": "LOCAL_ONLY"}):
        assert provider_fabric.provider_ineligibility_reason(
            spec, task_type="visual_interpretation", privacy_classification="school_private", env={**env, **alternative},
        )
    assert provider_fabric.provider_ineligibility_reason(
        replace(spec, model_id="gpt-6.2-sol"), task_type="visual_interpretation", privacy_classification="synthetic_test", env=env,
    ) == "included_credit_policy_blocked"


def test_credit_slots_are_shared_across_workers_and_never_reissued():
    store = InMemoryPrivateStorage()
    with ThreadPoolExecutor(max_workers=8) as workers:
        futures = [workers.submit(CreditLedger(store).reserve, "visual", SLOT_CEILING_NUSD) for _ in range(SLOT_COUNT - 2)]
    assert {future.result().slot for future in futures} == set(range(2, SLOT_COUNT))
    synthetic = CreditLedger(store, synthetic=True)
    assert synthetic.reserve("visual", 1).slot == 0
    assert synthetic.reserve("semantic", 1).slot == 1
    for ledger, stage in ((CreditLedger(store), "visual"), (CreditLedger(store, synthetic=True), "semantic")):
        with pytest.raises(ProviderError, match="allowance is exhausted"):
            ledger.reserve(stage, 1)
    with pytest.raises(ProviderError, match="exceeds"):
        CreditLedger(store).reserve("visual", SLOT_CEILING_NUSD + 1)
    assert SLOT_COUNT * SLOT_CEILING_NUSD == 2_000_000_000


def test_visual_preserves_crop_binds_project_and_accounts_for_inclusive_reasoning(monkeypatch):
    store = InMemoryPrivateStorage()
    observed = []
    crop = _request()

    def post(request, timeout):
        assert len(store.objects) == 1  # Durable reservation precedes network I/O.
        assert request.full_url == "https://api.openai.com/v1/responses" and timeout == 75
        assert request.get_header("Openai-project") == "proj_test"
        observed.append(json.loads(request.data))
        return ApiResponse(json.dumps(_result_body()).encode())

    monkeypatch.setattr(openai_adapter.urllib.request, "urlopen", post)
    output = _visual(openai_adapter.OpenAIInterpreter(CreditLedger(store, synthetic=True), _env()), crop)
    sent = observed[0]
    assert sent["store"] is False and sent["service_tier"] == "default" and sent["reasoning"] == {"effort": "low"}
    assert "tools" not in sent and "previous_response_id" not in sent
    assert sent["input"][0]["content"][1]["detail"] == "high"
    assert sent["input"][0]["content"][1]["image_url"].endswith(openai_adapter.base64.b64encode(crop.crop_bytes).decode())
    assert sent["text"]["format"]["strict"] is True
    assert output.status == "success" and output.model_id == MODEL
    assert output.usage["reasoning_tokens"] == 180 and output.usage["image_input_tokens"] == 125
    assert output.usage["estimated_cost_nusd"] == 214_500
    assert all("synthetic maths only" not in str(record) for record in store.objects.values())


@pytest.mark.parametrize("defect,code", [("refusal", "OPENAI_REFUSED"), ("incomplete", "OPENAI_INCOMPLETE"),
                                        ("invalid_bbox", "OPENAI_SCHEMA_INVALID"), ("wrong_tier", "OPENAI_USAGE_UNVERIFIED")])
def test_refusals_output_caps_and_application_validation_fail_closed(monkeypatch, defect, code):
    fixture = _result_body()
    content = fixture["output"][0]["content"][0]
    if defect == "refusal":
        content["type"] = "refusal"
    elif defect == "incomplete":
        fixture["status"] = "incomplete"
    elif defect == "invalid_bbox":
        value = json.loads(content["text"])
        value["evidence"][0]["bbox"] = [0, 1, 2]
        content["text"] = json.dumps(value)
    else:
        fixture["service_tier"] = "priority"
    monkeypatch.setattr(openai_adapter.urllib.request, "urlopen", lambda *_a, **_k: ApiResponse(json.dumps(fixture).encode()))
    store = InMemoryPrivateStorage()
    with pytest.raises(ProviderError) as exc:
        _visual(openai_adapter.OpenAIInterpreter(CreditLedger(store, synthetic=True), _env()))
    assert exc.value.code == code
    assert len(store.objects) == 2


def test_rate_limit_falls_back_without_repeating_the_paid_request(monkeypatch):
    store = InMemoryPrivateStorage()
    calls = []

    def rate_limited(*_args, **_kwargs):
        calls.append("openai")
        headers = Message()
        headers["Retry-After"] = "17"
        raise urllib.error.HTTPError("https://example.invalid", 429, "rate limited", headers, io.BytesIO(b"{}"))

    def free_result(request, spec, *_args):
        calls.append(spec.provider_id)
        return provider_fabric.ProviderResult(spec.provider_id, spec.model_id, request.task_type,
                                              "success", {}, 1, 3, {}, {}, "fixture")

    monkeypatch.setattr(openai_adapter.urllib.request, "urlopen", rate_limited)
    env = _env()
    interpreter = openai_adapter.OpenAIInterpreter(CreditLedger(store), env, job_id=PILOT_JOB)
    fabric = provider_fabric.ProviderFabric(registry=provider_fabric.default_provider_registry(env),
        adapters={"openai": interpreter.visual, "groq": free_result}, env=env, clock=lambda: 0)
    request = replace(_request(), privacy_classification="school_private")
    result = fabric.route(request, deadline_monotonic=100, remaining_requests=1)
    assert result.provider_id == "groq" and calls == ["openai", "groq"]
    assert fabric.circuits["openai"].retry_after_seconds == 17
    assert any(value.get("charged_budget_nusd", 0) > 0 for value in store.objects.values())


def test_workflow_injects_openai_key_only_for_the_stage_1b_job():
    workflow = (Path(__file__).resolve().parents[2] / ".github/workflows/process-memo.yml").read_text()
    assert f"inputs.job_id == '{PILOT_JOB}' && secrets.OPENAI_API_KEY" in workflow
    assert "OPENAI_API_KEY: ''" in workflow
    assert "vars.MEMO_OPENAI_SCHOOL_PRIVATE_APPROVED" in workflow


def test_missing_pilot_checkpoint_prevents_any_inference(monkeypatch):
    crop = _request()
    monkeypatch.setattr(visual_evidence, "_render_regions", lambda *_: [{
        "page": 1, "asset_path": crop.region_id, "image_bytes": crop.crop_bytes,
        "mime_type": crop.crop_mime_type, "question_refs": ["1.1"],
    }])
    normalized = {"source": {"sha256": "fixture"}, "content": {
        "pages": [{"page": 1, "visual_inspection_required": True}],
    }}
    with pytest.raises(visual_evidence.VisualProviderDeferred) as error:
        visual_evidence.extract_visual_evidence(
            b"fixture", normalized, required_checkpoint_regions=frozenset({crop.region_id}),
            runner=lambda *_: pytest.fail("a required checkpoint was missing before routing"),
        )
    assert error.value.code == "OPENAI_CHECKPOINT_REUSE_REQUIRED"
