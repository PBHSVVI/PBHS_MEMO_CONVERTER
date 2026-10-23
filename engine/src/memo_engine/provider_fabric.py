from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from .ai_router import ProviderError, _post_json


TASK_VISUAL_INTERPRETATION = "visual_interpretation"
TASK_SEMANTIC_CLASSIFICATION = "semantic_classification"
PRIVACY_SCHOOL_PRIVATE = "school_private"
PRIVACY_SYNTHETIC_TEST = "synthetic_test"
FREE_ONLY_PLAN_MODE = "free_only"
DEFAULT_VISUAL_PROVIDER_ORDER = ("groq", "cloudflare", "mistral")
CLOUDFLARE_LLAMA_STRUCTURED_VISION_MODEL = "@cf/meta/llama-3.2-11b-vision-instruct"
CLOUDFLARE_COMPOSITE_VISION_MODEL = "@cf/google/gemma-4-26b-a4b-it"
CLOUDFLARE_PREFERRED_STRUCTURER_MODEL = "@cf/meta/llama-3.3-70b-instruct-fp8-fast"
CLOUDFLARE_COMPOSITE_PROMPT_VERSION = "cloudflare-composite-vision-v1"
CLOUDFLARE_STRUCTURER_PROMPT_VERSION = "cloudflare-grounded-structurer-v2"
CLOUDFLARE_GROUNDING_SCHEMA_VERSION = "cloudflare-grounded-wrapper-v2"
CLOUDFLARE_COMPOSITE_CHECKPOINT_VERSION = "cloudflare-composite-v2"

# This policy is authoritative for both Stage-S prompting and deterministic
# validation. Paths not explicitly exempted are content-bearing by default.
# Array indexes are normalized to ``*`` for policy matching only; diagnostics
# always retain their exact indexed JSON Pointer paths.
CLOUDFLARE_GROUNDING_EXEMPT_PATH_PATTERNS = frozenset({
    "/payload/schema_version",
    "/payload/page",
    "/payload/evidence/*/kind",
    "/payload/evidence/*/confidence",
    "/payload/evidence/*/source",
    "/payload/mark_changes/*/level",
    "/payload/mark_changes/*/confidence",
    "/payload/mark_changes/*/requires_confirmation",
})
CLOUDFLARE_GROUNDING_VALIDATION_MODES = {
    "/payload/visual_content_present": "presence",
    "/payload/evidence/*/question_ref": "exact",
    "/payload/evidence/*/transcription": "exact",
    "/payload/evidence/*/normalized_math": "math",
    "/payload/mark_changes/*/question_ref": "exact",
    "/payload/mark_changes/*/printed_value": "tokens",
    "/payload/mark_changes/*/visual_value": "tokens",
    "/payload/warnings/*": "exact",
}
CLOUDFLARE_TRANSCRIPT_VISION_PRIORITY = (
    CLOUDFLARE_COMPOSITE_VISION_MODEL,
    CLOUDFLARE_LLAMA_STRUCTURED_VISION_MODEL,
    "@cf/qwen/qwen3.8-27b",
)
CLOUDFLARE_JSON_MODE_DOCUMENTED_MODELS = frozenset({
    "@cf/meta/llama-3.3-70b-instruct-fp8-fast",
    "@cf/meta/llama-3-8b-instruct",
    "@cf/meta/llama-3.1-8b-instruct",
    "@hf/nousresearch/hermes-2-pro-mistral-7b",
    "@hf/thebloke/deepseek-coder-6.7b-instruct-awq",
    "@cf/deepseek-ai/deepseek-r1-distill-qwen-32b",
})
CLOUDFLARE_DEPRECATED_MODELS = frozenset({
    "@cf/meta/llama-3-8b-instruct",
    "@cf/meta/llama-3.1-8b-instruct",
    "@hf/nousresearch/hermes-2-pro-mistral-7b",
})
CLOUDFLARE_PAID_ONLY_MODELS = frozenset({
    "@cf/moonshotai/kimi-k2.6",
    "@cf/moonshotai/kimi-k2.7-code",
    "@cf/zai-org/glm-5.2",
    "@cf/zai-org/glm-5.3",
    "@cf/zai-org/glm-5.3-flash",
    "@cf/deepseek-ai/deepseek-v4-flash-0731",
    "@cf/deepseek-ai/deepseek-v4.1-flash-1017",
    "@cf/deepseek-ai/deepseek-v4-pro-0813",
})
CLOUDFLARE_ACTIVE_FREE_JSON_MODE_MODELS = frozenset(
    CLOUDFLARE_JSON_MODE_DOCUMENTED_MODELS
    - CLOUDFLARE_DEPRECATED_MODELS
    - CLOUDFLARE_PAID_ONLY_MODELS
)
CLOUDFLARE_FREE_VISION_MODELS = frozenset({
    "@cf/qwen/qwen3.8-27b",
    "@cf/google/gemma-4-26b-a4b-it",
    CLOUDFLARE_LLAMA_STRUCTURED_VISION_MODEL,
})
CLOUDFLARE_MODEL_CAPABILITIES = {
    "@cf/qwen/qwen3.8-27b": frozenset({"vision", "free_only", "school_private"}),
    "@cf/google/gemma-4-26b-a4b-it": frozenset({"vision", "free_only", "school_private"}),
    CLOUDFLARE_LLAMA_STRUCTURED_VISION_MODEL: frozenset({
        "vision", "free_only", "school_private"
    }),
}
CLOUDFLARE_STRUCTURED_VISUAL_MODELS = frozenset({
    model_id
    for model_id, capabilities in CLOUDFLARE_MODEL_CAPABILITIES.items()
    if "structured_visual" in capabilities
})


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def cloudflare_model_capabilities(model_id: str) -> frozenset[str]:
    return CLOUDFLARE_MODEL_CAPABILITIES.get(model_id, frozenset())


def select_cloudflare_structurer_model(visible_model_ids: set[str]) -> str | None:
    eligible = visible_model_ids & CLOUDFLARE_ACTIVE_FREE_JSON_MODE_MODELS
    if CLOUDFLARE_PREFERRED_STRUCTURER_MODEL in eligible:
        return CLOUDFLARE_PREFERRED_STRUCTURER_MODEL
    return sorted(eligible)[0] if eligible else None


def select_cloudflare_transcript_model(visible_model_ids: set[str]) -> str | None:
    for model in CLOUDFLARE_TRANSCRIPT_VISION_PRIORITY:
        if (
            model in visible_model_ids
            and model in CLOUDFLARE_FREE_VISION_MODELS
            and "vision" in cloudflare_model_capabilities(model)
        ):
            return model
    return None


def _cloudflare_composite_model_id(vision_model: str, structurer_model: str) -> str:
    return f"composite:{vision_model}|{structurer_model}"


def _cloudflare_composite_config(values: Any) -> tuple[str, str, str, bool]:
    vision_model = str(values.get(
        "MEMO_CLOUDFLARE_VISION_MODEL", CLOUDFLARE_COMPOSITE_VISION_MODEL
    ) or "").strip()
    structurer_model = str(values.get("MEMO_CLOUDFLARE_STRUCTURER_MODEL", "") or "").strip()
    model_id = _cloudflare_composite_model_id(vision_model, structurer_model)
    enabled = bool(
        _truthy(values.get("MEMO_CLOUDFLARE_COMPOSITE_VISUAL_ENABLED"))
        and vision_model in CLOUDFLARE_FREE_VISION_MODELS
        and "vision" in cloudflare_model_capabilities(vision_model)
        and structurer_model in CLOUDFLARE_ACTIVE_FREE_JSON_MODE_MODELS
    )
    return vision_model, structurer_model, model_id, enabled


@dataclass(frozen=True)
class ProviderSpec:
    provider_id: str
    model_id: str
    capabilities: frozenset[str]
    credential_names: tuple[str, ...]
    priority: int
    school_private_allowed: bool
    synthetic_allowed: bool = True
    requires_explicit_privacy_approval: bool = False
    privacy_approval_env: str | None = None
    plan_mode: str = FREE_ONLY_PLAN_MODE
    requires_paid_plan: bool = False
    automatic_overage_possible: bool = False
    free_model_ids: frozenset[str] = frozenset()
    zero_cost_confirmation_env: str | None = None
    enabled: bool = True


@dataclass(frozen=True)
class ProviderTaskRequest:
    task_type: str
    region_id: str
    current_question_owner: str | None
    source_question: str | None
    source_page: int
    source_digest: str
    crop_digest: str
    crop_bytes: bytes
    crop_mime_type: str
    interpretation_schema_version: str
    task_prompt_version: str
    privacy_classification: str
    prompt: str
    response_schema: dict[str, Any]
    provider_checkpoint: dict[str, Any] | None = None


@dataclass
class ProviderResult:
    provider_id: str
    model_id: str
    task_type: str
    status: str
    normalized_result: dict[str, Any]
    request_attempt: int
    latency_ms: int | None
    usage: dict[str, Any]
    quota: dict[str, Any]
    result_digest: str
    route_attempts: list[dict[str, Any]] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)


@dataclass
class CircuitState:
    provider_id: str
    reason: str
    category: str
    opened_at_monotonic: float
    retry_at_monotonic: float | None
    retry_after_seconds: float | None
    consecutive_failure_count: int = 1

    def is_open(self, now: float) -> bool:
        return self.retry_at_monotonic is None or now < self.retry_at_monotonic

    def audit(self) -> dict[str, Any]:
        return {
            "provider": self.provider_id,
            "reason": self.reason,
            "category": self.category,
            "opened_at_monotonic": round(self.opened_at_monotonic, 3),
            "retry_at_monotonic": (
                round(self.retry_at_monotonic, 3)
                if self.retry_at_monotonic is not None else None
            ),
            "retry_after_seconds": self.retry_after_seconds,
            "consecutive_failure_count": self.consecutive_failure_count,
        }


class ProviderPoolExhausted(RuntimeError):
    def __init__(
        self,
        attempts: list[dict[str, Any]],
        circuits: list[dict[str, Any]],
        retry_after_seconds: float | None,
    ) -> None:
        super().__init__("No eligible zero-cost visual provider is currently available.")
        self.code = "VISUAL_PROVIDER_POOL_EXHAUSTED"
        self.public_message = str(self)
        self.category = "transient_capacity"
        self.retry_after_seconds = retry_after_seconds
        self.http_status = None
        self.rate_limits: dict[str, Any] = {}
        self.attempts = attempts
        self.circuits = circuits


Adapter = Callable[
    [ProviderTaskRequest, ProviderSpec, float | None, int, Callable[[], float]],
    ProviderResult,
]
PayloadExtractor = Callable[[dict[str, Any]], tuple[dict[str, Any], dict[str, Any]]]


def _safe_provider_message(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    compact = " ".join(value.split())[:300]
    lowered = compact.lower()
    if any(term in lowered for term in ("authorization", "bearer ", "data:image", "api key", "token=")):
        return "Provider returned a redacted credential or payload-related message."
    return re.sub(
        r"(?i)(/accounts/)[0-9a-f]{16,64}",
        r"\1<redacted-account>",
        compact,
    )


def _provider_order() -> list[str]:
    configured = [
        item.strip().lower()
        for item in os.environ.get(
            "MEMO_VISUAL_PROVIDER_ORDER", ",".join(DEFAULT_VISUAL_PROVIDER_ORDER)
        ).split(",")
        if item.strip()
    ]
    return list(dict.fromkeys(configured))


def _approved_providers() -> set[str]:
    return {
        item.strip().lower()
        for item in os.environ.get(
            "MEMO_APPROVED_PROVIDERS", ",".join(DEFAULT_VISUAL_PROVIDER_ORDER)
        ).split(",")
        if item.strip()
    }


def default_provider_registry() -> dict[str, ProviderSpec]:
    order = _provider_order()
    priority = {provider: index for index, provider in enumerate(order)}
    approved = _approved_providers()
    _, _, cloudflare_model, cloudflare_composite_enabled = _cloudflare_composite_config(
        os.environ
    )
    return {
        "groq": ProviderSpec(
            provider_id="groq",
            model_id=os.environ.get("MEMO_GROQ_VISION_MODEL", "qwen/qwen3.8-27b").strip()
            or "qwen/qwen3.8-27b",
            capabilities=frozenset({
                "vision", "structured_json", "structured_visual", "semantic_text"
            }),
            credential_names=("GROQ_API_KEY",),
            priority=priority.get("groq", 100),
            school_private_allowed=True,
            free_model_ids=frozenset({"qwen/qwen3.8-27b"}),
            zero_cost_confirmation_env="GROQ_ZERO_COST_CONFIRMED",
            plan_mode=os.environ.get("GROQ_PLAN_MODE", FREE_ONLY_PLAN_MODE).strip().lower(),
            enabled="groq" in approved,
        ),
        "cloudflare": ProviderSpec(
            provider_id="cloudflare",
            model_id=cloudflare_model,
            capabilities=(
                frozenset({
                    "vision", "structured_json", "structured_visual",
                    "composite_visual", "free_only", "school_private",
                })
                if cloudflare_composite_enabled else frozenset()
            ),
            credential_names=("CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_AI_API_TOKEN"),
            priority=priority.get("cloudflare", 100),
            school_private_allowed=True,
            free_model_ids=(frozenset({cloudflare_model}) if cloudflare_composite_enabled else frozenset()),
            zero_cost_confirmation_env="CLOUDFLARE_ZERO_COST_CONFIRMED",
            plan_mode=os.environ.get(
                "CLOUDFLARE_WORKERS_AI_PLAN_MODE", FREE_ONLY_PLAN_MODE
            ).strip().lower(),
            enabled="cloudflare" in approved and cloudflare_composite_enabled,
        ),
        "mistral": ProviderSpec(
            provider_id="mistral",
            model_id=os.environ.get("MEMO_MISTRAL_VISION_MODEL", "").strip(),
            capabilities=frozenset({
                "vision", "structured_json", "structured_visual", "semantic_text"
            }),
            credential_names=("MISTRAL_API_KEY",),
            priority=priority.get("mistral", 100),
            school_private_allowed=False,
            requires_explicit_privacy_approval=True,
            privacy_approval_env="MISTRAL_SCHOOL_PRIVATE_APPROVED",
            zero_cost_confirmation_env="MISTRAL_ZERO_COST_CONFIRMED",
            plan_mode=os.environ.get("MISTRAL_PLAN_MODE", FREE_ONLY_PLAN_MODE).strip().lower(),
            enabled="mistral" in approved,
        ),
    }


def provider_ineligibility_reason(
    spec: ProviderSpec,
    *,
    task_type: str,
    privacy_classification: str,
    zero_cost_required: bool = True,
    env: dict[str, str] | None = None,
) -> str | None:
    values = os.environ if env is None else env
    capability = (
        "structured_visual"
        if task_type == TASK_VISUAL_INTERPRETATION
        else "semantic_text"
    )
    if not spec.enabled:
        return "disabled"
    if capability not in spec.capabilities:
        return "capability_unavailable"
    if not spec.model_id:
        return "model_unconfigured"
    if zero_cost_required and (
        spec.plan_mode != FREE_ONLY_PLAN_MODE
        or spec.requires_paid_plan
        or spec.automatic_overage_possible
        or (spec.free_model_ids and spec.model_id not in spec.free_model_ids)
    ):
        return "zero_cost_policy_blocked"
    if (
        zero_cost_required
        and spec.zero_cost_confirmation_env
        and not _truthy(values.get(spec.zero_cost_confirmation_env))
    ):
        return "zero_cost_unconfirmed"
    if privacy_classification == PRIVACY_SCHOOL_PRIVATE:
        approved = bool(
            spec.privacy_approval_env and _truthy(values.get(spec.privacy_approval_env))
        )
        if not spec.school_private_allowed and not approved:
            return "privacy_ineligible"
    elif privacy_classification == PRIVACY_SYNTHETIC_TEST:
        if not spec.synthetic_allowed:
            return "privacy_ineligible"
    else:
        return "privacy_classification_unsupported"
    if any(not str(values.get(name, "")).strip() for name in spec.credential_names):
        return "credential_unconfigured"
    return None


def eligible_providers(
    registry: dict[str, ProviderSpec],
    *,
    task_type: str,
    privacy_classification: str,
    zero_cost_required: bool = True,
    env: dict[str, str] | None = None,
) -> list[ProviderSpec]:
    return sorted(
        (
            spec
            for spec in registry.values()
            if provider_ineligibility_reason(
                spec,
                task_type=task_type,
                privacy_classification=privacy_classification,
                zero_cost_required=zero_cost_required,
                env=env,
            ) is None
        ),
        key=lambda spec: (spec.priority, spec.provider_id),
    )


def _image_data_url(request: ProviderTaskRequest) -> str:
    encoded = base64.b64encode(request.crop_bytes).decode("ascii")
    return f"data:{request.crop_mime_type};base64,{encoded}"


def _structured_content(payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    envelope = payload.get("result") if isinstance(payload.get("result"), dict) else payload
    try:
        message = envelope["choices"][0]["message"]["content"]
        if isinstance(message, list):
            message = "".join(
                str(item.get("text") or "") for item in message if isinstance(item, dict)
            )
        normalized = json.loads(message) if isinstance(message, str) else message
    except Exception as exc:
        raise ProviderError(
            "AI_PROVIDER_INVALID_RESPONSE",
            "The visual provider returned an unreadable structured response.",
            retryable=True,
            category="permanent_schema",
        ) from exc
    if not isinstance(normalized, dict):
        raise ProviderError(
            "AI_PROVIDER_INVALID_RESPONSE",
            "The visual provider response was not an object.",
            retryable=True,
            category="permanent_schema",
        )
    return normalized, envelope.get("usage") or {}


def _cloudflare_native_content(
    payload: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    result = payload.get("result")
    result_keys = sorted(str(key) for key in result) if isinstance(result, dict) else []
    response_path = None
    response: Any = None
    if isinstance(result, dict) and "response" in result:
        response = result.get("response")
        response_path = "result.response"
    elif isinstance(result, dict) and "choices" in result:
        try:
            response = result["choices"][0]["message"]["content"]
            if isinstance(response, list):
                response = "".join(
                    str(item.get("text") or "")
                    for item in response
                    if isinstance(item, dict)
                )
            response_path = "result.choices[0].message.content"
        except (KeyError, IndexError, TypeError):
            response = None
    diagnostics = {
        "provider_success": payload.get("success") if isinstance(payload.get("success"), bool) else None,
        "result_exists": result is not None,
        "result_keys": result_keys,
        "response_type": type(response).__name__ if response is not None else None,
        "response_path": response_path,
        "normalization_stage": "cloudflare_native_envelope",
    }
    if payload.get("success") is False:
        errors = payload.get("errors") if isinstance(payload.get("errors"), list) else []
        first = errors[0] if errors and isinstance(errors[0], dict) else {}
        provider_code = first.get("code") if isinstance(first.get("code"), (str, int)) else None
        provider_message = first.get("message") if isinstance(first.get("message"), str) else None
        json_mode_unmet = bool(
            provider_message
            and re.search(r"json mode (?:couldn't|could not) be met", provider_message, re.I)
        )
        raise ProviderError(
            "AI_PROVIDER_JSON_MODE_UNMET" if json_mode_unmet else "AI_PROVIDER_CLOUDFLARE_ERROR",
            (
                "The model could not satisfy the requested structured JSON schema."
                if json_mode_unmet
                else "Cloudflare reported that the Workers AI request was unsuccessful."
            ),
            retryable=False,
            category="content_request" if json_mode_unmet else "permanent_provider",
            provider_code=provider_code,
            provider_message=(provider_message[:300] if provider_message else None),
            diagnostics=diagnostics,
        )
    if not isinstance(result, dict) or response_path is None:
        raise ProviderError(
            "AI_PROVIDER_INVALID_RESPONSE",
            "Cloudflare returned an unreadable native response envelope.",
            retryable=True,
            category="permanent_schema",
            diagnostics=diagnostics,
        )
    try:
        normalized = json.loads(response) if isinstance(response, str) else response
    except (TypeError, ValueError) as exc:
        diagnostics["normalization_stage"] = "cloudflare_native_response_json"
        raise ProviderError(
            "AI_PROVIDER_INVALID_RESPONSE",
            "Cloudflare returned invalid structured response JSON.",
            retryable=True,
            category="permanent_schema",
            diagnostics=diagnostics,
        ) from exc
    if not isinstance(normalized, dict):
        diagnostics["normalization_stage"] = "cloudflare_native_response_object"
        raise ProviderError(
            "AI_PROVIDER_INVALID_RESPONSE",
            "Cloudflare's structured response was not an object.",
            retryable=True,
            category="permanent_schema",
            diagnostics=diagnostics,
        )
    diagnostics["normalization_stage"] = "complete"
    return normalized, result.get("usage") or {}


def _result(
    request: ProviderTaskRequest,
    spec: ProviderSpec,
    payload: dict[str, Any],
    elapsed_ms: int,
    payload_extractor: PayloadExtractor = _structured_content,
) -> ProviderResult:
    normalized, usage = payload_extractor(payload)
    diagnostics: dict[str, Any] = {}
    if payload_extractor is _cloudflare_native_content:
        result = payload.get("result")
        response_path = None
        response: Any = None
        if isinstance(result, dict) and "response" in result:
            response = result.get("response")
            response_path = "result.response"
        elif isinstance(result, dict) and "choices" in result:
            try:
                response = result["choices"][0]["message"]["content"]
                response_path = "result.choices[0].message.content"
            except (KeyError, IndexError, TypeError):
                response = None
        diagnostics = {
            "provider_success": payload.get("success") if isinstance(payload.get("success"), bool) else None,
            "result_exists": result is not None,
            "result_keys": sorted(str(key) for key in result) if isinstance(result, dict) else [],
            "response_type": type(response).__name__ if response is not None else None,
            "response_path": response_path,
            "normalization_stage": "complete",
        }
    quota = payload.get("_provider_rate_limits") or {}
    digest = hashlib.sha256(
        json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return ProviderResult(
        provider_id=spec.provider_id,
        model_id=spec.model_id,
        task_type=request.task_type,
        status="success",
        normalized_result=normalized,
        request_attempt=1,
        latency_ms=elapsed_ms,
        usage=usage,
        quota=quota,
        result_digest=digest,
        diagnostics=diagnostics,
    )


def _post_adapter_json(
    url: str,
    headers: dict[str, str],
    body: dict[str, Any],
    *,
    request: ProviderTaskRequest,
    spec: ProviderSpec,
    deadline_monotonic: float | None,
    remaining_requests: int,
    clock: Callable[[], float],
    payload_extractor: PayloadExtractor = _structured_content,
) -> ProviderResult:
    payload, elapsed_ms = _post_json(
        url,
        headers,
        body,
        timeout_seconds=max(
            5.0,
            min(75.0, float(os.environ.get(
                "MEMO_VISION_REQUEST_TIMEOUT_SECONDS",
                os.environ.get("MEMO_GROQ_VISION_REQUEST_TIMEOUT_SECONDS", "45"),
            ))),
        ),
        deadline_monotonic=deadline_monotonic,
        remaining_requests=remaining_requests,
        clock=clock,
        max_rate_retries=max(
            0, min(3, int(os.environ.get("MEMO_VISUAL_PROVIDER_RATE_RETRIES", "1")))
        ),
        max_transient_retries=max(
            0, min(3, int(os.environ.get("MEMO_VISUAL_PROVIDER_TRANSIENT_RETRIES", "2")))
        ),
    )
    return _result(request, spec, payload, elapsed_ms, payload_extractor)


def groq_visual_adapter(
    request: ProviderTaskRequest,
    spec: ProviderSpec,
    deadline_monotonic: float | None,
    remaining_requests: int,
    clock: Callable[[], float],
) -> ProviderResult:
    return _post_adapter_json(
        "https://api.groq.com/openai/v1/chat/completions",
        {"Authorization": f"Bearer {os.environ.get('GROQ_API_KEY', '').strip()}"},
        {
            "model": spec.model_id,
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": request.prompt},
                {"type": "image_url", "image_url": {"url": _image_data_url(request)}},
            ]}],
            "temperature": 0,
            "max_completion_tokens": 4096,
            "response_format": {"type": "json_schema", "json_schema": {
                "name": "memo_visual_evidence", "strict": True,
                "schema": request.response_schema,
            }},
        },
        request=request,
        spec=spec,
        deadline_monotonic=deadline_monotonic,
        remaining_requests=remaining_requests,
        clock=clock,
    )


def cloudflare_visual_adapter(
    request: ProviderTaskRequest,
    spec: ProviderSpec,
    deadline_monotonic: float | None,
    remaining_requests: int,
    clock: Callable[[], float],
) -> ProviderResult:
    account_id = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "").strip()
    model_path = spec.model_id
    llama_transport = spec.model_id == CLOUDFLARE_LLAMA_STRUCTURED_VISION_MODEL
    body: dict[str, Any] = {
        "messages": [{
            "role": "user",
            "content": request.prompt if llama_transport else [
                {"type": "text", "text": request.prompt},
                {"type": "image_url", "image_url": {"url": _image_data_url(request)}},
            ],
        }],
        "temperature": 0,
        "max_tokens": 4096,
        "response_format": {
            "type": "json_schema",
            "json_schema": request.response_schema,
        },
    }
    if llama_transport:
        body["image"] = _image_data_url(request)
        body["stream"] = False
    return _post_adapter_json(
        f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{model_path}",
        {"Authorization": f"Bearer {os.environ.get('CLOUDFLARE_AI_API_TOKEN', '').strip()}"},
        body,
        request=request,
        spec=spec,
        deadline_monotonic=deadline_monotonic,
        remaining_requests=remaining_requests,
        clock=clock,
        payload_extractor=_cloudflare_native_content,
    )


def cloudflare_stage_v_prompt(request: ProviderTaskRequest) -> str:
    anchor = request.current_question_owner or request.source_question or "unknown"
    return f"""You are an OBSERVER transcribing visible evidence from a mathematics memo crop.
Report only what is visibly present. Do not solve, calculate, correct arithmetic, infer
missing working, or invent labels. Preserve visible numbers, mathematical symbols,
labels, answer order, and spatial relationships. Distinguish question wording from
solution or answer evidence. Use explicit UNCERTAIN lines for unreadable content.

Plain text is required, not JSON. Helpful line prefixes are QUESTION:, TEXT:, MATH:,
LABEL:, RELATION:, ROLE:, and UNCERTAIN:, but exact formatting is not mandatory.
Known question anchor: {anchor}"""


def cloudflare_grounding_policy_prompt() -> str:
    exempt = "\n".join(
        f"- {path}" for path in sorted(CLOUDFLARE_GROUNDING_EXEMPT_PATH_PATTERNS)
    )
    return f"""EVERY populated CONTENT-BEARING payload leaf MUST have exactly one
grounding entry using that leaf's exact indexed JSON Pointer path. Before returning
JSON: inspect every populated payload leaf; add its path and an exact supporting
Stage-V quotation; omit unsupported optional content; never invent a quotation.
Do not use a parent/container path to cover children. Do not include grounding rows
for these deterministic or independently validated metadata paths:
{exempt}
All other populated payload leaves are content-bearing, including visual-presence
claims, text, mathematics, numeric values, warnings, labels, relationships, and
non-null bounding-box coordinates."""


def cloudflare_stage_s_prompt(transcript: str) -> str:
    return """YOU ARE A STRUCTURER, NOT A SOLVER.
Convert only the supplied Stage-V evidence transcript into the requested grounded
wrapper. Do not calculate, repair arithmetic, infer missing answers, reinterpret the
question, or introduce values, labels, or spatial relationships absent from the
transcript. Question-only text must never become answer or solution evidence.

""" + cloudflare_grounding_policy_prompt() + """

STAGE-V TRANSCRIPT:
""" + transcript


def cloudflare_grounded_wrapper_schema(payload_schema: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "description": "Grounded visual evidence wrapper; every content leaf requires an explicit mapping.",
        "properties": {
            "grounding_schema_version": {
                "type": "string", "enum": [CLOUDFLARE_GROUNDING_SCHEMA_VERSION]
            },
            "payload": payload_schema,
            "grounding": {
                "type": "array",
                "maxItems": 240,
                "uniqueItems": True,
                "description": "One exact indexed JSON Pointer mapping per populated content-bearing payload leaf.",
                "items": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "pattern": r"^/payload(?:/(?:[^~/]|~0|~1)+)+$",
                        },
                        "evidence_quote": {"type": "string", "minLength": 1},
                    },
                    "required": ["path", "evidence_quote"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["grounding_schema_version", "payload", "grounding"],
        "additionalProperties": False,
    }


def _cloudflare_response(payload: dict[str, Any]) -> tuple[Any, dict[str, Any], dict[str, Any]]:
    result = payload.get("result")
    if payload.get("success") is False:
        errors = payload.get("errors") if isinstance(payload.get("errors"), list) else []
        first = errors[0] if errors and isinstance(errors[0], dict) else {}
        message = first.get("message") if isinstance(first.get("message"), str) else None
        raise ProviderError(
            "AI_PROVIDER_CLOUDFLARE_ERROR",
            "Cloudflare reported that the Workers AI request was unsuccessful.",
            retryable=False,
            category="content_request",
            provider_code=first.get("code"),
            provider_message=message,
        )
    if not isinstance(result, dict):
        raise ProviderError(
            "AI_PROVIDER_INVALID_RESPONSE",
            "Cloudflare returned an unreadable response envelope.",
            category="permanent_schema",
        )
    response: Any = None
    path = None
    if "response" in result:
        response = result.get("response")
        path = "result.response"
    elif isinstance(result.get("choices"), list):
        try:
            response = result["choices"][0]["message"]["content"]
            if isinstance(response, list):
                response = "".join(
                    str(item.get("text") or "") for item in response if isinstance(item, dict)
                )
            path = "result.choices[0].message.content"
        except (KeyError, IndexError, TypeError):
            response = None
    if path is None:
        raise ProviderError(
            "AI_PROVIDER_INVALID_RESPONSE",
            "Cloudflare returned no usable model response.",
            category="permanent_schema",
        )
    return response, result.get("usage") or {}, {
        "provider_success": payload.get("success") if isinstance(payload.get("success"), bool) else None,
        "response_path": path,
        "response_type": type(response).__name__,
    }


def _cloudflare_stage_post(
    model: str,
    body: dict[str, Any],
    *,
    deadline_monotonic: float | None,
    remaining_requests: int,
    clock: Callable[[], float],
) -> tuple[dict[str, Any], int]:
    account_id = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "").strip()
    return _post_json(
        f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{model}",
        {"Authorization": f"Bearer {os.environ.get('CLOUDFLARE_AI_API_TOKEN', '').strip()}"},
        body,
        timeout_seconds=max(5.0, min(75.0, float(os.environ.get(
            "MEMO_VISION_REQUEST_TIMEOUT_SECONDS", "45"
        )))),
        deadline_monotonic=deadline_monotonic,
        remaining_requests=remaining_requests,
        clock=clock,
        max_rate_retries=max(
            0, min(3, int(os.environ.get("MEMO_VISUAL_PROVIDER_RATE_RETRIES", "1")))
        ),
        max_transient_retries=max(
            0, min(3, int(os.environ.get("MEMO_VISUAL_PROVIDER_TRANSIENT_RETRIES", "2")))
        ),
    )


def cloudflare_stage_v_call(
    request: ProviderTaskRequest,
    model: str,
    deadline_monotonic: float | None,
    remaining_requests: int,
    clock: Callable[[], float],
) -> dict[str, Any]:
    payload, elapsed_ms = _cloudflare_stage_post(
        model,
        {
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": cloudflare_stage_v_prompt(request)},
                {"type": "image_url", "image_url": {"url": _image_data_url(request)}},
            ]}],
            "temperature": 0,
            "max_tokens": 4096,
            "stream": False,
        },
        deadline_monotonic=deadline_monotonic,
        remaining_requests=remaining_requests,
        clock=clock,
    )
    response, usage, diagnostics = _cloudflare_response(payload)
    transcript = response.strip() if isinstance(response, str) else ""
    if not transcript:
        raise ProviderError(
            "AI_PROVIDER_EMPTY_TRANSCRIPT",
            "Cloudflare vision returned no usable evidence transcript.",
            retryable=False,
            category="content_request",
            diagnostics={"composite_stage": "visual_evidence"},
        )
    return {
        "transcript": transcript[:24_000],
        "usage": usage if isinstance(usage, dict) else {},
        "quota": payload.get("_provider_rate_limits") or {},
        "latency_ms": elapsed_ms,
        "diagnostics": diagnostics,
    }


def cloudflare_stage_s_call(
    request: ProviderTaskRequest,
    model: str,
    transcript: str,
    deadline_monotonic: float | None,
    remaining_requests: int,
    clock: Callable[[], float],
) -> dict[str, Any]:
    payload, elapsed_ms = _cloudflare_stage_post(
        model,
        {
            "messages": [{"role": "user", "content": cloudflare_stage_s_prompt(transcript)}],
            "temperature": 0,
            "max_tokens": 4096,
            "stream": False,
            "response_format": {
                "type": "json_schema",
                "json_schema": cloudflare_grounded_wrapper_schema(request.response_schema),
            },
        },
        deadline_monotonic=deadline_monotonic,
        remaining_requests=remaining_requests,
        clock=clock,
    )
    response, usage, diagnostics = _cloudflare_response(payload)
    try:
        wrapper = json.loads(response) if isinstance(response, str) else response
    except (TypeError, ValueError) as exc:
        raise ProviderError(
            "AI_PROVIDER_INVALID_RESPONSE",
            "Cloudflare structurer returned invalid JSON.",
            category="permanent_schema",
            diagnostics={"composite_stage": "json_structurer", **diagnostics},
        ) from exc
    if not isinstance(wrapper, dict):
        raise ProviderError(
            "AI_PROVIDER_INVALID_RESPONSE",
            "Cloudflare structurer response was not an object.",
            category="permanent_schema",
            diagnostics={"composite_stage": "json_structurer", **diagnostics},
        )
    return {
        "wrapper": wrapper,
        "usage": usage if isinstance(usage, dict) else {},
        "quota": payload.get("_provider_rate_limits") or {},
        "latency_ms": elapsed_ms,
        "diagnostics": diagnostics,
    }


def _grounding_normalize(value: str) -> str:
    return " ".join(str(value).split())


def _json_pointer_escape(value: Any) -> str:
    return str(value).replace("~", "~0").replace("/", "~1")


def _populated_json_pointer_leaves(
    value: Any, prefix: str = "/payload"
) -> dict[str, Any]:
    leaves: dict[str, Any] = {}
    if isinstance(value, dict):
        for key, child in value.items():
            leaves.update(_populated_json_pointer_leaves(
                child, f"{prefix}/{_json_pointer_escape(key)}"
            ))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            leaves.update(_populated_json_pointer_leaves(child, f"{prefix}/{index}"))
    elif value is not None and value != "":
        leaves[prefix] = value
    return leaves


def _json_pointer_container_paths(
    value: Any, prefix: str = "/payload"
) -> set[str]:
    paths: set[str] = set()
    if isinstance(value, dict):
        paths.add(prefix)
        for key, child in value.items():
            paths.update(_json_pointer_container_paths(
                child, f"{prefix}/{_json_pointer_escape(key)}"
            ))
    elif isinstance(value, list):
        paths.add(prefix)
        for index, child in enumerate(value):
            paths.update(_json_pointer_container_paths(child, f"{prefix}/{index}"))
    return paths


def _grounding_policy_pattern(path: str) -> str:
    return re.sub(r"/\d+(?=/|$)", "/*", path)


def cloudflare_grounding_path_policy(path: str) -> tuple[str, str]:
    pattern = _grounding_policy_pattern(path)
    if pattern in CLOUDFLARE_GROUNDING_EXEMPT_PATH_PATTERNS:
        return "grounding_exempt_metadata", "none"
    if "/bbox/" in pattern:
        return "content_bearing", "tokens"
    return "content_bearing", CLOUDFLARE_GROUNDING_VALIDATION_MODES.get(
        pattern, "exact"
    )


def enumerate_cloudflare_content_paths(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    requirements: dict[str, dict[str, Any]] = {}
    for path, value in _populated_json_pointer_leaves(payload).items():
        classification, mode = cloudflare_grounding_path_policy(path)
        if classification == "content_bearing":
            requirements[path] = {
                "classification": classification,
                "validation_mode": mode,
                "value": value,
            }
    return requirements


def enumerate_cloudflare_exempt_paths(payload: dict[str, Any]) -> set[str]:
    return {
        path for path in _populated_json_pointer_leaves(payload)
        if cloudflare_grounding_path_policy(path)[0] == "grounding_exempt_metadata"
    }


def _grounding_diagnostics(
    *,
    failure_category: str,
    path: str | None = None,
    missing_paths: list[str] | None = None,
    unknown_paths: list[str] | None = None,
    exempt_paths: list[str] | None = None,
    container_paths: list[str] | None = None,
    duplicate_paths: list[str] | None = None,
    conflicting_duplicate_paths: list[str] | None = None,
) -> dict[str, Any]:
    missing = sorted(set(missing_paths or []))
    unknown = sorted(set(unknown_paths or []))
    exempt = sorted(set(exempt_paths or []))
    containers = sorted(set(container_paths or []))
    duplicates = sorted(set(duplicate_paths or []))
    conflicts = sorted(set(conflicting_duplicate_paths or []))
    result: dict[str, Any] = {
        "grounding_failure_category": failure_category,
        "grounding_missing_paths": missing,
        "grounding_missing_count": len(missing),
        "grounding_unknown_paths": unknown,
        "grounding_unknown_count": len(unknown),
        "grounding_exempt_paths": exempt,
        "grounding_exempt_count": len(exempt),
        "grounding_container_paths": containers,
        "grounding_container_count": len(containers),
        "grounding_duplicate_paths": duplicates,
        "grounding_duplicate_path_count": len(duplicates),
        "grounding_conflicting_duplicate_paths": conflicts,
        "grounding_conflicting_duplicate_count": len(conflicts),
    }
    if path is not None:
        result["grounding_path"] = path
        result["grounding_path_classification"] = cloudflare_grounding_path_policy(path)[0]
    return result


def _raise_grounding_error(
    code: str, message: str, *, failure_category: str, **diagnostic_values: Any
) -> None:
    raise ProviderError(
        code,
        message,
        retryable=False,
        category="content_request",
        diagnostics=_grounding_diagnostics(
            failure_category=failure_category, **diagnostic_values
        ),
    )


def _numeric_tokens(value: Any) -> set[str]:
    return set(re.findall(r"(?<![A-Za-z])\d+(?:[.,]\d+)?", str(value)))


def _math_label_tokens(value: Any) -> set[str]:
    text = str(value)
    labels = set(re.findall(r"(?<![A-Za-z])([A-Za-z])(?=\s*(?:[=+\-*/^(),]|$))", text))
    labels.update(re.findall(r"(?<=[=+\-*/^(,])\s*([A-Za-z])(?![A-Za-z])", text))
    return labels


def validate_cloudflare_grounding(wrapper: Any, transcript: str) -> dict[str, Any]:
    if not isinstance(wrapper, dict) or not isinstance(wrapper.get("payload"), dict):
        _raise_grounding_error(
            "AI_PROVIDER_GROUNDING_INVALID",
            "The composite response did not contain a payload object.",
            failure_category="wrapper_invalid",
        )
    if wrapper.get("grounding_schema_version") != CLOUDFLARE_GROUNDING_SCHEMA_VERSION:
        _raise_grounding_error(
            "AI_PROVIDER_GROUNDING_CONTRACT_VERSION_INVALID",
            "The composite response used an unsupported grounding contract version.",
            failure_category="contract_version",
        )
    entries = wrapper.get("grounding")
    if not isinstance(entries, list):
        _raise_grounding_error(
            "AI_PROVIDER_GROUNDING_INVALID",
            "The composite response did not contain grounding entries.",
            failure_category="grounding_array_invalid",
        )
    payload = wrapper["payload"]
    leaves = _populated_json_pointer_leaves(payload)
    containers = _json_pointer_container_paths(payload)
    requirements = enumerate_cloudflare_content_paths(payload)
    exempt = enumerate_cloudflare_exempt_paths(payload)
    transcript_normalized = _grounding_normalize(transcript)
    grounding: dict[str, str] = {}
    duplicates: list[str] = []
    conflicts: list[str] = []
    unknown: list[str] = []
    supplied_exempt: list[str] = []
    supplied_containers: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            _raise_grounding_error(
                "AI_PROVIDER_GROUNDING_INVALID",
                "A grounding entry was not an object.",
                failure_category="grounding_entry_invalid",
            )
        path = entry.get("path")
        quote = entry.get("evidence_quote")
        if not isinstance(path, str) or not isinstance(quote, str) or not quote.strip():
            _raise_grounding_error(
                "AI_PROVIDER_GROUNDING_INVALID",
                "A grounding entry lacked a valid path or quotation.",
                failure_category="grounding_entry_invalid",
            )
        if path in containers and path not in leaves:
            supplied_containers.append(path)
            continue
        if path not in leaves:
            unknown.append(path)
            continue
        if path in exempt:
            supplied_exempt.append(path)
            continue
        if path in grounding:
            duplicates.append(path)
            if _grounding_normalize(grounding[path]) != _grounding_normalize(quote):
                conflicts.append(path)
            continue
        grounding[path] = quote

    common_diagnostics = {
        "unknown_paths": unknown,
        "exempt_paths": supplied_exempt,
        "container_paths": supplied_containers,
        "duplicate_paths": duplicates,
        "conflicting_duplicate_paths": conflicts,
    }
    if unknown:
        _raise_grounding_error(
            "AI_PROVIDER_GROUNDING_PATH_UNKNOWN",
            "A grounding entry referenced a path that does not exist.",
            failure_category="unknown_path",
            **common_diagnostics,
        )
    if supplied_containers:
        _raise_grounding_error(
            "AI_PROVIDER_GROUNDING_CONTAINER_PATH",
            "A grounding entry referenced a container instead of a content leaf.",
            failure_category="container_path",
            **common_diagnostics,
        )
    if supplied_exempt:
        _raise_grounding_error(
            "AI_PROVIDER_GROUNDING_METADATA_PATH",
            "A grounding entry referenced grounding-exempt metadata.",
            failure_category="metadata_path",
            **common_diagnostics,
        )
    if conflicts:
        _raise_grounding_error(
            "AI_PROVIDER_GROUNDING_DUPLICATE_CONFLICT",
            "Conflicting grounding quotations were supplied for one content path.",
            failure_category="duplicate_conflict",
            **common_diagnostics,
        )

    missing = sorted(set(requirements) - set(grounding))
    if missing:
        _raise_grounding_error(
            "AI_PROVIDER_GROUNDING_MISSING",
            "One or more content-bearing fields lacked grounding evidence.",
            failure_category="missing_coverage",
            missing_paths=missing,
            **common_diagnostics,
        )

    for path, quote in grounding.items():
        normalized_quote = _grounding_normalize(quote)
        if normalized_quote not in transcript_normalized:
            _raise_grounding_error(
                "AI_PROVIDER_GROUNDING_QUOTE_MISSING",
                "A grounding quotation was not present in the vision transcript.",
                failure_category="quote_absent",
                path=path,
                **common_diagnostics,
            )

    for path, requirement in requirements.items():
        value = requirement["value"]
        mode = requirement["validation_mode"]
        quote = grounding[path]
        normalized_quote = _grounding_normalize(quote)
        if mode == "exact" and _grounding_normalize(str(value)) not in normalized_quote:
            _raise_grounding_error(
                "AI_PROVIDER_GROUNDING_UNSUPPORTED_CONTENT",
                "A content-bearing field was not supported by its grounding quotation.",
                failure_category="content_mismatch",
                path=path,
                **common_diagnostics,
            )
        if not _numeric_tokens(value) <= _numeric_tokens(quote):
            _raise_grounding_error(
                "AI_PROVIDER_GROUNDING_UNSUPPORTED_NUMBER",
                "The structurer introduced a number absent from its evidence quotation.",
                failure_category="numeric_token_mismatch",
                path=path,
                **common_diagnostics,
            )
        if mode in {"math", "tokens"} and not _math_label_tokens(value) <= _math_label_tokens(quote):
            _raise_grounding_error(
                "AI_PROVIDER_GROUNDING_UNSUPPORTED_LABEL",
                "The structurer introduced a mathematical label absent from its evidence quotation.",
                failure_category="label_entity_mismatch",
                path=path,
                **common_diagnostics,
            )

    question_lines = [
        _grounding_normalize(line.partition(":")[2])
        for line in transcript.splitlines()
        if line.strip().upper().startswith("QUESTION:")
    ]
    nonquestion_text = " ".join(
        _grounding_normalize(line.partition(":")[2] if ":" in line else line)
        for line in transcript.splitlines()
        if not line.strip().upper().startswith("QUESTION:")
    )
    for index, item in enumerate(payload.get("evidence") or []):
        if not isinstance(item, dict) or item.get("kind") not in {"answer", "answer_working"}:
            continue
        path = f"/payload/evidence/{index}/transcription"
        quote = _grounding_normalize(grounding.get(path, ""))
        quote_content = _grounding_normalize(
            quote.partition(":")[2]
            if quote.upper().startswith("QUESTION:") else quote
        )
        if (
            quote_content
            and any(quote_content in line for line in question_lines)
            and quote_content not in nonquestion_text
        ):
            _raise_grounding_error(
                "AI_PROVIDER_QUESTION_PROMOTED_TO_ANSWER",
                "Question-only transcript text cannot become answer evidence.",
                failure_category="question_promoted_to_answer",
                path=path,
                **common_diagnostics,
            )
    return payload


def _valid_stage_v_checkpoint(
    checkpoint: Any, request: ProviderTaskRequest, model: str
) -> bool:
    if not isinstance(checkpoint, dict):
        return False
    stage = checkpoint.get("stage_v")
    if not isinstance(stage, dict) or stage.get("status") != "success":
        return False
    transcript = stage.get("transcript")
    return bool(
        isinstance(transcript, str)
        and stage.get("source_digest") == request.source_digest
        and stage.get("crop_digest") == request.crop_digest
        and stage.get("prompt_version") == CLOUDFLARE_COMPOSITE_PROMPT_VERSION
        and stage.get("model") == model
        and stage.get("transcript_digest")
        == hashlib.sha256(transcript.encode("utf-8")).hexdigest()
    )


def _valid_stage_s_checkpoint(
    checkpoint: Any, transcript_digest: str, model: str, schema_version: str
) -> bool:
    if not isinstance(checkpoint, dict):
        return False
    stage = checkpoint.get("stage_s")
    return bool(
        isinstance(stage, dict)
        and stage.get("status") == "success"
        and isinstance(stage.get("wrapper"), dict)
        and stage.get("transcript_digest") == transcript_digest
        and stage.get("schema_version") == schema_version
        and stage.get("grounding_schema_version") == CLOUDFLARE_GROUNDING_SCHEMA_VERSION
        and stage.get("prompt_version") == CLOUDFLARE_STRUCTURER_PROMPT_VERSION
        and stage.get("model") == model
    )


def _combined_usage(stage_v: dict[str, Any], stage_s: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    total = 0
    for prefix, stage in (("visual", stage_v), ("structurer", stage_s)):
        usage = stage.get("usage") if isinstance(stage, dict) else {}
        if not isinstance(usage, dict):
            continue
        for key, value in usage.items():
            if isinstance(value, (int, float)):
                result[f"{prefix}_{key}"] = value
                if key == "total_tokens":
                    total += value
    if total:
        result["total_tokens"] = total
    return result


def cloudflare_composite_visual_adapter(
    request: ProviderTaskRequest,
    spec: ProviderSpec,
    deadline_monotonic: float | None,
    remaining_requests: int,
    clock: Callable[[], float],
) -> ProviderResult:
    vision_model, structurer_model, expected_model_id, configured = (
        _cloudflare_composite_config(os.environ)
    )
    if not configured or spec.model_id != expected_model_id:
        raise ProviderError(
            "AI_PROVIDER_COMPOSITE_CONFIGURATION_INVALID",
            "The Cloudflare composite route is not fully qualified and enabled.",
            retryable=False,
            category="auth_configuration",
        )
    checkpoint = (
        dict(request.provider_checkpoint)
        if isinstance(request.provider_checkpoint, dict) else {}
    )
    checkpoint.setdefault("schema_version", CLOUDFLARE_COMPOSITE_CHECKPOINT_VERSION)

    stage_v_cache_hit = _valid_stage_v_checkpoint(checkpoint, request, vision_model)
    if stage_v_cache_hit:
        stage_v = dict(checkpoint["stage_v"])
    else:
        try:
            live_v = cloudflare_stage_v_call(
                request, vision_model, deadline_monotonic, remaining_requests, clock
            )
        except ProviderError as exc:
            checkpoint["stage_v"] = {
                "status": "failed",
                "provider": "cloudflare",
                "model": vision_model,
                "source_digest": request.source_digest,
                "crop_digest": request.crop_digest,
                "prompt_version": CLOUDFLARE_COMPOSITE_PROMPT_VERSION,
                "error_code": exc.code,
                "category": exc.category,
            }
            exc.diagnostics.update({
                "composite_stage": "visual_evidence",
                "circuit_provider": "cloudflare:visual_evidence",
                "stage_v_cache_hit": False,
                "_private_composite_checkpoint": checkpoint,
            })
            raise
        transcript = live_v["transcript"]
        stage_v = {
            "status": "success",
            "provider": "cloudflare",
            "model": vision_model,
            "source_digest": request.source_digest,
            "crop_digest": request.crop_digest,
            "prompt_version": CLOUDFLARE_COMPOSITE_PROMPT_VERSION,
            "transcript_digest": hashlib.sha256(transcript.encode("utf-8")).hexdigest(),
            "transcript": transcript,
            "usage": live_v.get("usage") or {},
            "quota": live_v.get("quota") or {},
            "latency_ms": live_v.get("latency_ms"),
            "response_path": (live_v.get("diagnostics") or {}).get("response_path"),
        }
        checkpoint["stage_v"] = stage_v

    transcript = stage_v["transcript"]
    transcript_digest = stage_v["transcript_digest"]
    stage_s_cache_hit = _valid_stage_s_checkpoint(
        checkpoint, transcript_digest, structurer_model,
        request.interpretation_schema_version,
    )
    if stage_s_cache_hit:
        stage_s = dict(checkpoint["stage_s"])
    else:
        try:
            live_s = cloudflare_stage_s_call(
                request, structurer_model, transcript,
                deadline_monotonic, remaining_requests, clock,
            )
        except ProviderError as exc:
            checkpoint["stage_s"] = {
                "status": "failed",
                "provider": "cloudflare",
                "model": structurer_model,
                "transcript_digest": transcript_digest,
                "schema_version": request.interpretation_schema_version,
                "grounding_schema_version": CLOUDFLARE_GROUNDING_SCHEMA_VERSION,
                "prompt_version": CLOUDFLARE_STRUCTURER_PROMPT_VERSION,
                "error_code": exc.code,
                "category": exc.category,
            }
            exc.diagnostics.update({
                "composite_stage": "json_structurer",
                "circuit_provider": "cloudflare:json_structurer",
                "stage_v_cache_hit": stage_v_cache_hit,
                "_private_composite_checkpoint": checkpoint,
            })
            raise
        stage_s = {
            "status": "success",
            "provider": "cloudflare",
            "model": structurer_model,
            "transcript_digest": transcript_digest,
            "schema_version": request.interpretation_schema_version,
            "grounding_schema_version": CLOUDFLARE_GROUNDING_SCHEMA_VERSION,
            "prompt_version": CLOUDFLARE_STRUCTURER_PROMPT_VERSION,
            "wrapper": live_s["wrapper"],
            "wrapper_digest": hashlib.sha256(json.dumps(
                live_s["wrapper"], sort_keys=True, separators=(",", ":")
            ).encode("utf-8")).hexdigest(),
            "usage": live_s.get("usage") or {},
            "quota": live_s.get("quota") or {},
            "latency_ms": live_s.get("latency_ms"),
            "response_path": (live_s.get("diagnostics") or {}).get("response_path"),
        }
        checkpoint["stage_s"] = stage_s

    try:
        payload = validate_cloudflare_grounding(stage_s["wrapper"], transcript)
    except ProviderError as exc:
        checkpoint["stage_s"] = {
            **stage_s,
            "status": "failed",
            "error_code": exc.code,
            "category": exc.category,
        }
        exc.diagnostics.update({
            "composite_stage": "deterministic_grounding",
            "circuit_provider": "cloudflare:json_structurer",
            "stage_v_cache_hit": stage_v_cache_hit,
            "_private_composite_checkpoint": checkpoint,
        })
        raise
    result_digest = hashlib.sha256(json.dumps(
        payload, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")).hexdigest()
    checkpoint["final"] = {
        "status": "success",
        "result_digest": result_digest,
        "vision_model": vision_model,
        "structurer_model": structurer_model,
    }
    quota = dict(stage_s.get("quota") or stage_v.get("quota") or {})
    return ProviderResult(
        provider_id="cloudflare",
        model_id=expected_model_id,
        task_type=request.task_type,
        status="success",
        normalized_result=payload,
        request_attempt=1,
        latency_ms=sum(
            int(value or 0) for value in (
                stage_v.get("latency_ms"), stage_s.get("latency_ms")
            )
        ),
        usage=_combined_usage(stage_v, stage_s),
        quota=quota,
        result_digest=result_digest,
        diagnostics={
            "composite": True,
            "vision_provider": "cloudflare",
            "vision_model": vision_model,
            "vision_transcript_digest": transcript_digest,
            "structurer_provider": "cloudflare",
            "structurer_model": structurer_model,
            "structurer_result_digest": stage_s.get("wrapper_digest"),
            "stage_v_cache_hit": stage_v_cache_hit,
            "stage_s_cache_hit": stage_s_cache_hit,
            "grounding_status": "passed",
            "_private_composite_checkpoint": checkpoint,
        },
    )


def mistral_visual_adapter(
    request: ProviderTaskRequest,
    spec: ProviderSpec,
    deadline_monotonic: float | None,
    remaining_requests: int,
    clock: Callable[[], float],
) -> ProviderResult:
    return _post_adapter_json(
        "https://api.mistral.ai/v1/chat/completions",
        {"Authorization": f"Bearer {os.environ.get('MISTRAL_API_KEY', '').strip()}"},
        {
            "model": spec.model_id,
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": request.prompt},
                {"type": "image_url", "image_url": _image_data_url(request)},
            ]}],
            "temperature": 0,
            "max_tokens": 4096,
            "service_tier": "standard_only",
            "response_format": {"type": "json_schema", "json_schema": {
                "name": "memo_visual_evidence", "strict": True,
                "schema": request.response_schema,
            }},
        },
        request=request,
        spec=spec,
        deadline_monotonic=deadline_monotonic,
        remaining_requests=remaining_requests,
        clock=clock,
    )


DEFAULT_ADAPTERS: dict[str, Adapter] = {
    "groq": groq_visual_adapter,
    "cloudflare": cloudflare_composite_visual_adapter,
    "mistral": mistral_visual_adapter,
}


class ProviderFabric:
    def __init__(
        self,
        *,
        registry: dict[str, ProviderSpec] | None = None,
        adapters: dict[str, Adapter] | None = None,
        env: dict[str, str] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.registry = registry or default_provider_registry()
        self.adapters = adapters or DEFAULT_ADAPTERS
        self.env = os.environ if env is None else env
        self.clock = clock
        self.circuits: dict[str, CircuitState] = {}
        self.quota: dict[str, dict[str, Any]] = {}
        self.failure_counts: dict[str, int] = {}

    def eligible(self, request: ProviderTaskRequest) -> list[ProviderSpec]:
        return eligible_providers(
            self.registry,
            task_type=request.task_type,
            privacy_classification=request.privacy_classification,
            zero_cost_required=True,
            env=self.env,
        )

    def _open_circuit(self, spec: ProviderSpec, exc: ProviderError) -> None:
        now = self.clock()
        previous = self.failure_counts.get(spec.provider_id, 0)
        self.failure_counts[spec.provider_id] = previous + 1
        retry_after = exc.retry_after_seconds
        self.circuits[spec.provider_id] = CircuitState(
            provider_id=spec.provider_id,
            reason=exc.code,
            category=exc.category,
            opened_at_monotonic=now,
            retry_at_monotonic=(now + retry_after if retry_after is not None else None),
            retry_after_seconds=retry_after,
            consecutive_failure_count=previous + 1,
        )

    def _known_exhausted(self, spec: ProviderSpec) -> bool:
        quota = self.quota.get(spec.provider_id) or {}
        return quota.get("remaining_requests") == 0 or quota.get("remaining_tokens") == 0

    def route(
        self,
        request: ProviderTaskRequest,
        *,
        deadline_monotonic: float | None,
        remaining_requests: int,
    ) -> ProviderResult:
        attempts: list[dict[str, Any]] = []
        eligible = self.eligible(request)
        eligible_ids = {spec.provider_id for spec in eligible}
        for spec in sorted(self.registry.values(), key=lambda item: (item.priority, item.provider_id)):
            if spec.provider_id in eligible_ids:
                continue
            attempts.append({
                "provider": spec.provider_id,
                "model": spec.model_id,
                "status": "skipped",
                "decision": provider_ineligibility_reason(
                    spec,
                    task_type=request.task_type,
                    privacy_classification=request.privacy_classification,
                    zero_cost_required=True,
                    env=self.env,
                ) or "ineligible",
            })
        for spec in eligible:
            circuit = self.circuits.get(spec.provider_id)
            if circuit and circuit.is_open(self.clock()):
                attempts.append({
                    "provider": spec.provider_id,
                    "model": spec.model_id,
                    "status": "skipped",
                    "decision": "circuit_open",
                    "error_code": circuit.reason,
                })
                continue
            if circuit:
                self.circuits.pop(spec.provider_id, None)
                self.quota.pop(spec.provider_id, None)
            if self._known_exhausted(spec):
                attempts.append({
                    "provider": spec.provider_id,
                    "model": spec.model_id,
                    "status": "skipped",
                    "decision": "known_free_quota_exhausted",
                })
                continue
            adapter = self.adapters.get(spec.provider_id)
            if adapter is None:
                attempts.append({
                    "provider": spec.provider_id,
                    "model": spec.model_id,
                    "status": "skipped",
                    "decision": "adapter_unavailable",
                })
                continue
            try:
                result = adapter(
                    request, spec, deadline_monotonic, remaining_requests, self.clock
                )
            except ProviderError as exc:
                diagnostics = dict(getattr(exc, "diagnostics", None) or {})
                private_checkpoint = diagnostics.pop("_private_composite_checkpoint", None)
                attempt = {
                    "provider": spec.provider_id,
                    "model": spec.model_id,
                    "status": "failed",
                    "decision": (
                        "content_result" if exc.category == "content_request" else "fallback"
                    ),
                    "error_code": exc.code,
                    "error_category": exc.category,
                    "http_status": exc.http_status,
                    "retry_after_seconds": exc.retry_after_seconds,
                    "quota": exc.rate_limits,
                    "provider_error_code": getattr(exc, "provider_code", None),
                    "provider_error_message": _safe_provider_message(
                        getattr(exc, "provider_message", None)
                    ),
                    **diagnostics,
                }
                if private_checkpoint is not None:
                    attempt["_private_composite_checkpoint"] = private_checkpoint
                attempts.append(attempt)
                if exc.category == "content_request":
                    exc.route_attempts = attempts
                    raise
                self._open_circuit(spec, exc)
                continue
            self.failure_counts[spec.provider_id] = 0
            self.quota[spec.provider_id] = dict(result.quota)
            exhausted = (
                result.quota.get("remaining_requests") == 0
                or result.quota.get("remaining_tokens") == 0
            )
            if exhausted:
                resets = [
                    result.quota.get("reset_requests_seconds"),
                    result.quota.get("reset_tokens_seconds"),
                ]
                resets = [
                    float(value) for value in resets
                    if isinstance(value, (int, float)) and value >= 0
                ]
                retry_after = max(resets) if resets else None
                now = self.clock()
                self.circuits[spec.provider_id] = CircuitState(
                    provider_id=spec.provider_id,
                    reason="AI_PROVIDER_FREE_QUOTA_EXHAUSTED",
                    category="transient_capacity",
                    opened_at_monotonic=now,
                    retry_at_monotonic=(now + retry_after if retry_after is not None else None),
                    retry_after_seconds=retry_after,
                )
            diagnostics = dict(result.diagnostics)
            private_checkpoint = diagnostics.pop("_private_composite_checkpoint", None)
            success_attempt = {
                "provider": spec.provider_id,
                "model": spec.model_id,
                "status": "success",
                "decision": "accepted",
                "latency_ms": result.latency_ms,
                "quota": result.quota,
                **diagnostics,
            }
            if private_checkpoint is not None:
                success_attempt["_private_composite_checkpoint"] = private_checkpoint
            attempts.append(success_attempt)
            result.route_attempts = attempts
            return result

        retry_values = [
            item.retry_after_seconds
            for item in self.circuits.values()
            if item.retry_after_seconds is not None
        ]
        raise ProviderPoolExhausted(
            attempts,
            [item.audit() for item in self.circuits.values()],
            min(retry_values) if retry_values else None,
        )

    def circuit_audit(self) -> list[dict[str, Any]]:
        return [item.audit() for item in self.circuits.values()]
