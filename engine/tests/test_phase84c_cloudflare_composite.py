from __future__ import annotations

import hashlib
import json
from dataclasses import replace

import pytest

from engine.src.memo_engine import provider_fabric, visual_evidence
from engine.src.memo_engine.ai_router import ProviderError
from engine.src.memo_engine.mathematical_consistency import CHECKED_PASS, check_expression
from engine.src.memo_engine.provider_fabric import (
    CLOUDFLARE_COMPOSITE_PROMPT_VERSION,
    CLOUDFLARE_COMPOSITE_VISION_MODEL,
    CLOUDFLARE_DEPRECATED_MODELS,
    CLOUDFLARE_GROUNDING_SCHEMA_VERSION,
    CLOUDFLARE_ENUM_NORMALIZATION_VERSION,
    CLOUDFLARE_JSON_MODE_DOCUMENTED_MODELS,
    CLOUDFLARE_LLAMA_STRUCTURED_VISION_MODEL,
    CLOUDFLARE_PREFERRED_STRUCTURER_MODEL,
    CLOUDFLARE_STRUCTURER_PROMPT_VERSION,
    PRIVACY_SCHOOL_PRIVATE,
    ProviderFabric,
    ProviderPoolExhausted,
    ProviderTaskRequest,
    assemble_cloudflare_grounded_wrapper,
    cloudflare_composite_visual_adapter,
    cloudflare_grounded_provider_body_schema,
    cloudflare_model_capabilities,
    default_provider_registry,
    normalize_cloudflare_model_semantic_enums,
    select_cloudflare_structurer_model,
    validate_cloudflare_grounding,
)


TRANSCRIPT = """LABEL: Question 1.2
MATH: 10/250 = 1/25 = 0.04 = 4%
LABEL: Circle A and Circle B
RELATION: A overlaps B; overlap contains 3.
ROLE: visible solution evidence"""


def _payload() -> dict:
    return {
        "schema_version": "1.0",
        "page": 1,
        "visual_content_present": True,
        "evidence": [
            {
                "question_ref": "1.2",
                "kind": "answer_working",
                "transcription": "10/250 = 1/25 = 0.04 = 4%",
                "normalized_math": "10/250 = 1/25 = 0.04 = 4%",
                "confidence": 0.98,
                "source": "visual_overlay",
                "bbox": None,
            },
            {
                "question_ref": "1.2",
                "kind": "diagram_entry",
                "transcription": "A overlaps B; overlap contains 3.",
                "normalized_math": None,
                "confidence": 0.96,
                "source": "visual_overlay",
                "bbox": None,
            },
        ],
        "mark_changes": [],
        "warnings": [],
    }


def _wrapper(payload: dict | None = None) -> dict:
    return {
        "grounding_schema_version": CLOUDFLARE_GROUNDING_SCHEMA_VERSION,
        "payload": payload or _payload(),
        "grounding": [
            {"path": "/payload/evidence/0/question_ref", "evidence_quote": "LABEL: Question 1.2"},
            {"path": "/payload/evidence/0/transcription", "evidence_quote": "MATH: 10/250 = 1/25 = 0.04 = 4%"},
            {"path": "/payload/evidence/0/normalized_math", "evidence_quote": "MATH: 10/250 = 1/25 = 0.04 = 4%"},
            {"path": "/payload/evidence/1/question_ref", "evidence_quote": "LABEL: Question 1.2"},
            {"path": "/payload/evidence/1/transcription", "evidence_quote": "RELATION: A overlaps B; overlap contains 3."},
            {"path": "/payload/visual_content_present", "evidence_quote": "ROLE: visible solution evidence"},
        ],
    }


def _provider_body(payload: dict | None = None) -> dict:
    wrapper = _wrapper(payload)
    return {"payload": wrapper["payload"], "grounding": wrapper["grounding"]}


def _request(checkpoint=None) -> ProviderTaskRequest:
    crop = b"synthetic-composite-crop"
    return ProviderTaskRequest(
        task_type="visual_interpretation",
        region_id="synthetic/region-1.png",
        current_question_owner="1.2",
        source_question="1.2",
        source_page=1,
        source_digest="source-digest",
        crop_digest=hashlib.sha256(crop).hexdigest(),
        crop_bytes=crop,
        crop_mime_type="image/png",
        interpretation_schema_version="1.0",
        task_prompt_version="visual-evidence-v1",
        privacy_classification=PRIVACY_SCHOOL_PRIVATE,
        prompt="production visual prompt",
        response_schema=visual_evidence._vision_schema(1),
        provider_checkpoint=checkpoint,
    )


def _configure(monkeypatch) -> None:
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "a" * 32)
    monkeypatch.setenv("CLOUDFLARE_AI_API_TOKEN", "configured")
    monkeypatch.setenv("CLOUDFLARE_ZERO_COST_CONFIRMED", "true")
    monkeypatch.setenv("CLOUDFLARE_WORKERS_AI_PLAN_MODE", "free_only")
    monkeypatch.setenv("MEMO_CLOUDFLARE_COMPOSITE_VISUAL_ENABLED", "true")
    monkeypatch.setenv("MEMO_CLOUDFLARE_VISION_MODEL", CLOUDFLARE_COMPOSITE_VISION_MODEL)
    monkeypatch.setenv("MEMO_CLOUDFLARE_STRUCTURER_MODEL", CLOUDFLARE_PREFERRED_STRUCTURER_MODEL)
    monkeypatch.setenv("MISTRAL_SCHOOL_PRIVATE_APPROVED", "false")


def _stage_v(*_args):
    return {
        "transcript": TRANSCRIPT,
        "usage": {"total_tokens": 20},
        "quota": {"remaining_requests": 8},
        "latency_ms": 4,
        "diagnostics": {"response_path": "result.response"},
    }


def _stage_s(*_args):
    provider_body = _provider_body()
    return {
        "provider_body": provider_body,
        "raw_result_digest": hashlib.sha256(json.dumps(
            provider_body, sort_keys=True, separators=(",", ":")
        ).encode()).hexdigest(),
        "usage": {"total_tokens": 30},
        "quota": {"remaining_requests": 7},
        "latency_ms": 6,
        "diagnostics": {"response_path": "result.response"},
    }


@pytest.mark.parametrize("model", [
    "@cf/google/gemma-4-26b-a4b-it",
    "@cf/qwen/qwen3.8-27b",
    CLOUDFLARE_LLAMA_STRUCTURED_VISION_MODEL,
])
def test_direct_cloudflare_vision_models_remain_not_structured_visual(model):
    assert "structured_visual" not in cloudflare_model_capabilities(model)


def test_composite_capability_requires_both_stages(monkeypatch):
    _configure(monkeypatch)
    assert "structured_visual" in default_provider_registry()["cloudflare"].capabilities
    monkeypatch.delenv("MEMO_CLOUDFLARE_STRUCTURER_MODEL")
    assert default_provider_registry()["cloudflare"].enabled is False


def test_stage_v_receives_image_and_stage_s_receives_only_transcript(monkeypatch):
    _configure(monkeypatch)
    bodies = []

    def post(_url, _headers, body, **_kwargs):
        bodies.append(body)
        if len(bodies) == 1:
            return {"success": True, "result": {"response": TRANSCRIPT}}, 2
        return {"success": True, "result": {"response": _provider_body()}}, 3

    monkeypatch.setattr(provider_fabric, "_post_json", post)
    provider_fabric.cloudflare_stage_v_call(_request(), CLOUDFLARE_COMPOSITE_VISION_MODEL, None, 1, lambda: 0)
    provider_fabric.cloudflare_stage_s_call(_request(), CLOUDFLARE_PREFERRED_STRUCTURER_MODEL, TRANSCRIPT, None, 1, lambda: 0)
    assert bodies[0]["messages"][0]["content"][1]["type"] == "image_url"
    assert "response_format" not in bodies[0]
    assert TRANSCRIPT in bodies[1]["messages"][0]["content"]
    assert "image" not in bodies[1]
    assert "image_url" not in json.dumps(bodies[1])
    transport = bodies[1]["response_format"]["json_schema"]
    assert set(provider_fabric.cloudflare_schema_keyword_inventory(transport)) == set(
        provider_fabric.CLOUDFLARE_TRANSPORT_SCHEMA_KEYWORDS
    )
    assert set(transport["properties"]) == {"payload", "grounding"}
    assert transport["required"] == ["payload", "grounding"]


def test_provider_body_excludes_application_owned_wrapper_metadata():
    schema = cloudflare_grounded_provider_body_schema(
        visual_evidence._vision_schema(1)
    )
    assert set(schema["properties"]) == {"payload", "grounding"}
    assert schema["required"] == ["payload", "grounding"]
    assert "grounding_schema_version" not in schema["properties"]


@pytest.mark.parametrize("kind", sorted(visual_evidence.EVIDENCE_KINDS))
def test_every_closed_production_evidence_kind_passes(kind):
    body = _provider_body()
    body["payload"]["evidence"][0]["kind"] = kind
    wrapper, _ = assemble_cloudflare_grounded_wrapper(
        body, visual_evidence._vision_schema(1)
    )
    assert wrapper["payload"]["evidence"][0]["kind"] == kind


@pytest.mark.parametrize("raw,expected", [
    ("Answer Working", "answer_working"),
    ("answer-working", "answer_working"),
    (" DIAGRAM_ENTRY ", "diagram_entry"),
])
def test_semantic_enum_lexical_normalization_is_bounded(raw, expected):
    body = _provider_body()
    body["payload"]["evidence"][0]["kind"] = raw
    normalized, provenance = normalize_cloudflare_model_semantic_enums(
        body, visual_evidence._vision_schema(1)
    )
    assert normalized["payload"]["evidence"][0]["kind"] == expected
    assert provenance["version"] == CLOUDFLARE_ENUM_NORMALIZATION_VERSION
    assert provenance["applied"] == [{
        "path": "/provider_body/payload/evidence/0/kind",
        "normalized_enum": expected,
    }]


@pytest.mark.parametrize("invalid", [
    "math", "label", "relationship", "solution", "arbitrary_kind",
])
def test_semantic_enum_aliases_remain_invalid(invalid):
    body = _provider_body()
    body["payload"]["evidence"][0]["kind"] = invalid
    with pytest.raises(ProviderError) as caught:
        assemble_cloudflare_grounded_wrapper(
            body, visual_evidence._vision_schema(1)
        )
    assert caught.value.code == "AI_PROVIDER_GROUNDED_WRAPPER_SCHEMA_INVALID"
    assert caught.value.diagnostics["grounding_failure_category"] == "internal_schema_enum"
    assert caught.value.diagnostics["enum_normalization_applied_count"] == 0


def test_mark_change_level_uses_same_lexical_only_normalizer():
    body = _provider_body()
    body["payload"]["mark_changes"] = [{
        "question_ref": "1.2", "level": "Document-Total", "printed_value": 4,
        "visual_value": 5, "confidence": 0.9, "requires_confirmation": True,
        "bbox": None,
    }]
    normalized, provenance = normalize_cloudflare_model_semantic_enums(
        body, visual_evidence._vision_schema(1)
    )
    assert normalized["payload"]["mark_changes"][0]["level"] == "document_total"
    assert provenance["applied"][0]["path"].endswith("/level")


def test_prompt_v5_locks_closed_kinds_and_prefix_mapping():
    prompt = provider_fabric.cloudflare_stage_s_prompt(
        TRANSCRIPT, visual_evidence._vision_schema(1)
    )
    assert provider_fabric.CLOUDFLARE_STRUCTURER_PROMPT_VERSION.endswith("-v5")
    for kind in visual_evidence.EVIDENCE_KINDS:
        assert kind in prompt
    assert "Stage-V prefixes are evidence-reading aids, NOT output evidence.kind values" in prompt
    assert "LABEL: is diagram_entry" in prompt
    assert "RELATION: is diagram_entry" in prompt
    assert "QUESTION: must not become answer or answer_working" in prompt
    assert visual_evidence.EVIDENCE_KINDS == {
        "answer", "answer_working", "marking_note", "teacher_comment",
        "tick", "cross", "diagram_entry", "other_visible_annotation",
    }


def test_wrapper_assembly_injects_canonical_version_and_separate_digest():
    body = _provider_body()
    raw_digest = hashlib.sha256(json.dumps(
        body, sort_keys=True, separators=(",", ":")
    ).encode()).hexdigest()
    wrapper, provenance = assemble_cloudflare_grounded_wrapper(
        body, visual_evidence._vision_schema(1)
    )
    assert wrapper["grounding_schema_version"] == CLOUDFLARE_GROUNDING_SCHEMA_VERSION
    assert provenance["application_metadata_injected"] == ["grounding_schema_version"]
    assert provenance["assembled_wrapper_digest"] != raw_digest
    provider_fabric.validate_cloudflare_internal_wrapper(
        wrapper, visual_evidence._vision_schema(1)
    )


def test_model_generated_protocol_version_cannot_override_canonical_version():
    body = {**_provider_body(), "grounding_schema_version": "model-invented-v99"}
    wrapper, provenance = assemble_cloudflare_grounded_wrapper(
        body, visual_evidence._vision_schema(1)
    )
    assert wrapper["grounding_schema_version"] == CLOUDFLARE_GROUNDING_SCHEMA_VERSION
    assert provenance["unexpected_application_metadata_fields"] == [
        "grounding_schema_version"
    ]


def test_unknown_model_content_field_fails_instead_of_being_discarded():
    with pytest.raises(ProviderError) as caught:
        assemble_cloudflare_grounded_wrapper(
            {**_provider_body(), "invented_answer": "unsafe"},
            visual_evidence._vision_schema(1),
        )
    assert caught.value.code == "AI_PROVIDER_GROUNDED_BODY_FIELD_UNSUPPORTED"
    assert caught.value.diagnostics["unexpected_field_names"] == ["invented_answer"]


@pytest.mark.parametrize("missing", ["payload", "grounding"])
def test_provider_body_missing_required_field_fails(missing):
    body = _provider_body()
    body.pop(missing)
    with pytest.raises(ProviderError) as caught:
        assemble_cloudflare_grounded_wrapper(
            body, visual_evidence._vision_schema(1)
        )
    assert caught.value.code == "AI_PROVIDER_GROUNDED_WRAPPER_SCHEMA_INVALID"
    assert caught.value.diagnostics["grounding_failure_category"] == "internal_schema_required"


def test_two_stage_success_creates_composite_provider_result(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setattr(provider_fabric, "cloudflare_stage_v_call", _stage_v)
    monkeypatch.setattr(provider_fabric, "cloudflare_stage_s_call", _stage_s)
    spec = default_provider_registry()["cloudflare"]
    result = cloudflare_composite_visual_adapter(_request(), spec, None, 1, lambda: 0)
    assert result.status == "success" and result.provider_id == "cloudflare"
    assert result.normalized_result == _payload()
    assert result.diagnostics["vision_model"] == CLOUDFLARE_COMPOSITE_VISION_MODEL
    assert result.diagnostics["structurer_model"] == CLOUDFLARE_PREFERRED_STRUCTURER_MODEL
    assert result.diagnostics["grounding_status"] == "passed"


@pytest.mark.parametrize("code,category", [
    ("AI_PROVIDER_NETWORK_ERROR", "transient_capacity"),
    ("AI_PROVIDER_RATE_LIMITED", "transient_capacity"),
])
def test_stage_v_failure_makes_zero_stage_s_calls(monkeypatch, code, category):
    _configure(monkeypatch)
    structurer_calls = []

    def fail(*_args):
        raise ProviderError(code, "unavailable", category=category)

    monkeypatch.setattr(provider_fabric, "cloudflare_stage_v_call", fail)
    monkeypatch.setattr(provider_fabric, "cloudflare_stage_s_call", lambda *_args: structurer_calls.append(1))
    with pytest.raises(ProviderError) as caught:
        cloudflare_composite_visual_adapter(
            _request(), default_provider_registry()["cloudflare"], None, 1, lambda: 0
        )
    assert structurer_calls == []
    assert caught.value.diagnostics["circuit_provider"] == "cloudflare:visual_evidence"


def test_stage_s_failure_retains_successful_stage_v_checkpoint(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setattr(provider_fabric, "cloudflare_stage_v_call", _stage_v)

    def fail(*_args):
        raise ProviderError("AI_PROVIDER_RATE_LIMITED", "capacity", category="transient_capacity")

    monkeypatch.setattr(provider_fabric, "cloudflare_stage_s_call", fail)
    with pytest.raises(ProviderError) as caught:
        cloudflare_composite_visual_adapter(
            _request(), default_provider_registry()["cloudflare"], None, 1, lambda: 0
        )
    checkpoint = caught.value.diagnostics["_private_composite_checkpoint"]
    assert checkpoint["stage_v"]["status"] == "success"
    assert checkpoint["stage_s"]["status"] == "failed"
    assert caught.value.diagnostics["circuit_provider"] == "cloudflare:json_structurer"


def test_retry_reuses_stage_v_and_calls_only_stage_s(monkeypatch):
    _configure(monkeypatch)
    calls = {"v": 0, "s": 0}

    def first_v(*args):
        calls["v"] += 1
        return _stage_v(*args)

    def fail_s(*_args):
        calls["s"] += 1
        raise ProviderError("AI_PROVIDER_RATE_LIMITED", "capacity", category="transient_capacity")

    monkeypatch.setattr(provider_fabric, "cloudflare_stage_v_call", first_v)
    monkeypatch.setattr(provider_fabric, "cloudflare_stage_s_call", fail_s)
    spec = default_provider_registry()["cloudflare"]
    with pytest.raises(ProviderError) as caught:
        cloudflare_composite_visual_adapter(_request(), spec, None, 1, lambda: 0)
    checkpoint = caught.value.diagnostics["_private_composite_checkpoint"]
    monkeypatch.setattr(provider_fabric, "cloudflare_stage_v_call", lambda *_args: pytest.fail("Stage V repeated"))

    def second_s(*args):
        calls["s"] += 1
        return _stage_s(*args)

    monkeypatch.setattr(provider_fabric, "cloudflare_stage_s_call", second_s)
    result = cloudflare_composite_visual_adapter(
        _request(checkpoint), spec, None, 1, lambda: 0
    )
    assert calls == {"v": 1, "s": 2}
    assert result.diagnostics["stage_v_cache_hit"] is True


def test_private_visual_checkpoint_retains_stage_v_without_transcript_in_attempts(monkeypatch):
    _configure(monkeypatch)
    region = {
        "page": 1, "question_refs": ["1.2"], "printed_text": "",
        "image_bytes": b"synthetic-composite-crop", "mime_type": "image/png",
        "asset_path": "synthetic/region-1.png",
    }
    monkeypatch.setattr(visual_evidence, "_render_regions", lambda *_: [region])
    monkeypatch.setattr(provider_fabric, "cloudflare_stage_v_call", _stage_v)

    def fail_s(*_args):
        raise ProviderError("AI_PROVIDER_RATE_LIMITED", "capacity", category="transient_capacity")

    monkeypatch.setattr(provider_fabric, "cloudflare_stage_s_call", fail_s)
    spec = default_provider_registry()["cloudflare"]
    env = {
        "CLOUDFLARE_ACCOUNT_ID": "configured",
        "CLOUDFLARE_AI_API_TOKEN": "configured",
        "CLOUDFLARE_ZERO_COST_CONFIRMED": "true",
    }
    normalized = {
        "job_id": "synthetic", "source": {"sha256": "source-digest"},
        "content": {"pages": [{"visual_inspection_required": True}]},
    }
    first, _ = visual_evidence.extract_visual_evidence(
        b"source", normalized,
        provider_fabric=ProviderFabric(
            registry={"cloudflare": spec},
            adapters={"cloudflare": cloudflare_composite_visual_adapter},
            env=env,
        ),
    )
    assert first["composite_checkpoints"][0]["stage_v"]["transcript"] == TRANSCRIPT
    assert TRANSCRIPT not in json.dumps(first["provider_attempts"])

    monkeypatch.setattr(
        provider_fabric, "cloudflare_stage_v_call",
        lambda *_args: pytest.fail("Stage V must be reused"),
    )
    monkeypatch.setattr(provider_fabric, "cloudflare_stage_s_call", _stage_s)
    second, _ = visual_evidence.extract_visual_evidence(
        b"source", normalized, checkpoint_record=first,
        provider_fabric=ProviderFabric(
            registry={"cloudflare": spec},
            adapters={"cloudflare": cloudflare_composite_visual_adapter},
            env=env,
        ),
    )
    assert second["summary"]["success_count"] == 1
    assert second["runs"][0]["provider"] == "cloudflare"


def test_valid_grounding_passes():
    assert validate_cloudflare_grounding(_wrapper(), TRANSCRIPT) == _payload()


def test_fabricated_number_fails_grounding():
    payload = _payload()
    payload["evidence"][0]["normalized_math"] = "10/250 = 0.05"
    with pytest.raises(ProviderError, match="number") as caught:
        validate_cloudflare_grounding(_wrapper(payload), TRANSCRIPT)
    assert caught.value.code == "AI_PROVIDER_GROUNDING_UNSUPPORTED_NUMBER"


def test_corrected_arithmetic_not_in_transcript_fails_grounding():
    transcript = "MATH: 2 + 2 = 5\nLABEL: Question 1.2"
    payload = _payload()
    payload["evidence"] = [{
        **payload["evidence"][0],
        "transcription": "2 + 2 = 5",
        "normalized_math": "2 + 2 = 4",
    }]
    wrapper = {"grounding_schema_version": CLOUDFLARE_GROUNDING_SCHEMA_VERSION,
               "payload": payload, "grounding": [
        {"path": "/payload/evidence/0/question_ref", "evidence_quote": "LABEL: Question 1.2"},
        {"path": "/payload/evidence/0/transcription", "evidence_quote": "MATH: 2 + 2 = 5"},
        {"path": "/payload/evidence/0/normalized_math", "evidence_quote": "MATH: 2 + 2 = 5"},
        {"path": "/payload/visual_content_present", "evidence_quote": "MATH: 2 + 2 = 5"},
    ]}
    with pytest.raises(ProviderError) as caught:
        validate_cloudflare_grounding(wrapper, transcript)
    assert caught.value.code == "AI_PROVIDER_GROUNDING_UNSUPPORTED_NUMBER"


def test_unsupported_math_label_fails_grounding():
    transcript = TRANSCRIPT + "\nMATH: 2 = 2"
    payload = _payload()
    payload["evidence"][0]["normalized_math"] = "x = 2"
    wrapper = _wrapper(payload)
    wrapper["grounding"][2]["evidence_quote"] = "MATH: 2 = 2"
    with pytest.raises(ProviderError) as caught:
        validate_cloudflare_grounding(wrapper, transcript)
    assert caught.value.code == "AI_PROVIDER_GROUNDING_UNSUPPORTED_LABEL"


def test_missing_quote_fails_grounding():
    wrapper = _wrapper()
    wrapper["grounding"] = wrapper["grounding"][:-1]
    with pytest.raises(ProviderError) as caught:
        validate_cloudflare_grounding(wrapper, TRANSCRIPT)
    assert caught.value.code == "AI_PROVIDER_GROUNDING_MISSING"


def test_whitespace_normalized_exact_quote_passes():
    transcript = TRANSCRIPT.replace("10/250 = 1/25", "10/250   =\n  1/25")
    wrapper = _wrapper()
    wrapper["grounding"][1]["evidence_quote"] = "MATH: 10/250 = 1/25 = 0.04 = 4%"
    wrapper["grounding"][2]["evidence_quote"] = "MATH: 10/250 = 1/25 = 0.04 = 4%"
    assert validate_cloudflare_grounding(wrapper, transcript)["evidence"]


def test_question_only_transcript_cannot_become_answer():
    transcript = "QUESTION: Calculate 2 + 2\nLABEL: Question 1.2"
    payload = _payload()
    payload["evidence"] = [{
        **payload["evidence"][0],
        "transcription": "Calculate 2 + 2",
        "normalized_math": None,
    }]
    wrapper = {"grounding_schema_version": CLOUDFLARE_GROUNDING_SCHEMA_VERSION,
               "payload": payload, "grounding": [
        {"path": "/payload/evidence/0/question_ref", "evidence_quote": "LABEL: Question 1.2"},
        {"path": "/payload/evidence/0/transcription", "evidence_quote": "QUESTION: Calculate 2 + 2"},
        {"path": "/payload/visual_content_present", "evidence_quote": "QUESTION: Calculate 2 + 2"},
    ]}
    with pytest.raises(ProviderError) as caught:
        validate_cloudflare_grounding(wrapper, transcript)
    assert caught.value.code == "AI_PROVIDER_QUESTION_PROMOTED_TO_ANSWER"


def test_essential_spatial_evidence_remains_diagram_entry():
    payload = validate_cloudflare_grounding(_wrapper(), TRANSCRIPT)
    diagram = payload["evidence"][1]
    assert diagram["kind"] == "diagram_entry"
    assert diagram["transcription"] == "A overlaps B; overlap contains 3."


def test_grounded_math_continues_to_consistency_validator():
    payload = validate_cloudflare_grounding(_wrapper(), TRANSCRIPT)
    result, _ = check_expression(payload["evidence"][0]["normalized_math"])
    assert result["status"] == CHECKED_PASS


def test_composite_provenance_contains_both_models(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setattr(provider_fabric, "cloudflare_stage_v_call", _stage_v)
    monkeypatch.setattr(provider_fabric, "cloudflare_stage_s_call", _stage_s)
    result = cloudflare_composite_visual_adapter(
        _request(), default_provider_registry()["cloudflare"], None, 1, lambda: 0
    )
    assert result.diagnostics["vision_model"] == CLOUDFLARE_COMPOSITE_VISION_MODEL
    assert result.diagnostics["structurer_model"] == CLOUDFLARE_PREFERRED_STRUCTURER_MODEL
    assert result.diagnostics["vision_transcript_digest"]
    assert result.diagnostics["structurer_result_digest"]
    assert result.diagnostics["structurer_raw_result_digest"]
    assert result.diagnostics["assembled_wrapper_digest"]
    assert (
        result.diagnostics["structurer_raw_result_digest"]
        != result.diagnostics["assembled_wrapper_digest"]
    )
    assert result.diagnostics["application_metadata_injected"] == [
        "grounding_schema_version"
    ]


def test_stage_v_cache_identity_contains_required_fields(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setattr(provider_fabric, "cloudflare_stage_v_call", _stage_v)
    monkeypatch.setattr(provider_fabric, "cloudflare_stage_s_call", _stage_s)
    result = cloudflare_composite_visual_adapter(
        _request(), default_provider_registry()["cloudflare"], None, 1, lambda: 0
    )
    stage = result.diagnostics["_private_composite_checkpoint"]["stage_v"]
    assert stage["source_digest"] == "source-digest"
    assert stage["crop_digest"] == _request().crop_digest
    assert stage["prompt_version"] == CLOUDFLARE_COMPOSITE_PROMPT_VERSION
    assert stage["model"] == CLOUDFLARE_COMPOSITE_VISION_MODEL


def test_stage_s_cache_identity_contains_required_fields(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setattr(provider_fabric, "cloudflare_stage_v_call", _stage_v)
    monkeypatch.setattr(provider_fabric, "cloudflare_stage_s_call", _stage_s)
    result = cloudflare_composite_visual_adapter(
        _request(), default_provider_registry()["cloudflare"], None, 1, lambda: 0
    )
    stage = result.diagnostics["_private_composite_checkpoint"]["stage_s"]
    assert stage["transcript_digest"]
    assert stage["schema_version"] == "1.0"
    assert stage["grounding_schema_version"] == CLOUDFLARE_GROUNDING_SCHEMA_VERSION
    assert stage["prompt_version"] == CLOUDFLARE_STRUCTURER_PROMPT_VERSION
    assert stage["model"] == CLOUDFLARE_PREFERRED_STRUCTURER_MODEL
    assert stage["raw_result_digest"]
    assert stage["assembled_wrapper_digest"]
    assert stage["raw_result_digest"] != stage["assembled_wrapper_digest"]


def test_both_stage_cache_hits_make_zero_provider_calls(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setattr(provider_fabric, "cloudflare_stage_v_call", _stage_v)
    monkeypatch.setattr(provider_fabric, "cloudflare_stage_s_call", _stage_s)
    spec = default_provider_registry()["cloudflare"]
    first = cloudflare_composite_visual_adapter(_request(), spec, None, 1, lambda: 0)
    checkpoint = first.diagnostics["_private_composite_checkpoint"]
    monkeypatch.setattr(provider_fabric, "cloudflare_stage_v_call", lambda *_: pytest.fail("network V"))
    monkeypatch.setattr(provider_fabric, "cloudflare_stage_s_call", lambda *_: pytest.fail("network S"))
    second = cloudflare_composite_visual_adapter(
        _request(checkpoint), spec, None, 1, lambda: 0
    )
    assert second.diagnostics["stage_v_cache_hit"] is True
    assert second.diagnostics["stage_s_cache_hit"] is True


def test_all_provider_unavailable_defers_cleanly(monkeypatch):
    _configure(monkeypatch)
    registry = default_provider_registry()
    registry["groq"] = replace(registry["groq"], enabled=False)
    registry["cloudflare"] = replace(registry["cloudflare"], enabled=False)
    registry["mistral"] = replace(registry["mistral"], enabled=False)
    with pytest.raises(ProviderPoolExhausted) as caught:
        ProviderFabric(registry=registry, adapters={}, env={}).route(
            _request(), deadline_monotonic=None, remaining_requests=1
        )
    assert caught.value.code == "VISUAL_PROVIDER_POOL_EXHAUSTED"


def test_infrastructure_failure_does_not_create_teacher_review_flood(monkeypatch):
    _configure(monkeypatch)
    region = {
        "page": 1, "question_refs": ["1.2"], "printed_text": "",
        "image_bytes": b"synthetic-composite-crop", "mime_type": "image/png",
        "asset_path": "synthetic/region-1.png",
    }
    monkeypatch.setattr(visual_evidence, "_render_regions", lambda *_: [region])

    def fail(*_args):
        raise ProviderError("AI_PROVIDER_RATE_LIMITED", "capacity", category="transient_capacity")

    fabric = ProviderFabric(
        registry={"cloudflare": default_provider_registry()["cloudflare"]},
        adapters={"cloudflare": fail},
        env={
            "CLOUDFLARE_ACCOUNT_ID": "configured",
            "CLOUDFLARE_AI_API_TOKEN": "configured",
            "CLOUDFLARE_ZERO_COST_CONFIRMED": "true",
        },
    )
    record, _ = visual_evidence.extract_visual_evidence(
        b"source", {"job_id": "synthetic", "source": {"sha256": "source-digest"},
                    "content": {"pages": [{"visual_inspection_required": True}]}},
        provider_fabric=fabric,
    )
    assert record["summary"]["infrastructure_deferred"] is True
    assert record["evidence"] == [] and record["mark_changes"] == []


def test_mistral_private_false_remains_enforced(monkeypatch):
    _configure(monkeypatch)
    mistral = default_provider_registry()["mistral"]
    assert provider_fabric.provider_ineligibility_reason(
        mistral,
        task_type="visual_interpretation",
        privacy_classification=PRIVACY_SCHOOL_PRIVATE,
        env={"MISTRAL_API_KEY": "configured", "MISTRAL_ZERO_COST_CONFIRMED": "true",
             "MISTRAL_SCHOOL_PRIVATE_APPROVED": "false"},
    ) in {"model_unconfigured", "privacy_ineligible"}


def test_paid_and_deprecated_structurers_are_excluded():
    visible = set(provider_fabric.CLOUDFLARE_PAID_ONLY_MODELS) | set(CLOUDFLARE_DEPRECATED_MODELS)
    assert select_cloudflare_structurer_model(visible) is None


def test_current_documented_active_structurer_is_preferred():
    visible = {
        CLOUDFLARE_PREFERRED_STRUCTURER_MODEL,
        "@cf/deepseek-ai/deepseek-r1-distill-qwen-32b",
    }
    assert select_cloudflare_structurer_model(visible) == CLOUDFLARE_PREFERRED_STRUCTURER_MODEL


def test_preview_only_capability_cannot_activate_model():
    preview_only = "@cf/example/preview-json-model"
    assert preview_only not in CLOUDFLARE_JSON_MODE_DOCUMENTED_MODELS
    assert select_cloudflare_structurer_model({preview_only}) is None


def test_direct_models_are_not_reenabled_by_composite_configuration(monkeypatch):
    _configure(monkeypatch)
    for model in provider_fabric.CLOUDFLARE_FREE_VISION_MODELS:
        assert "structured_visual" not in cloudflare_model_capabilities(model)


def test_composite_is_fallback_after_groq(monkeypatch):
    _configure(monkeypatch)
    registry = default_provider_registry()
    assert registry["groq"].priority < registry["cloudflare"].priority


def test_stage_prompts_lock_observer_and_structurer_roles():
    stage_v = provider_fabric.cloudflare_stage_v_prompt(_request())
    stage_s = provider_fabric.cloudflare_stage_s_prompt(TRANSCRIPT)
    assert "OBSERVER" in stage_v and "Do not solve" in stage_v
    assert "STRUCTURER, NOT A SOLVER" in stage_s
    assert TRANSCRIPT in stage_s
