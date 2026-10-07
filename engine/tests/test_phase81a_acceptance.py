from __future__ import annotations

import copy
import inspect
from pathlib import Path

import pytest

from engine.src.memo_engine import acceptance
from engine.src.memo_engine.acceptance import (
    AcceptanceFailure,
    ReadOnlySupabase,
    _assert_sanitized_report,
    _ephemeral_geometry_correction,
    _media_acceptance,
    _open_exceptions,
    _require,
)
from engine.src.memo_engine.corrections import apply_confirmed_corrections


JOB_ID = "bc6201e2-eecf-4d95-94f4-36eeca62defe"
BASE_URL = "https://njrqiurqljwtuqrvguhj.supabase.co"


def _exception() -> dict:
    return {
        "status": "open",
        "level": "amber",
        "category": "geometry_line_relationship_conflict",
        "affected_ids": ["3.2"],
    }


def _q32_canonical() -> dict:
    return {
        "audit": {"job_id": JOB_ID},
        "questions": [{
            "number": "3",
            "items": [{
                "number": "3.2",
                "children": [],
                "alternatives": [{"blocks": [
                    {"type": "math", "math": {"plain_text": "mBC × mAB = -1"}},
                    {"type": "prose", "text": "BC perpendicular BC"},
                    {"type": "prose", "text": "Unchanged explanation"},
                ]}],
            }],
        }],
    }


def test_read_only_client_exposes_no_mutating_api():
    client = ReadOnlySupabase(BASE_URL, "test-secret")
    for name in (
        "patch_job", "add_event", "add_exceptions", "upload_object",
        "upload_json", "mark_corrections_applied",
        "supersede_unresolved_exceptions",
    ):
        assert not hasattr(client, name)


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_read_only_client_rejects_write_http_verbs(method, monkeypatch):
    client = ReadOnlySupabase(BASE_URL, "test-secret")
    opened = False

    def unexpected(*args, **kwargs):
        nonlocal opened
        opened = True

    monkeypatch.setattr("urllib.request.urlopen", unexpected)
    with pytest.raises(AcceptanceFailure, match=f"READ_ONLY_HTTP_METHOD_REJECTED:{method}"):
        client._request_bytes(method, "/rest/v1/jobs")
    assert opened is False


def test_read_only_client_rejects_another_project():
    with pytest.raises(AcceptanceFailure, match="ACCEPTANCE_PROJECT_REF_MISMATCH"):
        ReadOnlySupabase("https://kxhcbpuhqaxmkphfqfol.supabase.co", "test-secret")


def test_acceptance_module_does_not_import_or_call_production_lifecycle():
    source = inspect.getsource(acceptance)
    assert "SupabaseRest" not in source
    for mutation in (
        ".patch_job(", ".add_event(", ".add_exceptions(",
        ".upload_object(", ".upload_json(", ".mark_corrections_applied(",
    ):
        assert mutation not in source


def test_real_confirmed_correction_replays_only_in_memory():
    structure = {
        "questions": [{
            "question_id": "3.2", "path": [3, 2], "depth": 2,
            "source_block_index": 4, "printed_marks": 0,
            "computed_shorthand_marks": 0, "mark_points": [],
        }],
        "exceptions": [{
            "category": "geometry_line_relationship_conflict",
            "affected_id": "3.2",
        }],
    }
    correction = {
        "id": "confirmed-1", "confirmation_status": "confirmed",
        "confirmed_at": "2026-01-01T00:00:00Z",
        "proposed_patch": {
            "operation": "replace_item_content",
            "category": "geometry_line_relationship_conflict",
            "affected_id": "3.2", "target_id": "3.2",
            "question_text": None,
            "solution_lines": ["BC perpendicular AB"],
        },
    }
    original = copy.deepcopy(structure)
    replayed, applied, issues = apply_confirmed_corrections(
        structure, {}, [correction]
    )
    assert issues == []
    assert len(applied) == 1
    assert replayed["questions"][0]["content_override"]["solution_lines"] == ["BC perpendicular AB"]
    assert structure == original


def test_pass1_geometry_review_is_bounded_to_q32():
    canonical = {"status": "needs_review", "exceptions": [_exception()]}
    found = _open_exceptions(canonical)
    assert len(found) == 1
    assert found[0]["category"] == "geometry_line_relationship_conflict"
    assert found[0]["affected_ids"] == ["3.2"]


def test_ephemeral_fix_uses_replace_item_content_and_preserves_other_lines():
    correction = _ephemeral_geometry_correction(_q32_canonical())
    patch = correction["proposed_patch"]
    assert correction["confirmation_status"] == "confirmed"
    assert patch["operation"] == "replace_item_content"
    assert patch["affected_id"] == "3.2"
    assert patch["solution_lines"] == [
        "mBC × mAB = -1", "BC perpendicular AB", "Unchanged explanation"
    ]


def test_ephemeral_fix_resolves_only_intended_geometry_issue():
    canonical = _q32_canonical()
    correction = _ephemeral_geometry_correction(canonical)
    assert correction["id"] == "phase81a-ephemeral-q32"
    assert canonical == _q32_canonical()
    assert correction["proposed_patch"]["category"] == "geometry_line_relationship_conflict"


def _media_fixture():
    roles = [
        ("Q1", "s1", "substantive_figure"),
        ("2.1", "s2", "substantive_figure"),
        ("Q3", "s3", "substantive_figure"),
        ("Q4", "s4", "substantive_figure"),
        ("Q5", "s5", "substantive_figure"),
        ("6.1", "s6", "substantive_figure"),
        ("9.1", "s7", "substantive_figure"),
        ("Q5", "c1", "contextual_raster"),
        ("Q5", "c2", "contextual_raster"),
        ("Q9", "c3", "contextual_raster"),
    ]
    entities = [
        {"asset_id": asset_id, "media_class": media_class}
        for _, asset_id, media_class in roles
    ]
    assets = []
    figures = []
    for index, (owner, asset_id, media_class) in enumerate(roles):
        anchor = {
            "unit_index": 0, "row_index": index, "cell_index": 0,
            "paragraph_index": index, "drawing_order": 0,
        }
        assets.append({
            "asset_id": asset_id, "media_class": media_class,
            "source_anchor": {**anchor, "page": 1},
        })
        figures.append({
            "owner": owner, "asset_id": asset_id, "media_class": media_class,
            "source_refs": [{"docx_anchor": anchor}],
        })
    normalized = {"content": {"media_entities": entities}}
    canonical = {
        "source": {"assets": assets},
        "questions": [],
        "_test_figures": figures,
        "_test_q61": {"correction_origin": {"source_block_index": None}},
    }
    return normalized, canonical, figures


def test_media_context_acceptance_conditions(monkeypatch):
    normalized, canonical, figures = _media_fixture()
    monkeypatch.setattr(acceptance, "_figure_ownership", lambda value: figures)
    monkeypatch.setattr(acceptance, "_find_item", lambda value, number: value["_test_q61"])
    result = _media_acceptance(normalized, canonical)
    assert result["normalized_media_count"] == 10
    assert result["substantive_figure_count"] == 7
    assert result["required_figure_roles_present"] is True
    assert result["duplicate_ownership"] is False


def test_pass2_total_and_render_ready_contract():
    replay = {
        "canonical": {
            "status": "render_ready", "exceptions": [],
            "totals": {"computed": 150},
        },
        "validation": {"passed": True},
    }
    assert _open_exceptions(replay["canonical"]) == []
    assert replay["canonical"]["totals"]["computed"] == 150
    assert replay["canonical"]["status"] == "render_ready"
    assert replay["validation"]["passed"] is True


def test_sanitized_report_rejects_source_text_and_secret_markers():
    safe = {
        "source_job_id": JOB_ID,
        "pass1": {"exception_categories": ["geometry_line_relationship_conflict"]},
    }
    _assert_sanitized_report(safe)
    with pytest.raises(AcceptanceFailure, match="SANITIZED_REPORT_FORBIDDEN_FIELD"):
        _assert_sanitized_report({"source_text": "learner content"})
    with pytest.raises(AcceptanceFailure, match="SANITIZED_REPORT_SECRET_MARKER"):
        _assert_sanitized_report({"value": "sb_secret_example"})


def test_post_run_immutability_comparison_detects_mutation():
    before = {
        "job": {"status": "complete", "updated_at": "before"},
        "corrections": [{"id": "one"}], "events": [{"id": 1}],
        "output_hashes": {"docx": "a", "pdf": "b"},
    }
    after = copy.deepcopy(before)
    after["events"].append({"id": 2})
    with pytest.raises(AcceptanceFailure, match="LIVE_SOURCE_MUTATION_DETECTED"):
        _require(before == after, "LIVE_SOURCE_MUTATION_DETECTED")


def test_workflow_uses_dedicated_acceptance_command_only():
    workflow = Path(".github/workflows/phase81a-acceptance.yml").read_text(encoding="utf-8")
    assert "memo_engine.acceptance phase81a-replay" in workflow
    assert "memo_engine.cli run-job" not in workflow
    assert "process-memo" not in workflow
    assert "upload-artifact" not in workflow
