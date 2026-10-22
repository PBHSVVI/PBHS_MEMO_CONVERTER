from __future__ import annotations

import json
import os
import random
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


class ProviderError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = True,
        retry_after_seconds: float | None = None,
        provider_saturated: bool = False,
        category: str | None = None,
        http_status: int | None = None,
        rate_limits: dict[str, Any] | None = None,
        provider_code: str | int | None = None,
        provider_message: str | None = None,
        diagnostics: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.public_message = message
        self.retryable = retryable
        self.retry_after_seconds = retry_after_seconds
        self.provider_saturated = provider_saturated
        self.category = category or ("transient_capacity" if retryable else "permanent_provider")
        self.http_status = http_status
        self.rate_limits = rate_limits or {}
        self.provider_code = provider_code
        self.provider_message = provider_message
        self.diagnostics = diagnostics or {}


SEMANTIC_TYPES = [
    "method",
    "accuracy",
    "answer",
    "consistent_accuracy",
    "formula",
    "factorisation",
    "substitution",
    "simplification",
    "statement",
    "reason",
    "statement_reason",
    "conclusion",
    "construction",
    "given",
    "graph_feature",
    "selection",
    "progressive",
    "other",
]


def _result_schema(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    candidate_ids = [str(item["candidate_id"]) for item in candidates]
    if len(candidate_ids) != len(set(candidate_ids)):
        raise ProviderError(
            "AI_PROVIDER_INPUT_DUPLICATE_CANDIDATE",
            "The semantic batch contains duplicate candidate identifiers.",
            retryable=False,
        )

    value_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "semantic_type": {"type": "string", "enum": SEMANTIC_TYPES},
            "confidence_score": {"type": "number", "minimum": 0, "maximum": 1},
            "band": {"type": "string", "enum": ["green", "amber", "red"]},
            "rationale": {"type": "string"},
        },
        "required": [
            "semantic_type",
            "confidence_score",
            "band",
            "rationale",
        ],
        "additionalProperties": False,
    }

    return {
        "type": "object",
        "properties": {
            "results": {
                "type": "object",
                "properties": {
                    candidate_id: value_schema
                    for candidate_id in candidate_ids
                },
                "required": candidate_ids,
                "additionalProperties": False,
            }
        },
        "required": ["results"],
        "additionalProperties": False,
    }



@dataclass
class ProviderRun:
    provider: str
    model: str
    candidate_count: int
    prompt_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    elapsed_ms: int
    results: list[dict[str, Any]]


def _duration_seconds(value: str | None) -> float | None:
    if not value:
        return None
    value = value.strip().lower()
    try:
        return float(value)
    except ValueError:
        pass

    match = re.fullmatch(
        r"(?:(?P<hours>\d+(?:\.\d+)?)h)?"
        r"(?:(?P<minutes>\d+(?:\.\d+)?)m)?"
        r"(?:(?P<seconds>\d+(?:\.\d+)?)s)?",
        value,
    )
    if not match:
        return None

    hours = float(match.group("hours") or 0)
    minutes = float(match.group("minutes") or 0)
    seconds = float(match.group("seconds") or 0)
    total = hours * 3600 + minutes * 60 + seconds
    return total if total > 0 else None


def _rate_limit_wait_seconds(
    exc: urllib.error.HTTPError,
    attempt: int,
) -> float:
    retry_after = _duration_seconds(exc.headers.get("retry-after"))
    token_reset = _duration_seconds(exc.headers.get("x-ratelimit-reset-tokens"))

    candidates = [value for value in [retry_after, token_reset] if value is not None]
    if candidates:
        # Add a small deterministic cushion so we do not retry on the exact boundary.
        return min(max(max(candidates) + 1.5, 2.0), 120.0)

    # Headerless fallback: bounded exponential backoff.
    return min(10.0 * (2 ** attempt), 90.0)


def _safe_rate_metadata(headers: Any) -> dict[str, Any]:
    """Return only bounded, non-sensitive provider capacity metadata."""
    if headers is None:
        return {}
    result: dict[str, Any] = {}
    integer_fields = {
        "x-ratelimit-limit-requests": "limit_requests",
        "x-ratelimit-limit-tokens": "limit_tokens",
        "x-ratelimit-remaining-requests": "remaining_requests",
        "x-ratelimit-remaining-tokens": "remaining_tokens",
        "ratelimit-limit": "limit_requests",
        "ratelimit-remaining": "remaining_requests",
    }
    for header, field in integer_fields.items():
        try:
            value = int(str(headers.get(header, "")).strip())
        except (TypeError, ValueError):
            continue
        if value >= 0:
            result[field] = value
    duration_fields = {
        "retry-after": "retry_after_seconds",
        "x-ratelimit-reset-requests": "reset_requests_seconds",
        "x-ratelimit-reset-tokens": "reset_tokens_seconds",
        "ratelimit-reset": "reset_requests_seconds",
    }
    for header, field in duration_fields.items():
        value = _duration_seconds(headers.get(header))
        if value is not None:
            result[field] = min(value, 3600.0)
    return result


def _post_json(
    url: str,
    headers: dict[str, str],
    body: dict[str, Any],
    *,
    timeout_seconds: float = 90.0,
    deadline_monotonic: float | None = None,
    remaining_requests: int = 1,
    clock: Any = time.monotonic,
    sleeper: Any = time.sleep,
    jitter: Any = random.uniform,
    max_rate_retries: int | None = None,
    max_transient_retries: int = 2,
) -> tuple[dict[str, Any], int]:
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    started = clock()

    if max_rate_retries is None:
        max_rate_retries = max(
            0,
            min(8, int(os.environ.get("MEMO_AI_MAX_RATE_RETRIES", "5"))),
        )
    else:
        max_rate_retries = max(0, min(8, int(max_rate_retries)))
    max_transient_retries = max(0, min(4, int(max_transient_retries)))
    rate_attempt = 0
    transient_attempt = 0
    response_rate_limits: dict[str, Any] = {}

    while True:
        req = urllib.request.Request(
            url,
            data=data,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "PBHS-Memo-Converter/phase5.1",
                **headers,
            },
        )

        try:
            with urllib.request.urlopen(req, timeout=timeout_seconds) as response:
                raw = response.read()
                response_rate_limits = _safe_rate_metadata(getattr(response, "headers", None))
                elapsed_ms = int((clock() - started) * 1000)
                break

        except urllib.error.HTTPError as exc:
            detail = exc.read(4000).decode("utf-8", errors="replace")

            provider_code = None
            provider_type = None
            provider_message = None
            try:
                parsed = json.loads(detail)
                error = parsed.get("error") if isinstance(parsed, dict) else None
                if not isinstance(error, dict) and isinstance(parsed, dict):
                    errors = parsed.get("errors")
                    if isinstance(errors, list) and errors and isinstance(errors[0], dict):
                        error = errors[0]
                if isinstance(error, dict):
                    raw_code = error.get("code")
                    raw_type = error.get("type")
                    raw_message = error.get("message")
                    if isinstance(raw_code, str):
                        provider_code = raw_code[:120]
                    elif isinstance(raw_code, int):
                        provider_code = raw_code
                    if isinstance(raw_type, str):
                        provider_type = raw_type[:120]
                    if isinstance(raw_message, str):
                        provider_message = raw_message[:500]
            except Exception:
                pass

            if (
                provider_message
                and re.search(r"json mode (?:couldn't|could not) be met", provider_message, re.I)
            ):
                raise ProviderError(
                    "AI_PROVIDER_JSON_MODE_UNMET",
                    "The model could not satisfy the requested structured JSON schema.",
                    retryable=False,
                    category="content_request",
                    http_status=exc.code,
                    provider_code=provider_code,
                    provider_message=provider_message,
                ) from exc

            if exc.code == 429:
                rate_limits = _safe_rate_metadata(exc.headers)
                if rate_attempt >= max_rate_retries:
                    raise ProviderError(
                        "AI_PROVIDER_RATE_LIMITED",
                        "The AI provider remained rate limited after automatic backoff.",
                        retryable=True,
                        retry_after_seconds=_rate_limit_wait_seconds(exc, rate_attempt),
                        provider_saturated=True,
                        category="transient_capacity",
                        http_status=429,
                        rate_limits=rate_limits,
                    ) from exc

                wait_seconds = _rate_limit_wait_seconds(exc, rate_attempt)
                if deadline_monotonic is not None:
                    remaining_phase = max(0.0, deadline_monotonic - clock())
                    request_count = max(1, int(remaining_requests))
                    useful_wait = remaining_phase / request_count
                    request_budget = min(timeout_seconds, useful_wait)
                    if (
                        wait_seconds > useful_wait
                        or wait_seconds + request_budget > remaining_phase
                    ):
                        raise ProviderError(
                            "AI_PROVIDER_RATE_LIMITED",
                            (
                                "The AI provider retry delay does not fit within "
                                "the remaining visual processing budget."
                            ),
                            retryable=True,
                            retry_after_seconds=wait_seconds,
                            provider_saturated=True,
                            category="transient_capacity",
                            http_status=429,
                            rate_limits=rate_limits,
                        ) from exc
                rate_attempt += 1
                wait_seconds = min(120.0, wait_seconds + max(0.0, float(jitter(0.0, 0.75))))
                print(
                    "AI provider rate limit reached; "
                    f"waiting {wait_seconds:.1f}s before retry "
                    f"{rate_attempt}/{max_rate_retries}."
                )
                sleeper(wait_seconds)
                continue

            if exc.code in {500, 502, 503} and transient_attempt < max_transient_retries:
                wait_seconds = min(12.0, (2.0 ** transient_attempt) + float(jitter(0.0, 0.75)))
                if deadline_monotonic is not None and clock() + wait_seconds + timeout_seconds > deadline_monotonic:
                    raise ProviderError(
                        "AI_PROVIDER_CAPACITY_UNAVAILABLE",
                        "The AI provider is temporarily unavailable beyond the remaining processing budget.",
                        retryable=True,
                        retry_after_seconds=wait_seconds,
                        provider_saturated=True,
                        category="transient_capacity",
                        http_status=exc.code,
                        rate_limits=_safe_rate_metadata(exc.headers),
                    ) from exc
                transient_attempt += 1
                sleeper(wait_seconds)
                continue

            if exc.code == 400 and provider_code == "tool_use_failed":
                raise ProviderError(
                    "AI_PROVIDER_TOOL_USE_FAILED",
                    "The AI model could not safely complete the structured semantic response.",
                    retryable=True,
                    category="permanent_schema",
                    http_status=400,
                ) from exc

            if exc.code == 400 and provider_code == "json_validate_failed":
                raise ProviderError(
                    "AI_PROVIDER_JSON_VALIDATE_FAILED",
                    "The AI model generated a structured response that Groq could not validate.",
                    retryable=True,
                    category="permanent_schema",
                    http_status=400,
                ) from exc

            if exc.code == 403:
                safe_code = provider_code or "forbidden"
                normalized = "".join(
                    ch if ch.isalnum() else "_"
                    for ch in safe_code.upper()
                ).strip("_")[:80]
                code = (
                    f"AI_PROVIDER_FORBIDDEN_{normalized}"
                    if normalized
                    else "AI_PROVIDER_FORBIDDEN"
                )

                if provider_code == "model_permission_blocked_org":
                    message = (
                        "Groq blocked the requested model at the organization level. "
                        "Enable the model under Groq Settings -> Organization -> Limits."
                    )
                elif provider_code == "model_permission_blocked_project":
                    message = (
                        "Groq blocked the requested model at the API key's project level. "
                        "Select the project that owns this API key, then enable the model "
                        "under Groq Settings -> Projects -> Limits."
                    )
                elif provider_message:
                    message = f"The AI provider denied the request: {provider_message}"
                else:
                    message = (
                        "The AI provider denied the request with HTTP 403. Check organization and "
                        "project model permissions."
                    )

                raise ProviderError(
                    code,
                    message,
                    retryable=False,
                    category="auth_configuration",
                    http_status=403,
                    provider_code=provider_code,
                    provider_message=provider_message,
                ) from exc

            if exc.code in {401, 403}:
                raise ProviderError(
                    "AI_PROVIDER_AUTH_CONFIGURATION_FAILED",
                    "The configured AI provider credential or model access is not valid.",
                    retryable=False,
                    category="auth_configuration",
                    http_status=exc.code,
                    provider_code=provider_code,
                    provider_message=provider_message,
                ) from exc

            raise ProviderError(
                "AI_PROVIDER_HTTP_ERROR",
                (
                    f"The configured AI provider returned HTTP {exc.code}"
                    + (
                        f" ({provider_type}/{provider_code})"
                        if provider_type or provider_code
                        else ""
                    )
                    + "."
                ),
                retryable=500 <= exc.code < 600,
                category=(
                    "transient_capacity" if 500 <= exc.code < 600
                    else "content_request"
                ),
                http_status=exc.code,
                rate_limits=_safe_rate_metadata(exc.headers),
                provider_code=provider_code,
                provider_message=provider_message,
            ) from exc

        except Exception as exc:
            raise ProviderError(
                "AI_PROVIDER_NETWORK_ERROR",
                "The configured AI provider could not be reached.",
                retryable=True,
                category="transient_capacity",
            ) from exc

    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise ProviderError(
            "AI_PROVIDER_INVALID_RESPONSE",
            "The AI provider returned an unreadable response.",
            retryable=True,
            category="permanent_schema",
        ) from exc
    if response_rate_limits:
        payload["_provider_rate_limits"] = response_rate_limits
    return payload, elapsed_ms


def _system_prompt() -> str:
    return """You are a mathematics marking-guideline semantic classifier.

Your ONLY task is to classify the semantic role of each supplied marking point.
Do not solve the mathematics. Do not alter question numbering, marks, source text,
or printed totals. Do not invent missing content.

Controlled semantic types:
method, accuracy, answer, consistent_accuracy, formula, factorisation,
substitution, simplification, statement, reason, statement_reason, conclusion,
construction, given, graph_feature, selection, progressive, other.

Hard shorthand constraints:
- M -> method.
- CA -> consistent_accuracy.
- R -> reason.
- A -> accuracy OR answer only.
- F -> formula OR factorisation only.
- S -> statement OR substitution OR simplification only.

Use the question context, descriptor, shorthand code and neighbouring marking points.
If evidence is genuinely insufficient, use band amber or red. Green means the
semantic choice is safe enough that no unresolved ambiguity could change the
meaning of the marking guideline. Confidence alone never overrides the shorthand
constraints or source evidence.

Keep each rationale to one short sentence of at most 16 words. Return only the requested structured output."""


def groq_classify(candidates: list[dict[str, Any]], model: str) -> ProviderRun:
    key = os.environ.get("GROQ_API_KEY", "").strip()
    if not key:
        raise ProviderError(
            "AI_PROVIDER_NOT_CONFIGURED",
            "GROQ_API_KEY is not configured for the hosted worker.",
            retryable=False,
        )

    body = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": (
                    _system_prompt()
                    + "\n\nSemantic candidates:\n"
                    + json.dumps(
                        {"candidates": candidates},
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                ),
            },
        ],
        "temperature": 0,
        "reasoning_effort": "low",
        "include_reasoning": False,
        "max_completion_tokens": 1536,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "memo_mark_semantics",
                "strict": True,
                "schema": _result_schema(candidates),
            },
        },
    }

    payload, elapsed_ms = _post_json(
        "https://api.groq.com/openai/v1/chat/completions",
        {"Authorization": f"Bearer {key}"},
        body,
    )

    try:
        content = payload["choices"][0]["message"]["content"]
        result = json.loads(content)
        keyed = result["results"]
        expected_ids = [str(item["candidate_id"]) for item in candidates]

        if set(keyed.keys()) != set(expected_ids):
            raise ValueError("provider result key set does not match candidate set")

        items = [
            {
                "candidate_id": candidate_id,
                **keyed[candidate_id],
            }
            for candidate_id in expected_ids
        ]
    except Exception as exc:
        raise ProviderError(
            "AI_PROVIDER_SCHEMA_ERROR",
            "The AI provider response did not match the exact semantic candidate contract.",
            retryable=True,
        ) from exc

    usage = payload.get("usage") or {}
    return ProviderRun(
        provider="groq",
        model=model,
        candidate_count=len(candidates),
        prompt_tokens=usage.get("prompt_tokens"),
        output_tokens=usage.get("completion_tokens"),
        total_tokens=usage.get("total_tokens"),
        elapsed_ms=elapsed_ms,
        results=items,
    )


def configured_provider() -> str:
    privacy_mode = os.environ.get(
        "MEMO_PRIVACY_MODE", "APPROVED_EXTERNAL_ONLY"
    ).strip().upper()

    if privacy_mode == "LOCAL_ONLY":
        raise ProviderError(
            "AI_EXTERNAL_DISABLED",
            "External AI is disabled by the current privacy mode.",
            retryable=False,
        )

    approved = {
        part.strip().lower()
        for part in os.environ.get("MEMO_APPROVED_PROVIDERS", "groq").split(",")
        if part.strip()
    }

    if "groq" in approved and os.environ.get("GROQ_API_KEY", "").strip():
        return "groq"

    raise ProviderError(
        "AI_PROVIDER_NOT_CONFIGURED",
        "No approved external AI provider is configured.",
        retryable=False,
        category="auth_configuration",
    )


def classify(
    candidates: list[dict[str, Any]],
    *,
    strong: bool = False,
) -> ProviderRun:
    provider = configured_provider()
    if provider != "groq":
        raise ProviderError(
            "AI_PROVIDER_UNSUPPORTED",
            "The configured AI provider is not supported by this Phase 4 build.",
            retryable=False,
        )

    model_env = "MEMO_GROQ_STRONG_MODEL" if strong else "MEMO_GROQ_FAST_MODEL"
    default_model = "openai/gpt-oss-120b" if strong else "openai/gpt-oss-20b"
    model = os.environ.get(model_env, default_model).strip() or default_model
    return groq_classify(candidates, model)
