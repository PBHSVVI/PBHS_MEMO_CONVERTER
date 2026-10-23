from __future__ import annotations

import json
import os
from dataclasses import replace
from pathlib import Path
from typing import Any

from . import visual_evidence
from .ai_router import ProviderError
from .phase84b_benchmark import _region, _score, synthetic_fixtures
from .provider_fabric import (
    CLOUDFLARE_LLAMA_STRUCTURED_VISION_MODEL,
    PRIVACY_SYNTHETIC_TEST,
    ProviderFabric,
    cloudflare_model_capabilities,
    cloudflare_visual_adapter,
    default_provider_registry,
)


REPORT_SCHEMA = "phase8.4b.5-cloudflare-llama-live-proof-v1"


def _safe_failure(exc: Exception) -> dict[str, Any]:
    diagnostics = getattr(exc, "diagnostics", None)
    return {
        "status": "failed",
        "error_code": getattr(exc, "code", type(exc).__name__),
        "category": getattr(exc, "category", None),
        "http_status": getattr(exc, "http_status", None),
        "provider_code": getattr(exc, "provider_code", None),
        "provider_success": diagnostics.get("provider_success") if isinstance(diagnostics, dict) else None,
        "response_path": diagnostics.get("response_path") if isinstance(diagnostics, dict) else None,
        "normalization_stage": diagnostics.get("normalization_stage") if isinstance(diagnostics, dict) else None,
    }


def run() -> dict[str, Any]:
    account_id = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "").strip()
    token = os.environ.get("CLOUDFLARE_AI_API_TOKEN", "").strip()
    if not account_id or not token:
        raise RuntimeError("CLOUDFLARE_CREDENTIALS_MISSING")
    if os.environ.get("CLOUDFLARE_ZERO_COST_CONFIRMED", "").strip().lower() != "true":
        raise RuntimeError("CLOUDFLARE_ZERO_COST_NOT_CONFIRMED")
    if os.environ.get("MISTRAL_SCHOOL_PRIVATE_APPROVED", "").strip().lower() != "false":
        raise RuntimeError("MISTRAL_PRIVACY_GATE_NOT_FALSE")

    # This live proof has a hard one-request ceiling and no retry path.
    os.environ["MEMO_VISUAL_PROVIDER_RATE_RETRIES"] = "0"
    os.environ["MEMO_VISUAL_PROVIDER_TRANSIENT_RETRIES"] = "0"
    os.environ["MEMO_VISION_REQUEST_TIMEOUT_SECONDS"] = "75"

    capabilities = cloudflare_model_capabilities(CLOUDFLARE_LLAMA_STRUCTURED_VISION_MODEL)
    report: dict[str, Any] = {
        "schema": REPORT_SCHEMA,
        "synthetic_only": True,
        "privacy_classification": PRIVACY_SYNTHETIC_TEST,
        "model": CLOUDFLARE_LLAMA_STRUCTURED_VISION_MODEL,
        "capabilities": {name: name in capabilities for name in (
            "vision", "structured_json", "structured_visual", "free_only", "school_private"
        )},
        "transport": {
            "messages": True,
            "top_level_image": True,
            "raw_json_schema": True,
            "stream": False,
            "rate_retries": 0,
            "transient_retries": 0,
        },
        "agreement_calls": 0,
        "inference_calls": 0,
        "preflight": None,
        "checkpoint": None,
        "cache_reuse": None,
        "failover": None,
        "zero_cost": {
            "confirmation": True,
            "plan_mode": "free_only",
            "billable_spend": 0,
            "paid_feature_enabled_by_run": False,
        },
    }

    registry = default_provider_registry()
    llama = replace(
        registry["cloudflare"],
        model_id=CLOUDFLARE_LLAMA_STRUCTURED_VISION_MODEL,
        capabilities=capabilities,
        enabled=True,
        priority=1,
    )
    groq = replace(registry["groq"], enabled=True, priority=0)
    fixture = synthetic_fixtures()[0]
    region = _region(fixture)
    calls = 0
    captured = []

    def groq_unavailable(*_args: Any) -> Any:
        raise ProviderError(
            "AI_PROVIDER_TEST_UNAVAILABLE",
            "Synthetic qualification deliberately marked Groq unavailable.",
            category="transient_capacity",
        )

    def one_call_cloudflare(*args: Any) -> Any:
        nonlocal calls
        if calls >= 1:
            raise RuntimeError("PHASE84B5_INFERENCE_BUDGET_EXCEEDED")
        calls += 1
        result = cloudflare_visual_adapter(*args)
        captured.append(result)
        return result

    env = {
        "GROQ_API_KEY": "synthetic-unavailable",
        "GROQ_ZERO_COST_CONFIRMED": "true",
        "CLOUDFLARE_ACCOUNT_ID": account_id,
        "CLOUDFLARE_AI_API_TOKEN": token,
        "CLOUDFLARE_ZERO_COST_CONFIRMED": "true",
    }
    normalized = {
        "job_id": "synthetic-phase84b5",
        "source": {},
        "content": {"pages": [{"visual_inspection_required": True}]},
    }
    original_render = visual_evidence._render_regions
    visual_evidence._render_regions = lambda *_args, **_kwargs: [region]
    try:
        first_record, _ = visual_evidence.extract_visual_evidence(
            b"phase84b5-llama-cache-source",
            normalized,
            provider_fabric=ProviderFabric(
                registry={"groq": groq, "cloudflare": llama},
                adapters={"groq": groq_unavailable, "cloudflare": one_call_cloudflare},
                env=env,
            ),
            privacy_classification=PRIVACY_SYNTHETIC_TEST,
        )
        report["inference_calls"] = calls
        attempts = first_record.get("provider_attempts") or []
        successful = [item for item in first_record.get("runs", []) if item.get("status") == "success"]
        report["failover"] = {
            "passed": any(
                item.get("provider") == "groq" and item.get("status") == "failed"
                for item in attempts
            ) and bool(captured) and captured[-1].provider_id == "cloudflare",
            "selected_provider": captured[-1].provider_id if captured else None,
            "extra_inference_calls": 0,
        }
        if not successful or not captured:
            failed = next((item for item in reversed(attempts) if item.get("status") == "failed"), {})
            report["preflight"] = {
                "status": "failed",
                "error_code": failed.get("error_code"),
                "category": failed.get("error_category"),
                "http_status": failed.get("http_status"),
                "provider_success": failed.get("provider_success"),
                "response_path": failed.get("response_path"),
                "normalization_stage": failed.get("normalization_stage"),
            }
            return report

        result = captured[-1]
        score = _score(fixture, result)
        report["preflight"] = {
            "status": "success",
            "http_result": "accepted_2xx",
            "provider": result.provider_id,
            "model": result.model_id,
            "provider_status": result.status,
            "provider_success": result.diagnostics.get("provider_success"),
            "result_exists": result.diagnostics.get("result_exists"),
            "result_keys": result.diagnostics.get("result_keys"),
            "response_type": result.diagnostics.get("response_type"),
            "response_path": result.diagnostics.get("response_path"),
            "normalization_stage": result.diagnostics.get("normalization_stage"),
            "parsed_value_type": type(result.normalized_result).__name__,
            "json_parsed": isinstance(result.normalized_result, dict),
            "schema_valid": score["schema_valid"],
            "provider_result_created": True,
            "result_digest_present": bool(result.result_digest),
            "usage": score["usage"],
            "tokens_recovered": score["tokens_recovered"],
            "hallucinated_values": score["hallucinated_values"],
            "content_quality": score["status"],
            "evidence_count": score["evidence_count"],
        }
        report["checkpoint"] = {
            "persisted": bool(successful[0].get("result_digest")),
            "source_digest_present": bool(successful[0].get("source_digest")),
            "crop_digest_present": bool(successful[0].get("crop_digest")),
            "prompt_version_present": bool(successful[0].get("task_prompt_version")),
            "schema_version_present": bool(successful[0].get("interpretation_schema_version")),
        }
        before_cache = calls
        second_record, _ = visual_evidence.extract_visual_evidence(
            b"phase84b5-llama-cache-source",
            normalized,
            provider_fabric=ProviderFabric(
                registry={"groq": groq, "cloudflare": llama},
                adapters={"groq": groq_unavailable, "cloudflare": one_call_cloudflare},
                env=env,
            ),
            privacy_classification=PRIVACY_SYNTHETIC_TEST,
            checkpoint_record=first_record,
        )
        report["cache_reuse"] = {
            "passed": calls == before_cache,
            "second_inference_calls": calls - before_cache,
            "reused_success_count": second_record["summary"]["reused_success_count"],
        }
    except Exception as exc:
        report["preflight"] = _safe_failure(exc)
    finally:
        visual_evidence._render_regions = original_render
        report["inference_calls"] = calls
    return report


def main() -> int:
    report = run()
    path = Path(os.environ.get("PHASE84B5_REPORT_PATH", "phase84b5-report.json"))
    path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    preflight = report.get("preflight") or {}
    summary = {
        "agreement_calls": report.get("agreement_calls"),
        "inference_calls": report.get("inference_calls"),
        "preflight": preflight.get("status"),
        "content_quality": preflight.get("content_quality"),
        "cache_reuse": (report.get("cache_reuse") or {}).get("passed"),
        "failover": (report.get("failover") or {}).get("passed"),
        "billable_spend": 0,
    }
    print("PHASE84B5_SAFE_SUMMARY=" + json.dumps(summary, sort_keys=True))
    passed = all((
        summary["agreement_calls"] == 0,
        summary["inference_calls"] == 1,
        summary["preflight"] == "success",
        summary["content_quality"] == "pass",
        summary["cache_reuse"] is True,
        summary["failover"] is True,
    ))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
