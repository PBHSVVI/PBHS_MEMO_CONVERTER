from __future__ import annotations

import io
import json
import re
import shutil
import subprocess
import zipfile
from typing import Any
from xml.etree import ElementTree as ET

from .ingestion import IngestionError, sha256_hex


class NormalizationError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.public_message = message


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
M_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
NS = {"w": W_NS, "m": M_NS, "a": A_NS}


def _attr(ns: str, name: str) -> str:
    return f"{{{ns}}}{name}"


def _text_from_element(element: ET.Element) -> str:
    parts: list[str] = []
    for node in element.iter():
        if node.tag in {_attr(W_NS, "t"), _attr(M_NS, "t")}:
            parts.append(node.text or "")
        elif node.tag == _attr(W_NS, "tab"):
            parts.append("\t")
        elif node.tag in {_attr(W_NS, "br"), _attr(W_NS, "cr")}:
            parts.append("\n")
    return "".join(parts)


def _paragraph_record(p: ET.Element) -> dict[str, Any]:
    ppr = p.find("w:pPr", NS)
    style = None
    num_id = None
    ilvl = None

    if ppr is not None:
        style_node = ppr.find("w:pStyle", NS)
        if style_node is not None:
            style = style_node.get(_attr(W_NS, "val"))

        num_pr = ppr.find("w:numPr", NS)
        if num_pr is not None:
            num_node = num_pr.find("w:numId", NS)
            level_node = num_pr.find("w:ilvl", NS)
            if num_node is not None:
                num_id = num_node.get(_attr(W_NS, "val"))
            if level_node is not None:
                ilvl = level_node.get(_attr(W_NS, "val"))

    equations: list[dict[str, Any]] = []
    for math in p.findall(".//m:oMath", NS):
        equations.append(
            {
                "text": _text_from_element(math),
                "omml": ET.tostring(math, encoding="unicode"),
            }
        )

    text = _text_from_element(p)
    return {
        "type": "paragraph",
        "text": text,
        "style": style,
        "numbering": {"num_id": num_id, "level": ilvl}
        if num_id is not None or ilvl is not None
        else None,
        "equations": equations,
        "has_math": bool(equations),
        "drawing_count": len(p.findall(".//w:drawing", NS)),
    }


def _table_record(tbl: ET.Element) -> dict[str, Any]:
    rows: list[list[dict[str, Any]]] = []
    for tr in tbl.findall("./w:tr", NS):
        row: list[dict[str, Any]] = []
        for tc in tr.findall("./w:tc", NS):
            paragraphs = [_paragraph_record(p) for p in tc.findall("./w:p", NS)]
            row.append(
                {
                    "text": "\n".join(
                        item["text"] for item in paragraphs if item["text"].strip()
                    ),
                    "paragraphs": paragraphs,
                }
            )
        rows.append(row)
    return {"type": "table", "rows": rows}


def normalize_docx(data: bytes) -> dict[str, Any]:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            document_xml = archive.read("word/document.xml")
            media: list[dict[str, Any]] = []
            for name in sorted(archive.namelist()):
                if name.startswith("word/media/") and not name.endswith("/"):
                    blob = archive.read(name)
                    media.append(
                        {
                            "path": name,
                            "size_bytes": len(blob),
                            "sha256": sha256_hex(blob),
                        }
                    )
    except (zipfile.BadZipFile, KeyError) as exc:
        raise NormalizationError(
            "NORMALIZATION_DOCX_INVALID",
            "The DOCX package could not be read during normalisation.",
        ) from exc

    try:
        root = ET.fromstring(document_xml)
    except ET.ParseError as exc:
        raise NormalizationError(
            "NORMALIZATION_DOCX_XML_INVALID",
            "The DOCX document XML could not be parsed during normalisation.",
        ) from exc

    body = root.find("w:body", NS)
    if body is None:
        raise NormalizationError(
            "NORMALIZATION_DOCX_BODY_MISSING",
            "The DOCX document body is missing.",
        )

    units: list[dict[str, Any]] = []
    paragraph_count = 0
    table_count = 0
    equation_count = 0
    drawing_count = 0

    for child in list(body):
        if child.tag == _attr(W_NS, "p"):
            record = _paragraph_record(child)
            paragraph_count += 1
            equation_count += len(record["equations"])
            drawing_count += record["drawing_count"]
            units.append(record)
        elif child.tag == _attr(W_NS, "tbl"):
            record = _table_record(child)
            table_count += 1
            for row in record["rows"]:
                for cell in row:
                    for paragraph in cell["paragraphs"]:
                        paragraph_count += 1
                        equation_count += len(paragraph["equations"])
                        drawing_count += paragraph["drawing_count"]
            units.append(record)

    return {
        "kind": "docx",
        "units": units,
        "summary": {
            "unit_count": len(units),
            "paragraph_count": paragraph_count,
            "table_count": table_count,
            "equation_count": equation_count,
            "drawing_count": drawing_count,
            "embedded_media_count": len(media),
        },
        "embedded_media": media,
        "ocr": {
            "engine": None,
            "attempted": 0,
            "used": 0,
            "reason": "Digital OOXML structure available; OCR not used.",
        },
    }


def _quality_gate(text: str) -> tuple[bool, list[str]]:
    stripped = text.strip()
    reasons: list[str] = []
    if not stripped:
        reasons.append("NO_DIGITAL_TEXT")
        return True, reasons

    alnum = sum(ch.isalnum() for ch in stripped)
    replacement = stripped.count("\ufffd")
    control = sum(ord(ch) < 32 and ch not in "\n\r\t" for ch in stripped)

    if len(stripped) < 40 and alnum < 20:
        reasons.append("VERY_LOW_TEXT_VOLUME")
    if replacement / max(1, len(stripped)) > 0.02:
        reasons.append("HIGH_REPLACEMENT_CHARACTER_RATE")
    if control / max(1, len(stripped)) > 0.02:
        reasons.append("HIGH_CONTROL_CHARACTER_RATE")

    return bool(reasons), reasons


def _tesseract_version() -> str:
    exe = shutil.which("tesseract")
    if not exe:
        raise NormalizationError(
            "NORMALIZATION_OCR_ENGINE_MISSING",
            "Local OCR was required but Tesseract is not installed on the hosted runner.",
        )
    result = subprocess.run(
        [exe, "--version"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=15,
    )
    first = result.stdout.decode("utf-8", errors="replace").splitlines()
    return first[0].strip() if first else "tesseract"


def _ocr_image(image_bytes: bytes) -> str:
    exe = shutil.which("tesseract")
    if not exe:
        raise NormalizationError(
            "NORMALIZATION_OCR_ENGINE_MISSING",
            "Local OCR was required but Tesseract is not installed on the hosted runner.",
        )
    result = subprocess.run(
        [exe, "stdin", "stdout", "-l", "eng", "--psm", "6"],
        input=image_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=120,
    )
    if result.returncode != 0:
        raise NormalizationError(
            "NORMALIZATION_OCR_FAILED",
            "Local OCR failed on one of the required pages.",
        )
    return result.stdout.decode("utf-8", errors="replace")


def normalize_pdf(data: bytes, ingestion: dict[str, Any]) -> dict[str, Any]:
    try:
        import fitz
    except ImportError as exc:
        raise NormalizationError(
            "NORMALIZATION_PDF_RENDERER_MISSING",
            "The PDF rendering dependency is not installed.",
        ) from exc

    try:
        document = fitz.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise NormalizationError(
            "NORMALIZATION_PDF_INVALID",
            "The PDF could not be opened during normalisation.",
        ) from exc

    ingestion_pages = {
        int(page["page"]): page.get("text", "")
        for page in ingestion.get("extraction", {}).get("pages", [])
        if isinstance(page, dict) and "page" in page
    }

    pages: list[dict[str, Any]] = []
    ocr_attempted = 0
    ocr_used = 0
    ocr_engine: str | None = None

    try:
        for index in range(document.page_count):
            page = document.load_page(index)
            page_number = index + 1

            digital_text = ingestion_pages.get(page_number)
            if digital_text is None:
                digital_text = page.get_text("text") or ""

            needs_ocr, reasons = _quality_gate(digital_text)
            ocr_text = ""

            if needs_ocr:
                if ocr_engine is None:
                    ocr_engine = _tesseract_version()
                ocr_attempted += 1
                pix = page.get_pixmap(matrix=fitz.Matrix(2.5, 2.5), alpha=False)
                ocr_text = _ocr_image(pix.tobytes("png"))
                if ocr_text.strip():
                    ocr_used += 1

            effective_text = digital_text
            effective_source = "digital"

            if not digital_text.strip() and ocr_text.strip():
                effective_text = ocr_text
                effective_source = "ocr"
            elif needs_ocr and ocr_text.strip():
                # Preserve both representations. Downstream logic should not silently
                # overwrite usable digital text with OCR guesses.
                effective_source = "digital_plus_ocr"

            pages.append(
                {
                    "page": page_number,
                    "width_points": float(page.rect.width),
                    "height_points": float(page.rect.height),
                    "image_count": len(page.get_images(full=True)),
                    "digital_text": digital_text,
                    "digital_text_length": len(digital_text),
                    "ocr_required": needs_ocr,
                    "ocr_reasons": reasons,
                    "ocr_text": ocr_text,
                    "ocr_text_length": len(ocr_text),
                    "effective_text": effective_text,
                    "effective_text_source": effective_source,
                }
            )
    finally:
        document.close()

    return {
        "kind": "pdf",
        "pages": pages,
        "summary": {
            "page_count": len(pages),
            "ocr_required_pages": sum(1 for p in pages if p["ocr_required"]),
            "digital_pages": sum(1 for p in pages if not p["ocr_required"]),
        },
        "ocr": {
            "engine": ocr_engine,
            "attempted": ocr_attempted,
            "used": ocr_used,
        },
    }


def normalize_image(kind: str, data: bytes) -> dict[str, Any]:
    engine = _tesseract_version()
    text = _ocr_image(data)
    return {
        "kind": kind,
        "pages": [
            {
                "page": 1,
                "digital_text": "",
                "digital_text_length": 0,
                "ocr_required": True,
                "ocr_reasons": ["IMAGE_SOURCE"],
                "ocr_text": text,
                "ocr_text_length": len(text),
                "effective_text": text,
                "effective_text_source": "ocr",
            }
        ],
        "summary": {
            "page_count": 1,
            "ocr_required_pages": 1,
            "digital_pages": 0,
        },
        "ocr": {
            "engine": engine,
            "attempted": 1,
            "used": 1 if text.strip() else 0,
        },
    }


def normalize_source(
    job: dict[str, Any],
    source_bytes: bytes,
    ingestion: dict[str, Any],
) -> dict[str, Any]:
    source = ingestion["source"]
    kind = source["detected_kind"]

    actual_sha = sha256_hex(source_bytes)
    if actual_sha != source["sha256"]:
        raise NormalizationError(
            "NORMALIZATION_SOURCE_HASH_MISMATCH",
            "The source file changed between ingestion and normalisation.",
        )

    if kind == "docx":
        content = normalize_docx(source_bytes)
    elif kind == "pdf":
        content = normalize_pdf(source_bytes, ingestion)
    elif kind in {"png", "jpeg"}:
        content = normalize_image(kind, source_bytes)
    else:
        raise NormalizationError(
            "NORMALIZATION_UNSUPPORTED_KIND",
            "The ingested source type cannot be normalised.",
        )

    return {
        "schema_version": "1.0",
        "phase": "phase2_normalization",
        "job_id": job["id"],
        "source": {
            "sha256": source["sha256"],
            "detected_kind": kind,
            "detected_mime": source["detected_mime"],
        },
        "content": content,
    }
