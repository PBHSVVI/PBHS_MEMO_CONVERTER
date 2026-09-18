from __future__ import annotations

import json
import os
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


RESULT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "candidate_id": {"type": "string"},
                    "semantic_type": {"type": "string", "enum": SEMANTIC_TYPES},
                    "confidence_score": {"type": "number", "minimum": 0, "maximum": 1},
                    "band": {"type": "string", "enum": ["green", "amber", "red"]},
                    "rationale": {"type": "string"},
                },
                "required": [
                    "candidate_id",
                    "semantic_type",
                    "confidence_score",
                    "band",
                    "rationale",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["items"],
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


def _post_json(url: str, headers: dict[str, str], body: dict[str, Any]) -> tuple[dict[str, Any], int]:
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            # Groq is fronted by Cloudflare. Python urllib's default
            # `Python-urllib/<version>` browser signature can be rejected at the
            # edge with HTTP 403 / Cloudflare 1010 before Groq's API layer sees
            # the request. Use a stable application identifier instead.
            "User-Agent": "PBHS-Memo-Converter/phase4.2",
            **headers,
        },
    )
    started = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=90) as response:
            raw = response.read()
            elapsed_ms = int((time.monotonic() - started) * 1000)
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
            raise ProviderError(
                "AI_PROVIDER_RATE_LIMITED",
                "The configured AI provider is temporarily rate limited.",
                retryable=True,
            ) from exc

        if exc.code == 403:
            safe_code = provider_code or "forbidden"
            normalized = "".join(
                ch if ch.isalnum() else "_"
                for ch in safe_code.upper()
            ).strip("_")[:80]
            code = f"AI_PROVIDER_FORBIDDEN_{normalized}" if normalized else "AI_PROVIDER_FORBIDDEN"

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
                    "Groq denied the request with HTTP 403. Check the organization and "
                    "the exact project that owns GROQ_API_KEY for model permissions."
                )

            raise ProviderError(code, message, retryable=False) from exc

        raise ProviderError(
            "AI_PROVIDER_HTTP_ERROR",
            (
                f"The configured AI provider returned HTTP {exc.code}"
                + (f" ({provider_type}/{provider_code})" if provider_type or provider_code else "")
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

Return only the requested structured output."""


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
            {"role": "system", "content": _system_prompt()},
            {
                "role": "user",
                "content": json.dumps(
                    {"candidates": candidates},
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            },
        ],
        "temperature": 0,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "memo_mark_semantics",
                "strict": True,
                "schema": RESULT_SCHEMA,
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
        items = result["items"]
    except Exception as exc:
        raise ProviderError(
            "AI_PROVIDER_SCHEMA_ERROR",
            "The AI provider response did not match the semantic contract.",
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
