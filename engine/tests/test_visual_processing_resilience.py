from __future__ import annotations

import copy
import io
import urllib.error
from email.message import Message
from pathlib import Path

import pytest

from engine.src.memo_engine.ai_router import ProviderError, _post_json
from engine.src.memo_engine.cli import finalize_interrupted_job
from engine.src.memo_engine import cli, visual_evidence


ROOT = Path(__file__).resolve().parents[2]


def _normalized() -> dict:
    return {
        "job_id": "job-visual",
        "source": {"sha256": "sha"},
        "content": {
            "pages": [
                {"page_number": 1, "visual_inspection_required": True},
                {"page_number": 2, "visual_inspection_required": True},
            ]
        },
    }


def _regions(count: int) -> list[dict]:
    return [
        {
            "page": 1 + (index // 2),
            "question_refs": [f"{index + 1}.1"],
            "printed_text": "",
            "image_bytes": f"image-{index}".encode(),
            "mime_type": "image/png",
            "asset_path": f"internal/visual/regions/region-{index + 1}.png",
        }
        for index in range(count)
    ]


def _success(region: dict, _model: str) -> dict:
    return {
        "schema_version": "1.0",
        "page": region["page"],
        "visual_content_present": False,
        "evidence": [],
        "mark_changes": [],
        "warnings": [],
        "provider": "groq",
        "model": "test-vision",
        "elapsed_ms": 5,
        "usage": {},
    }


def test_each_visual_region_emits_reading_and_completed_heartbeats(monkeypatch):
    monkeypatch.setattr(visual_evidence, "_render_regions", lambda *_: _regions(21))
    events = []

    record, _ = visual_evidence.extract_visual_evidence(
        b"source",
        _normalized(),
        runner=_success,
        progress_callback=lambda payload: events.append(payload),
    )

    assert len(events) == 42
    assert events[0] == {
        "status": "processing", "region_index": 1, "region_count": 21,
        "page": 1, "question_refs": ["1.1"],
    }
    assert events[-1]["status"] == "success"
    assert events[-1]["region_index"] == 21
    assert all(item["region_count"] == 21 for item in events)
    assert record["summary"]["success_count"] == 21


def test_one_vision_timeout_defers_without_teacher_review_flood(monkeypatch):
    monkeypatch.setattr(visual_evidence, "_render_regions", lambda *_: _regions(2))
    calls = []

    def one_timeout(region, model):
        calls.append(region["asset_path"])
        if len(calls) == 1:
            raise ProviderError("AI_PROVIDER_NETWORK_ERROR", "timed out", retryable=True)
        return _success(region, model)

    record, _ = visual_evidence.extract_visual_evidence(
        b"source", _normalized(), runner=one_timeout
    )
    fused = visual_evidence.fuse_visual_evidence(
        {"questions": [], "exceptions": [], "summary": {}}, record
    )

    assert len(calls) == 1
    assert record["summary"]["failure_count"] == 0
    assert record["summary"]["infrastructure_deferred"] is True
    assert record["summary"]["unprocessed_count"] == 2
    assert fused["exceptions"] == []


def test_visual_request_uses_its_bounded_timeout(monkeypatch):
    observed = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{}'

    def urlopen(_request, timeout):
        observed["timeout"] = timeout
        return Response()

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    _post_json("https://example.invalid", {}, {}, timeout_seconds=45)
    assert observed["timeout"] == 45


def test_success_response_exposes_only_normalized_rate_metadata(monkeypatch):
    class Response:
        headers = Message()
        headers["x-ratelimit-limit-requests"] = "30"
        headers["x-ratelimit-remaining-requests"] = "0"
        headers["x-ratelimit-reset-requests"] = "3m2.5s"
        headers["authorization"] = "must-not-leak"

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{"ok":true}'

    monkeypatch.setattr("urllib.request.urlopen", lambda *_args, **_kwargs: Response())
    payload, _ = _post_json("https://example.invalid", {}, {})
    assert payload["_provider_rate_limits"] == {
        "limit_requests": 30,
        "remaining_requests": 0,
        "reset_requests_seconds": 182.5,
    }
    assert "authorization" not in str(payload).lower()


def test_visual_phase_budget_defers_remaining_regions_without_review(monkeypatch):
    monkeypatch.setattr(visual_evidence, "_render_regions", lambda *_: _regions(3))
    values = iter([0.0, 1.0, 16.0, 16.0])
    calls = []

    record, _ = visual_evidence.extract_visual_evidence(
        b"source",
        _normalized(),
        runner=lambda region, model: calls.append(region) or _success(region, model),
        phase_timeout_seconds=15,
        clock=lambda: next(values),
    )

    assert len(calls) == 1
    assert record["summary"]["success_count"] == 1
    assert record["summary"]["failure_count"] == 0
    assert record["summary"]["unprocessed_count"] == 2
    assert record["warnings"] == []
    fused = visual_evidence.fuse_visual_evidence(
        {"questions": [], "exceptions": [], "summary": {}}, record
    )
    assert fused["exceptions"] == []


def test_transport_failure_opens_provider_circuit_without_fabricated_region_runs(monkeypatch):
    monkeypatch.setattr(visual_evidence, "_render_regions", lambda *_: _regions(6))
    calls = []

    def unavailable(region, _model):
        calls.append(region)
        raise ProviderError("AI_PROVIDER_NETWORK_ERROR", "unavailable", retryable=True)

    record, _ = visual_evidence.extract_visual_evidence(
        b"source", _normalized(), runner=unavailable
    )

    assert len(calls) == 1
    assert record["summary"]["failure_count"] == 0
    assert record["summary"]["unprocessed_count"] == 6
    assert len(record["runs"]) == 1
    assert record["provider_state"]["circuits"][0]["provider"] == "groq"


def test_partial_success_is_checkpointed_before_later_failure(monkeypatch):
    monkeypatch.setattr(visual_evidence, "_render_regions", lambda *_: _regions(2))
    checkpoints = []
    call_count = 0

    def mixed(region, model):
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise ProviderError("AI_PROVIDER_NETWORK_ERROR", "unavailable")
        result = _success(region, model)
        result["visual_content_present"] = True
        result["evidence"] = [{
            "question_ref": "1.1", "kind": "answer", "transcription": "x=2",
            "normalized_math": "x=2", "confidence": 0.95,
            "source": "visual_overlay", "bbox": None,
        }]
        return result

    record, _ = visual_evidence.extract_visual_evidence(
        b"source",
        _normalized(),
        runner=mixed,
        checkpoint_callback=lambda partial, artifact: checkpoints.append(
            (copy.deepcopy(partial), artifact["path"])
        ),
    )

    assert len(checkpoints) == 2
    assert checkpoints[0][0]["evidence"][0]["transcription"] == "x=2"
    assert checkpoints[0][1].endswith("region-1.png")
    assert record["summary"]["success_count"] == 1
    assert record["summary"]["failure_count"] == 0
    assert record["summary"]["infrastructure_deferred"] is True


def test_retry_reuses_successful_checkpoint_and_retries_failed_region(monkeypatch):
    monkeypatch.setattr(visual_evidence, "_render_regions", lambda *_: _regions(2))
    checkpoint = {
        "schema_version": "1.0",
        "ownership_algorithm_version": visual_evidence.OWNERSHIP_ALGORITHM_VERSION,
        "source_sha256": "sha",
        "evidence": [{"question_ref": "1.1", "transcription": "saved"}],
        "mark_changes": [],
        "warnings": [{"code": "AI_PROVIDER_NETWORK_ERROR"}],
        "runs": [
            {
                "success": True,
                "rendered_asset_ref": "internal/visual/regions/region-1.png",
                "page": 1,
            },
            {
                "success": False,
                "rendered_asset_ref": "internal/visual/regions/region-2.png",
                "page": 1,
            },
        ],
        "summary": {"visual_content_count": 1},
    }
    called = []
    progress = []

    record, _ = visual_evidence.extract_visual_evidence(
        b"source",
        _normalized(),
        runner=lambda region, model: called.append(region["asset_path"]) or _success(region, model),
        checkpoint_record=checkpoint,
        progress_callback=lambda payload: progress.append(payload),
    )

    assert called == ["internal/visual/regions/region-2.png"]
    assert progress[0]["status"] == "checkpointed"
    assert record["summary"]["success_count"] == 2
    assert record["summary"]["failure_count"] == 0
    assert record["summary"]["partial_checkpoint_reuse"] is True
    assert record["summary"]["reused_success_count"] == 1
    assert record["summary"]["retried_region_count"] == 1
    assert record["summary"]["new_success_count"] == 1
    assert record["summary"]["new_failure_count"] == 0
    assert record["retry_history"][0]["rendered_asset_ref"].endswith("region-2.png")
    assert not any(item.get("code") == "AI_PROVIDER_NETWORK_ERROR" for item in record["warnings"])


def test_mixed_success_and_retryable_failure_is_partial_not_full_cache():
    candidate = {
        "schema_version": "1.0",
        "ownership_algorithm_version": visual_evidence.OWNERSHIP_ALGORITHM_VERSION,
        "source_sha256": "sha",
        "evidence": [],
        "mark_changes": [],
        "runs": [
            {"success": True, "rendered_asset_ref": "one.png"},
            {"success": False, "error_code": "AI_PROVIDER_RATE_LIMITED", "rendered_asset_ref": "two.png"},
        ],
        "summary": {"regions_rendered": 2, "pages_flagged": 1},
    }
    assert visual_evidence.visual_checkpoint_is_compatible(candidate, "sha")
    assert not visual_evidence.visual_cache_is_complete(candidate, "sha")


@pytest.mark.parametrize("failure_code", ["AI_PROVIDER_RATE_LIMITED", "VISUAL_PHASE_BUDGET_EXCEEDED"])
def test_retryable_cached_failure_is_attempted_again(monkeypatch, failure_code):
    monkeypatch.setattr(visual_evidence, "_render_regions", lambda *_: _regions(1))
    checkpoint = {
        "schema_version": "1.0",
        "ownership_algorithm_version": visual_evidence.OWNERSHIP_ALGORITHM_VERSION,
        "source_sha256": "sha",
        "evidence": [], "mark_changes": [], "warnings": [],
        "runs": [{"success": False, "error_code": failure_code, "rendered_asset_ref": "internal/visual/regions/region-1.png"}],
        "summary": {"regions_rendered": 1, "pages_flagged": 1},
    }
    called = []
    record, _ = visual_evidence.extract_visual_evidence(
        b"source", _normalized(),
        runner=lambda region, model: called.append(region["asset_path"]) or _success(region, model),
        checkpoint_record=checkpoint,
    )
    assert called == ["internal/visual/regions/region-1.png"]
    assert record["summary"]["new_success_count"] == 1
    assert record["retry_history"][0]["error_code"] == failure_code


def test_complete_success_or_deterministic_failure_can_be_full_cache():
    candidate = {
        "schema_version": "1.0",
        "ownership_algorithm_version": visual_evidence.OWNERSHIP_ALGORITHM_VERSION,
        "source_sha256": "sha",
        "evidence": [],
        "mark_changes": [],
        "runs": [
            {"success": True, "rendered_asset_ref": "one.png"},
            {"success": False, "error_code": "VISUAL_INVALID_RESPONSE", "rendered_asset_ref": "two.png"},
        ],
        "summary": {"regions_rendered": 2, "pages_flagged": 1},
    }
    assert visual_evidence.visual_cache_is_complete(candidate, "sha")
    candidate["runs"][1] = {"success": True, "rendered_asset_ref": "two.png"}
    assert visual_evidence.visual_cache_is_complete(candidate, "sha")


def test_exhausted_rate_limit_defers_without_fabricating_unread_regions(monkeypatch):
    monkeypatch.setattr(visual_evidence, "_render_regions", lambda *_: _regions(6))
    calls = []

    def saturated(region, _model):
        calls.append(region)
        raise ProviderError(
            "AI_PROVIDER_RATE_LIMITED",
            "provider remains saturated",
            provider_saturated=True,
        )

    record, _ = visual_evidence.extract_visual_evidence(
        b"source", _normalized(), runner=saturated
    )

    assert len(calls) == 1
    assert record["runs"][0]["error_code"] == "AI_PROVIDER_RATE_LIMITED"
    assert len(record["runs"]) == 1
    assert record["summary"]["unprocessed_count"] == 6
    fused = visual_evidence.fuse_visual_evidence(
        {"questions": [], "exceptions": [], "summary": {}}, record
    )
    assert fused["exceptions"] == []


def test_twenty_one_region_rate_limit_preserves_first_and_does_not_flood_review(monkeypatch):
    monkeypatch.setattr(visual_evidence, "_render_regions", lambda *_: _regions(21))
    calls = []

    def one_then_rate_limit(region, model):
        calls.append(region["asset_path"])
        if len(calls) == 2:
            raise ProviderError(
                "AI_PROVIDER_RATE_LIMITED",
                "capacity",
                retry_after_seconds=120,
                provider_saturated=True,
                category="transient_capacity",
                http_status=429,
            )
        return _success(region, model)

    record, _ = visual_evidence.extract_visual_evidence(
        b"source", _normalized(), runner=one_then_rate_limit
    )
    fused = visual_evidence.fuse_visual_evidence(
        {"questions": [], "exceptions": [], "summary": {}}, record
    )

    assert calls == [
        "internal/visual/regions/region-1.png",
        "internal/visual/regions/region-2.png",
    ]
    assert record["summary"]["success_count"] == 1
    assert record["summary"]["unprocessed_count"] == 20
    assert record["runs"][0]["crop_digest"]
    assert record["runs"][0]["result_digest"]
    assert fused["exceptions"] == []


def test_short_retry_after_retries_without_real_sleep(monkeypatch):
    headers = Message()
    headers["retry-after"] = "1"
    calls = 0
    sleeps = []

    class Response:
        headers = Message()

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{"ok":true}'

    def urlopen(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise urllib.error.HTTPError(
                "https://example.invalid", 429, "rate limited", headers, io.BytesIO(b"{}")
            )
        return Response()

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    payload, _ = _post_json(
        "https://example.invalid", {}, {},
        sleeper=lambda seconds: sleeps.append(seconds),
        jitter=lambda *_: 0.0,
        max_rate_retries=1,
    )
    assert payload["ok"] is True
    assert calls == 2
    assert sleeps == [2.5]


def test_transient_503_retries_without_real_sleep(monkeypatch):
    calls = 0
    sleeps = []

    class Response:
        headers = Message()

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{"ok":true}'

    def urlopen(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise urllib.error.HTTPError(
                "https://example.invalid", 503, "capacity", Message(), io.BytesIO(b"{}")
            )
        return Response()

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    payload, _ = _post_json(
        "https://example.invalid", {}, {},
        sleeper=lambda seconds: sleeps.append(seconds),
        jitter=lambda *_: 0.0,
        max_transient_retries=1,
    )
    assert payload["ok"] is True
    assert calls == 2
    assert sleeps == [1.0]


def test_long_rate_reset_from_success_headers_defers_before_next_call(monkeypatch):
    monkeypatch.setattr(visual_evidence, "_render_regions", lambda *_: _regions(3))
    calls = []

    def exhausted_after_success(region, model):
        calls.append(region["asset_path"])
        result = _success(region, model)
        result["rate_limits"] = {
            "remaining_requests": 0,
            "reset_requests_seconds": 180,
        }
        return result

    record, _ = visual_evidence.extract_visual_evidence(
        b"source", _normalized(), runner=exhausted_after_success
    )
    assert calls == ["internal/visual/regions/region-1.png"]
    assert record["summary"]["success_count"] == 1
    assert record["summary"]["unprocessed_count"] == 2
    assert record["provider_state"]["circuits"][0]["retry_after_seconds"] == 180


def test_partial_cache_reuses_seven_successes_after_rate_limit(monkeypatch):
    monkeypatch.setattr(visual_evidence, "_render_regions", lambda *_: _regions(10))
    first_calls = []

    def first_attempt(region, model):
        first_calls.append(region["asset_path"])
        if len(first_calls) == 8:
            raise ProviderError(
                "AI_PROVIDER_RATE_LIMITED", "capacity",
                retry_after_seconds=120, category="transient_capacity",
            )
        return _success(region, model)

    first, _ = visual_evidence.extract_visual_evidence(
        b"source", _normalized(), runner=first_attempt
    )
    second_calls = []
    second, _ = visual_evidence.extract_visual_evidence(
        b"source", _normalized(),
        runner=lambda region, model: second_calls.append(region["asset_path"]) or _success(region, model),
        checkpoint_record=first,
    )
    assert len(first_calls) == 8
    assert second_calls == [
        "internal/visual/regions/region-8.png",
        "internal/visual/regions/region-9.png",
        "internal/visual/regions/region-10.png",
    ]
    assert second["summary"]["reused_success_count"] == 7
    assert second["summary"]["success_count"] == 10
    assert second["summary"]["infrastructure_deferred"] is False


def test_genuine_unread_content_remains_one_teacher_review_item(monkeypatch):
    monkeypatch.setattr(visual_evidence, "_render_regions", lambda *_: _regions(2))
    calls = []

    def unread_then_success(region, model):
        calls.append(region["asset_path"])
        if len(calls) == 1:
            raise visual_evidence.VisualEvidenceError(
                "VISUAL_SOURCE_UNREAD", "The crop is genuinely unreadable."
            )
        return _success(region, model)

    record, _ = visual_evidence.extract_visual_evidence(
        b"source", _normalized(), runner=unread_then_success
    )
    fused = visual_evidence.fuse_visual_evidence(
        {"questions": [], "exceptions": [], "summary": {}}, record
    )
    assert len(calls) == 2
    assert record["summary"]["content_failure_count"] == 1
    assert [item["category"] for item in fused["exceptions"]] == ["visual_evidence_unread"]


def test_auth_failure_is_infrastructure_not_teacher_review(monkeypatch):
    monkeypatch.setattr(visual_evidence, "_render_regions", lambda *_: _regions(4))

    def auth_failure(_region, _model):
        raise ProviderError(
            "AI_PROVIDER_AUTH_CONFIGURATION_FAILED",
            "credential invalid",
            retryable=False,
            category="auth_configuration",
            http_status=401,
        )

    record, _ = visual_evidence.extract_visual_evidence(
        b"source", _normalized(), runner=auth_failure
    )
    fused = visual_evidence.fuse_visual_evidence(
        {"questions": [], "exceptions": [], "summary": {}}, record
    )
    assert record["provider_state"]["status"] == "configuration_failed"
    assert record["summary"]["unprocessed_count"] == 4
    assert fused["exceptions"] == []
    assert "credential invalid" not in str(record)


def test_non_retryable_bad_crop_affects_only_that_region(monkeypatch):
    monkeypatch.setattr(visual_evidence, "_render_regions", lambda *_: _regions(3))
    calls = []

    def bad_crop(region, model):
        calls.append(region["asset_path"])
        if len(calls) == 2:
            raise ProviderError(
                "AI_PROVIDER_REQUEST_REJECTED",
                "bad crop",
                retryable=False,
                category="content_request",
                http_status=400,
            )
        return _success(region, model)

    record, _ = visual_evidence.extract_visual_evidence(
        b"source", _normalized(), runner=bad_crop
    )
    fused = visual_evidence.fuse_visual_evidence(
        {"questions": [], "exceptions": [], "summary": {}}, record
    )
    assert len(calls) == 3
    assert record["summary"]["success_count"] == 2
    assert record["summary"]["content_failure_count"] == 1
    assert len(fused["exceptions"]) == 1


def test_retry_after_that_cannot_serve_remaining_regions_skips_wait(monkeypatch):
    headers = Message()
    headers["retry-after"] = "120"

    def rate_limited(*_args, **_kwargs):
        raise urllib.error.HTTPError(
            "https://example.invalid", 429, "rate limited", headers, io.BytesIO(b"{}")
        )

    monkeypatch.setattr("urllib.request.urlopen", rate_limited)
    sleeps = []
    clock_values = iter([0.0, 0.0])

    with pytest.raises(ProviderError, match="remaining visual processing budget") as caught:
        _post_json(
            "https://example.invalid",
            {},
            {},
            timeout_seconds=45,
            deadline_monotonic=180,
            remaining_requests=16,
            clock=lambda: next(clock_values),
            sleeper=lambda seconds: sleeps.append(seconds),
        )

    assert caught.value.code == "AI_PROVIDER_RATE_LIMITED"
    assert caught.value.provider_saturated is True
    assert caught.value.retry_after_seconds == pytest.approx(120)
    assert sleeps == []


def test_stale_pre_ownership_checkpoint_is_not_reused(monkeypatch):
    monkeypatch.setattr(visual_evidence, "_render_regions", lambda *_: _regions(1))
    checkpoint = {
        "schema_version": "1.0",
        "source_sha256": "sha",
        "evidence": [{"question_ref": "1.1", "transcription": "legacy"}],
        "mark_changes": [],
        "warnings": [],
        "runs": [{
            "success": True,
            "rendered_asset_ref": "internal/visual/regions/region-1.png",
            "page": 1,
        }],
        "summary": {"visual_content_count": 1},
    }
    calls = []

    visual_evidence.extract_visual_evidence(
        b"source",
        _normalized(),
        runner=lambda region, model: calls.append(region["asset_path"]) or _success(region, model),
        checkpoint_record=checkpoint,
    )

    assert calls == ["internal/visual/regions/region-1.png"]


class _FinalizerDatabase:
    def __init__(self, status="processing", stage="visual_evidence"):
        self.job = {"id": "job", "user_id": "user", "status": status, "stage": stage}
        self.patch = None
        self.event = None

    def get_job(self, _job_id):
        return self.job

    def patch_job(self, job_id, expected_status, values):
        assert expected_status == "processing"
        self.patch = values
        return {**self.job, **values}

    def add_event(self, _job, event_type, stage, payload):
        self.event = (event_type, stage, payload)


def test_worker_finalizer_recovers_only_still_processing_visual_job(monkeypatch):
    database = _FinalizerDatabase()
    monkeypatch.setattr(cli, "SupabaseRest", lambda: database)
    assert finalize_interrupted_job("job") == 0
    assert database.patch["status"] == "failed_retryable"
    assert database.patch["stage"] == "visual_evidence_failed"
    assert database.patch["error_code"] == "VISUAL_PROCESSING_TIMEOUT"
    assert database.event[0] == "worker_failed"


@pytest.mark.parametrize("status", ["complete", "needs_review", "failed_retryable"])
def test_worker_finalizer_never_overwrites_terminal_or_review_state(monkeypatch, status):
    database = _FinalizerDatabase(status=status)
    monkeypatch.setattr(cli, "SupabaseRest", lambda: database)
    assert finalize_interrupted_job("job") == 0
    assert database.patch is None
    assert database.event is None


def test_hosted_workflow_bounds_worker_and_always_runs_finalizer():
    workflow = (ROOT / ".github" / "workflows" / "process-memo.yml").read_text(
        encoding="utf-8"
    )
    assert 'MEMO_VISUAL_PHASE_TIMEOUT_SECONDS: "900"' in workflow
    assert 'MEMO_GROQ_VISION_REQUEST_TIMEOUT_SECONDS: "45"' in workflow
    assert "id: hosted_worker\n        timeout-minutes: 38" in workflow
    assert "always() && steps.hosted_worker.outcome != 'success'" in workflow
    assert "finalize-interrupted-job" in workflow


def test_worker_persists_visual_stage_heartbeats_and_private_checkpoint():
    source = (ROOT / "engine" / "src" / "memo_engine" / "cli.py").read_text(
        encoding="utf-8"
    )
    visual_section = source[
        source.index('"stage": "visual_evidence"'):
        source.index('job = db.patch_job(\n            job_id,\n            "processing",\n            {"stage": "structure"')
    ]
    assert visual_section.index("phase2_visual_evidence_started") < visual_section.index(
        "extract_visual_evidence("
    )
    assert "phase2_visual_region_progress" in visual_section
    assert "internal/visual/evidence.checkpoint.json" in visual_section
    assert "checkpoint_record=visual_checkpoint_record" in visual_section
