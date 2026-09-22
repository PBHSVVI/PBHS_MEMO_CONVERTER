#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

EXPECTED_BLOB_SHAS = {
    "engine/src/memo_engine/corrections.py": "14441f2cd753c6592ac4e5703ef110fa2364828c",
    "engine/src/memo_engine/correction_reinterpretation.py": "db68c3708cf061c5e1777b0cb162bbe51d21c2dd",
    "engine/src/memo_engine/cli.py": "d9c85a65d6b9f377a1c2efac91d9663781b76412",
    ".github/workflows/process-memo.yml": "5a0f2dad961ed46370b80691d20990230aa2889d",
}

VALIDATION_ONLY_BLOB_SHAS = {
    "engine/src/memo_engine/structure.py": "ac7373a0f7ff7cd1a49571235dae852cd12e6a5a",
    "engine/src/memo_engine/canonical.py": "12912e37845c38edf55acca3072383f0e725ce11",
    "supabase/functions/submit-correction/index.ts": "40be87a901f78be79805189e0a08c51137d15e13",
    "supabase/functions/confirm-correction/index.ts": "484a64322427476d7c05c94ab92ec2d6276e0223",
}

NEW_FILES = {
    "engine/src/memo_engine/phase7_5.py": "patch_payload/engine/src/memo_engine/phase7_5.py",
    "engine/tests/test_phase7_5_raw_categories.py": "patch_payload/engine/tests/test_phase7_5_raw_categories.py",
}


def git_blob_sha(data: bytes) -> str:
    header = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data).hexdigest()


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one anchor, found {count}")
    return text.replace(old, new, 1)


def stage_corrections(text: str) -> str:
    text = replace_once(
        text,
        ")\n\nQUESTION_ID_RE = re.compile",
        ")\nfrom .phase7_5 import apply_phase7_5_patch\n\nQUESTION_ID_RE = re.compile",
        "corrections import",
    )
    text = replace_once(
        text,
        'elif category in {"numbering_jump", "suspicious_question_identifier"} and operation in {"accept_suggestion", "rename_question_identifier"} and target_id:',
        'elif category in {"numbering_jump", "suspicious_question_identifier", "scored_major_precedes_subquestions"} and operation in {"accept_suggestion", "rename_question_identifier"} and target_id:',
        "corrections rename dispatcher",
    )
    old = '''        else:\n            issue = _issue(\n                "correction_application_unsupported",\n                str(affected_id) if affected_id is not None else None,\n                f"Confirmed correction {correction_id} cannot yet be applied deterministically; further reinterpretation is required.",\n            )\n'''
    new = '''        else:\n            applied_item, issue, handled = apply_phase7_5_patch(\n                result,\n                normalized,\n                correction_id=correction_id,\n                category=category,\n                affected_id=affected_id,\n                operation=operation,\n                patch=patch,\n            )\n            if not handled:\n                issue = _issue(\n                    "correction_application_unsupported",\n                    str(affected_id) if affected_id is not None else None,\n                    f"Confirmed correction {correction_id} cannot yet be applied deterministically; further reinterpretation is required.",\n                )\n'''
    return replace_once(text, old, new, "corrections Phase 7.5 dispatcher")


def stage_reinterpretation(text: str) -> str:
    text = replace_once(
        text,
        "from .normalization import NormalizationError, normalize_source\n",
        "from .normalization import NormalizationError, normalize_source\n"
        "from .phase7_5 import phase7_5_deterministic_proposal\n",
        "reinterpretation import",
    )
    old = '''    category = str(exception.get("category") or "")\n    affected = str(exception.get("affected_id") or "").strip()\n    candidates = _question_candidates(evidence_text)\n'''
    new = '''    category = str(exception.get("category") or "")\n    affected = str(exception.get("affected_id") or "").strip()\n\n    phase_proposal, phase_display, phase_evidence = phase7_5_deterministic_proposal(\n        exception, evidence_text\n    )\n    if phase_evidence.get("phase7_5_handled"):\n        return phase_proposal, phase_display, phase_evidence\n\n    candidates = _question_candidates(evidence_text)\n'''
    text = replace_once(text, old, new, "reinterpretation Phase 7.5 routing")
    text = replace_once(
        text,
        '"Phase 7.2 correction reinterpretation: "',
        '"Phase 7.5 correction reinterpretation: "',
        "reinterpretation version label",
    )
    return text


def stage_cli(text: str) -> str:
    text = replace_once(
        text,
        "from .corrections import apply_confirmed_corrections\n",
        "from .corrections import apply_confirmed_corrections\n"
        "from .phase7_5 import enrich_structure_phase7_5\n",
        "cli Phase 7.5 import",
    )
    text = replace_once(
        text,
        "        structure = extract_structure(normalized)\n",
        "        structure = enrich_structure_phase7_5(\n"
        "            extract_structure(normalized), normalized\n"
        "        )\n",
        "cli structure enrichment",
    )
    version_count = text.count('"phase7.2"')
    if version_count != 5:
        raise RuntimeError(
            f"cli engine version: expected five phase7.2 literals, found {version_count}"
        )
    return text.replace('"phase7.2"', '"phase7.5"')


def stage_workflow(text: str) -> str:
    text = replace_once(
        text,
        "          python -m pip install --disable-pip-version-check -r engine/requirements.txt\n",
        "          python -m pip install --disable-pip-version-check -r engine/requirements.txt \"pytest>=8,<9\"\n",
        "workflow pytest install",
    )
    old = '''      - name: Validate workflow input\n        run: python engine/scripts/validate_job_id.py "$MEMO_JOB_ID"\n\n      - name: Run hosted memo worker\n'''
    new = '''      - name: Validate workflow input\n        run: python engine/scripts/validate_job_id.py "$MEMO_JOB_ID"\n\n      - name: Run deterministic engine tests\n        run: python -m pytest -q engine/tests\n\n      - name: Run hosted memo worker\n'''
    return replace_once(text, old, new, "workflow test gate")


STAGERS = {
    "engine/src/memo_engine/corrections.py": stage_corrections,
    "engine/src/memo_engine/correction_reinterpretation.py": stage_reinterpretation,
    "engine/src/memo_engine/cli.py": stage_cli,
    ".github/workflows/process-memo.yml": stage_workflow,
}


def validate_python(label: str, text: str) -> None:
    if label.endswith(".py"):
        compile(text, label, "exec")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Apply the bounded PBHS Memo Converter Phase 7.5 patch."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate exact repo state and patchability without writing files.",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parent
    payload_root = root / "patch_payload"

    staged: dict[str, str] = {}
    print("PBHS Memo Converter — Phase 7.5 patch")
    print(f"Repository root: {root}")

    for relative, expected_sha in VALIDATION_ONLY_BLOB_SHAS.items():
        path = root / relative
        if not path.is_file():
            raise RuntimeError(f"Required compatibility file is missing: {relative}")
        actual_sha = git_blob_sha(path.read_bytes())
        if actual_sha != expected_sha:
            raise RuntimeError(
                f"Refusing to patch: compatibility file {relative} changed; "
                f"expected Git blob {expected_sha}, found {actual_sha}."
            )
        print(f"OK compatible blob: {relative}  {actual_sha}")

    for relative, expected_sha in EXPECTED_BLOB_SHAS.items():
        path = root / relative
        if not path.is_file():
            raise RuntimeError(f"Required repo file is missing: {relative}")
        data = path.read_bytes()
        actual_sha = git_blob_sha(data)
        if actual_sha != expected_sha:
            raise RuntimeError(
                f"Refusing to patch {relative}: expected Git blob {expected_sha}, "
                f"found {actual_sha}. Main has changed; refresh the patch first."
            )
        original = data.decode("utf-8")
        updated = STAGERS[relative](original)
        validate_python(relative, updated)
        staged[relative] = updated
        print(f"OK current blob: {relative}  {actual_sha}")

    for target, source in NEW_FILES.items():
        payload = payload_root.parent / source
        if not payload.is_file():
            raise RuntimeError(f"Patch payload is missing: {source}")
        payload_text = payload.read_text(encoding="utf-8")
        validate_python(target, payload_text)
        target_path = root / target
        if target_path.exists() and target_path.read_bytes() != payload.read_bytes():
            raise RuntimeError(
                f"Refusing to overwrite unexpected existing new-file target: {target}"
            )
        print(f"OK payload: {target}")

    if args.check:
        print("CHECK PASSED — exact main state matches and the patch is syntactically valid.")
        return 0

    for relative, updated in staged.items():
        (root / relative).write_text(updated, encoding="utf-8", newline="\n")
        print(f"UPDATED: {relative}")

    for target, source in NEW_FILES.items():
        payload = payload_root.parent / source
        target_path = root / target
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(payload.read_bytes())
        print(f"ADDED:   {target}")

    print("APPLIED — now run: python -m pytest -q engine/tests")
    print("Then inspect git diff before committing/pushing main.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"PATCH ABORTED: {exc}", file=sys.stderr)
        raise SystemExit(1)
