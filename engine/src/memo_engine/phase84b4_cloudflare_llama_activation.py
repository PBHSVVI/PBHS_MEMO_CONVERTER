from __future__ import annotations

import json
import os
from dataclasses import replace
from pathlib import Path
from typing import Any

from . import visual_evidence
from .ai_router import ProviderError, _post_json
from .phase84b_benchmark import _region, _score, synthetic_fixtures
from .phase84b1_cloudflare_activation import list_account_models
from .provider_fabric import (
    CLOUDFLARE_LLAMA_STRUCTURED_VISION_MODEL,
    PRIVACY_SYNTHETIC_TEST,
    ProviderFabric,
    cloudflare_model_capabilities,
    cloudflare_visual_adapter,
    default_provider_registry,
)


REPORT_SCHEMA = "phase8.4b.4-cloudflare-llama-activation-v1"
API_ROOT = "https://api.cloudflare.com/client/v4"


def _safe_failure(exc: Exception) -> dict[str, Any]:
    return {
        "status": "failed",
        "error_code": getattr(exc, "code", type(exc).__name__),
        "category": getattr(exc, "category", None),
        "http_status": getattr(exc, "http_status", None),
        "provider_code": getattr(exc, "provider_code", None),
    }


def accept_meta_terms(account_id: str) -> dict[str, Any]:
    payload, _ = _post_json(
        f"{API_ROOT}/accounts/{account_id}/ai/run/{CLOUDFLARE_LLAMA_STRUCTURED_VISION_MODEL}",
        {"Authorization": f"Bearer {os.environ.get('CLOUDFLARE_AI_API_TOKEN', '').strip()}"},
        {"prompt": "agree"},
        timeout_seconds=30,
        remaining_requests=1,
        max_rate_retries=0,
        max_transient_retries=0,
    )
    success = payload.get("success") is True
    errors = payload.get("errors") if isinstance(payload.get("errors"), list) else []
    first = errors[0] if errors and isinstance(errors[0], dict) else {}
    return {
        "status": "accepted" if success else "failed",
        "http_status": 200,
        "success": success,
        "provider_code": first.get("code") if isinstance(first.get("code"), (str, int)) else None,
    }


def run() -> dict[str, Any]:
    account_id = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "").strip()
    if not account_id:
        raise RuntimeError("CLOUDFLARE_ACCOUNT_ID_MISSING")
    if os.environ.get("CLOUDFLARE_ZERO_COST_CONFIRMED", "").strip().lower() != "true":
        raise RuntimeError("CLOUDFLARE_ZERO_COST_NOT_CONFIRMED")
    if os.environ.get("MISTRAL_SCHOOL_PRIVATE_APPROVED", "").strip().lower() != "false":
        raise RuntimeError("MISTRAL_PRIVACY_GATE_NOT_FALSE")

    os.environ["MEMO_VISUAL_PROVIDER_RATE_RETRIES"] = "0"
    os.environ["MEMO_VISUAL_PROVIDER_TRANSIENT_RETRIES"] = "0"
    report: dict[str, Any] = {
        "schema": REPORT_SCHEMA,
        "synthetic_only": True,
        "model": CLOUDFLARE_LLAMA_STRUCTURED_VISION_MODEL,
        "visibility": None,
        "terms": None,
        "preflight": None,
        "cache_reuse": None,
        "failover": None,
        "run_path_requests": {"terms": 0, "synthetic_inference": 0, "total": 0},
        "zero_cost": {
            "confirmation": True,
            "plan_mode": "free_only",
            "billable_spend": 0,
            "paid_feature_enabled_by_run": False,
        },
    }

    cards, total, status = list_account_models(account_id)
    visible = CLOUDFLARE_LLAMA_STRUCTURED_VISION_MODEL in {card["id"] for card in cards}
    report["visibility"] = {
        "visible": visible,
        "http_status": status,
        "account_visible_model_count": total,
    }
    if not visible:
        return report

    report["run_path_requests"]["terms"] = 1
    report["run_path_requests"]["total"] = 1
    try:
        report["terms"] = accept_meta_terms(account_id)
    except Exception as exc:
        report["terms"] = _safe_failure(exc)
        return report
    if report["terms"].get("status") != "accepted":
        return report

    registry = default_provider_registry()
    llama = replace(
        registry["cloudflare"],
        model_id=CLOUDFLARE_LLAMA_STRUCTURED_VISION_MODEL,
        capabilities=cloudflare_model_capabilities(CLOUDFLARE_LLAMA_STRUCTURED_VISION_MODEL),
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

    def counted_cloudflare(*args: Any) -> Any:
        nonlocal calls
        calls += 1
        result = cloudflare_visual_adapter(*args)
        captured.append(result)
        return result

    env = {
        "GROQ_API_KEY": "synthetic-unavailable",
        "GROQ_ZERO_COST_CONFIRMED": "true",
        "CLOUDFLARE_ACCOUNT_ID": account_id,
        "CLOUDFLARE_AI_API_TOKEN": os.environ.get("CLOUDFLARE_AI_API_TOKEN", ""),
        "CLOUDFLARE_ZERO_COST_CONFIRMED": "true",
    }
    original_render = visual_evidence._render_regions
    visual_evidence._render_regions = lambda *_args, **_kwargs: [region]
    try:
        report["run_path_requests"]["synthetic_inference"] = 1
        report["run_path_requests"]["total"] = 2
        first_record, _ = visual_evidence.extract_visual_evidence(
            b"phase84b4-llama-cache-source",
            {"job_id": "synthetic-phase84b4", "source": {}, "content": {
                "pages": [{"visual_inspection_required": True}]
            }},
            provider_fabric=ProviderFabric(
                registry={"groq": groq, "cloudflare": llama},
                adapters={"groq": groq_unavailable, "cloudflare": counted_cloudflare},
                env=env,
            ),
            privacy_classification=PRIVACY_SYNTHETIC_TEST,
        )
        attempts = first_record.get("provider_attempts") or []
        successful = [item for item in first_record.get("runs", []) if item.get("status") == "success"]
        if not successful or not captured:
            failed = next((item for item in reversed(attempts) if item.get("status") == "failed"), {})
            report["preflight"] = {
                "status": "failed",
                "error_code": failed.get("error_code"),
                "error_category": failed.get("error_category"),
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
            "provider": result.provider_id,
            "model": result.model_id,
            "provider_status": result.status,
            "result_digest_present": bool(result.result_digest),
            "usage": score["usage"],
            "response_path": result.diagnostics.get("response_path"),
            "schema_valid": score["schema_valid"],
            "tokens_recovered": score["tokens_recovered"],
            "hallucinated_values": score["hallucinated_values"],
            "content_quality": score["status"],
            "evidence_count": score["evidence_count"],
        }
        report["failover"] = {
            "passed": any(
                item.get("provider") == "groq" and item.get("status") == "failed"
                for item in attempts
            ) and result.provider_id == "cloudflare",
            "selected_provider": result.provider_id,
            "extra_inference_calls": 0,
        }
        before_cache = calls
        second_record, _ = visual_evidence.extract_visual_evidence(
            b"phase84b4-llama-cache-source",
            {"job_id": "synthetic-phase84b4", "source": {}, "content": {
                "pages": [{"visual_inspection_required": True}]
            }},
            provider_fabric=ProviderFabric(
                registry={"cloudflare": replace(llama, priority=0)},
                adapters={"cloudflare": counted_cloudflare},
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
    report["run_path_requests"]["synthetic_inference"] = calls
    report["run_path_requests"]["total"] = 1 + calls
    return report


def main() -> int:
    report = run()
    path = Path(os.environ.get("PHASE84B4_REPORT_PATH", "phase84b4-report.json"))
    path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    preflight = report.get("preflight") or {}
    summary = {
        "visible": (report.get("visibility") or {}).get("visible"),
        "terms": (report.get("terms") or {}).get("status"),
        "preflight": preflight.get("status"),
        "content_quality": preflight.get("content_quality"),
        "cache_reuse": (report.get("cache_reuse") or {}).get("passed"),
        "failover": (report.get("failover") or {}).get("passed"),
        "run_path_requests": report.get("run_path_requests"),
        "billable_spend": 0,
    }
    print("PHASE84B4_SAFE_SUMMARY=" + json.dumps(summary, sort_keys=True))
    passed = all((
        summary["visible"] is True,
        summary["terms"] == "accepted",
        summary["preflight"] == "success",
        summary["content_quality"] == "pass",
        summary["cache_reuse"] is True,
        summary["failover"] is True,
        summary["run_path_requests"] == {"terms": 1, "synthetic_inference": 1, "total": 2},
    ))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
