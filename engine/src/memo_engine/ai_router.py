from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


class ProviderError(RuntimeError):
    def __init__(self, code: str, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        self.code = code
        self.public_message = message
        self.retryable = retryable


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


def _post_json(
    url: str,
    headers: dict[str, str],
    body: dict[str, Any],
) -> tuple[dict[str, Any], int]:
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    started = time.monotonic()

    max_rate_retries = max(
        0,
        min(8, int(os.environ.get("MEMO_AI_MAX_RATE_RETRIES", "5"))),
    )
    rate_attempt = 0

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
            with urllib.request.urlopen(req, timeout=90) as response:
                raw = response.read()
                elapsed_ms = int((time.monotonic() - started) * 1000)
                break

        except urllib.error.HTTPError as exc:
            detail = exc.read(4000).decode("utf-8", errors="replace")

            provider_code = None
            provider_type = None
            provider_message = None
            try:
                parsed = json.loads(detail)
                error = parsed.get("error") if isinstance(parsed, dict) else None
                if isinstance(error, dict):
                    raw_code = error.get("code")
                    raw_type = error.get("type")
                    raw_message = error.get("message")
                    if isinstance(raw_code, str):
                        provider_code = raw_code[:120]
                    if isinstance(raw_type, str):
                        provider_type = raw_type[:120]
                    if isinstance(raw_message, str):
                        provider_message = raw_message[:500]
            except Exception:
                pass

            if exc.code == 429:
                if rate_attempt >= max_rate_retries:
                    raise ProviderError(
                        "AI_PROVIDER_RATE_LIMITED",
                        "The AI provider remained rate limited after automatic backoff.",
                        retryable=True,
                    ) from exc

                wait_seconds = _rate_limit_wait_seconds(exc, rate_attempt)
                rate_attempt += 1
                print(
                    "Groq rate limit reached; "
                    f"waiting {wait_seconds:.1f}s before retry "
                    f"{rate_attempt}/{max_rate_retries}."
                )
                time.sleep(wait_seconds)
                continue

            if exc.code == 400 and provider_code == "tool_use_failed":
                raise ProviderError(
                    "AI_PROVIDER_TOOL_USE_FAILED",
                    "The AI model could not safely complete the structured semantic response.",
                    retryable=True,
                ) from exc

            if exc.code == 400 and provider_code == "json_validate_failed":
                raise ProviderError(
                    "AI_PROVIDER_JSON_VALIDATE_FAILED",
                    "The AI model generated a structured response that Groq could not validate.",
                    retryable=True,
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
                    message = f"Groq denied the request: {provider_message}"
                else:
                    message = (
                        "Groq denied the request with HTTP 403. Check organization and "
                        "project model permissions."
                    )

                raise ProviderError(code, message, retryable=False) from exc

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
            ) from exc

        except Exception as exc:
            raise ProviderError(
                "AI_PROVIDER_NETWORK_ERROR",
                "The configured AI provider could not be reached.",
                retryable=True,
            ) from exc

    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise ProviderError(
            "AI_PROVIDER_INVALID_RESPONSE",
            "The AI provider returned an unreadable response.",
            retryable=True,
        ) from exc

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
