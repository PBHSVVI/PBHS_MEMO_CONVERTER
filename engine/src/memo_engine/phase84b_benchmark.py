from __future__ import annotations

import hashlib
import io
import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import replace
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from . import visual_evidence
from .provider_fabric import (
    PRIVACY_SCHOOL_PRIVATE,
    PRIVACY_SYNTHETIC_TEST,
    TASK_VISUAL_INTERPRETATION,
    ProviderFabric,
    ProviderPoolExhausted,
    ProviderTaskRequest,
    cloudflare_visual_adapter,
    default_provider_registry,
    mistral_visual_adapter,
)


REPORT_SCHEMA = "phase8.4b-live-benchmark-v1"
CLOUDFLARE_MODEL = "@cf/qwen/qwen3.8-27b"
MISTRAL_MODELS_ENDPOINT = "https://api.mistral.ai/v1/models"


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


def _png(draw_fixture: Any, width: int = 760, height: int = 360) -> bytes:
    image = Image.new("RGB", (width, height), "white")
    draw_fixture(ImageDraw.Draw(image))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def synthetic_fixtures() -> list[dict[str, Any]]:
    body, small, bold = _font(30), _font(24), _font(34)

    def numeric(draw: ImageDraw.ImageDraw) -> None:
        draw.text((32, 26), "Q1.2", fill="#25334A", font=bold)
        draw.text((56, 126), "10/250 = 1/25 = 0.04 = 4%", fill="#9A1D2E", font=bold)

    def tree(draw: ImageDraw.ImageDraw) -> None:
        draw.text((28, 18), "Q2.1 Probability tree", fill="#25334A", font=body)
        root, left, right = (95, 185), (330, 95), (330, 270)
        draw.line((root, left), fill="#9A1D2E", width=4)
        draw.line((root, right), fill="#9A1D2E", width=4)
        draw.text((185, 95), "0.6", fill="#9A1D2E", font=small)
        draw.text((185, 235), "0.4", fill="#9A1D2E", font=small)
        draw.text((345, 74), "A", fill="#9A1D2E", font=body)
        draw.text((345, 248), "B", fill="#9A1D2E", font=body)
        for origin, targets in ((left, (44, 142)), (right, (220, 316))):
            for target_y in targets:
                draw.line((origin, (610, target_y)), fill="#9A1D2E", width=3)
        for position, label in (((450, 30), "0.5"), ((450, 136), "0.5"),
                                ((450, 208), "0.2"), ((450, 306), "0.8")):
            draw.text(position, label, fill="#9A1D2E", font=small)

    def venn(draw: ImageDraw.ImageDraw) -> None:
        draw.text((28, 18), "Q3.1 Venn diagram", fill="#25334A", font=body)
        draw.ellipse((145, 72, 440, 330), outline="#9A1D2E", width=4)
        draw.ellipse((320, 72, 615, 330), outline="#1F6B4F", width=4)
        for position, label, colour in (
            ((225, 165), "7", "#9A1D2E"), ((365, 165), "3", "#25334A"),
            ((505, 165), "5", "#1F6B4F"), ((675, 280), "2", "#25334A"),
        ):
            draw.text(position, label, fill=colour, font=bold)

    def question_solution(draw: ImageDraw.ImageDraw) -> None:
        draw.text((28, 22), "Q4.1 Calculate 3 x 7.", fill="#25334A", font=body)
        draw.line((28, 92, 710, 92), fill="#D5D9DF", width=2)
        draw.text((54, 145), "Answer: 3 x 7 = 21", fill="#9A1D2E", font=bold)
        draw.text((54, 225), "1A Correct answer", fill="#9A1D2E", font=body)

    return [
        {"id": "numeric_working", "question_ref": "1.2", "image": _png(numeric),
         "tokens": ["10", "250", "1", "25", "0.04", "4"], "spatial": False,
         "expected_kinds": {"answer", "answer_working"},
         "allowed_numbers": {"10", "250", "1", "25", "0.04", "4", "1.2"}},
        {"id": "probability_tree", "question_ref": "2.1", "image": _png(tree),
         "tokens": ["0.6", "0.4", "0.5", "0.2", "0.8"], "spatial": True,
         "expected_kinds": {"diagram", "answer_working"},
         "allowed_numbers": {"0.6", "0.4", "0.5", "0.2", "0.8", "2.1"}},
        {"id": "venn_diagram", "question_ref": "3.1", "image": _png(venn),
         "tokens": ["7", "3", "5", "2"], "spatial": True,
         "expected_kinds": {"diagram", "answer_working"},
         "allowed_numbers": {"7", "3", "5", "2", "3.1"}},
        {"id": "question_vs_solution", "question_ref": "4.1", "image": _png(question_solution),
         "tokens": ["3", "7", "21"], "spatial": False,
         "expected_kinds": {"answer", "answer_working", "mark_annotation"},
         "allowed_numbers": {"3", "7", "21", "1", "4.1"}},
    ]


def _region(fixture: dict[str, Any]) -> dict[str, Any]:
    with Image.open(io.BytesIO(fixture["image"])) as image:
        width, height = image.size
    bounds = [0.0, 0.0, float(width), float(height)]
    return {
        "asset_path": f"synthetic/phase84b/{fixture['id']}.png",
        "page": 1,
        "image_bytes": fixture["image"],
        "mime_type": "image/png",
        "question_refs": [fixture["question_ref"]],
        "printed_text": "",
        "region_index": 0,
        "page_bbox": bounds,
        "render_bbox": bounds,
        "owned_bbox": bounds,
        "pixel_width": width,
        "pixel_height": height,
    }


def _request(fixture: dict[str, Any], privacy: str = PRIVACY_SYNTHETIC_TEST) -> ProviderTaskRequest:
    digest = hashlib.sha256(fixture["image"]).hexdigest()
    prompt = visual_evidence.visual_system_prompt() + (
        "\n\nThis is a synthetic qualification image. The coloured memo annotations and "
        "diagram content are visual-overlay evidence. Return JSON only; preserve every "
        "visible number, branch association, and answer order. Do not solve or add values."
        f"\nKnown question anchor: {fixture['question_ref']}"
    )
    return ProviderTaskRequest(
        task_type=TASK_VISUAL_INTERPRETATION,
        region_id=f"synthetic/phase84b/{fixture['id']}.png",
        current_question_owner=fixture["question_ref"],
        source_question=fixture["question_ref"],
        source_page=1,
        source_digest=digest,
        crop_digest=digest,
        crop_bytes=fixture["image"],
        crop_mime_type="image/png",
        interpretation_schema_version=visual_evidence.SCHEMA_VERSION,
        task_prompt_version=visual_evidence.VISUAL_TASK_PROMPT_VERSION,
        privacy_classification=privacy,
        prompt=prompt,
        response_schema=visual_evidence._vision_schema(1),
    )


def _safe_numeric_map(value: dict[str, Any], *, allow_service_tier: bool = False) -> dict[str, Any]:
    result = {str(key): item for key, item in value.items() if isinstance(item, (int, float))}
    if allow_service_tier and isinstance(value.get("service_tier"), str):
        result["service_tier"] = value["service_tier"]
    return result


def _score(fixture: dict[str, Any], result: Any) -> dict[str, Any]:
    payload = dict(result.normalized_result)
    payload.update({"provider": result.provider_id, "model": result.model_id})
    validated = visual_evidence.validate_visual_response(payload, _region(fixture))
    evidence = validated["evidence"]
    text = " ".join(
        f"{item.get('transcription') or ''} {item.get('normalized_math') or ''}"
        for item in evidence
    ).lower()
    recovered = {token: token.lower() in text for token in fixture["tokens"]}
    numbers = set(re.findall(r"(?<![A-Za-z])\d+(?:\.\d+)?", text))
    hallucinated = sorted(numbers - fixture["allowed_numbers"])
    kinds = {str(item.get("kind")) for item in evidence}
    owner_ok = bool(evidence) and all(
        item.get("question_ref") in {None, fixture["question_ref"]} for item in evidence
    )
    role_ok = bool(kinds & fixture["expected_kinds"])
    spatial_ok = not fixture["spatial"] or "diagram" in kinds
    status = (
        "pass"
        if all(recovered.values()) and not hallucinated and owner_ok and role_ok and spatial_ok
        else ("partial" if evidence else "fail")
    )
    return {
        "fixture": fixture["id"],
        "provider": result.provider_id,
        "model": result.model_id,
        "status": status,
        "schema_valid": True,
        "tokens_recovered": recovered,
        "hallucinated_values": hallucinated,
        "owner_correct": owner_ok,
        "role_correct": role_ok,
        "spatial_classification_correct": spatial_ok,
        "normalization_success": True,
        "evidence_count": len(evidence),
        "latency_ms": result.latency_ms,
        "usage": _safe_numeric_map(result.usage, allow_service_tier=True),
        "quota": _safe_numeric_map(result.quota),
    }


def _failure(provider: str, fixture: str, exc: Exception) -> dict[str, Any]:
    return {
        "fixture": fixture,
        "provider": provider,
        "status": "failed",
        "schema_valid": False,
        "error_code": getattr(exc, "code", type(exc).__name__),
        "error_category": getattr(exc, "category", "unknown"),
        "http_status": getattr(exc, "http_status", None),
        "retry_after_seconds": getattr(exc, "retry_after_seconds", None),
    }


def list_mistral_models() -> tuple[list[dict[str, Any]], int]:
    request = urllib.request.Request(
        MISTRAL_MODELS_ENDPOINT,
        headers={
            "Authorization": f"Bearer {os.environ.get('MISTRAL_API_KEY', '').strip()}",
            "Accept": "application/json",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"MISTRAL_MODEL_LIST_HTTP_{exc.code}") from None
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        raise RuntimeError("MISTRAL_MODEL_LIST_INVALID")
    safe_cards = []
    for card in data:
        if not isinstance(card, dict) or not isinstance(card.get("id"), str):
            continue
        capabilities = card.get("capabilities") if isinstance(card.get("capabilities"), dict) else {}
        safe_cards.append({
            "id": card["id"],
            "vision_declared": bool(capabilities.get("vision") or capabilities.get("image_input")),
            "deprecated": bool(card.get("deprecation") or card.get("deprecated")),
        })
    return safe_cards, len(data)


def select_mistral_vision_model(cards: list[dict[str, Any]]) -> tuple[str | None, list[str]]:
    documented_patterns = (
        "ministral-3b", "ministral-8b", "ministral-14b", "mistral-small",
        "mistral-medium", "mistral-large", "pixtral", "magistral",
    )
    candidates = sorted({
        card["id"] for card in cards
        if not card["deprecated"] and (
            card["vision_declared"]
            or any(pattern in card["id"].lower() for pattern in documented_patterns)
        )
    })
    for desired in (
        "ministral-3b-2512", "ministral-3b-latest",
        "ministral-8b-2512", "ministral-8b-latest",
        "mistral-small-2506", "mistral-small-latest",
        "ministral-14b-2512", "ministral-14b-latest",
    ):
        if desired in candidates:
            return desired, candidates
    return (candidates[0] if candidates else None), candidates


def _provider_env() -> dict[str, str]:
    return {
        "GROQ_API_KEY": "disabled-for-phase84b",
        "GROQ_ZERO_COST_CONFIRMED": "true",
        "CLOUDFLARE_ACCOUNT_ID": os.environ.get("CLOUDFLARE_ACCOUNT_ID", ""),
        "CLOUDFLARE_AI_API_TOKEN": os.environ.get("CLOUDFLARE_AI_API_TOKEN", ""),
        "CLOUDFLARE_ZERO_COST_CONFIRMED": os.environ.get("CLOUDFLARE_ZERO_COST_CONFIRMED", ""),
        "MISTRAL_API_KEY": os.environ.get("MISTRAL_API_KEY", ""),
        "MISTRAL_ZERO_COST_CONFIRMED": os.environ.get("MISTRAL_ZERO_COST_CONFIRMED", ""),
        "MISTRAL_SCHOOL_PRIVATE_APPROVED": "false",
    }


def run() -> dict[str, Any]:
    os.environ["MEMO_VISUAL_PROVIDER_RATE_RETRIES"] = "0"
    os.environ["MEMO_VISUAL_PROVIDER_TRANSIENT_RETRIES"] = "0"
    os.environ["MISTRAL_SCHOOL_PRIVATE_APPROVED"] = "false"
    fixtures = synthetic_fixtures()
    registry = default_provider_registry()
    cloudflare = registry["cloudflare"]
    cloudflare_calls = 0
    mistral_calls = 0
    captured_cf: list[Any] = []
    report: dict[str, Any] = {
        "schema": REPORT_SCHEMA,
        "synthetic_only": True,
        "billable_spend": 0,
        "cloudflare": {
            "model": cloudflare.model_id,
            "endpoint_shape": "https://api.cloudflare.com/client/v4/accounts/<redacted-account>/ai/run/@cf/qwen/qwen3.8-27b",
            "preflight": None,
            "benchmarks": [],
        },
        "mistral": {
            "model_list_count": None,
            "vision_candidates": [],
            "selected_model": None,
            "preflight": None,
            "benchmarks": [],
        },
        "groq": {"calls": 0, "status": "skipped_to_preserve_free_quota"},
        "policy": {},
    }

    def counted_cloudflare(request: Any, spec: Any, deadline: Any, remaining: int, clock: Any) -> Any:
        nonlocal cloudflare_calls
        cloudflare_calls += 1
        result = cloudflare_visual_adapter(request, spec, deadline, remaining, clock)
        captured_cf.append(result)
        return result

    cf_registry = {
        "groq": replace(registry["groq"], enabled=False),
        "cloudflare": cloudflare,
        "mistral": replace(registry["mistral"], enabled=False),
    }
    env = _provider_env()
    preflight_fixture = fixtures[0]
    region = _region(preflight_fixture)
    original_render = visual_evidence._render_regions
    visual_evidence._render_regions = lambda *_args, **_kwargs: [region]
    try:
        first_record, _ = visual_evidence.extract_visual_evidence(
            b"phase84b-cloudflare-cache-source",
            {"job_id": "synthetic-phase84b", "source": {}, "content": {
                "pages": [{"visual_inspection_required": True}]
            }},
            provider_fabric=ProviderFabric(
                registry=cf_registry, adapters={"cloudflare": counted_cloudflare}, env=env
            ),
            privacy_classification=PRIVACY_SYNTHETIC_TEST,
        )
        if not captured_cf:
            attempts = first_record.get("provider_attempts") or []
            failed = next(
                (item for item in reversed(attempts) if item.get("status") == "failed"),
                {},
            )
            report["cloudflare"]["preflight"] = {
                "fixture": "preflight",
                "provider": "cloudflare",
                "status": "failed",
                "schema_valid": False,
                "error_code": failed.get("error_code", "CLOUDFLARE_PREFLIGHT_FAILED"),
                "error_category": failed.get("error_category", "unknown"),
                "http_status": failed.get("http_status"),
                "retry_after_seconds": failed.get("retry_after_seconds"),
            }
            raise RuntimeError("CLOUDFLARE_PREFLIGHT_RECORDED_FAILURE")
        cf_result = captured_cf[-1]
        scored = _score(preflight_fixture, cf_result)
        report["cloudflare"]["preflight"] = {
            "status": "success",
            "http_result": "accepted",
            "schema_valid": scored["schema_valid"],
            "normalization_success": scored["normalization_success"],
            "latency_ms": scored["latency_ms"],
            "usage": scored["usage"],
            "quota": scored["quota"],
            "route_attempts": cf_result.route_attempts,
        }
        report["cloudflare"]["benchmarks"].append(scored)
        before_second = cloudflare_calls
        second_record, _ = visual_evidence.extract_visual_evidence(
            b"phase84b-cloudflare-cache-source",
            {"job_id": "synthetic-phase84b", "source": {}, "content": {
                "pages": [{"visual_inspection_required": True}]
            }},
            provider_fabric=ProviderFabric(
                registry=cf_registry, adapters={"cloudflare": counted_cloudflare}, env=env
            ),
            privacy_classification=PRIVACY_SYNTHETIC_TEST,
            checkpoint_record=first_record,
        )
        report["policy"]["cache_reuse"] = {
            "passed": cloudflare_calls == before_second,
            "second_live_calls": cloudflare_calls - before_second,
            "reused_success_count": second_record["summary"]["reused_success_count"],
        }
    except Exception as exc:
        if report["cloudflare"]["preflight"] is None:
            report["cloudflare"]["preflight"] = _failure("cloudflare", "preflight", exc)
    finally:
        visual_evidence._render_regions = original_render

    if report["cloudflare"]["preflight"].get("status") == "success":
        for fixture in fixtures[1:]:
            if cloudflare_calls >= 5:
                break
            try:
                result = ProviderFabric(
                    registry={"cloudflare": cloudflare},
                    adapters={"cloudflare": counted_cloudflare},
                    env=env,
                ).route(_request(fixture), deadline_monotonic=time.monotonic() + 60, remaining_requests=1)
                report["cloudflare"]["benchmarks"].append(_score(fixture, result))
            except Exception as exc:
                report["cloudflare"]["benchmarks"].append(
                    _failure("cloudflare", fixture["id"], exc)
                )
                break

    run_mistral = os.environ.get("PHASE84B_RUN_MISTRAL", "true").strip().lower() == "true"
    selected_model = None
    if run_mistral:
        try:
            cards, visible_count = list_mistral_models()
            selected_model, candidates = select_mistral_vision_model(cards)
            report["mistral"]["model_list_count"] = visible_count
            report["mistral"]["vision_candidates"] = candidates
            report["mistral"]["selected_model"] = selected_model
        except Exception as exc:
            report["mistral"]["model_list_error"] = (
                str(exc) if str(exc).startswith("MISTRAL_") else type(exc).__name__
            )
    else:
        report["mistral"]["status"] = "skipped_call_budget_already_consumed"

    if selected_model:
        mistral_spec = replace(registry["mistral"], model_id=selected_model, enabled=True)

        def counted_mistral(request: Any, spec: Any, deadline: Any, remaining: int, clock: Any) -> Any:
            nonlocal mistral_calls
            mistral_calls += 1
            return mistral_visual_adapter(request, spec, deadline, remaining, clock)

        mi_registry = {
            "groq": replace(registry["groq"], enabled=False),
            "cloudflare": replace(registry["cloudflare"], enabled=False),
            "mistral": mistral_spec,
        }
        try:
            result = ProviderFabric(
                registry=mi_registry,
                adapters={"mistral": counted_mistral},
                env=env,
            ).route(_request(preflight_fixture), deadline_monotonic=time.monotonic() + 60, remaining_requests=1)
            scored = _score(preflight_fixture, result)
            report["mistral"]["preflight"] = {
                "status": "success",
                "schema_valid": scored["schema_valid"],
                "normalization_success": scored["normalization_success"],
                "latency_ms": scored["latency_ms"],
                "usage": scored["usage"],
                "quota": scored["quota"],
                "route_attempts": result.route_attempts,
            }
        except Exception as exc:
            report["mistral"]["preflight"] = _failure("mistral", "preflight", exc)

        if report["mistral"]["preflight"].get("status") == "success":
            for fixture in fixtures:
                if mistral_calls >= 5:
                    break
                try:
                    result = ProviderFabric(
                        registry={"mistral": mistral_spec},
                        adapters={"mistral": counted_mistral},
                        env=env,
                    ).route(_request(fixture), deadline_monotonic=time.monotonic() + 60, remaining_requests=1)
                    report["mistral"]["benchmarks"].append(_score(fixture, result))
                except Exception as exc:
                    report["mistral"]["benchmarks"].append(
                        _failure("mistral", fixture["id"], exc)
                    )
                    break

        before_private = mistral_calls
        try:
            ProviderFabric(
                registry={"mistral": mistral_spec},
                adapters={"mistral": counted_mistral},
                env=env,
            ).route(
                _request(preflight_fixture, PRIVACY_SCHOOL_PRIVATE),
                deadline_monotonic=time.monotonic() + 5,
                remaining_requests=1,
            )
            denied = False
        except ProviderPoolExhausted as exc:
            denied = any(item.get("decision") == "privacy_ineligible" for item in exc.attempts)
        report["policy"]["mistral_school_private_denial"] = {
            "passed": denied and mistral_calls == before_private,
            "provider_calls": mistral_calls - before_private,
            "approval_flag": False,
        }

    defer_registry = {name: replace(spec, enabled=False) for name, spec in registry.items()}
    try:
        ProviderFabric(registry=defer_registry, adapters={}, env={}).route(
            _request(preflight_fixture), deadline_monotonic=time.monotonic() + 5, remaining_requests=1
        )
        defer_passed = False
    except ProviderPoolExhausted as exc:
        defer_passed = exc.code == "VISUAL_PROVIDER_POOL_EXHAUSTED"
    report["policy"]["all_provider_defer"] = {
        "passed": defer_passed,
        "paid_route": False,
        "teacher_review_created": False,
    }
    report["policy"]["zero_cost"] = {
        "cloudflare_confirmation": os.environ.get("CLOUDFLARE_ZERO_COST_CONFIRMED") == "true",
        "mistral_confirmation": os.environ.get("MISTRAL_ZERO_COST_CONFIRMED") == "true",
        "mistral_school_private_approved": False,
        "billable_spend": 0,
    }
    report["cloudflare"]["live_inference_calls"] = cloudflare_calls
    report["mistral"]["live_inference_calls"] = mistral_calls
    report["mistral"]["model_list_calls"] = 1 if run_mistral else 0
    return report


def main() -> int:
    report = run()
    path = Path(os.environ.get("PHASE84B_REPORT_PATH", "phase84b-report.json"))
    path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    summary = {
        "schema": report["schema"],
        "cloudflare_model": report["cloudflare"]["model"],
        "cloudflare_preflight": report["cloudflare"]["preflight"].get("status"),
        "cloudflare_calls": report["cloudflare"]["live_inference_calls"],
        "mistral_model_count": report["mistral"]["model_list_count"],
        "mistral_vision_candidates": report["mistral"]["vision_candidates"],
        "mistral_selected_model": report["mistral"]["selected_model"],
        "mistral_preflight": (report["mistral"]["preflight"] or {}).get("status"),
        "mistral_calls": report["mistral"]["live_inference_calls"],
        "school_private_approved": False,
        "billable_spend": 0,
    }
    print("PHASE84B_SAFE_SUMMARY=" + json.dumps(summary, sort_keys=True))
    cloudflare_ok = report["cloudflare"]["preflight"].get("status") == "success"
    mistral_ok = (
        not run_mistral
        or (report["mistral"]["preflight"] or {}).get("status") == "success"
    )
    return 0 if cloudflare_ok and mistral_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
