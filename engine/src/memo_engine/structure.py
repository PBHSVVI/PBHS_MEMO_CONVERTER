from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


QUESTION_RE = re.compile(r"(?m)^[ \t]*(\d{1,2}(?:\.\d{1,2}){0,2})\.?(?=\s|$|\t)")
ALLOC_RE = re.compile(r"\((\d{1,2})\)")
SUBTOTAL_RE = re.compile(r"\[(\d{1,3})\]")
MARK_LINE_RE = re.compile(r"(?i)^\s*(\d+)\s*(?:(CA|M|A|F|S|R)\b|[A-Za-z])")
INLINE_MARK_RE = re.compile(r"(?i)(\d+)\s*(CA|M|A|F|S|R)\b")


def qtuple(qid: str) -> tuple[int, ...]:
    return tuple(int(p) for p in qid.split("."))


def semantic_for_code(code: str | None, descriptor: str) -> str:
    c = (code or "").upper()
    d = descriptor.lower()
    if c == "M":
        return "method"
    if c == "A":
        return "accuracy"
    if c == "CA":
        return "consistent_accuracy"
    if c == "F":
        if "formula" in d:
            return "formula"
        if "fac" in d or "factor" in d:
            return "factorisation"
        return "formula_or_factorisation"
    if c == "S":
        return "statement_or_substitution_or_simplification"
    if c == "R":
        return "reason"
    if "formula" in d:
        return "formula"
    if "sub" in d:
        return "substitution"
    if "fac" in d or "factor" in d:
        return "factorisation"
    if "reason" in d:
        return "reason"
    if "conclusion" in d:
        return "conclusion"
    if "interval" in d or "bracket" in d:
        return "answer"
    if "answer" in d or "ans" in d:
        return "answer"
    if "deriv" in d:
        return "method"
    if "simpl" in d:
        return "simplification"
    if "equation" in d:
        return "statement"
    return "other"


def parse_mark_points(text: str) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    seen_spans: set[tuple[int, int]] = set()

    for line in text.splitlines():
        m = MARK_LINE_RE.match(line)
        if not m:
            continue
        count = int(m.group(1))
        code = m.group(2)
        descriptor = line[m.end(1):].strip()
        points.append({
            "count": count,
            "code": code.upper() if code else None,
            "descriptor": descriptor,
            "semantic": semantic_for_code(code, descriptor),
            "source": line.strip(),
        })

    # Catch compact items such as "1M1sub..." where the first regex alone
    # may under-represent intended marking detail. We do not guess the second
    # semantic; we only surface an ambiguity gate later if arithmetic differs.
    return points


def flatten_units(normalized: dict[str, Any]) -> list[dict[str, Any]]:
    content = normalized["content"]
    units = content.get("units")
    if units is None:
        # PDF/image fallback: page-wise text acts as deterministic blocks.
        result = []
        for page in content.get("pages", []):
            result.append({
                "kind": "page",
                "left": page.get("effective_text", ""),
                "right": "",
                "page": page.get("page"),
            })
        return result

    blocks: list[dict[str, Any]] = []
    for unit_index, unit in enumerate(units):
        if unit.get("type") == "paragraph":
            text = unit.get("text", "")
            if text.strip():
                blocks.append({
                    "kind": "paragraph",
                    "left": text,
                    "right": "",
                    "unit_index": unit_index,
                })
        elif unit.get("type") == "table":
            for row_index, row in enumerate(unit.get("rows", [])):
                texts = [cell.get("text", "") for cell in row]
                left = texts[0] if texts else ""
                right = "\n".join(t for t in texts[1:] if t.strip())
                if left.strip() or right.strip():
                    blocks.append({
                        "kind": "table_row",
                        "left": left,
                        "right": right,
                        "unit_index": unit_index,
                        "row_index": row_index,
                    })
    return blocks


def add_exception(
    exceptions: list[dict[str, Any]],
    *,
    level: str,
    category: str,
    affected_id: str | None,
    message: str,
    suggestions: list[dict[str, Any]] | None = None,
) -> None:
    exceptions.append({
        "level": level,
        "category": category,
        "affected_id": affected_id,
        "message": message,
        "suggestions": suggestions or [],
    })


def extract_structure(normalized: dict[str, Any]) -> dict[str, Any]:
    blocks = flatten_units(normalized)
    questions: list[dict[str, Any]] = []
    exceptions: list[dict[str, Any]] = []
    subtotals: list[dict[str, Any]] = []

    current_major: int | None = None
    previous_qid: str | None = None
    detected_qids: list[str] = []

    for idx, block in enumerate(blocks):
        left = block["left"]
        right = block["right"]
        combined = "\n".join([left, right])

        qids = [m.group(1) for m in QUESTION_RE.finditer(left)]
        allocs = [int(x) for x in ALLOC_RE.findall(right)]
        subtotal_vals = [int(x) for x in SUBTOTAL_RE.findall(combined)]
        mark_points = parse_mark_points(right)
        computed_marks = sum(p["count"] for p in mark_points)

        for s in subtotal_vals:
            subtotals.append({
                "value": s,
                "after_question": previous_qid,
                "block_index": idx,
            })

        if not qids:
            # A mark-bearing row with no detectable question label is structurally suspicious.
            if allocs and left.strip():
                add_exception(
                    exceptions,
                    level="amber",
                    category="missing_question_identifier",
                    affected_id=previous_qid,
                    message="A mark-bearing memo row has no deterministic question identifier.",
                    suggestions=[],
                )
            continue

        # Multiple qids in one row is allowed if allocations pair cleanly.
        if len(qids) > 1 and len(allocs) not in {0, len(qids)}:
            add_exception(
                exceptions,
                level="amber",
                category="question_allocation_pairing_ambiguous",
                affected_id=",".join(qids),
                message="Multiple question identifiers share a row but printed allocations do not pair deterministically.",
            )

        # Pair one-to-one where possible.
        allocations_by_qid: dict[str, int | None] = {}
        if len(qids) == len(allocs):
            allocations_by_qid = dict(zip(qids, allocs))
        elif len(qids) == 1 and len(allocs) == 1:
            allocations_by_qid[qids[0]] = allocs[0]
        else:
            for q in qids:
                allocations_by_qid[q] = None

        for qpos, qid in enumerate(qids):
            detected_qids.append(qid)
            qt = qtuple(qid)
            major = qt[0]

            if current_major is not None and major > current_major + 1:
                add_exception(
                    exceptions,
                    level="red",
                    category="major_question_gap",
                    affected_id=qid,
                    message=f"Question numbering jumps from major question {current_major} to {major}.",
                )
            current_major = max(current_major or major, major)

            if previous_qid is not None:
                prev = qtuple(previous_qid)
                # Strong typo heuristic: same major, same depth >= 2, a component
                # jumps by > 3 and later numbering may return to a lower sibling.
                if len(prev) == len(qt) and len(qt) >= 2 and prev[0] == qt[0]:
                    for pos in range(1, len(qt)):
                        if qt[:pos] == prev[:pos] and qt[pos] > prev[pos] + 3:
                            add_exception(
                                exceptions,
                                level="amber",
                                category="numbering_jump",
                                affected_id=qid,
                                message=f"Question identifier {qid} contains an unusually large numbering jump after {previous_qid}.",
                                suggestions=[{
                                    "kind": "review_numbering",
                                    "candidate": ".".join(map(str, (*qt[:pos], prev[pos] + 1, *qt[pos+1:]))),
                                }],
                            )
                            break

            printed = allocations_by_qid.get(qid)

            if len(qids) == 1 and len(allocs) > 1:
                add_exception(
                    exceptions,
                    level="red",
                    category="multiple_printed_allocations",
                    affected_id=qid,
                    message=f"Question {qid} has multiple printed mark allocations in one marking cell.",
                )

            if printed is not None and computed_marks and printed != computed_marks:
                add_exception(
                    exceptions,
                    level="amber",
                    category="mark_arithmetic_mismatch",
                    affected_id=qid,
                    message=f"Question {qid} prints ({printed}) marks but deterministic shorthand counting yields {computed_marks}.",
                )

            questions.append({
                "question_id": qid,
                "path": list(qt),
                "depth": len(qt),
                "source_block_index": idx,
                "printed_marks": printed,
                "computed_shorthand_marks": computed_marks if computed_marks else None,
                "mark_points": mark_points,
                "source_preview": left[:240],
            })
            previous_qid = qid

    # Duplicate identifiers
    seen: set[str] = set()
    for q in detected_qids:
        if q in seen:
            add_exception(
                exceptions,
                level="red",
                category="duplicate_question_identifier",
                affected_id=q,
                message=f"Question identifier {q} appears more than once.",
            )
        seen.add(q)

    # Missing sibling heuristic over observed question ids. This is intentionally
    # conservative and only fires where a clear x.1 -> x.3 gap exists.
    tuples = [qtuple(q) for q in detected_qids]
    by_parent: dict[tuple[int, ...], list[int]] = {}
    for qt in tuples:
        if len(qt) >= 2:
            by_parent.setdefault(qt[:-1], []).append(qt[-1])
    for parent, children in by_parent.items():
        vals = sorted(set(children))
        for a, b in zip(vals, vals[1:]):
            if b == a + 2:
                missing = ".".join(map(str, (*parent, a + 1)))
                add_exception(
                    exceptions,
                    level="amber",
                    category="possible_missing_question",
                    affected_id=missing,
                    message=f"Question sequence suggests that {missing} may be missing.",
                    suggestions=[{"kind": "review_numbering", "candidate": missing}],
                )

    subtotal_sum = sum(x["value"] for x in subtotals)
    if subtotals and subtotal_sum != 150:
        add_exception(
            exceptions,
            level="amber",
            category="subtotal_sum_unexpected",
            affected_id=None,
            message=f"Detected question subtotals sum to {subtotal_sum}, not 150.",
        )

    # Known-safe rule: malformed depth where second component >= 10 in an otherwise
    # ordinary school-paper hierarchy is not auto-corrected; it must be reviewed.
    for qid in detected_qids:
        qt = qtuple(qid)
        if len(qt) >= 2 and qt[1] >= 10:
            add_exception(
                exceptions,
                level="amber",
                category="suspicious_question_identifier",
                affected_id=qid,
                message=f"Question identifier {qid} is structurally unusual and must be confirmed rather than silently normalised.",
                suggestions=[],
            )

    red = sum(1 for e in exceptions if e["level"] == "red")
    amber = sum(1 for e in exceptions if e["level"] == "amber")

    return {
        "schema_version": "1.0",
        "phase": "phase3_structure",
        "job_id": normalized["job_id"],
        "questions": questions,
        "subtotals": subtotals,
        "summary": {
            "detected_question_count": len(questions),
            "unique_question_count": len(set(detected_qids)),
            "subtotal_count": len(subtotals),
            "subtotal_sum": subtotal_sum,
            "amber_count": amber,
            "red_count": red,
            "review_required": bool(exceptions),
        },
        "exceptions": exceptions,
    }
