from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
REVIEW_PAGE = ROOT / "docs" / "phase7-5-review" / "index.html"


def _section(name: str) -> str:
    html = REVIEW_PAGE.read_text(encoding="utf-8")
    match = re.search(
        rf"// BEGIN {name}\s*(.*?)\s*// END {name}",
        html,
        flags=re.S,
    )
    assert match, f"{name.lower()} is missing from the review page"
    return match.group(1)


def _run_node(program: str, *values: dict) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for the semantic conflict regression")
    result = subprocess.run(
        [node, "--input-type=module", "-e", program, *(json.dumps(value) for value in values)],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return json.loads(result.stdout)


def test_candidate_id_resolves_to_teacher_facing_mark_point_and_explicit_choices():
    exception = {
        "category": "ambiguous_mark_semantics",
        "affected_id": "4.2.2",
        "suggestions": [{
            "candidate_id": "4_2_2__m4",
            "semantic_type": "consistent_accuracy",
            "confidence_score": 0.97,
            "resolution_method": "groq:model",
            "conflict_reason": "shorthand_semantic_conflict",
        }],
    }
    structure = {"questions": [{
        "question_id": "4.2.2",
        "mark_points": [
            {"count": 1, "code": "M", "descriptor": "method"},
            {"count": 1, "code": "A", "descriptor": "working"},
            {"count": 1, "code": "R", "descriptor": "reason"},
            {"count": 1, "code": "A", "descriptor": "Correct c-value"},
        ],
    }]}
    program = (
        "const humanCategory=value=>String(value||'').replaceAll('_',' ');\n"
        + _section("SEMANTIC CONFLICT MODEL")
        + "\nconst ex=JSON.parse(process.argv[1]);const structure=JSON.parse(process.argv[2]);"
        + "\nconst model=semanticConflictModel(ex,ex.suggestions[0],structure);"
        + "\nconsole.log(JSON.stringify({model,presentation:semanticConflictPresentation(model)}));"
    )

    result = _run_node(program, exception, structure)

    dash = chr(0x2014)
    assert result["presentation"] == {
        "title": f"Question 4.2.2 {dash} final marking point",
        "entered": f"1A {dash} Correct c-value",
        "suggested": f"1CA {dash} Correct c-value",
        "suggested_choice": f"Use CA {dash} Consistent accuracy",
        "entered_choice": f"Keep A {dash} Accuracy",
    }
    assert result["model"]["mark_index"] == 3
    assert result["model"]["candidate_id"] == "4_2_2__m4"


def test_other_semantic_keeps_actual_mark_point_and_offers_bounded_code_choices():
    exception = {
        "category": "ambiguous_mark_semantics",
        "affected_id": "7.2",
        "suggestions": [{
            "candidate_id": "7_2__m6",
            "mark_index": 5,
            "semantic_type": "other",
            "confidence_score": 0.60,
        }],
    }
    structure = {"questions": [{
        "question_id": "7.2",
        "mark_points": [
            {"count": 1, "code": "M", "descriptor": f"step {index}"}
            for index in range(1, 6)
        ] + [{"count": 1, "code": "A", "descriptor": "change sign"}],
    }]}
    program = (
        "const humanCategory=value=>String(value||'').replaceAll('_',' ');\n"
        + _section("SEMANTIC CONFLICT MODEL")
        + "\nconst ex=JSON.parse(process.argv[1]);const structure=JSON.parse(process.argv[2]);"
        + "\nconst model=semanticConflictModel(ex,ex.suggestions[0],structure);"
        + "\nconsole.log(JSON.stringify({model,presentation:semanticConflictPresentation(model),options:semanticCodeOptions(model)}));"
    )

    result = _run_node(program, exception, structure)

    assert result["presentation"]["title"] == "Question 7.2 — final marking point"
    assert result["presentation"]["entered"] == "1A — change sign"
    assert result["presentation"]["suggested"] is None
    assert result["presentation"]["suggested_choice"] is None
    assert [item["code"] for item in result["options"]] == ["M", "A", "CA", "F", "S", "R"]
    assert result["options"][1]["action"] == "Keep current code A — Accuracy"


def test_suggestion_controls_never_render_raw_json():
    html = REVIEW_PAGE.read_text(encoding="utf-8")
    start = html.index("async function renderChoices(ex)")
    end = html.index("async function showException", start)
    source = html[start:end]
    assert "JSON.stringify(s)" not in source
    assert "Use ${label}" in source
    assert "semanticConflictPresentation" in source
    assert "Accept supplied suggestion" not in html
    assert "automatic check could not confidently identify the intended marking code" in source
    assert "semanticCodeOptions(model)" in source
    assert "Compare the two plain-language choices below" not in html


def test_technical_identifiers_remain_under_technical_details():
    html = REVIEW_PAGE.read_text(encoding="utf-8")
    assert '<summary>Technical details</summary><div>Candidate:' in html
    assert "Candidate: <code>${esc(model.candidate_id)}" in html
    assert "Semantic type: <code>${esc(model.suggested_semantic)}" in html
    assert "Confidence: <code>${esc(model.confidence_score)}" in html
    assert "Provider path: <code>${esc(model.provider)}" in html


def test_legacy_pending_semantic_suggestion_requires_cancel_and_explicit_choice():
    html = REVIEW_PAGE.read_text(encoding="utf-8")
    assert "Cancel and reopen conflict choices" in html
    assert "older suggestion attempt does not contain an explicit marking-code choice" in html
    assert "!corr.proposed_patch&&ex.category==='ambiguous_mark_semantics'" in html


def test_selected_semantic_choice_has_readable_confirmation_showback():
    dash = chr(0x2014)
    correction = {
        "display_text": f"Question 4.2.2 {dash} final marking point: use 1CA {dash} Correct c-value (Consistent accuracy).",
        "proposed_patch": {
            "operation": "resolve_mark_semantic_conflict",
            "affected_id": "4.2.2",
            "candidate_id": "4_2_2__m4",
            "mark_index": 3,
            "source_count": 1,
            "source_descriptor": "Correct c-value",
            "selected_code": "CA",
            "selected_semantic_type": "consistent_accuracy",
            "suggested_semantic_type": "consistent_accuracy",
            "confidence_score": 0.97,
            "resolution_method": "groq:model",
            "teacher_choice": "suggested",
        },
    }
    program = (
        _section("TEACHER SHOWBACK MODEL")
        + "\nconsole.log(JSON.stringify(teacherShowBackModel(JSON.parse(process.argv[1]))));"
    )

    result = _run_node(program, correction)

    assert result["summary"].startswith(f"Question 4.2.2 {dash} final marking point")
    assert result["semantic_choice"]["selected_code"] == "CA"
    assert result["semantic_choice"]["descriptor"] == "Correct c-value"
    assert result["semantic_choice"]["candidate_id"] == "4_2_2__m4"


def test_submit_endpoint_builds_confirmation_ready_auditable_semantic_patch():
    source = (ROOT / "supabase" / "functions" / "submit-correction" / "index.ts").read_text(encoding="utf-8")
    assert "body.semantic_resolution" in source
    assert 'operation: "resolve_mark_semantic_conflict"' in source
    assert 'reinterpretation_method: "structured_semantic_conflict_choice"' in source
    assert 'exceptionStatus = "awaiting_confirmation"' in source
    assert "ALLOWED_SEMANTICS_BY_CODE[selectedCode]?.has(selectedSemantic)" in source
    assert '!["suggested", "entered", "code"].includes(String(choice))' in source
    assert 'choice === "code" && (suggestedCode || !MARK_CODES.has(explicitCode))' in source
    assert "DEFAULT_SEMANTIC_BY_CODE[selectedCode]" in source


def test_semantic_review_disables_generic_free_text_and_keeps_technical_values_collapsed():
    html = REVIEW_PAGE.read_text(encoding="utf-8")
    assert "grouped||semantic" in html
    assert '<summary>Technical details</summary>' in html
    assert 'semantic_resolution:{candidate_id:model.candidate_id,choice' in html


def test_existing_a_to_f_conflict_remains_an_explicit_two_choice_review():
    exception = {
        "category": "ambiguous_mark_semantics",
        "affected_id": "6.1",
        "suggestions": [{"candidate_id": "6_1__m1", "semantic_type": "formula"}],
    }
    structure = {"questions": [{
        "question_id": "6.1",
        "mark_points": [{"count": 1, "code": "A", "descriptor": "state the formula"}],
    }]}
    program = (
        "const humanCategory=value=>String(value||'').replaceAll('_',' ');\n"
        + _section("SEMANTIC CONFLICT MODEL")
        + "\nconst ex=JSON.parse(process.argv[1]);const model=semanticConflictModel(ex,ex.suggestions[0],JSON.parse(process.argv[2]));"
        + "\nconsole.log(JSON.stringify(semanticConflictPresentation(model)));"
    )
    result = _run_node(program, exception, structure)
    assert result["suggested_choice"] == "Use F — Formula"
    assert result["entered_choice"] == "Keep A — Accuracy"


def test_submit_endpoint_blocks_a_second_pending_correction_for_the_whole_job():
    source = (ROOT / "supabase" / "functions" / "submit-correction" / "index.ts").read_text(encoding="utf-8")
    pending_start = source.index('from("corrections").select("id,exception_id")')
    pending_end = source.index("if (active?.length)", pending_start)
    pending_query = source[pending_start:pending_end]
    assert '.eq("job_id", jobId)' in pending_query
    assert '.eq("exception_id", exceptionId)' not in pending_query
