from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import replace
from pathlib import Path
from typing import Any

from . import visual_evidence
from .ai_router import ProviderError
from .phase84b_benchmark import _region, synthetic_fixtures
from .provider_fabric import (
    CLOUDFLARE_FREE_VISION_MODELS,
    PRIVACY_SYNTHETIC_TEST,
    ProviderFabric,
    ProviderPoolExhausted,
    cloudflare_visual_adapter,
    default_provider_registry,
)


REPORT_SCHEMA = "phase8.4b.1-cloudflare-activation-v1"
API_ROOT = "https://api.cloudflare.com/client/v4"
MODEL_PRIORITY = (
    "@cf/google/gemma-4-26b-a4b-it",
    "@cf/qwen/qwen3.8-27b",
)


class CloudflareDiagnosticError(RuntimeError):
    def __init__(
        self,
        code: str,
        *,
        http_status: int | None = None,
        provider_code: int | str | None = None,
        provider_message: str | None = None,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.http_status = http_status
        self.provider_code = provider_code
        self.provider_message = _safe_message(provider_message)


def _safe_message(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = " ".join(value.split())[:300]
    lowered = value.lower()
    if any(term in lowered for term in ("bearer ", "authorization", "api key", "token=")):
        return "Cloudflare returned a redacted credential-related message."
    return re.sub(
        r"(?i)(/accounts/)[0-9a-f]{16,64}",
        r"\1<redacted-account>",
        value,
    )


def _safe_errors(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    errors = payload.get("errors")
    if not isinstance(errors, list):
        error = payload.get("error")
        errors = [error] if isinstance(error, dict) else []
    result = []
    for item in errors[:5]:
        if not isinstance(item, dict):
            continue
        result.append({
            "code": item.get("code") if isinstance(item.get("code"), (int, str)) else None,
            "message": _safe_message(item.get("message")),
        })
    return result


def _get_json(path: str, *, query: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
    token = os.environ.get("CLOUDFLARE_AI_API_TOKEN", "").strip()
    if not token:
        raise CloudflareDiagnosticError("CLOUDFLARE_TOKEN_MISSING")
    url = API_ROOT + path
    if query:
        url += "?" + urllib.parse.urlencode(query)
    request = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
            return int(response.status), payload
    except urllib.error.HTTPError as exc:
        try:
            payload = json.loads(exc.read(16_000).decode("utf-8", errors="replace"))
        except Exception:
            payload = {}
        errors = _safe_errors(payload)
        first = errors[0] if errors else {}
        raise CloudflareDiagnosticError(
            "CLOUDFLARE_HTTP_ERROR",
            http_status=exc.code,
            provider_code=first.get("code"),
            provider_message=first.get("message"),
        ) from None


def _verification(path: str) -> dict[str, Any]:
    try:
        status, payload = _get_json(path)
        result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
        return {
            "http_status": status,
            "success": payload.get("success") is True,
            "token_status": result.get("status"),
            "errors": _safe_errors(payload),
        }
    except CloudflareDiagnosticError as exc:
        return {
            "http_status": exc.http_status,
            "success": False,
            "token_status": None,
            "errors": [{"code": exc.provider_code, "message": exc.provider_message}],
        }


def _model_id(card: dict[str, Any]) -> str | None:
    candidates: list[Any] = [card.get("name"), card.get("id")]
    properties = card.get("properties")
    if isinstance(properties, dict):
        candidates.extend((properties.get("name"), properties.get("id")))
    for value in candidates:
        if isinstance(value, str) and value.startswith("@cf/"):
            return value
    return None


def _vision_declared(card: dict[str, Any]) -> bool:
    safe_text = json.dumps(card, sort_keys=True).lower()
    return any(term in safe_text for term in ('"vision"', '"image-to-text"', '"image_text_to_text"'))


def list_account_models(account_id: str) -> tuple[list[dict[str, Any]], int, int]:
    cards: list[dict[str, Any]] = []
    page = 1
    last_status = 0
    while page <= 10:
        last_status, payload = _get_json(
            f"/accounts/{account_id}/ai/models/search",
            query={"page": page, "per_page": 100, "hide_experimental": "true"},
        )
        result = payload.get("result")
        if not isinstance(result, list):
            raise CloudflareDiagnosticError("CLOUDFLARE_MODEL_SEARCH_INVALID")
        cards.extend(item for item in result if isinstance(item, dict))
        info = payload.get("result_info") if isinstance(payload.get("result_info"), dict) else {}
        total_pages = int(info.get("total_pages") or 1)
        if page >= total_pages or not result:
            break
        page += 1
    safe_cards = []
    for card in cards:
        model_id = _model_id(card)
        if model_id:
            safe_cards.append({"id": model_id, "vision_declared": _vision_declared(card)})
    return safe_cards, len(cards), last_status


def select_free_vision_model(cards: list[dict[str, Any]]) -> tuple[str | None, list[str]]:
    # Vision capability is established by the bounded repository allowlist. The
    # account catalogue is authoritative for visibility, but not every catalogue
    # card currently repeats the public model page's Vision badge.
    visible = {card["id"] for card in cards}
    eligible = [model for model in MODEL_PRIORITY if model in visible and model in CLOUDFLARE_FREE_VISION_MODELS]
    return (eligible[0] if eligible else None), eligible


def _failure(exc: Exception) -> dict[str, Any]:
    return {
        "status": "failed",
        "error_code": getattr(exc, "code", type(exc).__name__),
        "http_status": getattr(exc, "http_status", None),
        "provider_code": getattr(exc, "provider_code", None),
        "provider_message": _safe_message(getattr(exc, "provider_message", None)),
        "category": getattr(exc, "category", None),
    }


def run() -> dict[str, Any]:
    account_id = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "").strip()
    if not account_id:
        raise CloudflareDiagnosticError("CLOUDFLARE_ACCOUNT_ID_MISSING")
    if os.environ.get("MISTRAL_SCHOOL_PRIVATE_APPROVED", "").strip().lower() != "false":
        raise CloudflareDiagnosticError("MISTRAL_PRIVACY_GATE_NOT_FALSE")
    if os.environ.get("CLOUDFLARE_ZERO_COST_CONFIRMED", "").strip().lower() != "true":
        raise CloudflareDiagnosticError("CLOUDFLARE_ZERO_COST_NOT_CONFIRMED")

    os.environ["MEMO_VISUAL_PROVIDER_RATE_RETRIES"] = "0"
    os.environ["MEMO_VISUAL_PROVIDER_TRANSIENT_RETRIES"] = "0"
    user_token = _verification("/user/tokens/verify")
    account_id_format_valid = re.fullmatch(r"[0-9a-fA-F]{32}", account_id) is not None
    account_token = (
        _verification(f"/accounts/{account_id}/tokens/verify")
        if account_id_format_valid
        else {
            "http_status": None,
            "success": False,
            "token_status": None,
            "errors": [{
                "code": "CLOUDFLARE_ACCOUNT_ID_INVALID_FORMAT",
                "message": "The configured Cloudflare account ID must contain 32 hexadecimal characters.",
            }],
        }
    )
    report: dict[str, Any] = {
        "schema": REPORT_SCHEMA,
        "synthetic_only": True,
        "billable_spend": 0,
        "token_verification": user_token,
        "account_token_verification": account_token,
        "account_id_format_valid": account_id_format_valid,
        "model_search": None,
        "prior_qwen_404": None,
        "selected_model": None,
        "endpoint": None,
        "preflight": None,
        "cache_reuse": None,
        "failover": None,
        "zero_cost": {
            "plan_mode": "free_only",
            "confirmation": True,
            "paid_model_selected": False,
            "workers_paid_enabled_by_run": False,
            "ai_gateway_used": False,
        },
        "live_inference_calls": 0,
    }
    if not (user_token["success"] and user_token["token_status"] == "active"):
        return report
    if not account_id_format_valid:
        report["account_relationship"] = {
            "valid": False,
            "basis": "configured_account_id_invalid_format",
            "workers_ai_read_authorized": False,
        }
        report["model_search"] = {
            "status": "skipped",
            "error_code": "CLOUDFLARE_ACCOUNT_ID_INVALID_FORMAT",
            "http_status": None,
        }
        report["prior_qwen_404"] = {
            "http_status": 404,
            "provider_code": 7003,
            "explanation": "The prior request used a malformed configured account ID, so Cloudflare could not route the account-scoped URL; the response did not test model availability.",
        }
        return report

    try:
        cards, total, model_status = list_account_models(account_id)
    except Exception as exc:
        report["model_search"] = _failure(exc)
        return report

    selected, eligible = select_free_vision_model(cards)
    visible_ids = sorted({card["id"] for card in cards})
    visible_vision = sorted({
        card["id"] for card in cards
        if card.get("vision_declared") or card["id"] in CLOUDFLARE_FREE_VISION_MODELS
    })
    report["model_search"] = {
        "status": "success",
        "http_status": model_status,
        "account_visible_model_count": total,
        "account_visible_vision_models": visible_vision,
        "approved_free_visible_models": eligible,
        "qwen_visible": "@cf/qwen/qwen3.8-27b" in visible_ids,
        "gemma_visible": "@cf/google/gemma-4-26b-a4b-it" in visible_ids,
    }
    account_valid = account_token["success"] or model_status == 200
    report["account_relationship"] = {
        "valid": account_valid,
        "basis": "account_token_verify" if account_token["success"] else "workers_ai_model_search",
        "workers_ai_read_authorized": model_status == 200,
    }
    report["prior_qwen_404"] = {
        "http_status": 404,
        "explanation": (
            "The model is not visible to the configured account."
            if "@cf/qwen/qwen3.8-27b" not in visible_ids
            else "The model is visible now; the prior sanitized response did not preserve a Cloudflare internal code, so the old 404 cannot be classified more narrowly without another Qwen call."
        ),
    }
    if not selected:
        return report

    report["selected_model"] = selected
    report["endpoint"] = f"{API_ROOT}/accounts/<redacted-account>/ai/run/{selected}"
    registry = default_provider_registry()
    cloudflare = replace(registry["cloudflare"], model_id=selected, enabled=True, priority=1)
    groq = replace(registry["groq"], enabled=True, priority=0)

    def groq_unavailable(*_args: Any) -> Any:
        raise ProviderError(
            "AI_PROVIDER_TEST_UNAVAILABLE",
            "Synthetic qualification deliberately marked Groq unavailable.",
            category="transient_capacity",
        )

    calls = 0

    def counted_cloudflare(*args: Any) -> Any:
        nonlocal calls
        calls += 1
        return cloudflare_visual_adapter(*args)

    env = {
        "GROQ_API_KEY": "synthetic-unavailable",
        "GROQ_ZERO_COST_CONFIRMED": "true",
        "CLOUDFLARE_ACCOUNT_ID": account_id,
        "CLOUDFLARE_AI_API_TOKEN": os.environ.get("CLOUDFLARE_AI_API_TOKEN", ""),
        "CLOUDFLARE_ZERO_COST_CONFIRMED": "true",
    }
    fixture = synthetic_fixtures()[0]
    region = _region(fixture)
    original_render = visual_evidence._render_regions
    visual_evidence._render_regions = lambda *_args, **_kwargs: [region]
    first_record = None
    try:
        first_record, _ = visual_evidence.extract_visual_evidence(
            b"phase84b1-cloudflare-cache-source",
            {"job_id": "synthetic-phase84b1", "source": {}, "content": {"pages": [{"visual_inspection_required": True}]}},
            provider_fabric=ProviderFabric(
                registry={"groq": groq, "cloudflare": cloudflare},
                adapters={"groq": groq_unavailable, "cloudflare": counted_cloudflare},
                env=env,
            ),
            privacy_classification=PRIVACY_SYNTHETIC_TEST,
        )
        successful = [item for item in first_record.get("runs", []) if item.get("status") == "success"]
        selected_run = successful[-1] if successful else {}
        attempts = first_record.get("provider_attempts") or []
        failed_attempt = next(
            (item for item in reversed(attempts) if item.get("status") == "failed"),
            {},
        )
        cloudflare_attempt = next(
            (item for item in reversed(attempts) if item.get("provider") == "cloudflare"),
            failed_attempt,
        )
        report["preflight"] = {
            "status": "success" if successful else "failed",
            "model": selected,
            "image_accepted": bool(successful),
            "response_received": bool(successful),
            "normalized_provider_result": bool(selected_run.get("result_digest")),
            "schema_compatible": bool(first_record.get("evidence")),
            "error_code": failed_attempt.get("error_code"),
            "error_category": failed_attempt.get("error_category"),
            "http_status": failed_attempt.get("http_status"),
            "cloudflare_success": cloudflare_attempt.get("provider_success"),
            "provider_error_code": failed_attempt.get("provider_error_code"),
            "provider_error_message": _safe_message(failed_attempt.get("provider_error_message")),
            "result_exists": cloudflare_attempt.get("result_exists"),
            "result_keys": cloudflare_attempt.get("result_keys") or [],
            "response_type": cloudflare_attempt.get("response_type"),
            "normalization_stage": cloudflare_attempt.get("normalization_stage"),
        }
        report["failover"] = {
            "passed": bool(successful) and any(
                item.get("provider") == "groq" and item.get("status") == "failed" for item in attempts
            ),
            "selected_provider": selected_run.get("provider"),
            "groq_test_state": "unavailable",
        }
        if not successful:
            report["cache_reuse"] = {
                "passed": False,
                "second_inference_calls": 0,
                "reused_success_count": 0,
                "skipped": "preflight_unsuccessful",
            }
            report["live_inference_calls"] = calls
            return report
        before_cache = calls
        second_record, _ = visual_evidence.extract_visual_evidence(
            b"phase84b1-cloudflare-cache-source",
            {"job_id": "synthetic-phase84b1", "source": {}, "content": {"pages": [{"visual_inspection_required": True}]}},
            provider_fabric=ProviderFabric(
                registry={"cloudflare": cloudflare},
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
    except (ProviderError, ProviderPoolExhausted, RuntimeError) as exc:
        report["preflight"] = _failure(exc)
    finally:
        visual_evidence._render_regions = original_render
    report["live_inference_calls"] = calls
    return report


def main() -> int:
    report = run()
    path = Path(os.environ.get("PHASE84B1_REPORT_PATH", "phase84b1-report.json"))
    path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    summary = {
        "token_status": report["token_verification"]["token_status"],
        "account_relationship": (report.get("account_relationship") or {}).get("valid"),
        "model_count": (report.get("model_search") or {}).get("account_visible_model_count"),
        "qwen_visible": (report.get("model_search") or {}).get("qwen_visible"),
        "gemma_visible": (report.get("model_search") or {}).get("gemma_visible"),
        "selected_model": report.get("selected_model"),
        "preflight": (report.get("preflight") or {}).get("status"),
        "cache_reuse": (report.get("cache_reuse") or {}).get("passed"),
        "failover": (report.get("failover") or {}).get("passed"),
        "live_inference_calls": report.get("live_inference_calls"),
        "billable_spend": 0,
    }
    print("PHASE84B1_SAFE_SUMMARY=" + json.dumps(summary, sort_keys=True))
    passed = all((
        summary["token_status"] == "active",
        summary["account_relationship"] is True,
        summary["selected_model"] in CLOUDFLARE_FREE_VISION_MODELS,
        summary["preflight"] == "success",
        summary["cache_reuse"] is True,
        summary["failover"] is True,
        summary["live_inference_calls"] == 1,
    ))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
