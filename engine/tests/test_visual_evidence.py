from __future__ import annotations

import copy
import io
from pathlib import Path

import fitz
from PIL import Image

from engine.src.memo_engine.ai_router import ProviderError
from engine.src.memo_engine.canonical import _content_segments
from engine.src.memo_engine.normalization import normalize_pdf
from engine.src.memo_engine.visual_evidence import (
    extract_visual_evidence,
    fuse_visual_evidence,
    image_visual_screen,
    screen_pdf_page,
    visual_system_prompt,
)


ROOT = Path(__file__).resolve().parents[2]


def _pdf(*, text: str = "3.1 Find the regression equation. (3)", colour=None, black=False, ink=False, pages=1) -> bytes:
    document = fitz.open()
    for index in range(pages):
        page = document.new_page(width=595, height=842)
        page.insert_text((60, 80), text if index == 0 else "4.1 Complete the calculation. (2)", fontsize=12)
        if colour is not None:
            page.draw_line((80, 130), (320, 165), color=colour, width=3)
        if black:
            page.draw_line((90, 190), (110, 215), color=(0, 0, 0), width=3)
            page.draw_line((110, 215), (170, 155), color=(0, 0, 0), width=3)
        if ink:
            page.add_ink_annot([[(100, 250), (140, 265), (200, 245)]])
    result = document.tobytes()
    document.close()
    return result


def _ingestion(data: bytes, texts: list[str]) -> dict:
    return {
        "extraction": {
            "pages": [
                {"page": index + 1, "text": text, "text_length": len(text)}
                for index, text in enumerate(texts)
            ]
        }
    }


def _normalized(data: bytes, texts: list[str]) -> dict:
    return {
        "job_id": "synthetic-hybrid",
        "source": {"sha256": "synthetic", "detected_kind": "pdf"},
        "content": normalize_pdf(data, _ingestion(data, texts)),
    }


def _response(page=1, *, confidence=0.94, kind="answer_working", mark_changes=None):
    return {
        "schema_version": "1.0",
        "page": page,
        "visual_content_present": True,
        "evidence": [{
            "question_ref": "3.1",
            "kind": kind,
            "transcription": "y = 0,72x + 6,71",
            "normalized_math": "y = 0,72x + 6,71",
            "confidence": confidence,
            "source": "visual_overlay",
            "bbox": [70, 110, 360, 240],
        }],
        "mark_changes": mark_changes or [],
        "warnings": [],
        "provider": "groq",
        "model": "test-vision",
        "elapsed_ms": 4,
        "usage": {},
    }


def _structure():
    return {
        "questions": [{
            "question_id": "3.1", "source_preview": "3.1 Find the regression equation.",
            "source_block_index": 0, "mark_points": [],
        }],
        "exceptions": [],
        "summary": {},
    }


def test_clean_digital_pdf_makes_no_vision_call():
    text = "3.1 Find the regression equation. (3)"
    normalized = _normalized(_pdf(text=text), [text])
    calls = []
    visual, artifacts = extract_visual_evidence(
        _pdf(text=text), normalized,
        runner=lambda region, model: calls.append(region),
    )
    assert calls == []
    assert artifacts == []
    assert visual["summary"]["pages_flagged"] == 0
    assert visual["summary"]["vision_calls"] == 0


def test_digital_text_with_coloured_or_black_handwriting_is_flagged():
    text = "3.1 Find the regression equation. (3)"
    coloured = _normalized(_pdf(text=text, colour=(1, 0, 0)), [text])
    black = _normalized(_pdf(text=text, black=True), [text])
    assert "COLOURED_OVERLAY_PRESENT" in coloured["content"]["pages"][0]["visual_inspection_reasons"]
    assert "NON_TEXT_VECTOR_DRAWINGS_PRESENT" in black["content"]["pages"][0]["visual_inspection_reasons"]
    assert black["content"]["pages"][0]["visual_inspection_required"] is True


def test_pdf_ink_annotation_and_write_on_document_trigger_visual_inspection():
    text = "WRITE-ON TEST 3.1 Find the regression equation. (3)"
    data = _pdf(text=text, ink=True, pages=2)
    normalized = _normalized(data, [text, "4.1 Complete the calculation. (2)"])
    first, second = normalized["content"]["pages"]
    assert "PDF_INK_ANNOTATIONS_PRESENT" in first["visual_inspection_reasons"]
    assert "WRITE_ON_DOCUMENT" in first["visual_inspection_reasons"]
    assert second["visual_inspection_required"] is True
    assert "WRITE_ON_DOCUMENT" in second["visual_inspection_reasons"]


def test_blank_scanned_and_image_sources_use_visual_path():
    for kind in ("png", "jpeg"):
        screen = image_visual_screen(kind)
        assert screen["visual_inspection_required"] is True
        assert "IMAGE_PAGE" in screen["visual_inspection_reasons"]

    image = Image.new("RGB", (300, 180), "white")
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    document = fitz.open()
    page = document.new_page()
    page.insert_image(page.rect, stream=stream.getvalue())
    scan = screen_pdf_page(page, "")
    document.close()
    assert scan["visual_inspection_required"] is True
    assert "IMAGE_PAGE" in scan["visual_inspection_reasons"]
    assert "RASTER_OVERLAY_PRESENT" in scan["visual_inspection_reasons"]


def test_amanda_shaped_synthetic_hybrid_attaches_answer_without_duplicate():
    text = "3.1 Find the regression equation. (3)"
    data = _pdf(text=text, colour=(1, 0, 0), black=True)
    normalized = _normalized(data, [text])
    response = _response(mark_changes=[{
        "question_ref": "3.1", "level": "subtotal", "printed_value": 3,
        "visual_value": 4, "confidence": 0.95, "requires_confirmation": True,
        "bbox": [400, 60, 520, 120],
    }])
    response["evidence"].append({
        "question_ref": "3.1", "kind": "tick", "transcription": "✓",
        "normalized_math": None, "confidence": 0.96,
        "source": "visual_overlay", "bbox": [80, 150, 180, 225],
    })
    visual, artifacts = extract_visual_evidence(data, normalized, runner=lambda region, model: response)
    structure = fuse_visual_evidence(_structure(), visual)
    assert len(structure["questions"]) == 1
    assert structure["questions"][0]["question_id"] == "3.1"
    assert structure["questions"][0]["visual_solution_segments"][0]["text"] == "y = 0,72x + 6,71"
    assert structure["summary"]["visual_evidence_attached_count"] == 2
    assert any(item["kind"] == "tick" for item in structure["questions"][0]["visual_evidence"])
    assert any(item["category"] == "visual_mark_change_review" for item in structure["exceptions"])
    assert artifacts[0]["path"].startswith("internal/visual/")


def test_handwritten_decimal_comma_and_fraction_semantics_are_preserved():
    text = "3.1 Find the regression equation. (3)"
    data = _pdf(text=text, black=True)
    normalized = _normalized(data, [text])
    response = _response()
    response["evidence"][0]["transcription"] = "x = 1/2; y = 0,72"
    response["evidence"][0]["normalized_math"] = "x = \\frac{1}{2}; y = 0,72"
    visual, _ = extract_visual_evidence(data, normalized, runner=lambda region, model: response)
    item = visual["evidence"][0]
    assert item["transcription"] == "x = 1/2; y = 0,72"
    assert item["normalized_math"] == "x = \\frac{1}{2}; y = 0,72"


def test_canonical_content_uses_visual_answer_without_repeating_printed_prompt():
    source = [{"text": "3.1 Find the regression equation. (3)", "source_ref": {"file_id": "source_1", "page": 1}}]
    visual = [{
        "text": "y = 0,72x + 6,71", "raw_transcription": "y = 0,72x + 6,71",
        "source_ref": {"file_id": "source_1", "page": 1},
        "rendered_asset_ref": "internal/visual/regions/page-0001-q3_1.png",
        "confidence": 0.94,
    }]
    fused = _content_segments({"visual_solution_segments": visual}, source)
    assert [item["text"] for item in fused] == ["y = 0,72x + 6,71"]
    assert fused[0]["visual_evidence"]["raw_transcription"] == "y = 0,72x + 6,71"


def test_confirmed_teacher_content_override_outweighs_visual_solution_and_preserves_both_origins():
    source_ref = {"file_id": "source_1", "page": 1}
    source = [{"text": "3.1 Printed source answer", "source_ref": source_ref}]
    visual = [{
        "text": "AI visual interpretation",
        "raw_transcription": "AI visual interpretation",
        "source_ref": source_ref,
        "rendered_asset_ref": "internal/visual/regions/page-0001-q3_1.png",
        "confidence": 0.94,
    }]
    visual_artifact = [{
        "question_ref": "3.1",
        "kind": "answer_working",
        "transcription": "AI visual interpretation",
        "normalized_math": "AI visual interpretation",
        "confidence": 0.94,
        "rendered_asset_ref": "internal/visual/regions/page-0001-q3_1.png",
    }]
    question = {
        "visual_solution_segments": visual,
        "visual_evidence": visual_artifact,
        "content_override": {
            "correction_id": "corr-teacher-3-1",
            "question_text": "Teacher-corrected question",
            "solution_lines": ["Teacher-corrected solution"],
        },
    }
    original_visual_artifact = copy.deepcopy(visual_artifact)

    content = _content_segments(question, source)

    assert [segment["text"] for segment in content] == [
        "Teacher-corrected question", "Teacher-corrected solution",
    ]
    assert all(segment["source_ref"] == source_ref for segment in content)
    assert all(segment["teacher_correction_id"] == "corr-teacher-3-1" for segment in content)
    assert all("visual_evidence" not in segment for segment in content)
    assert question["visual_evidence"] == original_visual_artifact


def test_teacher_correction_outweighs_low_confidence_visual_review_content():
    source_ref = {"file_id": "source_1", "page": 2}
    source = [{"text": "Printed source fallback", "source_ref": source_ref}]
    question = {
        "visual_solution_segments": [{
            "text": "Uncertain visual reading",
            "raw_transcription": "Uncertain visual reading",
            "source_ref": source_ref,
            "rendered_asset_ref": "internal/visual/regions/page-0002-q3_1.png",
            "confidence": 0.55,
        }],
        "visual_evidence": [{
            "question_ref": "3.1",
            "confidence": 0.55,
            "requires_confirmation": True,
            "rendered_asset_ref": "internal/visual/regions/page-0002-q3_1.png",
        }],
        "content_override": {
            "correction_id": "corr-after-visual-review",
            "question_text": "Confirmed teacher wording",
            "solution_lines": ["Confirmed teacher answer"],
        },
    }

    content = _content_segments(question, source)

    assert [segment["text"] for segment in content] == [
        "Confirmed teacher wording", "Confirmed teacher answer",
    ]
    assert all(segment["teacher_correction_id"] == "corr-after-visual-review" for segment in content)
    assert question["visual_evidence"][0]["confidence"] == 0.55


def test_low_confidence_symbol_requires_review_with_private_crop():
    text = "3.1 Find the regression equation. (3)"
    data = _pdf(text=text, black=True)
    visual, _ = extract_visual_evidence(data, _normalized(data, [text]), runner=lambda region, model: _response(confidence=0.55))
    structure = fuse_visual_evidence(_structure(), visual)
    exception = next(item for item in structure["exceptions"] if item["category"] == "visual_evidence_uncertain")
    assert exception["affected_id"] == "3.1"
    assert exception["suggestions"][0]["rendered_asset_ref"].startswith("internal/visual/")


def test_diagram_entry_uses_same_closed_evidence_contract():
    text = "3.1 Complete the Venn diagram. (3)"
    data = _pdf(text=text, black=True)
    visual, _ = extract_visual_evidence(data, _normalized(data, [text]), runner=lambda region, model: _response(kind="diagram_entry"))
    structure = fuse_visual_evidence(_structure(), visual)
    assert structure["questions"][0]["visual_evidence"][0]["kind"] == "diagram_entry"


def test_printed_mark_and_handwritten_change_is_review_candidate_not_override():
    text = "3.1 Find the regression equation. (3)"
    data = _pdf(text=text, colour=(1, 0, 0))
    change = [{
        "question_ref": "3.1", "level": "item", "printed_value": 3,
        "visual_value": 4, "confidence": 0.96, "requires_confirmation": True,
        "bbox": [400, 60, 520, 120],
    }]
    visual, _ = extract_visual_evidence(data, _normalized(data, [text]), runner=lambda region, model: _response(mark_changes=change))
    structure = fuse_visual_evidence(_structure(), visual)
    exception = next(item for item in structure["exceptions"] if item["category"] == "visual_mark_change_review")
    assert exception["suggestions"][0] == {
        "printed_value": 3, "visual_value": 4, "level": "item",
        "rendered_asset_ref": visual["mark_changes"][0]["rendered_asset_ref"],
    }
    assert "printed_marks" not in structure["questions"][0]


def test_vision_outage_after_positive_screening_fails_safe():
    text = "3.1 Find the regression equation. (3)"
    data = _pdf(text=text, black=True)

    def unavailable(region, model):
        raise ProviderError("AI_PROVIDER_RATE_LIMITED", "rate limited")

    visual, _ = extract_visual_evidence(data, _normalized(data, [text]), runner=unavailable)
    structure = fuse_visual_evidence(_structure(), visual)
    assert visual["summary"]["failure_count"] >= 1
    assert any(item["category"] == "visual_evidence_unread" and item["level"] == "red" for item in structure["exceptions"])


def test_malformed_model_json_fails_safe():
    text = "3.1 Find the regression equation. (3)"
    data = _pdf(text=text, black=True)
    visual, _ = extract_visual_evidence(data, _normalized(data, [text]), runner=lambda region, model: {"answer": "invented"})
    assert visual["summary"]["failure_count"] >= 1
    assert visual["warnings"][0]["code"] == "VISUAL_MODEL_SCHEMA_INVALID"


def test_prompt_forbids_solving_and_invention():
    prompt = visual_system_prompt()
    for phrase in (
        "DO NOT solve a missing answer",
        "DO NOT infer an answer",
        "DO NOT invent marking allocations",
        "DO NOT reproduce printed question text",
        "DO NOT silently repair unclear handwriting",
    ):
        assert phrase in prompt


def test_no_image_or_base64_content_is_logged(capsys):
    text = "3.1 Find the regression equation. (3)"
    data = _pdf(text=text, black=True)
    extract_visual_evidence(data, _normalized(data, [text]), runner=lambda region, model: _response())
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
    assert "base64" not in captured.out.lower()


def test_hosted_workflow_configures_distinct_approved_vision_model():
    workflow = (ROOT / ".github" / "workflows" / "process-memo.yml").read_text(encoding="utf-8")
    assert "MEMO_GROQ_VISION_MODEL: qwen/qwen3.8-27b" in workflow
    assert "MEMO_APPROVED_PROVIDERS: groq" in workflow


def test_review_ui_loads_private_visual_crop_without_public_url():
    review = (ROOT / "docs" / "phase7-5-review" / "index.html").read_text(encoding="utf-8")
    assert "renderVisualEvidenceCrop" in review
    assert "internal/visual/" in review
    assert ".storage.from('memo-files').download(path)" in review
    assert "getPublicUrl" not in review
    assert "Accept this reading" in review
    assert "content_correction:{target_id:target" in review
