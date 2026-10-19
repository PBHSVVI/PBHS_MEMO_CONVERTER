from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import re
import time
from typing import Any, Callable

from PIL import Image, ImageStat

from .ai_router import ProviderError, _post_json, configured_provider
from .math_notation import normalize_visual_math


SCHEMA_VERSION = "1.0"
OWNERSHIP_ALGORITHM_VERSION = "anchored-crop-v2"
EVIDENCE_KINDS = {
    "answer",
    "answer_working",
    "marking_note",
    "teacher_comment",
    "tick",
    "cross",
    "diagram_entry",
    "other_visible_annotation",
}
VISUAL_REVIEW_THRESHOLD = 0.85
VISUAL_EVIDENCE_MAX_ITEMS = 40
DEFAULT_VISUAL_PHASE_TIMEOUT_SECONDS = 900.0
DEFAULT_VISION_REQUEST_TIMEOUT_SECONDS = 45.0
VISUAL_FAILURE_CIRCUIT_THRESHOLD = 3
NON_RETRYABLE_VISUAL_FAILURE_CODES = {
    "VISUAL_INVALID_RESPONSE",
    "VISUAL_SOURCE_UNSUPPORTED",
    "AI_PROVIDER_UNSUPPORTED",
}
QUESTION_REF_RE = re.compile(r"^\d{1,2}(?:\.\d{1,2}){0,2}$")
QUESTION_TOKEN_RE = re.compile(r"(?<!\d)(\d{1,2}(?:\.\d{1,2}){1,2})\.?(?!\d)")
WRITE_ON_RE = re.compile(r"\bWRITE[ -]?ON\s+(?:TEST|ASSESSMENT|PAPER)\b", re.I)


class VisualEvidenceError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.public_message = message


def visual_checkpoint_ownership_is_compatible(candidate: dict[str, Any]) -> bool:
    explicit = candidate.get("ownership_algorithm_version")
    if explicit is not None:
        return explicit == OWNERSHIP_ALGORITHM_VERSION
    items = list(candidate.get("evidence") or []) + list(candidate.get("mark_changes") or [])
    return bool(items) and all(
        isinstance(item, dict)
        and "source_page_bbox" in item
        and "owned_question_ref" in item
        and "association_status" in item
        for item in items
    )


def visual_checkpoint_is_compatible(candidate: Any, source_sha256: str | None) -> bool:
    return bool(
        isinstance(candidate, dict)
        and candidate.get("schema_version") == SCHEMA_VERSION
        and candidate.get("source_sha256") == source_sha256
        and visual_checkpoint_ownership_is_compatible(candidate)
    )


def visual_failure_is_retryable(code: Any) -> bool:
    return str(code or "VISUAL_PROVIDER_FAILED") not in NON_RETRYABLE_VISUAL_FAILURE_CODES


def visual_cache_is_complete(candidate: Any, source_sha256: str | None) -> bool:
    if not visual_checkpoint_is_compatible(candidate, source_sha256):
        return False
    summary = candidate.get("summary") or {}
    expected = int(summary.get("regions_rendered") or 0)
    flagged = int(summary.get("pages_flagged") or 0)
    runs = [item for item in candidate.get("runs", []) if isinstance(item, dict)]
    if expected == 0:
        return flagged == 0
    refs = {str(item.get("rendered_asset_ref")) for item in runs if item.get("rendered_asset_ref")}
    if len(refs) < expected:
        return False
    return not any(
        item.get("success") is not True and visual_failure_is_retryable(item.get("error_code"))
        for item in runs
    )


def _coloured_pixel_ratio(image_bytes: bytes) -> float:
    with Image.open(io.BytesIO(image_bytes)) as image:
        sample = image.convert("RGB")
        sample.thumbnail((700, 900))
        pixel_source = getattr(sample, "get_flattened_data", sample.getdata)
        pixels = list(pixel_source())
    if not pixels:
        return 0.0
    coloured = sum(
        1 for red, green, blue in pixels
        if max(red, green, blue) - min(red, green, blue) >= 55
        and min(red, green, blue) < 225
    )
    return coloured / len(pixels)


def _annotation_types(page: Any) -> list[str]:
    result: list[str] = []
    try:
        annotations = page.annots()
        if annotations is None:
            return result
        for annotation in annotations:
            kind = annotation.type[1] if annotation.type else "unknown"
            result.append(str(kind).lower())
    except Exception:
        pass
    return result


def screen_pdf_page(page: Any, digital_text: str) -> dict[str, Any]:
    reasons: list[str] = []
    annotations = _annotation_types(page)
    if any("ink" in kind for kind in annotations):
        reasons.append("PDF_INK_ANNOTATIONS_PRESENT")

    images = page.get_images(full=True)
    drawings = page.get_drawings()
    if images:
        reasons.append("RASTER_OVERLAY_PRESENT")
    if drawings:
        reasons.extend([
            "NON_TEXT_VECTOR_DRAWINGS_PRESENT",
            "VISUAL_CONTENT_OUTSIDE_TEXT_LAYER",
        ])
    if not digital_text.strip():
        reasons.append("IMAGE_PAGE")
    if WRITE_ON_RE.search(digital_text):
        reasons.append("WRITE_ON_DOCUMENT")

    coloured_ratio = 0.0
    try:
        import fitz

        preview = page.get_pixmap(matrix=fitz.Matrix(1.25, 1.25), alpha=False)
        coloured_ratio = _coloured_pixel_ratio(preview.tobytes("png"))
    except Exception:
        coloured_ratio = 0.0
    if coloured_ratio >= 0.00035:
        reasons.append("COLOURED_OVERLAY_PRESENT")

    reasons = list(dict.fromkeys(reasons))
    return {
        "visual_inspection_required": bool(reasons),
        "visual_inspection_reasons": reasons,
        "visual_overlay_detected": bool(
            annotations or images or drawings or coloured_ratio >= 0.00035
        ),
        "visual_evidence_source": "deterministic_pdf_screen",
        "visual_extraction_confidence": None,
        "annotation_types": annotations,
        "raster_image_count": len(images),
        "vector_drawing_count": len(drawings),
        "coloured_pixel_ratio": round(coloured_ratio, 6),
    }


def apply_document_visual_escalation(pages: list[dict[str, Any]]) -> None:
    document_write_on = any(
        "WRITE_ON_DOCUMENT" in page.get("visual_inspection_reasons", [])
        for page in pages
    )
    if not document_write_on:
        return
    for page in pages:
        if int(page.get("digital_text_length") or 0) < 30 and not page.get("image_count"):
            continue
        page["visual_inspection_required"] = True
        reasons = list(page.get("visual_inspection_reasons") or [])
        if "WRITE_ON_DOCUMENT" not in reasons:
            reasons.append("WRITE_ON_DOCUMENT")
        page["visual_inspection_reasons"] = reasons


def image_visual_screen(kind: str) -> dict[str, Any]:
    return {
        "visual_inspection_required": True,
        "visual_inspection_reasons": ["IMAGE_PAGE", "IMAGE_SOURCE"],
        "visual_overlay_detected": True,
        "visual_evidence_source": f"deterministic_{kind}_screen",
        "visual_extraction_confidence": None,
        "annotation_types": [],
        "raster_image_count": 1,
        "vector_drawing_count": 0,
        "coloured_pixel_ratio": None,
    }


def _question_regions(page: Any) -> list[dict[str, Any]]:
    anchors: list[tuple[float, str]] = []
    try:
        words = page.get_text("words") or []
    except Exception:
        words = []
    for word in words:
        if len(word) < 5:
            continue
        match = QUESTION_TOKEN_RE.fullmatch(str(word[4]).strip())
        if match:
            anchors.append((float(word[1]), match.group(1)))
    anchors = sorted(set(anchors))
    result: list[dict[str, Any]] = []
    for index, (top, question_ref) in enumerate(anchors):
        bottom = anchors[index + 1][0] if index + 1 < len(anchors) else float(page.rect.height)
        if bottom - top < 18:
            continue
        margin = 24.0
        owned_bbox = [0.0, top, float(page.rect.width), bottom]
        result.append({
            "question_refs": [question_ref],
            "bbox": [
                0.0,
                max(0.0, top - margin),
                float(page.rect.width),
                min(float(page.rect.height), bottom + margin),
            ],
            "owned_bbox": owned_bbox,
        })
    return result


def _render_regions(source_bytes: bytes, normalized: dict[str, Any]) -> list[dict[str, Any]]:
    kind = normalized.get("content", {}).get("kind")
    flagged = [
        page for page in normalized.get("content", {}).get("pages", [])
        if page.get("visual_inspection_required")
    ]
    if not flagged:
        return []
    if kind in {"png", "jpeg"}:
        extension = "png" if kind == "png" else "jpg"
        return [{
            "page": 1,
            "question_refs": [],
            "bbox": None,
            "asset_path": f"internal/visual/pages/page-0001.{extension}",
            "image_bytes": source_bytes,
            "mime_type": "image/png" if kind == "png" else "image/jpeg",
            "printed_text": flagged[0].get("effective_text", ""),
        }]

    try:
        import fitz
        document = fitz.open(stream=source_bytes, filetype="pdf")
    except Exception as exc:
        raise VisualEvidenceError(
            "VISUAL_RENDER_FAILED", "Visual source pages could not be rendered."
        ) from exc

    regions: list[dict[str, Any]] = []
    max_regions = max(1, min(40, int(os.environ.get("MEMO_VISION_MAX_REGIONS", "24"))))
    try:
        for page_meta in flagged:
            page_number = int(page_meta["page"])
            page = document.load_page(page_number - 1)
            page_regions = _question_regions(page)
            if not page_regions:
                page_regions = [{"question_refs": [], "bbox": None}]
            for region_index, region in enumerate(page_regions, start=1):
                if len(regions) >= max_regions:
                    break
                clip = fitz.Rect(region["bbox"]) if region["bbox"] else None
                pixmap = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0), clip=clip, alpha=False)
                image_bytes = pixmap.tobytes("png")
                if region["question_refs"]:
                    suffix = "-".join(region["question_refs"]).replace(".", "_")
                    asset_path = f"internal/visual/regions/page-{page_number:04d}-q{suffix}.png"
                else:
                    asset_path = f"internal/visual/pages/page-{page_number:04d}.png"
                regions.append({
                    "page": page_number,
                    "question_refs": region["question_refs"],
                    "bbox": region["bbox"],
                    "render_bbox": region["bbox"],
                    "owned_bbox": region.get("owned_bbox"),
                    "render_scale": 2.0,
                    "asset_path": asset_path,
                    "image_bytes": image_bytes,
                    "mime_type": "image/png",
                    "printed_text": page_meta.get("digital_text", ""),
                    "region_index": region_index,
                })
            if len(regions) >= max_regions:
                break
    finally:
        document.close()
    return regions


def visual_system_prompt() -> str:
    return """You are an evidence transcriber for a mathematics marking memo.
Return ONLY additional visible handwritten, digital-ink, diagram, tick, cross,
teacher-note, or mark-change evidence from the supplied image.

DO NOT solve a missing answer. DO NOT infer an answer merely because the printed
question is visible. DO NOT invent marking allocations.
DO NOT reproduce printed question text as handwritten evidence.
Printed allocations such as (2) and printed subtotals such as [7] are already
represented by the digital text layer. Do not return them as new evidence. If
handwriting visibly changes a printed mark, return only a mark_changes item.
DO NOT assume a tick means an unseen mark
criterion. DO NOT silently repair unclear handwriting. Preserve decimal commas and
visible fraction meaning. For normalized_math, output mathematical notation rather
than prose descriptions of symbols. Never use the command \\backslash merely to
describe a visible slash. Use only common closed notation such as \\frac, \\sqrt,
\\times, \\cdot, \\leq, \\geq, \\neq, \\pm, \\in, \\notin, \\cup, \\cap, and
\\setminus when the visible meaning is unambiguous. Raw transcription must retain
what is actually visible. If notation is uncertain, set normalized_math to null,
lower confidence, and add a warning. If a symbol or association is unclear, lower
confidence and add a warning. Use only the supplied closed kinds and question anchors."""


def _vision_schema(page_number: int) -> dict[str, Any]:
    evidence_item = {
        "type": "object",
        "properties": {
            "question_ref": {"type": ["string", "null"]},
            "kind": {"type": "string", "enum": sorted(EVIDENCE_KINDS)},
            "transcription": {"type": "string"},
            "normalized_math": {"type": ["string", "null"]},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "source": {"type": "string", "enum": ["visual_overlay"]},
            "bbox": {
                "type": ["array", "null"],
                "items": {"type": "number"},
                "minItems": 4,
                "maxItems": 4,
            },
        },
        "required": ["question_ref", "kind", "transcription", "normalized_math", "confidence", "source", "bbox"],
        "additionalProperties": False,
    }
    mark_change = {
        "type": "object",
        "properties": {
            "question_ref": {"type": ["string", "null"]},
            "level": {"type": "string", "enum": ["item", "subtotal", "document_total"]},
            "printed_value": {"type": ["integer", "null"]},
            "visual_value": {"type": "integer", "minimum": 0, "maximum": 999},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "requires_confirmation": {"type": "boolean", "enum": [True]},
            "bbox": {"type": ["array", "null"], "items": {"type": "number"}, "minItems": 4, "maxItems": 4},
        },
        "required": ["question_ref", "level", "printed_value", "visual_value", "confidence", "requires_confirmation", "bbox"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "schema_version": {"type": "string", "enum": [SCHEMA_VERSION]},
            "page": {"type": "integer", "enum": [page_number]},
            "visual_content_present": {"type": "boolean"},
            "evidence": {"type": "array", "items": evidence_item, "maxItems": 40},
            "mark_changes": {"type": "array", "items": mark_change, "maxItems": 20},
            "warnings": {"type": "array", "items": {"type": "string"}, "maxItems": 20},
        },
        "required": ["schema_version", "page", "visual_content_present", "evidence", "mark_changes", "warnings"],
        "additionalProperties": False,
    }


def groq_visual_extract(
    region: dict[str, Any],
    model: str,
    *,
    deadline_monotonic: float | None = None,
    remaining_requests: int = 1,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    if configured_provider() != "groq":
        raise ProviderError("AI_PROVIDER_UNSUPPORTED", "Only approved Groq vision is supported.", retryable=False)
    key = os.environ.get("GROQ_API_KEY", "").strip()
    encoded = base64.b64encode(region["image_bytes"]).decode("ascii")
    prompt = visual_system_prompt() + "\n\nKnown question anchors: " + json.dumps(region["question_refs"])
    if region.get("question_refs"):
        prompt += (
            "\nThis is an anchored crop. The named question owns the central region. "
            "The crop margins may show neighbouring questions for context; do not "
            "return their content as evidence for this crop."
        )
    prompt += "\nDigitally extracted printed text (context only):\n" + str(region["printed_text"])[:12000]
    body = {
        "model": model,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:{region['mime_type']};base64,{encoded}"}},
        ]}],
        "temperature": 0,
        "max_completion_tokens": 4096,
        "response_format": {"type": "json_schema", "json_schema": {
            "name": "memo_visual_evidence", "strict": True,
            "schema": _vision_schema(int(region["page"])),
        }},
    }
    payload, elapsed_ms = _post_json(
        "https://api.groq.com/openai/v1/chat/completions",
        {"Authorization": f"Bearer {key}"}, body,
        timeout_seconds=_bounded_env_seconds(
            "MEMO_GROQ_VISION_REQUEST_TIMEOUT_SECONDS",
            DEFAULT_VISION_REQUEST_TIMEOUT_SECONDS,
            minimum=5.0,
            maximum=75.0,
        ),
        deadline_monotonic=deadline_monotonic,
        remaining_requests=remaining_requests,
        clock=clock,
    )
    try:
        result = json.loads(payload["choices"][0]["message"]["content"])
    except Exception as exc:
        raise VisualEvidenceError("VISUAL_MODEL_SCHEMA_INVALID", "The visual response was not valid structured evidence.") from exc
    result["provider"] = "groq"
    result["model"] = model
    result["elapsed_ms"] = elapsed_ms
    result["usage"] = payload.get("usage") or {}
    return result


def _bounded_env_seconds(
    name: str,
    default: float,
    *,
    minimum: float,
    maximum: float,
) -> float:
    try:
        value = float(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def _bounded_text(value: Any, *, maximum: int = 2000) -> str:
    if not isinstance(value, str):
        raise VisualEvidenceError("VISUAL_MODEL_SCHEMA_INVALID", "Visual transcription must be text.")
    return value.strip()[:maximum]


def _page_bbox(bbox: Any, region: dict[str, Any]) -> list[float] | None:
    if not isinstance(bbox, list) or len(bbox) != 4:
        return None
    render_bbox = region.get("render_bbox") or region.get("bbox")
    if not isinstance(render_bbox, list) or len(render_bbox) != 4:
        return [float(value) for value in bbox]
    scale = float(region.get("render_scale") or 1.0)
    if scale <= 0:
        scale = 1.0
    return [
        float(render_bbox[0]) + float(bbox[0]) / scale,
        float(render_bbox[1]) + float(bbox[1]) / scale,
        float(render_bbox[0]) + float(bbox[2]) / scale,
        float(render_bbox[1]) + float(bbox[3]) / scale,
    ]


def _association_status(
    question_ref: Any,
    source_page_bbox: list[float] | None,
    region: dict[str, Any],
) -> tuple[str, str | None]:
    anchors = [str(value) for value in region.get("question_refs") or []]
    owner = anchors[0] if len(anchors) == 1 else None
    if owner is None:
        return "unanchored", None
    if question_ref is not None and str(question_ref) != owner:
        return "cross_anchor_mismatch", owner
    owned_bbox = region.get("owned_bbox")
    if source_page_bbox is not None and isinstance(owned_bbox, list) and len(owned_bbox) == 4:
        center_x = (source_page_bbox[0] + source_page_bbox[2]) / 2
        center_y = (source_page_bbox[1] + source_page_bbox[3]) / 2
        if not (
            float(owned_bbox[0]) <= center_x <= float(owned_bbox[2])
            and float(owned_bbox[1]) <= center_y < float(owned_bbox[3])
        ):
            return "context_only", owner
    return "owned", owner


def _is_printed_numeric_rediscovery(item: dict[str, Any], region: dict[str, Any]) -> bool:
    transcription = re.sub(r"\s+", "", str(item.get("transcription") or ""))
    printed = re.sub(r"\s+", "", str(region.get("printed_text") or ""))
    if re.fullmatch(r"(?:\(\d{1,3}\)|\[\d{1,3}\])", transcription):
        return transcription in printed
    # A bare question identifier which is already one of the deterministic
    # crop anchors is printed source identity, not solution content.  Keep the
    # raw observation for audit, but do not attach it as a solution.
    return bool(
        QUESTION_REF_RE.fullmatch(transcription)
        and transcription in {
            re.sub(r"\s+", "", str(value))
            for value in region.get("question_refs") or []
        }
    )


def _bbox_iou(left: Any, right: Any) -> float:
    if not (
        isinstance(left, list) and len(left) == 4
        and isinstance(right, list) and len(right) == 4
    ):
        return 0.0
    x1, y1 = max(left[0], right[0]), max(left[1], right[1])
    x2, y2 = min(left[2], right[2]), min(left[3], right[3])
    intersection = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    left_area = max(0.0, left[2] - left[0]) * max(0.0, left[3] - left[1])
    right_area = max(0.0, right[2] - right[0]) * max(0.0, right[3] - right[1])
    union = left_area + right_area - intersection
    return intersection / union if union else 0.0


def _normalized_evidence_text(item: dict[str, Any]) -> str:
    if "level" in item and "visual_value" in item:
        return json.dumps(
            [item.get("level"), item.get("printed_value"), item.get("visual_value")],
            ensure_ascii=False,
            separators=(",", ":"),
        )
    value = item.get("normalized_math") or item.get("transcription") or ""
    return re.sub(r"\s+", " ", str(value)).strip().lower()


def _cross_runtime_json_value(value: Any) -> Any:
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, list):
        return [_cross_runtime_json_value(item) for item in value]
    return value


def visual_evidence_identity_payload(item: dict[str, Any], index: int) -> dict[str, Any]:
    """Return the cross-runtime immutable legacy evidence identity payload."""
    return {
        "bbox": _cross_runtime_json_value(item.get("source_page_bbox") or item.get("bbox")),
        "index": index,
        "kind": item.get("kind"),
        "page": _cross_runtime_json_value(item.get("page")),
        "question_ref": item.get("question_ref"),
        "rendered_asset_ref": item.get("rendered_asset_ref"),
        "text": _normalized_evidence_text(item),
    }


def legacy_visual_evidence_id(item: dict[str, Any], index: int) -> str:
    canonical = json.dumps(
        visual_evidence_identity_payload(item, index),
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def ensure_visual_evidence_ids(items: list[dict[str, Any]]) -> None:
    """Backfill missing historical IDs in memory; stored modern IDs are immutable."""
    for index, item in enumerate(items):
        if not item.get("evidence_id"):
            item["evidence_id"] = legacy_visual_evidence_id(item, index)


def probable_printed_identifier(item: dict[str, Any]) -> bool:
    value = re.sub(
        r"\s+", "", str(item.get("normalized_math") or item.get("transcription") or "")
    ).rstrip(".")
    return bool(QUESTION_REF_RE.fullmatch(value))


def _longest_sequential_identifier_run(items: list[dict[str, Any]]) -> int:
    grouped: dict[str, set[int]] = {}
    for item in items:
        value = re.sub(
            r"\s+", "", str(item.get("normalized_math") or item.get("transcription") or "")
        ).rstrip(".")
        parts = value.split(".")
        if len(parts) < 2 or not all(part.isdigit() for part in parts):
            continue
        grouped.setdefault(".".join(parts[:-1]), set()).add(int(parts[-1]))
    longest = 0
    for values in grouped.values():
        current = 0
        previous = None
        for value in sorted(values):
            current = current + 1 if previous is not None and value == previous + 1 else 1
            longest = max(longest, current)
            previous = value
    return longest


def classify_visual_review_unit(observations: list[dict[str, Any]]) -> dict[str, Any]:
    count = len(observations)
    distinct = {
        (str(item.get("kind") or "mark_change"), _normalized_evidence_text(item))
        for item in observations
    }
    identifier_count = sum(probable_printed_identifier(item) for item in observations)
    identifier_ratio = identifier_count / count if count else 0.0
    sequential_run = _longest_sequential_identifier_run(observations)
    cap_hit = count == VISUAL_EVIDENCE_MAX_ITEMS
    kind_count = len({str(item.get("kind") or "mark_change") for item in observations})
    runaway = bool(
        (cap_hit and (identifier_ratio >= 0.5 or sequential_run >= 5))
        or (count >= 25 and identifier_ratio >= 0.7 and sequential_run >= 5)
    )
    mixed = bool(
        not runaway
        and count >= 4
        and len(distinct) >= 3
        and (identifier_ratio >= 0.5 or kind_count >= 3)
    )
    classification = "runaway_model_output" if runaway else "mixed" if mixed else "normal"
    warnings = ["VISUAL_EVIDENCE_ITEM_CAP_REACHED"] if cap_hit else []
    return {
        "classification": classification,
        "cap_hit": cap_hit,
        "warnings": warnings,
        "probable_printed_identifier_count": identifier_count,
        "identifier_ratio": round(identifier_ratio, 4),
        "sequential_identifier_run": sequential_run,
        "distinct_observation_count": len(distinct),
    }


def distinct_visual_observations(observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for item in observations:
        key = (str(item.get("kind") or "mark_change"), _normalized_evidence_text(item))
        groups.setdefault(key, []).append(item)
    result = []
    for (kind, _), matches in groups.items():
        first = matches[0]
        result.append({
            "reading": str(first.get("transcription") or first.get("normalized_math") or "").strip(),
            "kind": kind,
            "evidence_ids": [str(item["evidence_id"]) for item in matches],
            "raw_observation_count": len(matches),
            "probable_printed_source_rediscovery": all(
                probable_printed_identifier(item) for item in matches
            ),
        })
    return result


def _deduplicate_visual_items(items: list[dict[str, Any]]) -> None:
    ensure_visual_evidence_ids(items)
    effective: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        item.setdefault("effective", True)
        if not item.get("effective"):
            continue
        duplicate = next((candidate for candidate in effective if (
            candidate.get("page") == item.get("page")
            and str(candidate.get("question_ref")) == str(item.get("question_ref"))
            and candidate.get("kind") == item.get("kind")
            and _normalized_evidence_text(candidate) == _normalized_evidence_text(item)
            and (
                (
                    candidate.get("source_page_bbox") is not None
                    and item.get("source_page_bbox") is not None
                )
                or candidate.get("rendered_asset_ref") == item.get("rendered_asset_ref")
            )
            and _bbox_iou(
                candidate.get("source_page_bbox") or candidate.get("bbox"),
                item.get("source_page_bbox") or item.get("bbox"),
            ) >= 0.35
        )), None)
        if duplicate is None:
            effective.append(item)
            continue
        item["effective"] = False
        item["evidence_status"] = "semantic_duplicate"
        item["duplicate_of"] = duplicate["evidence_id"]
        duplicate.setdefault("duplicate_provenance", []).append({
            "evidence_id": item["evidence_id"],
            "rendered_asset_ref": item.get("rendered_asset_ref"),
            "source_page_bbox": item.get("source_page_bbox"),
        })


def visual_association_unit_key(item: dict[str, Any]) -> tuple[str, int | None, str, str]:
    """Return the stable physical review identity for one visual observation."""
    page = item.get("page")
    try:
        page = int(page) if page is not None else None
    except (TypeError, ValueError):
        page = None
    return (
        str(item.get("rendered_asset_ref") or ""),
        page,
        str(item.get("owned_question_ref") or ""),
        str(item.get("association_status") or item.get("evidence_status") or "unresolved_question"),
    )


def visual_association_review_units(
    items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Collapse raw observations into bounded physical teacher-review units.

    The raw items remain untouched in evidence.json.  Only the exception-facing
    projection is consolidated here.
    """
    groups: dict[tuple[str, int | None, str, str], list[dict[str, Any]]] = {}
    for item in items:
        groups.setdefault(visual_association_unit_key(item), []).append(item)

    units: list[dict[str, Any]] = []
    for key, observations in groups.items():
        asset, page, owned, status = key
        evidence_ids = list(dict.fromkeys(
            str(item.get("evidence_id") or "") for item in observations
            if item.get("evidence_id")
        ))
        claimed = list(dict.fromkeys(
            str(item.get("question_ref")) for item in observations
            if item.get("question_ref") is not None
        ))
        readings = list(dict.fromkeys(
            str(item.get("transcription") or item.get("normalized_math") or "").strip()
            for item in observations
            if str(item.get("transcription") or item.get("normalized_math") or "").strip()
        ))
        bboxes: list[list[float]] = []
        for item in observations:
            bbox = item.get("source_page_bbox") or item.get("bbox")
            if isinstance(bbox, list) and len(bbox) == 4 and bbox not in bboxes:
                bboxes.append([float(value) for value in bbox])
        providers = list(dict.fromkeys(
            f"{item.get('extractor_provider') or 'unknown'}:{item.get('extractor_model') or 'unknown'}"
            for item in observations
        ))
        identity = json.dumps({
            "asset": asset, "page": page, "owned": owned, "status": status,
        }, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        classification = classify_visual_review_unit(observations)
        units.append({
            "schema_version": "1.0",
            "review_unit_type": "visual_evidence_association",
            "review_unit_id": hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20],
            "rendered_asset_ref": asset,
            "page": page,
            "owned_question_ref": owned or None,
            "association_status": status,
            "claimed_question_refs": claimed,
            "transcriptions": readings,
            "evidence_ids": evidence_ids,
            "source_page_bboxes": bboxes,
            "owned_bbox": next((item.get("owned_bbox") for item in observations if item.get("owned_bbox") is not None), None),
            "raw_observation_count": len(observations),
            "provider_models": providers,
            "observation_kinds": list(dict.fromkeys(str(item.get("kind") or "mark_change") for item in observations)),
            "unit_classification": classification["classification"],
            "cap_hit": classification["cap_hit"],
            "audit_warnings": classification["warnings"],
            "probable_printed_identifier_count": classification["probable_printed_identifier_count"],
            "sequential_identifier_run": classification["sequential_identifier_run"],
            "distinct_observations": distinct_visual_observations(observations),
        })
    return units


def validate_visual_response(payload: Any, region: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise VisualEvidenceError("VISUAL_MODEL_SCHEMA_INVALID", "Visual response must be an object.")
    required = {"schema_version", "page", "visual_content_present", "evidence", "mark_changes", "warnings"}
    allowed = required | {"provider", "model", "elapsed_ms", "usage"}
    if set(payload) - allowed or not required.issubset(payload):
        raise VisualEvidenceError("VISUAL_MODEL_SCHEMA_INVALID", "Visual response fields do not match the closed schema.")
    if payload["schema_version"] != SCHEMA_VERSION or payload["page"] != region["page"]:
        raise VisualEvidenceError("VISUAL_MODEL_SCHEMA_INVALID", "Visual response identity is invalid.")
    if not isinstance(payload["visual_content_present"], bool):
        raise VisualEvidenceError("VISUAL_MODEL_SCHEMA_INVALID", "Visual presence must be boolean.")
    if (
        not isinstance(payload["evidence"], list)
        or len(payload["evidence"]) > VISUAL_EVIDENCE_MAX_ITEMS
        or not isinstance(payload["mark_changes"], list)
        or len(payload["mark_changes"]) > 20
        or not isinstance(payload["warnings"], list)
    ):
        raise VisualEvidenceError("VISUAL_MODEL_SCHEMA_INVALID", "Visual response arrays exceed the closed schema.")
    evidence: list[dict[str, Any]] = []
    for item in payload["evidence"]:
        if not isinstance(item, dict) or set(item) != {"question_ref", "kind", "transcription", "normalized_math", "confidence", "source", "bbox"}:
            raise VisualEvidenceError("VISUAL_MODEL_SCHEMA_INVALID", "Visual evidence item is invalid.")
        question_ref = item["question_ref"]
        if question_ref is not None and not QUESTION_REF_RE.fullmatch(str(question_ref)):
            raise VisualEvidenceError("VISUAL_MODEL_SCHEMA_INVALID", "Visual question reference is invalid.")
        if item["kind"] not in EVIDENCE_KINDS or item["source"] != "visual_overlay":
            raise VisualEvidenceError("VISUAL_MODEL_SCHEMA_INVALID", "Visual evidence kind or source is invalid.")
        confidence = float(item["confidence"])
        if not 0 <= confidence <= 1:
            raise VisualEvidenceError("VISUAL_MODEL_SCHEMA_INVALID", "Visual confidence is invalid.")
        bbox = item["bbox"]
        if bbox is not None and (not isinstance(bbox, list) or len(bbox) != 4 or not all(isinstance(v, (int, float)) for v in bbox)):
            raise VisualEvidenceError("VISUAL_MODEL_SCHEMA_INVALID", "Visual evidence bounding box is invalid.")
        normalized_math = item["normalized_math"]
        model_normalized_math = normalized_math
        normalization_issue = None
        if normalized_math is not None:
            model_normalized_math = _bounded_text(normalized_math)
            normalized_math, normalization_issue = normalize_visual_math(
                model_normalized_math
            )
        source_page_bbox = _page_bbox(bbox, region)
        association_status, owned_question_ref = _association_status(
            question_ref, source_page_bbox, region
        )
        validated_item = {
            **item,
            "question_ref": question_ref,
            "transcription": _bounded_text(item["transcription"]),
            "normalized_math": normalized_math,
            "model_normalized_math": model_normalized_math,
            "math_normalization_issue": normalization_issue,
            "confidence": confidence,
            "page": region["page"],
            "rendered_asset_ref": region["asset_path"],
            "source_page_bbox": source_page_bbox,
            "owned_bbox": region.get("owned_bbox"),
            "owned_question_ref": owned_question_ref,
            "association_status": association_status,
            "extractor_provider": str(payload.get("provider") or "groq"),
            "extractor_model": str(payload.get("model") or "unknown"),
        }
        if association_status in {"cross_anchor_mismatch", "context_only"}:
            validated_item["effective"] = False
            validated_item["evidence_status"] = association_status
        elif _is_printed_numeric_rediscovery(validated_item, region):
            validated_item["effective"] = False
            validated_item["evidence_status"] = "printed_source_rediscovery"
        else:
            validated_item["effective"] = True
        evidence.append(validated_item)

    mark_changes: list[dict[str, Any]] = []
    for item in payload["mark_changes"]:
        expected = {"question_ref", "level", "printed_value", "visual_value", "confidence", "requires_confirmation", "bbox"}
        if not isinstance(item, dict) or set(item) != expected or item["requires_confirmation"] is not True:
            raise VisualEvidenceError("VISUAL_MODEL_SCHEMA_INVALID", "Visual mark change is invalid.")
        question_ref = item["question_ref"]
        if question_ref is not None and not QUESTION_REF_RE.fullmatch(str(question_ref)):
            raise VisualEvidenceError("VISUAL_MODEL_SCHEMA_INVALID", "Visual mark-change question reference is invalid.")
        if item["level"] not in {"item", "subtotal", "document_total"}:
            raise VisualEvidenceError("VISUAL_MODEL_SCHEMA_INVALID", "Visual mark-change level is invalid.")
        confidence = float(item["confidence"])
        if not 0 <= confidence <= 1:
            raise VisualEvidenceError("VISUAL_MODEL_SCHEMA_INVALID", "Visual mark-change confidence is invalid.")
        bbox = item["bbox"]
        if bbox is not None and (not isinstance(bbox, list) or len(bbox) != 4 or not all(isinstance(v, (int, float)) for v in bbox)):
            raise VisualEvidenceError("VISUAL_MODEL_SCHEMA_INVALID", "Visual mark-change bounding box is invalid.")
        source_page_bbox = _page_bbox(bbox, region)
        association_status, owned_question_ref = _association_status(
            question_ref, source_page_bbox, region
        )
        effective = (
            association_status not in {"cross_anchor_mismatch", "context_only"}
            and item.get("printed_value") != item.get("visual_value")
        )
        mark_changes.append({
            **item,
            "confidence": confidence,
            "page": region["page"],
            "rendered_asset_ref": region["asset_path"],
            "source_page_bbox": source_page_bbox,
            "owned_bbox": region.get("owned_bbox"),
            "owned_question_ref": owned_question_ref,
            "association_status": association_status,
            "effective": effective,
            "evidence_status": (
                association_status
                if association_status in {"cross_anchor_mismatch", "context_only"}
                else ("printed_source_rediscovery" if not effective else "mark_change")
            ),
            "extractor_provider": str(payload.get("provider") or "groq"),
            "extractor_model": str(payload.get("model") or "unknown"),
        })
    warnings = [_bounded_text(item, maximum=300) for item in payload["warnings"] if isinstance(item, str)]
    return {**payload, "evidence": evidence, "mark_changes": mark_changes, "warnings": warnings}


def extract_visual_evidence(
    source_bytes: bytes,
    normalized: dict[str, Any],
    *,
    runner: Callable[[dict[str, Any], str], dict[str, Any]] = groq_visual_extract,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
    checkpoint_callback: Callable[[dict[str, Any], dict[str, Any]], None] | None = None,
    checkpoint_record: dict[str, Any] | None = None,
    phase_timeout_seconds: float | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    phase_started = clock()
    if phase_timeout_seconds is None:
        phase_timeout_seconds = _bounded_env_seconds(
            "MEMO_VISUAL_PHASE_TIMEOUT_SECONDS",
            DEFAULT_VISUAL_PHASE_TIMEOUT_SECONDS,
            minimum=30.0,
            maximum=1800.0,
        )
    screened_pages = normalized.get("content", {}).get("pages", [])
    flagged_pages = [page for page in screened_pages if page.get("visual_inspection_required")]
    record: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "ownership_algorithm_version": OWNERSHIP_ALGORITHM_VERSION,
        "phase": "phase2_visual_evidence",
        "job_id": normalized.get("job_id"),
        "source_sha256": normalized.get("source", {}).get("sha256"),
        "evidence": [],
        "mark_changes": [],
        "warnings": [],
        "runs": [],
        "retry_history": [],
        "summary": {
            "pages_screened": len(screened_pages),
            "pages_flagged": len(flagged_pages),
            "regions_rendered": 0,
            "vision_calls": 0,
            "image_count": 0,
            "success_count": 0,
            "failure_count": 0,
            "visual_content_count": 0,
            "partial_checkpoint_reuse": False,
            "reused_success_count": 0,
            "retried_region_count": 0,
            "new_success_count": 0,
            "new_failure_count": 0,
            "unprocessed_count": 0,
        },
    }

    if visual_checkpoint_is_compatible(checkpoint_record, record["source_sha256"]):
        successful_runs = [
            item for item in checkpoint_record.get("runs", [])
            if isinstance(item, dict)
            and item.get("success") is True
            and isinstance(item.get("rendered_asset_ref"), str)
        ]
        record["retry_history"] = list(checkpoint_record.get("retry_history") or []) + [
            item for item in checkpoint_record.get("runs", [])
            if isinstance(item, dict) and item.get("success") is not True
        ]
        record["evidence"] = list(checkpoint_record.get("evidence") or [])
        record["mark_changes"] = list(checkpoint_record.get("mark_changes") or [])
        record["warnings"] = [
            item for item in checkpoint_record.get("warnings", [])
            if isinstance(item, dict) and item.get("code") == "VISUAL_MODEL_WARNING"
        ]
        record["runs"] = successful_runs
        record["summary"]["partial_checkpoint_reuse"] = bool(successful_runs)
        record["summary"]["reused_success_count"] = len(successful_runs)
        record["summary"]["success_count"] = len(successful_runs)
        record["summary"]["visual_content_count"] = int(
            (checkpoint_record.get("summary") or {}).get("visual_content_count") or 0
        )
    if not flagged_pages:
        return record, []

    model = os.environ.get("MEMO_GROQ_VISION_MODEL", "qwen/qwen3.8-27b").strip() or "qwen/qwen3.8-27b"
    try:
        regions = _render_regions(source_bytes, normalized)
    except VisualEvidenceError as exc:
        record["warnings"].append({"code": exc.code, "message": exc.public_message})
        record["summary"]["failure_count"] += 1
        return record, []

    artifacts: list[dict[str, Any]] = []
    unique_regions: list[tuple[dict[str, Any], dict[str, Any]]] = []
    seen: set[str] = set()
    for region in regions:
        digest = hashlib.sha256(region["image_bytes"]).hexdigest()
        if digest in seen:
            continue
        seen.add(digest)
        artifact = {
            "path": region["asset_path"],
            "data": region["image_bytes"],
            "content_type": region["mime_type"],
            "sha256": digest,
        }
        artifacts.append(artifact)
        unique_regions.append((region, artifact))
        record["summary"]["regions_rendered"] += 1
        record["summary"]["image_count"] += 1

    total_regions = len(unique_regions)
    completed_refs = {
        item["rendered_asset_ref"]
        for item in record["runs"]
        if item.get("success") is True
    }
    consecutive_transport_failures = 0
    stop_code: str | None = None

    def emit_progress(
        status: str,
        index: int,
        region: dict[str, Any],
        *,
        error_code: str | None = None,
    ) -> None:
        if progress_callback is None:
            return
        payload = {
            "status": status,
            "region_index": index,
            "region_count": total_regions,
            "page": int(region["page"]),
            "question_refs": [
                str(value) for value in (region.get("question_refs") or [])[:4]
            ],
        }
        if error_code:
            payload["error_code"] = error_code
        progress_callback(payload)

    def record_failure(
        region: dict[str, Any],
        artifact: dict[str, Any],
        index: int,
        code: str,
    ) -> None:
        record["warnings"].append({
            "code": code,
            "message": "Detected visual memo evidence could not be read reliably.",
            "page": region["page"],
            "rendered_asset_ref": region["asset_path"],
        })
        record["runs"].append({
            "provider": "groq", "model": model, "page": region["page"],
            "image_count": 1, "success": False, "error_code": code,
            "rendered_asset_ref": region["asset_path"],
        })
        record["summary"]["failure_count"] += 1
        record["summary"]["new_failure_count"] += 1
        if code in {"VISUAL_PHASE_BUDGET_EXCEEDED", "VISUAL_PROVIDER_CIRCUIT_OPEN"}:
            record["summary"]["unprocessed_count"] += 1
        emit_progress("failed", index, region, error_code=code)
        if checkpoint_callback is not None:
            checkpoint_callback(record, artifact)

    for index, (region, artifact) in enumerate(unique_regions, start=1):
        if region["asset_path"] in completed_refs:
            emit_progress("checkpointed", index, region)
            continue
        if stop_code:
            record_failure(region, artifact, index, stop_code)
            continue
        if clock() - phase_started >= phase_timeout_seconds:
            stop_code = "VISUAL_PHASE_BUDGET_EXCEEDED"
            record_failure(
                region, artifact, index, stop_code
            )
            continue

        emit_progress("processing", index, region)
        record["summary"]["vision_calls"] += 1
        record["summary"]["retried_region_count"] += 1
        try:
            if runner is groq_visual_extract:
                raw = runner(
                    region,
                    model,
                    deadline_monotonic=phase_started + phase_timeout_seconds,
                    remaining_requests=total_regions - index + 1,
                    clock=clock,
                )
            else:
                raw = runner(region, model)
            result = validate_visual_response(raw, region)
        except (ProviderError, VisualEvidenceError, ValueError, TypeError) as exc:
            code = getattr(exc, "code", "VISUAL_PROVIDER_FAILED")
            record_failure(region, artifact, index, code)
            if isinstance(exc, ProviderError) and code == "AI_PROVIDER_RATE_LIMITED":
                # This code is emitted only after provider retry handling is
                # exhausted or the advertised wait no longer fits the shared
                # phase budget. Treat it as strong saturation evidence.
                stop_code = "VISUAL_PROVIDER_CIRCUIT_OPEN"
            elif isinstance(exc, ProviderError) and exc.retryable:
                consecutive_transport_failures += 1
                if consecutive_transport_failures >= VISUAL_FAILURE_CIRCUIT_THRESHOLD:
                    stop_code = "VISUAL_PROVIDER_CIRCUIT_OPEN"
            else:
                consecutive_transport_failures = 0
            continue
        consecutive_transport_failures = 0
        record["evidence"].extend(result["evidence"])
        record["mark_changes"].extend(result["mark_changes"])
        record["warnings"].extend({"code": "VISUAL_MODEL_WARNING", "message": item, "page": region["page"]} for item in result["warnings"])
        if len(result["evidence"]) == VISUAL_EVIDENCE_MAX_ITEMS:
            record["warnings"].append({
                "code": "VISUAL_EVIDENCE_ITEM_CAP_REACHED",
                "message": "The visual model returned the maximum permitted evidence items for one physical crop.",
                "page": region["page"],
                "rendered_asset_ref": region["asset_path"],
                "item_count": VISUAL_EVIDENCE_MAX_ITEMS,
            })
        record["runs"].append({
            "provider": str(result.get("provider") or "groq"),
            "model": str(result.get("model") or model),
            "page": region["page"], "image_count": 1, "success": True,
            "rendered_asset_ref": region["asset_path"],
            "elapsed_ms": result.get("elapsed_ms"),
        })
        record["summary"]["success_count"] += 1
        record["summary"]["new_success_count"] += 1
        if result["visual_content_present"]:
            record["summary"]["visual_content_count"] += 1
        emit_progress("success", index, region)
        if checkpoint_callback is not None:
            checkpoint_callback(record, artifact)
    _deduplicate_visual_items(record["evidence"])
    _deduplicate_visual_items(record["mark_changes"])
    record["summary"]["effective_evidence_count"] = sum(
        1 for item in record["evidence"] if item.get("effective", True)
    )
    record["summary"]["suppressed_evidence_count"] = sum(
        1 for item in record["evidence"] if not item.get("effective", True)
    )
    return record, artifacts


def fuse_visual_evidence(structure: dict[str, Any], visual: dict[str, Any]) -> dict[str, Any]:
    questions = {str(item.get("question_id")): item for item in structure.get("questions", [])}
    attached = 0
    evidence_items = visual.get("evidence", [])
    _deduplicate_visual_items(evidence_items)
    mark_changes = visual.get("mark_changes", [])
    _deduplicate_visual_items(mark_changes)
    association_items = [
        item for item in [*evidence_items, *mark_changes]
        if item.get("evidence_status") in {"cross_anchor_mismatch", "context_only"}
    ]
    association_items.extend({**item, "association_status": "unresolved_question"}
        for item in evidence_items
        if item.get("effective", True)
        and questions.get(str(item.get("question_ref"))) is None
    )
    for unit in visual_association_review_units(association_items):
        structure.setdefault("exceptions", []).append({
            "level": "amber",
            "category": "visual_evidence_association_uncertain",
            "affected_id": unit.get("owned_question_ref")
                or next(iter(unit.get("claimed_question_refs") or []), None),
            "message": (
                "One physical visual source region has alternative or duplicate "
                "readings and needs a bounded question-association decision."
            ),
            "suggestions": [unit],
        })
    for item in evidence_items:
        question_ref = item.get("question_ref")
        target = questions.get(str(question_ref)) if question_ref is not None else None
        confidence = float(item.get("confidence") or 0)
        if not item.get("effective", True):
            continue
        if target is None:
            continue
        target.setdefault("visual_evidence", []).append(item)
        attached += 1
        normalization_issue = item.get("math_normalization_issue")
        solution_kind = item.get("kind") in {"answer", "answer_working", "diagram_entry"}
        if normalization_issue and solution_kind:
            structure.setdefault("exceptions", []).append({
                "level": "amber", "category": "visual_math_notation_uncertain",
                "affected_id": question_ref,
                "message": "Visible mathematical notation could not be normalized safely and requires teacher confirmation.",
                "suggestions": [{
                    "rendered_asset_ref": item.get("rendered_asset_ref"),
                    "page": item.get("page"),
                    "transcription": item.get("transcription"),
                    "normalization_issue": normalization_issue,
                }],
            })
            continue
        if solution_kind and confidence >= VISUAL_REVIEW_THRESHOLD:
            text = str(item.get("normalized_math") or item.get("transcription") or "").strip()
            if text:
                target.setdefault("visual_solution_segments", []).append({
                    "text": text,
                    "raw_transcription": item.get("transcription"),
                    "source_ref": {"file_id": "source_1", "page": item.get("page")},
                    "rendered_asset_ref": item.get("rendered_asset_ref"),
                    "confidence": confidence,
                    "canonical_latex": item.get("normalized_math"),
                })
        if confidence < VISUAL_REVIEW_THRESHOLD:
            structure.setdefault("exceptions", []).append({
                "level": "amber", "category": "visual_evidence_uncertain",
                "affected_id": question_ref,
                "message": "Handwritten or visual memo evidence requires teacher confirmation.",
                "suggestions": [{
                    "rendered_asset_ref": item.get("rendered_asset_ref"),
                    "page": item.get("page"),
                    "transcription": item.get("transcription"),
                }],
            })

    for change in mark_changes:
        if not change.get("effective", True):
            continue
        structure.setdefault("exceptions", []).append({
            "level": "amber", "category": "visual_mark_change_review",
            "affected_id": change.get("question_ref"),
            "message": "A handwritten mark allocation differs from the printed value and requires confirmation.",
            "suggestions": [{
                "printed_value": change.get("printed_value"),
                "visual_value": change.get("visual_value"),
                "level": change.get("level"),
                "rendered_asset_ref": change.get("rendered_asset_ref"),
            }],
        })
    for warning in visual.get("warnings", []):
        if warning.get("code") in {
            "VISUAL_MODEL_WARNING", "VISUAL_EVIDENCE_ITEM_CAP_REACHED",
        }:
            continue
        structure.setdefault("exceptions", []).append({
            "level": "red", "category": "visual_evidence_unread",
            "affected_id": None,
            "message": "We found handwritten or visual memo information that could not be read reliably.",
            "suggestions": [{"rendered_asset_ref": warning.get("rendered_asset_ref"), "page": warning.get("page")}],
        })
    summary = structure.setdefault("summary", {})
    summary["visual_evidence_count"] = len(evidence_items)
    summary["visual_evidence_effective_count"] = sum(
        1 for item in evidence_items if item.get("effective", True)
    )
    summary["visual_evidence_attached_count"] = attached
    summary["visual_mark_change_observation_count"] = len(mark_changes)
    summary["visual_mark_change_count"] = sum(
        1 for change in mark_changes if change.get("effective", True)
    )
    summary["visual_review_required"] = any(
        item.get("category", "").startswith("visual_")
        for item in structure.get("exceptions", [])
    )
    summary["review_required"] = bool(structure.get("exceptions"))
    summary["amber_count"] = sum(1 for item in structure.get("exceptions", []) if item.get("level") == "amber")
    summary["red_count"] = sum(1 for item in structure.get("exceptions", []) if item.get("level") == "red")
    return structure
