"""Provider-boundary coordinates; never guess units from observed magnitudes."""
from __future__ import annotations

import copy
import hashlib
import json
import math
from typing import Any

OPENAI_COORDINATE_CONTRACT = "openai-crop-unit-interval-v1"
CROP_PIXELS = "crop_pixels"
CROP_UNIT_INTERVAL = "crop_unit_interval"


def json_digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _pixels(box: Any, width: int, height: int) -> list[float] | None:
    if box is None:
        return None
    if (not isinstance(box, list) or len(box) != 4
            or any(type(v) not in (int, float) or not math.isfinite(v) for v in box)):
        raise ValueError("Invalid normalized bounding box")
    left, top, right, bottom = box
    if not (0 <= left < right <= 1 and 0 <= top < bottom <= 1):
        raise ValueError("Bounding box violates the declared unit-interval contract")
    return [left * width, top * height, right * width, bottom * height]


def openai_crop_pixels(payload: dict[str, Any], width: int, height: int) -> dict[str, Any]:
    """Convert the declared contract once, retaining the exact provider input.

    Tagged replays must match their original response, rather than scaling again.
    This private envelope is never added to the provider's response schema.
    """
    if type(width) is not int or type(height) is not int or width <= 0 or height <= 0:
        raise ValueError("Invalid crop dimensions")
    if not isinstance(payload, dict):
        raise ValueError("Coordinate response must be an object")
    metadata = payload.get("coordinate_provenance")
    if metadata is not None:
        if (not isinstance(metadata, dict)
                or metadata.get("contract") != OPENAI_COORDINATE_CONTRACT
                or metadata.get("source_space") != CROP_UNIT_INTERVAL
                or metadata.get("target_space") != CROP_PIXELS
                or metadata.get("pixel_width") != width or metadata.get("pixel_height") != height):
            raise ValueError("Ambiguous or incompatible coordinate provenance")
        original = metadata.get("provider_response")
        if not isinstance(original, dict) or "coordinate_provenance" in original:
            raise ValueError("Invalid original coordinate response")
        expected = openai_crop_pixels(original, width, height)
        if expected != payload:
            raise ValueError("Coordinate replay differs from its original response")
        return copy.deepcopy(payload)
    converted = copy.deepcopy(payload)
    for field in ("evidence", "mark_changes"):
        if not isinstance(converted.get(field), list):
            raise ValueError("Coordinate response arrays are missing")
        for item in converted[field]:
            item["bbox"] = _pixels(item["bbox"], width, height)
    converted["coordinate_provenance"] = {
        "contract": OPENAI_COORDINATE_CONTRACT,
        "source_space": CROP_UNIT_INTERVAL, "target_space": CROP_PIXELS,
        "pixel_width": width, "pixel_height": height,
        "provider_response_digest": json_digest(payload),
        "provider_response": copy.deepcopy(payload),
    }
    return converted
