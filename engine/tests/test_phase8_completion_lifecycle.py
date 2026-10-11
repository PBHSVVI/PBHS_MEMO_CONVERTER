from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "engine" / "src" / "memo_engine" / "cli.py"
PAGE = ROOT / "docs" / "phase7-5-review" / "index.html"


def _section(name: str) -> str:
    html = PAGE.read_text(encoding="utf-8")
    start = html.index(f"// BEGIN {name}")
    end = html.index(f"// END {name}", start)
    return html[start:end]


def _node(program: str) -> str:
    result = subprocess.run(
        ["node", "--input-type=module", "--eval", program],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def test_worker_sets_completed_at_in_final_success_patch():
    source = CLI.read_text(encoding="utf-8")
    final_transition = source[source.index("        completed_at = utc_now()") :]
    assert '"status": "complete",\n                "stage": "complete"' in final_transition
    assert '"completed_at": completed_at,\n                "updated_at": completed_at' in final_transition


def test_non_success_paths_do_not_set_completed_at():
    source = CLI.read_text(encoding="utf-8")
    assert source.count('"completed_at"') == 2
    before_final = source[: source.index("        completed_at = utc_now()")]
    assert '"completed_at": completed_at' not in before_final
    needs_review = source[source.index("        if review_required:") : source.index("        # Record the successful Phase 5 handoff")]
    assert '"status": final_status' in needs_review
    assert '"completed_at"' not in needs_review
    failure_path = source[source.index("def fail_processing_job"):source.index("def _semantic_signature")]
    assert '"completed_at"' not in failure_path


def test_worker_start_clears_stale_completed_at_for_reprocessing_safety():
    source = CLI.read_text(encoding="utf-8")
    start_transition = source[source.index("    started_at = utc_now()") : source.index("    db.add_event(job, \"worker_started\"")]
    assert '"status": "processing",\n            "stage": "ingestion"' in start_transition
    assert '"started_at": started_at,\n            "completed_at": None' in start_transition


def test_poll_model_caps_delay_and_completion_ignores_completed_at():
    model = _section("PROCESSING POLL MODEL")
    program = (
        "const document={visibilityState:'hidden',addEventListener(){}};"
        "let monitorPromise=null,processingPollWake=null;\n"
        + model
        + "\nconsole.log(JSON.stringify({"
        "cap:nextProcessingPollDelay(15000),"
        "complete:processingComplete({status:'complete',completed_at:null}),"
        "notComplete:processingComplete({status:'processing',completed_at:'stale'})"
        "}));"
    )
    assert _node(program) == '{"cap":6000,"complete":true,"notComplete":false}'


def test_visibility_regain_wakes_existing_poll_once_without_a_second_loop():
    model = _section("PROCESSING POLL MODEL")
    program = (
        "let listener=null;"
        "const document={visibilityState:'hidden',addEventListener(_name,fn){listener=fn}};"
        "let monitorPromise=Promise.resolve(),processingPollWake=null;\n"
        + model
        + "\nlet resolved=0;const waiting=waitForProcessingPoll(10000).then(()=>resolved++);"
        "document.visibilityState='visible';listener();listener();await waiting;"
        "console.log(JSON.stringify({resolved,wakeCleared:processingPollWake===null}));"
    )
    assert _node(program) == '{"resolved":1,"wakeCleared":true}'


def test_processing_monitor_stops_timer_after_complete_observation():
    html = PAGE.read_text(encoding="utf-8")
    monitor = html[html.index("function monitorProcessing") : html.index("// END RESILIENT PROCESSING MODEL")]
    assert "await waitStable()" in monitor
    assert "clearInterval(processingTimer)" in monitor
    assert "processingTimer=null" in monitor
    assert "if(monitorPromise)return monitorPromise" in monitor
