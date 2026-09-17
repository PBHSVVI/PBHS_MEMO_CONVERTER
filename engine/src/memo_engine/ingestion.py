from __future__ import annotations

import hashlib
import io
import mimetypes
import zipfile
from pathlib import PurePosixPath
from typing import Any
from xml.etree import ElementTree as ET

MAX_SOURCE_BYTES = 50 * 1024 * 1024

PDF_MIME = "application/pdf"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PNG_MIME = "image/png"
JPEG_MIME = "image/jpeg"


class IngestionError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.public_message = message


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def validate_source_path(job: dict[str, Any]) -> str:
    source_path = job.get("source_path")
    if not isinstance(source_path, str) or not source_path.strip():
        raise IngestionError(
            "INGESTION_SOURCE_PATH_MISSING",
            "The job has no source file path.",
        )

    expected_prefix = f"{job['user_id']}/{job['id']}/source/"
    path = PurePosixPath(source_path)
    normalized = str(path)

    if source_path.startswith("/") or ".." in path.parts:
        raise IngestionError(
            "INGESTION_SOURCE_PATH_INVALID",
            "The source file path is invalid.",
        )
    if not normalized.startswith(expected_prefix):
        raise IngestionError(
            "INGESTION_SOURCE_PATH_OUTSIDE_JOB",
            "The source file is outside the job's permitted source namespace.",
        )
    return normalized


def detect_kind(data: bytes, filename: str | None) -> tuple[str, str]:
    if data.startswith(b"%PDF-"):
        return "pdf", PDF_MIME
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png", PNG_MIME
    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg", JPEG_MIME

    if data.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                names = set(archive.namelist())
                if "word/document.xml" in names and "[Content_Types].xml" in names:
                    return "docx", DOCX_MIME
        except zipfile.BadZipFile:
            pass

    suffix = PurePosixPath(filename or "").suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        return "jpeg", JPEG_MIME
    if suffix == ".png":
        return "png", PNG_MIME
    if suffix == ".pdf":
        return "pdf", PDF_MIME
    if suffix == ".docx":
        return "docx", DOCX_MIME

    guessed, _ = mimetypes.guess_type(filename or "")
    raise IngestionError(
        "INGESTION_UNSUPPORTED_FILE_TYPE",
        f"Unsupported source file type ({guessed or 'unknown'}).",
    )


def extract_docx_text(data: bytes) -> dict[str, Any]:
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}

    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            xml = archive.read("word/document.xml")
    except (zipfile.BadZipFile, KeyError) as exc:
        raise IngestionError(
            "INGESTION_DOCX_INVALID",
            "The DOCX package could not be read.",
        ) from exc

    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise IngestionError(
            "INGESTION_DOCX_XML_INVALID",
            "The DOCX document XML could not be parsed.",
        ) from exc

    paragraphs: list[str] = []
    for paragraph in root.findall(".//w:p", ns):
        pieces: list[str] = []
        for node in paragraph.iter():
            if node.tag == f"{{{ns['w']}}}t":
                pieces.append(node.text or "")
            elif node.tag == f"{{{ns['w']}}}tab":
                pieces.append("\t")
            elif node.tag in {f"{{{ns['w']}}}br", f"{{{ns['w']}}}cr"}:
                pieces.append("\n")
        text = "".join(pieces).strip()
        if text:
            paragraphs.append(text)

    joined = "\n".join(paragraphs)
    return {
        "method": "docx_xml",
        "page_count": None,
        "text": joined,
        "text_length": len(joined),
        "text_sha256": sha256_hex(joined.encode("utf-8")),
        "has_digital_text": bool(joined.strip()),
    }


def extract_pdf_text(data: bytes) -> dict[str, Any]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise IngestionError(
            "INGESTION_PDF_READER_MISSING",
            "The PDF reader dependency is not installed.",
        ) from exc

    try:
        reader = PdfReader(io.BytesIO(data), strict=False)
    except Exception as exc:
        raise IngestionError(
            "INGESTION_PDF_INVALID",
            "The PDF could not be opened.",
        ) from exc

    pages: list[dict[str, Any]] = []
    all_text: list[str] = []
    extraction_errors = 0

    for number, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
            extraction_errors += 1
        pages.append({"page": number, "text": text, "text_length": len(text)})
        all_text.append(text)

    joined = "\n\f\n".join(all_text)
    return {
        "method": "pypdf",
        "page_count": len(pages),
        "pages": pages,
        "text": joined,
        "text_length": len(joined),
        "text_sha256": sha256_hex(joined.encode("utf-8")),
        "has_digital_text": bool(joined.strip()),
        "page_extraction_errors": extraction_errors,
    }


def extract_source(kind: str, data: bytes) -> dict[str, Any]:
    if kind == "docx":
        return extract_docx_text(data)
    if kind == "pdf":
        return extract_pdf_text(data)
    if kind in {"png", "jpeg"}:
        return {
            "method": "none_image_requires_ocr",
            "page_count": 1,
            "text": "",
            "text_length": 0,
            "text_sha256": sha256_hex(b""),
            "has_digital_text": False,
        }
    raise IngestionError(
        "INGESTION_UNSUPPORTED_FILE_TYPE",
        "The detected source type is unsupported.",
    )


def build_ingestion_record(
    *,
    job: dict[str, Any],
    source_path: str,
    data: bytes,
    kind: str,
    detected_mime: str,
    extraction: dict[str, Any],
) -> dict[str, Any]:
    warnings: list[dict[str, str]] = []

    declared_mime = job.get("source_mime")
    if declared_mime and declared_mime != detected_mime:
        warnings.append({
            "code": "DECLARED_MIME_MISMATCH",
            "message": "Declared MIME type differs from detected file type.",
        })

    if kind in {"pdf", "docx"} and not extraction.get("has_digital_text"):
        warnings.append({
            "code": "NO_DIGITAL_TEXT",
            "message": "No digital text was extracted; OCR/vision will be required.",
        })

    if extraction.get("page_extraction_errors"):
        warnings.append({
            "code": "PDF_PAGE_EXTRACTION_ERRORS",
            "message": "One or more PDF pages could not be text-extracted deterministically.",
        })

    return {
        "schema_version": "1.0",
        "phase": "phase1_ingestion",
        "job_id": job["id"],
        "user_id": job["user_id"],
        "source": {
            "filename": job.get("source_filename"),
            "storage_path": source_path,
            "declared_mime": declared_mime,
            "detected_kind": kind,
            "detected_mime": detected_mime,
            "size_bytes": len(data),
            "sha256": sha256_hex(data),
        },
        "extraction": extraction,
        "warnings": warnings,
    }


def ingest_bytes(job: dict[str, Any], data: bytes) -> dict[str, Any]:
    if not data:
        raise IngestionError(
            "INGESTION_EMPTY_SOURCE",
            "The uploaded source file is empty.",
        )
    if len(data) > MAX_SOURCE_BYTES:
        raise IngestionError(
            "INGESTION_SOURCE_TOO_LARGE",
            "The source file exceeds the 50 MB Phase 1 limit.",
        )

    source_path = validate_source_path(job)
    filename = job.get("source_filename") or PurePosixPath(source_path).name
    kind, detected_mime = detect_kind(data, filename)
    extraction = extract_source(kind, data)

    return build_ingestion_record(
        job=job,
        source_path=source_path,
        data=data,
        kind=kind,
        detected_mime=detected_mime,
        extraction=extraction,
    )
