from __future__ import annotations

import hashlib
import io
import json
import os
import re
import sys
import time

from PIL import Image, ImageDraw, ImageFont

from .ai_router import ProviderError
from .http import SupabaseRest
from .openai_adapter import OpenAIInterpreter, check_model_access
from .openai_credit import CreditLedger
from .provider_fabric import (
    PRIVACY_SYNTHETIC_TEST, TASK_VISUAL_INTERPRETATION, ProviderTaskRequest,
    default_provider_registry, provider_ineligibility_reason,
)
from .visual_evidence import _vision_schema, spatial_visual_groups, validate_visual_response, visual_system_prompt


def _synthetic_crop() -> bytes:
    image = Image.new("RGB", (880, 480), "white")
    draw = ImageDraw.Draw(image)
    ink = "#253366"
    try:
        font = ImageFont.truetype("DejaVuSans-Oblique.ttf", 33)
    except OSError:
        font = ImageFont.load_default(size=33)
    draw.text((32, 26), "Question 1.1", font=font, fill="black")
    draw.text((48, 100), "P(A) = 3/5 = 0.6", font=font, fill=ink)
    draw.line([(145, 300), (318, 228), (438, 191)], fill=ink, width=4)
    draw.line([(145, 300), (316, 350), (438, 392)], fill=ink, width=4)
    draw.text((248, 206), "0.6", font=font, fill=ink)
    draw.text((248, 350), "0.4", font=font, fill=ink)
    draw.text((452, 163), "A", font=font, fill=ink)
    draw.text((452, 371), "not A", font=font, fill=ink)
    data = io.BytesIO()
    image.save(data, format="PNG")
    return data.getvalue()


def qualify() -> dict:
    interpreter = OpenAIInterpreter(CreditLedger(SupabaseRest(), synthetic=True), os.environ)
    spec = default_provider_registry()["openai"]
    if provider_ineligibility_reason(spec, task_type=TASK_VISUAL_INTERPRETATION,
                                     privacy_classification=PRIVACY_SYNTHETIC_TEST):
        raise ProviderError("OPENAI_SYNTHETIC_POLICY_BLOCKED", "The synthetic route is ineligible.")
    crop = _synthetic_crop()
    digest = hashlib.sha256(crop).hexdigest()
    request = ProviderTaskRequest(
        task_type=TASK_VISUAL_INTERPRETATION, region_id="synthetic/1.1.png",
        current_question_owner="1.1", source_question="1.1", source_page=1,
        source_digest=digest, crop_digest=digest, crop_bytes=crop, crop_mime_type="image/png",
        interpretation_schema_version="1.0", task_prompt_version="synthetic-phase85-v1",
        privacy_classification=PRIVACY_SYNTHETIC_TEST,
        prompt=visual_system_prompt() + '\nKnown question anchors: ["1.1"]. Read the separate blue working and probability tree. Question heading only is printed.',
        response_schema=_vision_schema(1),
    )
    result = interpreter.visual(request, spec, time.monotonic() + 90, 1, time.monotonic)
    bounds = [0, 0, 880, 480]
    page_bounds = [0, 0, 1000, 900]
    evidence = validate_visual_response(result.normalized_result, {
        "page": 1, "asset_path": request.region_id, "question_refs": ["1.1"],
        "page_bbox": page_bounds, "render_bbox": bounds, "owned_bbox": bounds, "printed_text": "Question 1.1",
    })["evidence"]
    answers = " ".join(row["transcription"] for row in evidence if row.get("effective") and row["kind"] in {"answer", "answer_working"})
    tree = " ".join(row["transcription"] for row in evidence if row.get("effective") and row["kind"] == "diagram_entry")
    groups = spatial_visual_groups(evidence, [{
        "page": 1, "path": request.region_id, "sha256": digest, "size_bytes": len(crop),
        "pixel_width": 880, "pixel_height": 480, "question_refs": ["1.1"],
        "page_bbox": page_bounds, "render_bbox": bounds, "owned_bbox": bounds,
        "preservation_method": "source_crop",
    }])
    if not (re.search(r"0[.,]6\b", answers) and re.search(r"0[.,]6\b", tree) and re.search(r"0[.,]4\b", tree)
            and any(group["reliable"] and group["asset"]["sha256"] == digest for group in groups)
            and hashlib.sha256(request.crop_bytes).hexdigest() == digest):
        raise ProviderError("OPENAI_SYNTHETIC_EVIDENCE_MISMATCH", "The synthetic answer or diagram did not match the source.")
    semantic = interpreter.semantic([{"candidate_id": "sample", "source_shorthand": "M", "descriptor": "Correct method"}])
    if semantic.results[0]["semantic_type"] != "method" or semantic.results[0]["band"] != "green":
        raise ProviderError("OPENAI_SYNTHETIC_SEMANTIC_MISMATCH", "The synthetic marking point was not classified correctly.")
    return {
        "visual": {"model": result.model_id, "latency_ms": result.latency_ms, "usage": result.usage, "quota": result.quota},
        "semantic": {"model": semantic.model, "latency_ms": semantic.elapsed_ms, "usage": semantic.usage},
        "production_schema_passed": True, "source_crop_unchanged": True,
    }


def main() -> int:
    try:
        check_model_access(os.environ)
        print("Luna catalogue access verified. Metadata check used zero inference calls.")
        if sys.argv[1:] == ["--synthetic"]:
            print(json.dumps(qualify(), sort_keys=True))
    except ProviderError as error:
        print(json.dumps({"phase85_error": error.code, "http_status": error.http_status}))
        return 1
    except Exception:
        print('Phase 8.5 check failed before a safe result was available.')
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
