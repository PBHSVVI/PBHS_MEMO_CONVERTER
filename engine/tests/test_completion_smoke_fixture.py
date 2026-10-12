from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from engine.scripts.generate_completion_smoke_fixture import build_fixture_bytes, generate_fixture
from engine.src.memo_engine import renderer
from engine.src.memo_engine.canonical import build_canonical_memo
from engine.src.memo_engine.ingestion import DOCX_MIME, ingest_bytes
from engine.src.memo_engine.normalization import normalize_source
from engine.src.memo_engine.renderer import render_docx, render_outputs
from engine.src.memo_engine.semantic import interpret_semantics
from engine.src.memo_engine.structure import extract_structure


ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "engine" / "src" / "memo_engine" / "cli.py"


def _libreoffice_executable() -> str | None:
    windows_default = Path(r"C:\Program Files\LibreOffice\program\soffice.exe")
    if os.name == "nt" and windows_default.is_file():
        return str(windows_default)
    return shutil.which("libreoffice") or shutil.which("soffice")


def _windows_pdf_export(executable: str, docx_path: str | Path, output_dir: str | Path) -> Path:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="pbhs-lo-test-") as profile:
        environment = dict(os.environ)
        environment["HOME"] = profile
        result = subprocess.run(
            [
                executable,
                "--headless",
                f"-env:UserInstallation={(Path(profile) / 'profile').as_uri()}",
                "--convert-to",
                "pdf",
                "--outdir",
                str(output),
                str(docx_path),
            ],
            capture_output=True,
            check=False,
            env=environment,
            timeout=180,
        )
    pdf = output / (Path(docx_path).stem + ".pdf")
    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
    assert pdf.is_file() and pdf.stat().st_size > 0
    return pdf


def _pipeline(source: bytes):
    job = {
        "id": "completion-smoke-fixture",
        "user_id": "public-fixture",
        "source_path": "public-fixture/completion-smoke-fixture/source/completion_smoke_memo.docx",
        "source_filename": "completion_smoke_memo.docx",
        "source_mime": DOCX_MIME,
        "teacher_metadata": {
            "schema_version": "1.0",
            "values": {},
            "confirmed_absent": [],
        },
        "teacher_metadata_revision": 0,
    }
    ingestion = ingest_bytes(job, source)
    normalized = normalize_source(job, source, ingestion)
    structure = extract_structure(normalized)
    semantic = interpret_semantics(structure)
    canonical, validation, new_exceptions = build_canonical_memo(
        job, ingestion, normalized, structure, semantic, source
    )
    return ingestion, normalized, structure, semantic, canonical, validation, new_exceptions


def test_generator_is_deterministic_and_docx_is_parseable(tmp_path):
    first = build_fixture_bytes()
    second = build_fixture_bytes()
    assert first == second

    output = generate_fixture(tmp_path / "completion_smoke_memo.docx")
    assert output.read_bytes() == first
    ingestion, *_ = _pipeline(first)
    assert ingestion["source"]["detected_kind"] == "docx"
    assert ingestion["source"]["detected_mime"] == DOCX_MIME


def test_fixture_reaches_render_ready_without_review():
    _, _, structure, semantic, canonical, validation, new_exceptions = _pipeline(
        build_fixture_bytes()
    )
    assert structure["exceptions"] == []
    assert semantic["exceptions"] == []
    assert semantic["summary"]["ai_candidate_count"] == 0
    assert new_exceptions == []
    assert canonical["exceptions"] == []
    assert canonical["status"] == "render_ready"
    assert validation["passed"] is True
    assert len(canonical["questions"]) == 1
    assert canonical["questions"][0]["number"] == "1"
    assert canonical["questions"][0]["subtotal"] == {
        "observed": 5,
        "computed": 5,
        "status": "match",
    }
    assert canonical["totals"] == {
        "observed": 5,
        "computed": 5,
        "expected": 5,
        "status": "match",
    }

    assert canonical["document_metadata"] == {
        "exam_type": "CLASS TEST",
        "year": 2026,
        "subject": "MATHEMATICS",
        "paper": "PAPER 1",
        "grade_label": "FORM 5",
        "language": None,
        "exam_code": None,
        "expected_total_marks": 5,
        "duration_minutes": 30,
        "observed_page_count_text": None,
    }
    fields = canonical["audit"]["metadata_resolution"]["fields"]
    for field in ("subject", "paper", "exam_type", "year", "grade_label", "duration_minutes"):
        assert fields[field]["selected_provenance"] == "source"


def test_fixture_docx_render_preflight_passes(tmp_path):
    source = build_fixture_bytes()
    *_, canonical, _, _ = _pipeline(source)
    result = render_docx(canonical, source, tmp_path / "memo.docx", page_count=1)
    assert result["passed"] is True
    assert (tmp_path / "memo.docx").is_file()


@pytest.mark.skipif(
    _libreoffice_executable() is None,
    reason="LibreOffice is required for local PDF qualification",
)
def test_fixture_full_docx_pdf_render_passes(tmp_path, monkeypatch):
    source = build_fixture_bytes()
    *_, canonical, _, _ = _pipeline(source)
    executable = _libreoffice_executable()
    original_which = shutil.which
    monkeypatch.setattr(
        "engine.src.memo_engine.renderer.shutil.which",
        lambda command: executable
        if command in {"libreoffice", "soffice"}
        else original_which(command),
    )
    if os.name == "nt":
        monkeypatch.setattr(
            renderer,
            "convert_docx_to_pdf",
            lambda docx_path, output_dir: _windows_pdf_export(
                str(executable), docx_path, output_dir
            ),
        )
    result = render_outputs(canonical, source, tmp_path)
    assert result["docx_preflight"]["passed"] is True
    assert result["pdf_preflight"]["passed"] is True
    assert Path(result["docx_path"]).is_file()
    assert Path(result["pdf_path"]).is_file()


def test_successful_terminal_lifecycle_patch_writes_completed_at():
    source = CLI.read_text(encoding="utf-8")
    final_transition = source[source.index("        completed_at = utc_now()") :]
    assert '"status": "complete",\n                "stage": "complete"' in final_transition
    assert '"completed_at": completed_at,\n                "updated_at": completed_at' in final_transition
