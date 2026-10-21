from __future__ import annotations

import hashlib
import io
import json
import shutil
import zipfile
from copy import deepcopy
from pathlib import Path

import pytest
from docx import Document
from PIL import Image, ImageDraw
from pypdf import PdfReader

from engine.src.memo_engine.canonical import _content_segments, build_canonical_memo
from engine.src.memo_engine.renderer import render_docx, render_outputs
from engine.src.memo_engine.visual_evidence import (
    OWNERSHIP_ALGORITHM_VERSION,
    SPATIAL_PRESERVATION_VERSION,
    fuse_visual_evidence,
    visual_checkpoint_is_compatible,
)


def _diagram_png(kind: str) -> bytes:
    image = Image.new("RGB", (560, 440), "white")
    draw = ImageDraw.Draw(image)
    if kind == "venn":
        draw.ellipse((55, 85, 310, 335), outline="black", width=5)
        draw.ellipse((180, 85, 435, 335), outline="black", width=5)
        draw.ellipse((115, 175, 370, 420), outline="black", width=5)
        draw.text((70, 60), "SET A", fill="black")
        draw.text((390, 60), "SET B", fill="black")
        draw.text((238, 405), "SET C", fill="black")
        for xy, value in [((110, 170), "4"), ((260, 140), "8"), ((345, 175), "6"), ((245, 260), "3")]:
            draw.text(xy, value, fill="black")
    else:
        draw.line((55, 215, 230, 90), fill="black", width=5)
        draw.line((55, 215, 230, 340), fill="black", width=5)
        draw.line((230, 90, 430, 45), fill="black", width=5)
        draw.line((230, 90, 430, 150), fill="black", width=5)
        draw.line((230, 340, 430, 285), fill="black", width=5)
        draw.line((230, 340, 430, 395), fill="black", width=5)
        for xy, value in [((105, 120), "0.4"), ((105, 285), "0.6"), ((325, 45), "S"), ((325, 380), "F")]:
            draw.text(xy, value, fill="black")
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _question(question_id: str = "1.1") -> dict:
    return {
        "question_id": question_id,
        "source_question_id": question_id,
        "path": [int(part) for part in question_id.split(".")],
        "depth": len(question_id.split(".")),
        "context_only": False,
        "source_block_index": 0,
        "source_page": 1,
        "source_character_offset": 0,
        "printed_marks": 1,
        "computed_shorthand_marks": 1,
        "mark_calculation_mode": "additive",
        "mark_points": [{
            "count": 1,
            "code": "A",
            "descriptor": "diagram answer",
            "notation": "shorthand",
        }],
        "source_preview": "Draw the required diagram.",
    }


def _visual(kind: str, *, reliable: bool = True, with_working: bool = False):
    data = _diagram_png(kind)
    path = f"internal/visual/regions/page-0001-q1_1-{kind}.png"
    asset = {
        "path": path,
        "sha256": hashlib.sha256(data).hexdigest(),
        "size_bytes": len(data),
        "mime_type": "image/png",
        "pixel_width": 560,
        "pixel_height": 440,
        "page": 1,
        "question_refs": ["1.1"],
        "render_bbox": [20.0, 80.0, 320.0, 330.0] if reliable else [0.0, 0.0, 595.0, 800.0],
        "owned_bbox": [20.0, 90.0, 320.0, 320.0],
        "page_bbox": [0.0, 0.0, 595.0, 842.0],
        "preservation_method": "source_crop",
    }
    evidence = []
    if with_working:
        evidence.append({
            "evidence_id": "working-1",
            "question_ref": "1.1",
            "kind": "answer_working",
            "transcription": "x = 5",
            "normalized_math": "x = 5",
            "confidence": 0.97,
            "effective": True,
            "page": 1,
            "rendered_asset_ref": path,
            "source_page_bbox": [35.0, 100.0, 80.0, 120.0],
            "owned_bbox": asset["owned_bbox"],
            "render_bbox": asset["render_bbox"],
            "page_bbox": asset["page_bbox"],
            "owned_question_ref": "1.1",
            "association_status": "owned",
        })
    labels = ["4", "8", "6", "3"] if kind == "venn" else ["0.4", "0.6", "S", "F"]
    boxes = [
        [70.0, 120.0, 90.0, 140.0],
        [150.0, 125.0, 175.0, 145.0],
        [230.0, 150.0, 250.0, 170.0],
        [155.0, 235.0, 175.0, 255.0],
    ]
    for index, (label, bbox) in enumerate(zip(labels, boxes), start=1):
        evidence.append({
            "evidence_id": f"diagram-{index}",
            "question_ref": "1.1",
            "kind": "diagram_entry",
            "transcription": label,
            "normalized_math": None,
            "confidence": 0.96,
            "effective": True,
            "page": 1,
            "rendered_asset_ref": path,
            "source_page_bbox": bbox,
            "owned_bbox": asset["owned_bbox"],
            "render_bbox": asset["render_bbox"],
            "page_bbox": asset["page_bbox"],
            "owned_question_ref": "1.1",
            "association_status": "owned",
        })
    return {"evidence": evidence, "mark_changes": [], "assets": [asset]}, data


def _build(structure: dict):
    normalized = {
        "job_id": "spatial-fixture",
        "source": {"sha256": "synthetic", "detected_kind": "pdf"},
        "content": {
            "kind": "pdf",
            "pages": [{"page": 1, "effective_text": "1.1 Draw the required diagram. (1)\nTOTAL: 1"}],
        },
    }
    semantic = {
        "phase": "phase4_semantics",
        "deterministic_results": [],
        "ai_results": [],
        "exceptions": [],
        "interpreter_runs": [],
    }
    job = {"id": "spatial-fixture", "source_filename": "fixture.pdf", "source_mime": "application/pdf"}
    ingestion = {"source": {"sha256": "synthetic", "detected_kind": "pdf", "detected_mime": "application/pdf", "size_bytes": 1}}
    return build_canonical_memo(job, ingestion, normalized, structure, semantic, b"%PDF-synthetic")


def _item(canonical: dict) -> dict:
    return canonical["questions"][0]["items"][0]


def _fused(kind: str, *, reliable: bool = True, with_working: bool = False):
    structure = {"job_id": "spatial-fixture", "questions": [_question()], "subtotals": [], "exceptions": []}
    visual, data = _visual(kind, reliable=reliable, with_working=with_working)
    fuse_visual_evidence(structure, visual)
    return structure, visual, data


def _pdf_image_count(path: Path) -> int:
    count = 0
    visited: set[int] = set()

    def visit_resources(resources) -> None:
        nonlocal count
        if resources is None:
            return
        resources = resources.get_object()
        xobjects = resources.get("/XObject")
        if xobjects is None:
            return
        for reference in xobjects.get_object().values():
            object_id = id(reference)
            if object_id in visited:
                continue
            visited.add(object_id)
            item = reference.get_object()
            subtype = item.get("/Subtype")
            if subtype == "/Image":
                count += 1
            elif subtype == "/Form":
                visit_resources(item.get("/Resources"))

    for page in PdfReader(str(path)).pages:
        visit_resources(page.get("/Resources"))
    return count


def test_venn_entries_become_one_source_backed_figure_without_flattening(tmp_path: Path):
    structure, visual, data = _fused("venn")
    question = structure["questions"][0]
    assert len(question["spatial_visual_groups"]) == 1
    assert "visual_solution_segments" not in question
    group = question["spatial_visual_groups"][0]
    assert group["reliable"] is True
    assert group["evidence_bbox_union"] == [70.0, 120.0, 250.0, 255.0]
    assert group["crop_bounds"] == visual["assets"][0]["render_bbox"]

    canonical, validation, _ = _build(structure)
    item = _item(canonical)
    blocks = item["alternatives"][0]["blocks"]
    assert [block["type"] for block in blocks] == ["figure"]
    assert not any(label in str(block) for label in ["4 8 6 3", "4 8", "6 3"] for block in blocks)
    figure = blocks[0]["figure"]
    assert figure["spatial_semantics_required"] is True
    assert figure["source_page"] == 1
    assert figure["visual_evidence_ids"] == ["diagram-1", "diagram-2", "diagram-3", "diagram-4"]
    assert "essential_visual_preservation_required" not in validation["error_codes"]

    canonical["status"] = "render_ready"
    canonical["document_metadata"].update({
        "exam_type": "CONTROLLED TEST", "year": 2026, "subject": "MATHEMATICS",
        "paper": "PAPER 1", "grade_label": "FORM 5", "duration_minutes": 60,
    })
    output = tmp_path / "venn.docx"
    preflight = render_docx(
        canonical,
        b"%PDF-synthetic",
        output,
        supplemental_assets={figure["asset_id"]: (data, "image/png")},
    )
    assert preflight["passed"] is True
    assert preflight["expected_figure_blocks"] == 1
    assert preflight["embedded_figure_elements"] >= 1
    with zipfile.ZipFile(output) as archive:
        media = [name for name in archive.namelist() if name.startswith("word/media/")]
        assert len(media) == 1
        assert hashlib.sha256(archive.read(media[0])).hexdigest() == hashlib.sha256(data).hexdigest()
        assert "image" in archive.read("word/_rels/document.xml.rels").decode("utf-8")
    document = Document(output)
    matching_rows = [row for table in document.tables for row in table.rows if "1.1" in row.cells[0].text]
    assert matching_rows
    assert matching_rows[0].cells[1]._tc.xpath(".//w:drawing")


@pytest.mark.skipif(
    not (shutil.which("libreoffice") or shutil.which("soffice")),
    reason="LibreOffice is required for hosted spatial PDF qualification",
)
def test_spatial_figure_survives_hosted_docx_to_pdf_conversion(tmp_path: Path):
    structure, _, data = _fused("venn")
    canonical, validation, _ = _build(structure)
    figure = _item(canonical)["alternatives"][0]["blocks"][0]["figure"]
    canonical["status"] = "render_ready"
    canonical["document_metadata"].update({
        "exam_type": "CONTROLLED TEST", "year": 2026, "subject": "MATHEMATICS",
        "paper": "PAPER 1", "grade_label": "FORM 5", "duration_minutes": 60,
    })

    assert validation["passed"] is True
    result = render_outputs(
        canonical,
        b"%PDF-synthetic",
        tmp_path / "outputs",
        supplemental_assets={figure["asset_id"]: (data, "image/png")},
    )
    docx_path = Path(result["docx_path"])
    pdf_path = Path(result["pdf_path"])
    pdf_images = _pdf_image_count(pdf_path)

    assert docx_path.stat().st_size > 0
    assert pdf_path.stat().st_size > 0
    assert 1 <= result["page_count"] <= 10
    assert result["docx_preflight"]["passed"] is True
    assert result["docx_preflight"]["expected_figure_blocks"] == 1
    assert result["docx_preflight"]["embedded_figure_elements"] >= 1
    assert result["pdf_preflight"]["passed"] is True
    assert result["pdf_preflight"]["missing_glyphs"] == []
    assert all(font["embedded"] for font in result["pdf_preflight"]["fonts"])
    assert pdf_images >= 1

    print("HOSTED_SPATIAL_PDF_QUALIFICATION=" + json.dumps({
        "canonical_figure_blocks": 1,
        "docx_bytes": docx_path.stat().st_size,
        "docx_embedded_figures": result["docx_preflight"]["embedded_figure_elements"],
        "docx_preflight_passed": result["docx_preflight"]["passed"],
        "pdf_bytes": pdf_path.stat().st_size,
        "pdf_image_xobjects": pdf_images,
        "pdf_page_count": result["page_count"],
        "pdf_preflight_passed": result["pdf_preflight"]["passed"],
        "pdf_required_glyphs": result["pdf_preflight"]["required_glyphs"],
        "pdf_missing_glyphs": result["pdf_preflight"]["missing_glyphs"],
        "pdf_fonts_embedded": all(
            font["embedded"] for font in result["pdf_preflight"]["fonts"]
        ),
        "orphan_or_missing_media": False,
    }, sort_keys=True))


def test_probability_tree_is_preserved_spatially():
    structure, _, _ = _fused("tree")
    canonical, validation, _ = _build(structure)
    blocks = _item(canonical)["alternatives"][0]["blocks"]
    assert [block["type"] for block in blocks] == ["figure"]
    assert blocks[0]["figure"]["preservation_method"] == "source_crop"
    assert "essential_visual_preservation_required" not in validation["error_codes"]


def test_unreliable_spatial_crop_blocks_review_and_never_flattens_labels():
    structure, _, _ = _fused("venn", reliable=False)
    question = structure["questions"][0]
    assert "spatial_visual_groups" not in question
    assert "visual_solution_segments" not in question
    issue = next(item for item in structure["exceptions"] if item["category"] == "essential_visual_preservation_required")
    assert "source_crop_excessive" in issue["suggestions"][0]["reason"]

    canonical, validation, _ = _build(structure)
    assert _item(canonical)["alternatives"][0]["blocks"] == []
    assert "essential_visual_preservation_required" in validation["error_codes"]
    assert sum(
        item["category"] == "essential_visual_preservation_required"
        for item in canonical["exceptions"]
    ) == 1
    assert canonical["status"] != "render_ready"


def test_nonessential_mark_change_is_not_promoted_to_figure():
    structure = {"questions": [_question()], "exceptions": []}
    visual = {
        "evidence": [],
        "assets": [],
        "mark_changes": [{
            "evidence_id": "circled-score",
            "question_ref": "1.1",
            "kind": "mark_change",
            "confidence": 0.97,
            "effective": True,
            "printed_value": 1,
            "visual_value": 2,
        }],
    }
    fuse_visual_evidence(structure, visual)
    question = structure["questions"][0]
    assert "spatial_visual_groups" not in question
    assert "essential_visual_evidence" not in question
    assert any(
        item["category"] == "visual_mark_change_review"
        for item in structure["exceptions"]
    )


def test_ordinary_working_and_spatial_figure_keep_evidence_order():
    structure, _, _ = _fused("tree", with_working=True)
    canonical, _, _ = _build(structure)
    blocks = _item(canonical)["alternatives"][0]["blocks"]
    assert [block["type"] for block in blocks] == ["math", "figure"]
    assert blocks[0]["math"]["plain_text"] == "x = 5"


def test_native_source_figure_precedes_visual_crop_without_losing_source_working():
    qdata = {
        "question_id": "1.1",
        "visual_solution_segments": [{"text": "x = 5", "confidence": 0.9}],
        "spatial_visual_groups": [{"reliable": True, "asset_id": "crop"}],
    }
    source = [{
        "text": "source working",
        "content_role": "solution_working",
        "drawing_assets": ["native_asset"],
        "source_ref": {"file_id": "source_1", "page": 1},
    }]
    selected = _content_segments(qdata, deepcopy(source))
    assert selected[0]["drawing_assets"] == ["native_asset"]
    assert all(segment.get("content_role") != "figure" for segment in selected)


def test_spatial_checkpoint_requires_matching_crop_metadata():
    checkpoint = {
        "schema_version": "1.0",
        "ownership_algorithm_version": OWNERSHIP_ALGORITHM_VERSION,
        "source_sha256": "source-digest",
        "evidence": [{
            "kind": "diagram_entry",
            "effective": True,
            "rendered_asset_ref": "internal/visual/regions/diagram.png",
        }],
        "assets": [],
    }
    assert visual_checkpoint_is_compatible(checkpoint, "source-digest") is False
    checkpoint["spatial_preservation_version"] = SPATIAL_PRESERVATION_VERSION
    checkpoint["assets"] = [{"path": "internal/visual/regions/diagram.png"}]
    assert visual_checkpoint_is_compatible(checkpoint, "source-digest") is True

