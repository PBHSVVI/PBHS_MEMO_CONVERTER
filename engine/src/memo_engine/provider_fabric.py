from __future__ import annotations

import base64
import hashlib
import json
import os
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
CLOUDFLARE_FREE_VISION_MODELS = frozenset({
    "@cf/qwen/qwen3.8-27b",
    "@cf/google/gemma-4-26b-a4b-it",
})


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


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
    return {
        "groq": ProviderSpec(
            provider_id="groq",
            model_id=os.environ.get("MEMO_GROQ_VISION_MODEL", "qwen/qwen3.8-27b").strip()
            or "qwen/qwen3.8-27b",
            capabilities=frozenset({"vision", "structured_output", "semantic_text"}),
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
            model_id=os.environ.get(
                "MEMO_CLOUDFLARE_VISION_MODEL", "@cf/qwen/qwen3.8-27b"
            ).strip() or "@cf/qwen/qwen3.8-27b",
            capabilities=frozenset({"vision", "structured_output", "semantic_text"}),
            credential_names=("CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_AI_API_TOKEN"),
            priority=priority.get("cloudflare", 100),
            school_private_allowed=True,
            free_model_ids=CLOUDFLARE_FREE_VISION_MODELS,
            zero_cost_confirmation_env="CLOUDFLARE_ZERO_COST_CONFIRMED",
            plan_mode=os.environ.get(
                "CLOUDFLARE_WORKERS_AI_PLAN_MODE", FREE_ONLY_PLAN_MODE
            ).strip().lower(),
            enabled="cloudflare" in approved,
        ),
        "mistral": ProviderSpec(
            provider_id="mistral",
            model_id=os.environ.get("MEMO_MISTRAL_VISION_MODEL", "").strip(),
            capabilities=frozenset({"vision", "structured_output", "semantic_text"}),
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
    capability = "vision" if task_type == TASK_VISUAL_INTERPRETATION else "semantic_text"
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


def _result(
    request: ProviderTaskRequest,
    spec: ProviderSpec,
    payload: dict[str, Any],
    elapsed_ms: int,
) -> ProviderResult:
    normalized, usage = _structured_content(payload)
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
    return _result(request, spec, payload, elapsed_ms)


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
    return _post_adapter_json(
        f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{model_path}",
        {"Authorization": f"Bearer {os.environ.get('CLOUDFLARE_AI_API_TOKEN', '').strip()}"},
        {
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": request.prompt},
                {"type": "image_url", "image_url": {"url": _image_data_url(request)}},
            ]}],
            "temperature": 0,
            "max_tokens": 4096,
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
    "cloudflare": cloudflare_visual_adapter,
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
                }
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
            attempts.append({
                "provider": spec.provider_id,
                "model": spec.model_id,
                "status": "success",
                "decision": "accepted",
                "latency_ms": result.latency_ms,
                "quota": result.quota,
            })
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
