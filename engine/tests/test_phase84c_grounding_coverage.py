from __future__ import annotations

import copy
import json

import pytest

from engine.src.memo_engine import (
    phase84c_cloudflare_composite_activation as activation,
    provider_fabric,
    visual_evidence,
)
from engine.src.memo_engine.ai_router import ProviderError
from engine.src.memo_engine.provider_fabric import (
    CLOUDFLARE_GROUNDING_SCHEMA_VERSION,
    CLOUDFLARE_STRUCTURER_PROMPT_VERSION,
    cloudflare_composite_visual_adapter,
    cloudflare_grounded_wrapper_schema,
    cloudflare_stage_s_prompt,
    default_provider_registry,
    enumerate_cloudflare_content_paths,
    enumerate_cloudflare_exempt_paths,
    validate_cloudflare_grounding,
)
from engine.tests.test_phase84c_cloudflare_composite import (
    TRANSCRIPT,
    _configure,
    _payload,
    _request,
    _stage_s,
    _stage_v,
    _wrapper,
)


def _without(wrapper: dict, path: str) -> dict:
    result = copy.deepcopy(wrapper)
    result["grounding"] = [
        item for item in result["grounding"] if item["path"] != path
    ]
    return result


def _missing_path(wrapper: dict, transcript: str, path: str) -> ProviderError:
    with pytest.raises(ProviderError) as caught:
        validate_cloudflare_grounding(_without(wrapper, path), transcript)
    assert caught.value.code == "AI_PROVIDER_GROUNDING_MISSING"
    assert caught.value.category == "content_request"
    assert path in caught.value.diagnostics["grounding_missing_paths"]
    return caught.value


def test_math_expression_present_without_grounding_fails_with_safe_path():
    error = _missing_path(
        _wrapper(), TRANSCRIPT, "/payload/evidence/0/normalized_math"
    )
    serialized = json.dumps(error.diagnostics, sort_keys=True)
    assert TRANSCRIPT not in serialized
    assert "10/250" not in serialized
    assert error.diagnostics["grounding_failure_category"] == "missing_coverage"


@pytest.mark.parametrize("item_index,label", [(0, "A"), (1, "B")])
def test_each_visible_label_requires_its_own_content_leaf_grounding(item_index, label):
    payload = _payload()
    payload["evidence"] = [
        {
            **payload["evidence"][1],
            "transcription": "A",
        },
        {
            **payload["evidence"][1],
            "transcription": "B",
        },
    ]
    transcript = "LABEL: Question 1.2\nLABEL: A\nLABEL: B\nROLE: visible solution evidence"
    wrapper = {
        "grounding_schema_version": CLOUDFLARE_GROUNDING_SCHEMA_VERSION,
        "payload": payload,
        "grounding": [
            {"path": "/payload/visual_content_present", "evidence_quote": "ROLE: visible solution evidence"},
            {"path": "/payload/evidence/0/question_ref", "evidence_quote": "LABEL: Question 1.2"},
            {"path": "/payload/evidence/0/transcription", "evidence_quote": "LABEL: A"},
            {"path": "/payload/evidence/1/question_ref", "evidence_quote": "LABEL: Question 1.2"},
            {"path": "/payload/evidence/1/transcription", "evidence_quote": "LABEL: B"},
        ],
    }
    _missing_path(
        wrapper, transcript, f"/payload/evidence/{item_index}/transcription"
    )


def test_relationship_present_without_grounding_fails():
    _missing_path(_wrapper(), TRANSCRIPT, "/payload/evidence/1/transcription")


def test_second_array_item_cannot_borrow_first_item_grounding():
    wrapper = _without(_wrapper(), "/payload/evidence/1/question_ref")
    wrapper = _without(wrapper, "/payload/evidence/1/transcription")
    with pytest.raises(ProviderError) as caught:
        validate_cloudflare_grounding(wrapper, TRANSCRIPT)
    assert caught.value.diagnostics["grounding_missing_count"] == 2


def test_parent_object_grounding_does_not_cover_child_leaves():
    wrapper = _wrapper()
    wrapper["grounding"].append({
        "path": "/payload/evidence/0",
        "evidence_quote": "MATH: 10/250 = 1/25 = 0.04 = 4%",
    })
    with pytest.raises(ProviderError) as caught:
        validate_cloudflare_grounding(wrapper, TRANSCRIPT)
    assert caught.value.code == "AI_PROVIDER_GROUNDING_CONTAINER_PATH"
    assert caught.value.diagnostics["grounding_container_paths"] == [
        "/payload/evidence/0"
    ]


def test_grounding_nonexistent_path_is_rejected():
    wrapper = _wrapper()
    wrapper["grounding"].append({
        "path": "/payload/evidence/9/transcription",
        "evidence_quote": "ROLE: visible solution evidence",
    })
    with pytest.raises(ProviderError) as caught:
        validate_cloudflare_grounding(wrapper, TRANSCRIPT)
    assert caught.value.code == "AI_PROVIDER_GROUNDING_PATH_UNKNOWN"
    assert caught.value.diagnostics["grounding_unknown_count"] == 1


def test_grounding_metadata_path_is_rejected():
    wrapper = _wrapper()
    wrapper["grounding"].append({
        "path": "/payload/evidence/0/confidence",
        "evidence_quote": "ROLE: visible solution evidence",
    })
    with pytest.raises(ProviderError) as caught:
        validate_cloudflare_grounding(wrapper, TRANSCRIPT)
    assert caught.value.code == "AI_PROVIDER_GROUNDING_METADATA_PATH"
    assert caught.value.diagnostics["grounding_exempt_paths"] == [
        "/payload/evidence/0/confidence"
    ]


def test_identical_duplicate_grounding_is_deduplicated_deterministically():
    wrapper = _wrapper()
    wrapper["grounding"].append(copy.deepcopy(wrapper["grounding"][1]))
    assert validate_cloudflare_grounding(wrapper, TRANSCRIPT) == _payload()


def test_conflicting_duplicate_grounding_is_rejected_without_quote_content():
    wrapper = _wrapper()
    wrapper["grounding"].append({
        "path": "/payload/evidence/0/transcription",
        "evidence_quote": "ROLE: visible solution evidence",
    })
    with pytest.raises(ProviderError) as caught:
        validate_cloudflare_grounding(wrapper, TRANSCRIPT)
    assert caught.value.code == "AI_PROVIDER_GROUNDING_DUPLICATE_CONFLICT"
    assert caught.value.diagnostics["grounding_conflicting_duplicate_count"] == 1
    assert "visible solution evidence" not in json.dumps(caught.value.diagnostics)


def test_exact_quote_absence_reports_only_safe_path_metadata():
    wrapper = _wrapper()
    wrapper["grounding"][1]["evidence_quote"] = "MATH: absent private content"
    with pytest.raises(ProviderError) as caught:
        validate_cloudflare_grounding(wrapper, TRANSCRIPT)
    assert caught.value.code == "AI_PROVIDER_GROUNDING_QUOTE_MISSING"
    assert caught.value.diagnostics["grounding_failure_category"] == "quote_absent"
    assert "absent private content" not in json.dumps(caught.value.diagnostics)


def test_numeric_token_mismatch_has_safe_failure_category():
    wrapper = _wrapper()
    wrapper["payload"]["evidence"][0]["normalized_math"] = "10/250 = 0.05"
    with pytest.raises(ProviderError) as caught:
        validate_cloudflare_grounding(wrapper, TRANSCRIPT)
    assert caught.value.code == "AI_PROVIDER_GROUNDING_UNSUPPORTED_NUMBER"
    assert caught.value.diagnostics["grounding_failure_category"] == "numeric_token_mismatch"


def test_relationship_quote_must_contain_both_entities_and_relation():
    transcript = TRANSCRIPT + "\nRELATION: A overlaps"
    wrapper = _wrapper()
    wrapper["grounding"][4]["evidence_quote"] = "RELATION: A overlaps"
    with pytest.raises(ProviderError) as caught:
        validate_cloudflare_grounding(wrapper, transcript)
    assert caught.value.code == "AI_PROVIDER_GROUNDING_UNSUPPORTED_CONTENT"
    assert caught.value.diagnostics["grounding_path"] == "/payload/evidence/1/transcription"


def test_complete_grounded_result_passes_production_schema():
    payload = validate_cloudflare_grounding(_wrapper(), TRANSCRIPT)
    region = {
        "page": 1,
        "asset_path": "synthetic/phase84c.png",
        "page_bbox": [0.0, 0.0, 100.0, 100.0],
        "render_bbox": [0.0, 0.0, 100.0, 100.0],
        "owned_bbox": [0.0, 0.0, 100.0, 100.0],
    }
    validated = visual_evidence.validate_visual_response(payload, region)
    assert len(validated["evidence"]) == 2
    assert validated["evidence"][1]["kind"] == "diagram_entry"


def test_optional_absent_and_empty_containers_need_no_grounding():
    requirements = enumerate_cloudflare_content_paths(_payload())
    assert "/payload/evidence/1/normalized_math" not in requirements
    assert not any(path.startswith("/payload/mark_changes/") for path in requirements)
    assert not any(path.startswith("/payload/warnings/") for path in requirements)


def test_current_production_payload_content_path_policy_is_complete_and_explicit():
    assert set(enumerate_cloudflare_content_paths(_payload())) == {
        "/payload/visual_content_present",
        "/payload/evidence/0/question_ref",
        "/payload/evidence/0/transcription",
        "/payload/evidence/0/normalized_math",
        "/payload/evidence/1/question_ref",
        "/payload/evidence/1/transcription",
    }


def test_metadata_fields_are_explicitly_exempt_without_grounding():
    exempt = enumerate_cloudflare_exempt_paths(_payload())
    assert "/payload/schema_version" in exempt
    assert "/payload/page" in exempt
    assert "/payload/evidence/0/kind" in exempt
    assert "/payload/evidence/0/confidence" in exempt
    assert "/payload/evidence/0/source" in exempt
    assert validate_cloudflare_grounding(_wrapper(), TRANSCRIPT) == _payload()


def test_nested_paths_use_indexed_json_pointer_and_rfc6901_escaping():
    payload = {"custom/key": [{"~label": "A"}]}
    requirements = enumerate_cloudflare_content_paths(payload)
    assert set(requirements) == {"/payload/custom~1key/0/~0label"}


def test_grounded_wrapper_schema_and_prompt_require_complete_leaf_mappings():
    schema = cloudflare_grounded_wrapper_schema(visual_evidence._vision_schema(1))
    assert schema["properties"]["grounding_schema_version"]["enum"] == [
        CLOUDFLARE_GROUNDING_SCHEMA_VERSION
    ]
    # Cloudflare JSON Mode receives a conservative transport schema. The
    # deterministic validator owns path syntax and duplicate enforcement.
    assert "uniqueItems" not in schema["properties"]["grounding"]
    assert "pattern" not in schema["properties"]["grounding"]["items"]["properties"]["path"]
    prompt = cloudflare_stage_s_prompt(TRANSCRIPT)
    assert "EVERY populated CONTENT-BEARING payload leaf" in prompt
    assert "Do not use a parent/container path" in prompt
    assert "/payload/evidence/*/confidence" in prompt


def test_old_stage_s_cache_is_invalidated_but_stage_v_is_reused(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setattr(provider_fabric, "cloudflare_stage_v_call", _stage_v)
    monkeypatch.setattr(provider_fabric, "cloudflare_stage_s_call", _stage_s)
    spec = default_provider_registry()["cloudflare"]
    first = cloudflare_composite_visual_adapter(_request(), spec, None, 1, lambda: 0)
    checkpoint = copy.deepcopy(first.diagnostics["_private_composite_checkpoint"])
    checkpoint["stage_s"]["prompt_version"] = "cloudflare-grounded-structurer-v1"
    checkpoint["stage_s"].pop("grounding_schema_version", None)
    calls = {"s": 0}

    monkeypatch.setattr(
        provider_fabric, "cloudflare_stage_v_call",
        lambda *_args: pytest.fail("unchanged Stage-V cache identity must be reused"),
    )

    def stage_s(*args):
        calls["s"] += 1
        return _stage_s(*args)

    monkeypatch.setattr(provider_fabric, "cloudflare_stage_s_call", stage_s)
    result = cloudflare_composite_visual_adapter(
        _request(checkpoint), spec, None, 1, lambda: 0
    )
    assert calls == {"s": 1}
    assert result.diagnostics["stage_v_cache_hit"] is True
    assert result.diagnostics["stage_s_cache_hit"] is False
    assert result.diagnostics["_private_composite_checkpoint"]["stage_s"][
        "prompt_version"
    ] == CLOUDFLARE_STRUCTURER_PROMPT_VERSION


def test_grounding_failure_is_content_contract_and_does_not_open_circuit(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setattr(provider_fabric, "cloudflare_stage_v_call", _stage_v)
    incomplete = _without(_wrapper(), "/payload/evidence/1/transcription")
    monkeypatch.setattr(
        provider_fabric, "cloudflare_stage_s_call",
        lambda *_args: {**_stage_s(), "wrapper": incomplete},
    )
    spec = default_provider_registry()["cloudflare"]
    fabric = provider_fabric.ProviderFabric(
        registry={"cloudflare": spec},
        adapters={"cloudflare": cloudflare_composite_visual_adapter},
        env={
            "CLOUDFLARE_ACCOUNT_ID": "configured",
            "CLOUDFLARE_AI_API_TOKEN": "configured",
            "CLOUDFLARE_ZERO_COST_CONFIRMED": "true",
        },
    )
    with pytest.raises(ProviderError) as caught:
        fabric.route(_request(), deadline_monotonic=None, remaining_requests=1)
    assert caught.value.category == "content_request"
    assert fabric.circuits == {}
    assert caught.value.route_attempts[0]["decision"] == "content_result"


def test_activation_failure_report_includes_paths_but_no_private_values():
    with pytest.raises(ProviderError) as caught:
        validate_cloudflare_grounding(
            _without(_wrapper(), "/payload/evidence/0/normalized_math"), TRANSCRIPT
        )
    report = activation._safe_failure(caught.value)
    assert report["grounding_missing_paths"] == [
        "/payload/evidence/0/normalized_math"
    ]
    serialized = json.dumps(report, sort_keys=True)
    assert TRANSCRIPT not in serialized
    assert "10/250" not in serialized
