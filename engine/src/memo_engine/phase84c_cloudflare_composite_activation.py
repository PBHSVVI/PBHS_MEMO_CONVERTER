from __future__ import annotations

import hashlib
import io
import json
import os
import re
from dataclasses import replace
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from . import provider_fabric, visual_evidence
from .ai_router import ProviderError
from .phase84b1_cloudflare_activation import list_account_models
from .provider_fabric import (
    CLOUDFLARE_PREFERRED_STRUCTURER_MODEL,
    PRIVACY_SYNTHETIC_TEST,
    ProviderFabric,
    ProviderResult,
    ProviderTaskRequest,
    default_provider_registry,
    select_cloudflare_structurer_model,
    select_cloudflare_transcript_model,
)


REPORT_SCHEMA = "phase8.4c-cloudflare-composite-live-proof-v1"


def _font(size: int) -> ImageFont.ImageFont:
    for path in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ):
        try:
            return ImageFont.truetype(path, size=size)
        except OSError:
            pass
    return ImageFont.load_default()


def synthetic_composite_fixture() -> dict[str, Any]:
    image = Image.new("RGB", (900, 480), "white")
    draw = ImageDraw.Draw(image)
    draw.text((30, 22), "Q1.2", fill="#25334A", font=_font(34))
    draw.text((48, 95), "10/250 = 1/25 = 0.04 = 4%", fill="#9A1D2E", font=_font(35))
    draw.text((48, 165), "Visible solution evidence", fill="#25334A", font=_font(22))
    draw.ellipse((145, 225, 455, 450), outline="#9A1D2E", width=5)
    draw.ellipse((350, 225, 660, 450), outline="#1F6B4F", width=5)
    draw.text((235, 250), "A", fill="#9A1D2E", font=_font(32))
    draw.text((545, 250), "B", fill="#1F6B4F", font=_font(32))
    draw.text((390, 335), "3", fill="#25334A", font=_font(36))
    stream = io.BytesIO()
    image.save(stream, format="PNG", optimize=True)
    return {
        "id": "equation_and_overlap",
        "question_ref": "1.2",
        "image": stream.getvalue(),
        "width": image.width,
        "height": image.height,
    }


def _request(fixture: dict[str, Any], checkpoint=None) -> ProviderTaskRequest:
    digest = hashlib.sha256(fixture["image"]).hexdigest()
    return ProviderTaskRequest(
        task_type="visual_interpretation",
        region_id="synthetic/phase84c/equation-and-overlap.png",
        current_question_owner=fixture["question_ref"],
        source_question=fixture["question_ref"],
        source_page=1,
        source_digest=digest,
        crop_digest=digest,
        crop_bytes=fixture["image"],
        crop_mime_type="image/png",
        interpretation_schema_version=visual_evidence.SCHEMA_VERSION,
        task_prompt_version=visual_evidence.VISUAL_TASK_PROMPT_VERSION,
        privacy_classification=PRIVACY_SYNTHETIC_TEST,
        prompt=visual_evidence.visual_system_prompt(),
        response_schema=visual_evidence._vision_schema(1),
        provider_checkpoint=checkpoint,
    )


def _region(fixture: dict[str, Any]) -> dict[str, Any]:
    bounds = [0.0, 0.0, float(fixture["width"]), float(fixture["height"])]
    return {
        "asset_path": "synthetic/phase84c/equation-and-overlap.png",
        "page": 1,
        "image_bytes": fixture["image"],
        "mime_type": "image/png",
        "question_refs": [fixture["question_ref"]],
        "printed_text": "",
        "region_index": 0,
        "page_bbox": bounds,
        "render_bbox": bounds,
        "owned_bbox": bounds,
        "pixel_width": fixture["width"],
        "pixel_height": fixture["height"],
    }


def _numbers(value: str) -> set[str]:
    return set(re.findall(r"(?<![A-Za-z])\d+(?:[.,]\d+)?", value))


def assess_stage_v_transcript(transcript: str) -> dict[str, Any]:
    compact = " ".join(transcript.split())
    math_compact = re.sub(r"\s+", "", compact).replace(",", ".")
    recovered = {
        "10": "10" in math_compact,
        "250": "250" in math_compact,
        "1/25": "1/25" in math_compact,
        "0.04": "0.04" in math_compact,
        "4%": "4%" in math_compact,
        "label_A": re.search(r"\bA\b", compact) is not None,
        "label_B": re.search(r"\bB\b", compact) is not None,
        "overlap_relation": re.search(r"\b(overlap|intersection|intersect|shared)\b", compact, re.I) is not None,
    }
    # The deterministic fixture contains two overlapping circles.  A vision
    # transcript may state that visible cardinality as "2" even though the
    # numeral is not printed inside the crop.
    allowed = {"10", "250", "1", "25", "0.04", "4", "1.2", "2", "3"}
    unexpected = sorted(_numbers(compact) - allowed)
    return {
        "status": "pass" if all(recovered.values()) and not unexpected else (
            "partial" if any(recovered.values()) else "fail"
        ),
        "recovered": recovered,
        "unexpected_numbers": unexpected,
        "transcript_digest": hashlib.sha256(transcript.encode("utf-8")).hexdigest(),
        "transcript_length": len(transcript),
    }


def _safe_failure(exc: Exception) -> dict[str, Any]:
    diagnostics = getattr(exc, "diagnostics", None)
    return {
        "status": "failed",
        "error_code": getattr(exc, "code", type(exc).__name__),
        "category": getattr(exc, "category", None),
        "http_status": getattr(exc, "http_status", None),
        "provider_code": getattr(exc, "provider_code", None),
        "composite_stage": diagnostics.get("composite_stage") if isinstance(diagnostics, dict) else None,
    }


def discover() -> dict[str, Any]:
    account_id = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "").strip()
    if not account_id or not os.environ.get("CLOUDFLARE_AI_API_TOKEN", "").strip():
        raise RuntimeError("CLOUDFLARE_CREDENTIALS_MISSING")
    if os.environ.get("CLOUDFLARE_ZERO_COST_CONFIRMED", "").strip().lower() != "true":
        raise RuntimeError("CLOUDFLARE_ZERO_COST_NOT_CONFIRMED")
    if os.environ.get("MISTRAL_SCHOOL_PRIVATE_APPROVED", "").strip().lower() != "false":
        raise RuntimeError("MISTRAL_PRIVACY_GATE_NOT_FALSE")
    cards, total, status = list_account_models(account_id)
    visible = {str(item["id"]) for item in cards}
    vision_model = select_cloudflare_transcript_model(visible)
    structurer_model = select_cloudflare_structurer_model(visible)
    return {
        "schema": REPORT_SCHEMA,
        "discovery_only": True,
        "http_status": status,
        "account_visible_model_count": total,
        "vision_model": vision_model,
        "vision_model_visible": vision_model in visible if vision_model else False,
        "structurer_model": structurer_model,
        "structurer_model_visible": structurer_model in visible if structurer_model else False,
        "structurer_active": bool(structurer_model),
        "structurer_free_only": bool(structurer_model),
        "agreement_calls": 0,
        "inference_calls": 0,
    }


def run() -> dict[str, Any]:
    discovery = discover()
    report: dict[str, Any] = {
        **discovery,
        "discovery_only": False,
        "privacy_classification": PRIVACY_SYNTHETIC_TEST,
        "stage_v": None,
        "stage_s": None,
        "grounding": None,
        "production_schema": None,
        "provider_result": None,
        "checkpoint": None,
        "cache_replay": None,
        "failover": None,
        "content_quality": None,
        "zero_cost": {
            "confirmation": True,
            "plan_mode": "free_only",
            "billable_spend": 0,
            "paid_feature_enabled_by_run": False,
        },
    }
    vision_model = discovery.get("vision_model")
    structurer_model = discovery.get("structurer_model")
    if not vision_model or not structurer_model:
        report["status"] = "discovery_failed"
        return report

    os.environ["MEMO_CLOUDFLARE_VISION_MODEL"] = str(vision_model)
    os.environ["MEMO_CLOUDFLARE_STRUCTURER_MODEL"] = str(structurer_model)
    os.environ["MEMO_CLOUDFLARE_COMPOSITE_VISUAL_ENABLED"] = "true"
    os.environ["MEMO_VISUAL_PROVIDER_RATE_RETRIES"] = "0"
    os.environ["MEMO_VISUAL_PROVIDER_TRANSIENT_RETRIES"] = "0"
    fixture = synthetic_composite_fixture()
    request = _request(fixture)
    spec = default_provider_registry()["cloudflare"]
    calls = {"stage_v": 0, "stage_s": 0}
    captures: dict[str, Any] = {}
    original_v = provider_fabric.cloudflare_stage_v_call
    original_s = provider_fabric.cloudflare_stage_s_call

    def bounded_v(*args: Any) -> Any:
        if calls["stage_v"] >= 1:
            raise RuntimeError("PHASE84C_STAGE_V_BUDGET_EXCEEDED")
        calls["stage_v"] += 1
        value = original_v(*args)
        quality = assess_stage_v_transcript(value["transcript"])
        captures["stage_v_quality"] = quality
        if quality["status"] != "pass":
            raise ProviderError(
                "AI_PROVIDER_TRANSCRIPT_CONTENT_QUALITY_FAILED",
                "The vision transcript was not materially usable.",
                retryable=False,
                category="content_request",
                diagnostics={"composite_stage": "visual_evidence"},
            )
        return value

    def bounded_s(*args: Any) -> Any:
        if calls["stage_s"] >= 1:
            raise RuntimeError("PHASE84C_STAGE_S_BUDGET_EXCEEDED")
        calls["stage_s"] += 1
        value = original_s(*args)
        captures["stage_s_wrapper_type"] = type(value.get("wrapper")).__name__
        return value

    provider_fabric.cloudflare_stage_v_call = bounded_v
    provider_fabric.cloudflare_stage_s_call = bounded_s
    result: ProviderResult | None = None
    try:
        result = provider_fabric.cloudflare_composite_visual_adapter(
            request, spec, None, 1, lambda: 0
        )
    except Exception as exc:
        report["status"] = "failed"
        failure = _safe_failure(exc)
        if calls["stage_s"]:
            report["stage_s"] = failure
        else:
            report["stage_v"] = failure
        if captures.get("stage_v_quality"):
            report["stage_v"] = {
                **(report.get("stage_v") or {}),
                **captures["stage_v_quality"],
            }
        report["inference_calls"] = sum(calls.values())
        return report
    finally:
        provider_fabric.cloudflare_stage_v_call = original_v
        provider_fabric.cloudflare_stage_s_call = original_s

    report["inference_calls"] = sum(calls.values())
    checkpoint = result.diagnostics.get("_private_composite_checkpoint")
    stage_v = checkpoint["stage_v"]
    stage_s = checkpoint["stage_s"]
    report["stage_v"] = {
        "status": "success",
        "model": stage_v["model"],
        "response_path": stage_v.get("response_path"),
        "usage": stage_v.get("usage") or {},
        **captures["stage_v_quality"],
    }
    report["stage_s"] = {
        "status": "success",
        "model": stage_s["model"],
        "response_path": stage_s.get("response_path"),
        "json_result": captures.get("stage_s_wrapper_type"),
        "usage": stage_s.get("usage") or {},
        "wrapper_digest_present": bool(stage_s.get("wrapper_digest")),
    }
    report["grounding"] = {"status": result.diagnostics.get("grounding_status")}
    try:
        validated = visual_evidence.validate_visual_response(
            {**result.normalized_result, "provider": "cloudflare", "model": result.model_id},
            _region(fixture),
        )
        schema_passed = True
    except Exception as exc:
        report["production_schema"] = _safe_failure(exc)
        report["status"] = "failed"
        return report
    report["production_schema"] = {"status": "passed", "evidence_count": len(validated["evidence"])}
    report["provider_result"] = {
        "created": True,
        "provider": result.provider_id,
        "model": result.model_id,
        "status": result.status,
        "result_digest_present": bool(result.result_digest),
        "vision_model": result.diagnostics.get("vision_model"),
        "structurer_model": result.diagnostics.get("structurer_model"),
        "both_stage_digests_present": bool(
            result.diagnostics.get("vision_transcript_digest")
            and result.diagnostics.get("structurer_result_digest")
        ),
    }
    evidence_text = " ".join(
        f"{item.get('transcription') or ''} {item.get('normalized_math') or ''}"
        for item in validated["evidence"]
    )
    final_quality = assess_stage_v_transcript(evidence_text)
    diagram_present = any(item.get("kind") == "diagram_entry" for item in validated["evidence"])
    final_quality["diagram_entry_present"] = diagram_present
    final_quality["status"] = (
        "pass" if final_quality["status"] == "pass" and diagram_present and schema_passed
        else "partial" if validated["evidence"] else "fail"
    )
    report["content_quality"] = final_quality
    report["checkpoint"] = {
        "persisted": bool(checkpoint and checkpoint.get("final", {}).get("result_digest")),
        "vision_transcript_digest_present": bool(stage_v.get("transcript_digest")),
        "structurer_result_digest_present": bool(stage_s.get("wrapper_digest")),
    }

    def prohibit_v(*_args: Any) -> Any:
        raise RuntimeError("PHASE84C_SECOND_STAGE_V_CALL_BLOCKED")

    def prohibit_s(*_args: Any) -> Any:
        raise RuntimeError("PHASE84C_SECOND_STAGE_S_CALL_BLOCKED")

    provider_fabric.cloudflare_stage_v_call = prohibit_v
    provider_fabric.cloudflare_stage_s_call = prohibit_s
    before_cache = dict(calls)
    cached_request = replace(request, provider_checkpoint=checkpoint)
    cached = provider_fabric.cloudflare_composite_visual_adapter(
        cached_request, spec, None, 1, lambda: 0
    )
    report["cache_replay"] = {
        "passed": calls == before_cache,
        "new_stage_v_calls": calls["stage_v"] - before_cache["stage_v"],
        "new_stage_s_calls": calls["stage_s"] - before_cache["stage_s"],
        "same_result_digest": cached.result_digest == result.result_digest,
    }

    def groq_unavailable(*_args: Any) -> Any:
        raise ProviderError(
            "AI_PROVIDER_TEST_UNAVAILABLE", "Synthetic Groq unavailable.",
            category="transient_capacity",
        )

    registry = default_provider_registry()
    groq = replace(registry["groq"], enabled=True, priority=0)
    cloudflare = replace(registry["cloudflare"], enabled=True, priority=1)
    env = {
        "GROQ_API_KEY": "synthetic-unavailable",
        "GROQ_ZERO_COST_CONFIRMED": "true",
        "CLOUDFLARE_ACCOUNT_ID": os.environ["CLOUDFLARE_ACCOUNT_ID"],
        "CLOUDFLARE_AI_API_TOKEN": os.environ["CLOUDFLARE_AI_API_TOKEN"],
        "CLOUDFLARE_ZERO_COST_CONFIRMED": "true",
    }
    before_failover = dict(calls)
    routed = ProviderFabric(
        registry={"groq": groq, "cloudflare": cloudflare},
        adapters={
            "groq": groq_unavailable,
            "cloudflare": provider_fabric.cloudflare_composite_visual_adapter,
        },
        env=env,
    ).route(cached_request, deadline_monotonic=None, remaining_requests=1)
    report["failover"] = {
        "passed": routed.provider_id == "cloudflare" and calls == before_failover,
        "selected_provider": routed.provider_id,
        "groq_unavailable": any(
            item.get("provider") == "groq" and item.get("status") == "failed"
            for item in routed.route_attempts
        ),
        "new_stage_v_calls": calls["stage_v"] - before_failover["stage_v"],
        "new_stage_s_calls": calls["stage_s"] - before_failover["stage_s"],
    }
    provider_fabric.cloudflare_stage_v_call = original_v
    provider_fabric.cloudflare_stage_s_call = original_s
    report["status"] = "passed" if all((
        calls == {"stage_v": 1, "stage_s": 1},
        report["content_quality"]["status"] == "pass",
        report["grounding"]["status"] == "passed",
        report["production_schema"]["status"] == "passed",
        report["cache_replay"]["passed"],
        report["failover"]["passed"],
    )) else "failed"
    return report


def main() -> int:
    report = discover() if os.environ.get("PHASE84C_DISCOVERY_ONLY") == "true" else run()
    path = Path(os.environ.get("PHASE84C_REPORT_PATH", "phase84c-report.json"))
    path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    summary = {
        "discovery_only": report.get("discovery_only"),
        "vision_model": report.get("vision_model"),
        "structurer_model": report.get("structurer_model"),
        "status": report.get("status"),
        "stage_v": (report.get("stage_v") or {}).get("status"),
        "stage_s": (report.get("stage_s") or {}).get("status"),
        "content_quality": (report.get("content_quality") or {}).get("status"),
        "agreement_calls": report.get("agreement_calls"),
        "inference_calls": report.get("inference_calls"),
        "billable_spend": 0,
    }
    print("PHASE84C_SAFE_SUMMARY=" + json.dumps(summary, sort_keys=True))
    if report.get("discovery_only"):
        return 0 if report.get("vision_model") and report.get("structurer_model") else 1
    return 0 if report.get("status") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
