from __future__ import annotations

import base64
import io
import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, replace
from typing import Any, Callable

from jsonschema import Draft202012Validator
from PIL import Image

from .ai_router import (
    ProviderError, ProviderRun, _result_schema, _safe_rate_metadata, _system_prompt,
    _transport_error_category, classify,
)
from .openai_credit import MODEL, CreditLedger, credit_eligible, private_job_enabled
from .provider_fabric import ProviderResult, ProviderSpec, ProviderTaskRequest, _result

API_ROOT = "https://api.openai.com/v1"
VISUAL_OUTPUT_LIMIT = 6250
SEMANTIC_OUTPUT_LIMIT = 2048
# Standard, ordinary-context USD per million tokens, expressed as nUSD per token.
INPUT_RATE, CACHED_RATE, CACHE_WRITE_RATE, OUTPUT_RATE = 100, 10, 125, 500


def _headers(env: Any) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {env['OPENAI_API_KEY']}", "Content-Type": "application/json"}
    for header, key in (("OpenAI-Organization", "MEMO_OPENAI_ORGANIZATION"),
                        ("OpenAI-Project", "MEMO_OPENAI_PROJECT")):
        if env.get(key):
            headers[header] = env[key]
    return headers


def check_model_access(env: Any) -> None:
    if not env.get("OPENAI_API_KEY", "").strip():
        raise ProviderError("OPENAI_KEY_MISSING", "The GitHub Actions OpenAI credential is missing.")
    request = urllib.request.Request(f"{API_ROOT}/models/{MODEL}", headers=_headers(env))
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            if json.load(response).get("id") == MODEL:
                return
    except urllib.error.HTTPError as exc:
        raise ProviderError("OPENAI_MODEL_ACCESS_FAILED", "The model catalogue denied Luna access.", http_status=exc.code) from None
    except Exception:
        pass
    raise ProviderError("OPENAI_MODEL_ACCESS_FAILED", "The Luna model catalogue check failed.")


def _transport_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Encode nullable fields in the transport subset, then validate the full original locally."""
    value = {key: item for key, item in schema.items() if key not in {"minimum", "maximum", "minItems", "maxItems"}}
    if "properties" in value:
        value["properties"] = {key: _transport_schema(item) for key, item in value["properties"].items()}
    if "items" in value:
        value["items"] = _transport_schema(value["items"])
    if isinstance(value.get("type"), list):
        types = value.pop("type")
        return {"anyOf": [{"type": kind, **(value if kind != "null" else {})} for kind in types]}
    return value


def _image_token_ceiling(image: bytes) -> int:
    try:
        with Image.open(io.BytesIO(image)) as raster:
            width, height = raster.size
    except Exception:
        raise ProviderError("OPENAI_IMAGE_INVALID", "The prepared question crop is unreadable.", category="content_request") from None
    # Bound unscaled 32px patches, round up and allow for model scaling/overhead.
    # High detail may resize downward. No application-side crop data is changed.
    patches = ((width + 31) // 32) * ((height + 31) // 32)
    if patches > 30_000:
        raise ProviderError("OPENAI_IMAGE_LIMIT", "The question crop exceeds the bounded image size.")
    return patches * 2 + 2048


def _token_count(values: dict[str, Any], key: str) -> int | None:
    value = values.get(key)
    return value if type(value) is int and value >= 0 else None


def _usage(payload: dict[str, Any]) -> dict[str, Any]:
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        return {}
    input_tokens = _token_count(usage, "input_tokens")
    output_tokens = _token_count(usage, "output_tokens")
    if input_tokens is None or output_tokens is None:
        return {}
    input_details = usage.get("input_tokens_details") or {}
    output_details = usage.get("output_tokens_details") or {}
    if not isinstance(input_details, dict) or not isinstance(output_details, dict):
        return {}
    cached = _token_count(input_details, "cached_tokens")
    written = _token_count(input_details, "cache_write_tokens")
    reasoning = _token_count(output_details, "reasoning_tokens")
    image = _token_count(input_details, "image_tokens")
    if ((cached or 0) + (written or 0) > input_tokens
            or (image or 0) > input_tokens or (reasoning or 0) > output_tokens):
        return {}
    uncached = input_tokens - (cached or 0) - (written or 0)
    estimated = uncached * INPUT_RATE + (cached or 0) * CACHED_RATE + (written or 0) * CACHE_WRITE_RATE + output_tokens * OUTPUT_RATE
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "cached_input_tokens": cached,
        "cache_write_tokens": written,
        "reasoning_tokens": reasoning,
        "image_input_tokens": image,
        "estimated_cost_nusd": estimated,
        "estimated_upper_cost_nusd": estimated + (uncached * (CACHE_WRITE_RATE - INPUT_RATE) if written is None else 0),
    }


def _provider_status(error: urllib.error.HTTPError) -> ProviderError:
    rate = _safe_rate_metadata(error.headers)
    if error.code == 429:
        try:
            code = json.loads(error.read(8192)).get("error", {}).get("code")
        except Exception:
            code = None
        if isinstance(code, str) and code in {"insufficient_quota", "credit_balance_exhausted"}:
            return ProviderError("OPENAI_CREDIT_UNAVAILABLE", "The OpenAI credit capacity is unavailable.", http_status=429)
        return ProviderError(
            "OPENAI_RATE_LIMITED", "OpenAI rate limited the request.", http_status=429,
            rate_limits=rate, retry_after_seconds=rate.get("retry_after_seconds") or rate.get("reset_tokens_seconds"),
            provider_saturated=True,
        )
    if error.code in {401, 403, 404}:
        return ProviderError("OPENAI_AUTH_CONFIGURATION", "OpenAI rejected the project credential or model access.",
                             retryable=False, category="auth_configuration", http_status=error.code)
    if error.code in {400, 413, 422}:
        try:
            detail = json.loads(error.read(8192)).get("error", {})
            code = detail.get("code")
        except Exception:
            code = None
        if isinstance(code, str) and code in {"content_policy_violation", "image_content_policy_violation", "moderation_blocked"}:
            return ProviderError("OPENAI_CONTENT_REJECTED", "OpenAI declined to interpret this evidence.",
                                 category="content_request", http_status=error.code)
        return ProviderError("OPENAI_REQUEST_REJECTED", "OpenAI rejected the request or schema configuration.",
                             retryable=False, category="auth_configuration", http_status=error.code)
    return ProviderError("OPENAI_SERVICE_UNAVAILABLE", "The OpenAI service could not complete the request.", http_status=error.code)


@dataclass(frozen=True)
class Response:
    value: dict[str, Any]
    model: str
    usage: dict[str, Any]
    quota: dict[str, Any]
    elapsed_ms: int


class OpenAIInterpreter:
    def __init__(self, ledger: CreditLedger, env: Any, *, job_id: str | None = None) -> None:
        if not credit_eligible(env) or (not ledger.synthetic and not private_job_enabled(env, job_id)):
            raise ProviderError("OPENAI_POLICY_BLOCKED", "OpenAI has no verified included-credit and source approval.")
        self.ledger = ledger
        self.env = env

    def _respond(self, *, stage: str, prompt: str, schema: dict[str, Any],
                 image: bytes | None = None, mime: str | None = None,
                 deadline: float | None = None, clock: Callable[[], float] = time.monotonic) -> Response:
        schema_name = "memo_visual_evidence" if stage == "visual" else "memo_mark_semantics"
        output_limit = VISUAL_OUTPUT_LIMIT if stage == "visual" else SEMANTIC_OUTPUT_LIMIT
        transport_schema = _transport_schema(schema)
        image_ceiling = _image_token_ceiling(image) if image is not None else 0
        text_ceiling = len(prompt.encode("utf-8")) + len(json.dumps(transport_schema).encode("utf-8")) + 2048
        input_ceiling = text_ceiling + image_ceiling
        # Reserve every input token at the highest enabled write price. Output
        # limits include reasoning tokens, so these are reserved exactly once.
        reserved = input_ceiling * CACHE_WRITE_RATE + output_limit * OUTPUT_RATE
        content = [{"type": "input_text", "text": prompt}]
        if image is not None:
            encoded = base64.b64encode(image).decode("ascii")
            content.append({"type": "input_image", "detail": "high", "image_url": f"data:{mime};base64,{encoded}"})
        body = {
            "model": MODEL,
            "service_tier": "default",
            "reasoning": {"effort": "low"},
            "store": False,
            "prompt_cache_options": {"mode": "explicit", "ttl": "30m"},
            "truncation": "disabled",
            "max_output_tokens": output_limit,
            "input": [{"role": "user", "content": content}],
            "text": {"format": {"type": "json_schema", "name": schema_name, "strict": True, "schema": transport_schema}},
        }
        request = urllib.request.Request(f"{API_ROOT}/responses", headers=_headers(self.env),
                                         data=json.dumps(body).encode("utf-8"), method="POST")
        if deadline is not None and deadline <= clock():
            raise ProviderError("VISUAL_PHASE_BUDGET_EXCEEDED", "The visual processing budget is exhausted.")
        reservation = self.ledger.reserve(stage, reserved)
        started = clock()
        timeout = min(75.0, deadline - started) if deadline is not None else 75.0
        if timeout <= 0:
            raise ProviderError("VISUAL_PHASE_BUDGET_EXCEEDED", "The visual processing budget is exhausted.")

        # Exactly one POST per immutable reservation. The response body is never
        # placed in logs or on the ledger, including for error responses.
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                quota = _safe_rate_metadata(response.headers)
                payload = json.load(response)
        except urllib.error.HTTPError as error:
            failure = _provider_status(error)
            self.ledger.finish(reservation, {
                "stage": stage, "model": MODEL, "status": failure.code,
                "elapsed_ms": round((clock() - started) * 1000), "quota": failure.rate_limits,
                "charged_budget_nusd": reserved,
            })
            raise failure from None
        except Exception as error:
            category = _transport_error_category(error)
            self.ledger.finish(reservation, {
                "stage": stage, "model": MODEL, "status": "unknown_charge",
                "elapsed_ms": round((clock() - started) * 1000), "transport": category,
                "charged_budget_nusd": reserved,
            })
            raise ProviderError("OPENAI_NETWORK_OR_RESPONSE_ERROR", "The OpenAI response could not be confirmed.",
                                diagnostics={"transport_error_category": category}) from None

        elapsed = round((clock() - started) * 1000)
        payload = payload if isinstance(payload, dict) else {}
        model = payload.get("model")
        model_verified = isinstance(model, str) and bool(re.fullmatch(r"gpt-6-luna(?:-\d{4}-\d{2}-\d{2})?", model))
        usage = _usage(payload)
        status = payload.get("status")
        contract_ok = (
            model_verified and payload.get("service_tier") == "default" and usage
            and usage["input_tokens"] <= input_ceiling and usage["output_tokens"] <= output_limit
            and usage["estimated_upper_cost_nusd"] <= reserved
        )
        error: ProviderError | None = None
        value: Any = None
        if status == "incomplete":
            reason = (payload.get("incomplete_details") or {}).get("reason") if isinstance(payload.get("incomplete_details"), dict) else None
            error = ProviderError("OPENAI_CONTENT_REJECTED" if reason == "content_filter" else "OPENAI_INCOMPLETE",
                                  "OpenAI did not complete the structured interpretation.", category="content_request")
        elif status != "completed":
            error = ProviderError("OPENAI_SERVICE_UNAVAILABLE", "OpenAI did not complete the request.")
        else:
            parts = []
            messages = payload.get("output")
            for message in messages if isinstance(messages, list) else []:
                if isinstance(message, dict) and message.get("type") == "message" and isinstance(message.get("content"), list):
                    parts.extend(part for part in message["content"] if isinstance(part, dict))
            if any(part.get("type") == "refusal" for part in parts):
                error = ProviderError("OPENAI_REFUSED", "OpenAI declined to interpret this evidence.", category="content_request")
            elif not contract_ok:
                error = ProviderError("OPENAI_USAGE_UNVERIFIED", "OpenAI model, Standard tier or usage could not be verified.")
            else:
                try:
                    value = json.loads("".join(part["text"] for part in parts if part.get("type") == "output_text"))
                    if not Draft202012Validator(schema).is_valid(value):
                        raise ValueError("closed schema mismatch")
                except (KeyError, ValueError, TypeError):
                    error = ProviderError("OPENAI_SCHEMA_INVALID", "The OpenAI result did not pass the application schema.", category="content_request")

        self.ledger.finish(reservation, {
            "stage": stage, "model": model if model_verified else MODEL,
            "status": error.code if error else "success", "elapsed_ms": elapsed,
            "usage": usage, "quota": quota,
            "charged_budget_nusd": usage["estimated_upper_cost_nusd"] if contract_ok else reserved,
        })
        if error:
            raise error
        return Response(value, model, usage, quota, elapsed)

    def visual(self, request: ProviderTaskRequest, spec: ProviderSpec, deadline: float | None,
               _remaining: int, clock: Callable[[], float]) -> ProviderResult:
        expected = "synthetic_test" if self.ledger.synthetic else "school_private"
        if request.privacy_classification != expected or spec.model_id != MODEL:
            raise ProviderError("OPENAI_POLICY_BLOCKED", "The OpenAI source or model is outside the approved route.")
        prompt = request.prompt + (
            "\nWhen reliably visible, use crop-relative normalized [left, top, right, bottom] bounds. "
            "Use answer_working for actual solution steps, and teacher_comment for annotations about the solution. "
            "Use diagram_entry for visible diagram labels and relationships."
        )
        result = self._respond(stage="visual", prompt=prompt, schema=request.response_schema,
                               image=request.crop_bytes, mime=request.crop_mime_type, deadline=deadline, clock=clock)
        return _result(request, replace(spec, model_id=result.model), {"_provider_rate_limits": result.quota},
                       result.elapsed_ms, lambda _: (result.value, result.usage))

    def semantic(self, candidates: list[dict[str, Any]], *, strong: bool = False) -> ProviderRun:
        fields = {"candidate_id", "source_shorthand", "descriptor", "source_notation",
                  "source_semantic", "question_context", "neighboring_marks"}
        packets = [{key: value for key, value in candidate.items() if key in fields} for candidate in candidates]
        prompt = _system_prompt() + "\n\nSemantic candidates:\n" + json.dumps({"candidates": packets}, ensure_ascii=False)
        try:
            result = self._respond(stage="semantic", prompt=prompt, schema=_result_schema(candidates))
        except ProviderError as error:
            if (self.ledger.synthetic or error.category == "content_request"
                    or self.env.get("GROQ_PLAN_MODE") != "free_only"
                    or self.env.get("GROQ_ZERO_COST_CONFIRMED") != "true"):
                # Unresolved content goes through the normal teacher review gates.
                error.retryable = True
                raise
            return classify(candidates, strong=False)
        keyed = result.value["results"]
        return ProviderRun("openai", result.model, len(candidates), result.usage["input_tokens"],
                           result.usage["output_tokens"], result.usage["total_tokens"], result.elapsed_ms,
                           [{"candidate_id": item["candidate_id"], **keyed[str(item["candidate_id"])]} for item in candidates],
                           usage=result.usage)
