from __future__ import annotations

import re
from typing import Any

QUESTION_RE = re.compile(
    r"(?m)^[ \t]*(\d{1,2}(?:\.\d{1,2}){0,2})\.?(?=\s|$|\t)"
)
JAMMED_QUESTION_RE = re.compile(
    r"(?m)^[ \t]*(\d{1,2}\.\d{1,2}\.\d{1,2})(?=[A-Za-z])"
)
SUBTOTAL_RE = re.compile(r"\[(\d{1,3})\]")
PAREN_NUMBER_RE = re.compile(r"\((\d{1,2})\)")
MARK_TOKEN_RE = re.compile(r"(?i)^\s*(\d+)\s*(.*)$")
CODE_RE = re.compile(r"(?i)^(CA|M|A|F|S|R)\b")
INLINE_CODE_RE = re.compile(r"(?i)(?:^|[;|])\s*(\d+)\s*(CA|M|A|F|S|R)\b")
CHECK_RE = re.compile(r"^\s*(✓+)\s*(.*)$")

MARK_DESCRIPTOR_PREFIXES = (
    "isol", "square", "squar", "fac", "fact", "rej", "interval", "bracket",
    "shape", "point", "conclusion", "simpl", "formula", "deriv", "answer",
    "ans", "sub", "equation", "equns", "method", "standard", "value",
    "geometric", "arithmetic", "condition", "correct", "common", "ratio",
    "sum", "algebra", "manip", "swop", "first", "second", "use", "m=", "c=",
)


def find_question_ids(text: str) -> list[str]:
    matches: list[tuple[int, str]] = []
    for pattern in (QUESTION_RE, JAMMED_QUESTION_RE):
        for m in pattern.finditer(text):
            matches.append((m.start(), m.group(1)))
    matches.sort(key=lambda item: item[0])
    result: list[str] = []
    seen: set[str] = set()
    for _, qid in matches:
        if qid not in seen:
            result.append(qid)
            seen.add(qid)
    return result


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
    if "equation" in d or "equns" in d:
        return "statement"
    if "shape" in d or "point" in d:
        return "graph_feature"
    return "other"


def _looks_like_descriptor(rest: str) -> bool:
    r = rest.strip().lower()
    if not r:
        return False
    if CODE_RE.match(r):
        return True
    return r.startswith(MARK_DESCRIPTOR_PREFIXES)


def _parse_numeric_mark(fragment: str) -> dict[str, Any] | None:
    compact = re.match(r"(?i)^\s*(\d+)([A-Za-z].*)$", fragment)
    if compact:
        count = int(compact.group(1))
        compact_rest = compact.group(2).strip()

        # Prefer known descriptive words over treating their first letter as
        # a shorthand code, e.g. "1interval", "1formula", "1sub".
        if compact_rest.lower().startswith(MARK_DESCRIPTOR_PREFIXES):
            return {
                "count": count,
                "code": None,
                "descriptor": compact_rest,
                "semantic": semantic_for_code(None, compact_rest),
                "source": fragment.strip(),
                "notation": "shorthand_compact_descriptor",
            }

        attached_code = re.match(r"(?i)^(CA|M|A|F|S|R)(.*)$", compact_rest)
        if attached_code:
            code = attached_code.group(1).upper()
            rest = attached_code.group(2).strip()
            return {
                "count": count,
                "code": code,
                "descriptor": rest,
                "semantic": semantic_for_code(code, rest),
                "source": fragment.strip(),
                "notation": "shorthand_attached",
            }

    normal = re.match(r"(?i)^\s*(\d+)\s+(.*)$", fragment)
    if not normal:
        return None
    count = int(normal.group(1))
    rest = normal.group(2).strip()
    code = None
    cm = re.match(r"(?i)^(CA|M|A|F|S|R)\b", rest)
    if cm:
        code = cm.group(1).upper()
        rest = rest[cm.end():].strip()
    elif not _looks_like_descriptor(rest):
        return None

    return {
        "count": count,
        "code": code,
        "descriptor": rest,
        "semantic": semantic_for_code(code, rest),
        "source": fragment.strip(),
        "notation": "shorthand",
    }


def parse_mark_points(text: str) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue

        check = CHECK_RE.match(stripped)
        if check:
            marks = check.group(1)
            descriptor = check.group(2).strip()
            points.append({
                "count": len(marks),
                "code": None,
                "descriptor": descriptor,
                "semantic": semantic_for_code(None, descriptor),
                "source": stripped,
                "notation": "tick",
            })
            continue

        primary = _parse_numeric_mark(stripped)
        if primary:
            points.append(primary)

        for m in INLINE_CODE_RE.finditer(stripped):
            if m.start() == 0:
                continue
            descriptor = stripped[m.end():].strip()
            points.append({
                "count": int(m.group(1)),
                "code": m.group(2).upper(),
                "descriptor": descriptor,
                "semantic": semantic_for_code(m.group(2), descriptor),
                "source": stripped[m.start():].strip(),
                "notation": "shorthand_inline",
            })
    return points


def printed_allocations(text: str) -> list[int]:
    values: list[int] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        for m in PAREN_NUMBER_RE.finditer(stripped):
            before = stripped[:m.start()].strip().lower()
            after = stripped[m.end():].strip().lower()

            if re.search(r"\b(sub|into|equation|eqn|line|from)\s*$", before):
                continue
            if after and not after.startswith("mark"):
                if not re.fullmatch(r"(?:\(\d{1,2}\)\s*)+", after):
                    continue
            values.append(int(m.group(1)))
    return values


def _base_mark_total(points: list[dict[str, Any]]) -> tuple[int, str]:
    if not points:
        return 0, "none"

    if (
        len(points) >= 2
        and all(p.get("code") in {"A", "CA"} for p in points)
        and all("correct" in p.get("descriptor", "").lower() for p in points)
    ):
        return max(p["count"] for p in points), "conditional_accuracy"

    return sum(p["count"] for p in points), "additive"


def effective_mark_total(
    points: list[dict[str, Any]],
    marking_text: str = "",
) -> tuple[int, str]:
    if re.search(r"(?im)^\s*OR\s*$", marking_text):
        branches = re.split(r"(?im)^\s*OR\s*$", marking_text)
        totals: list[int] = []
        for branch in branches:
            branch_points = parse_mark_points(branch)
            total, _ = _base_mark_total(branch_points)
            if total:
                totals.append(total)
        if totals:
            return max(totals), "alternative_max"

    return _base_mark_total(points)


def _partition_mark_points(
    points: list[dict[str, Any]],
    allocations: list[int],
) -> list[list[dict[str, Any]]] | None:
    if not points or not allocations:
        return None

    result: list[list[dict[str, Any]]] = []
    cursor = 0
    for target in allocations:
        part: list[dict[str, Any]] = []
        total = 0
        while cursor < len(points) and total < target:
            item = points[cursor]
            part.append(item)
            total += item["count"]
            cursor += 1
        if total != target:
            return None
        result.append(part)

    if cursor != len(points):
        return None
    return result


def flatten_units(normalized: dict[str, Any]) -> list[dict[str, Any]]:
    content = normalized["content"]
    units = content.get("units")
    if units is None:
        result = []
        for page in content.get("pages", []):
            text = page.get("effective_text", "")
            result.append({
                "kind": "page",
                "source": text,
                "marking": "",
                "allocation": "",
                "cells": [text],
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
                    "source": text,
                    "marking": "",
                    "allocation": "",
                    "cells": [text],
                    "unit_index": unit_index,
                })
        elif unit.get("type") == "table":
            for row_index, row in enumerate(unit.get("rows", [])):
                cells = [cell.get("text", "") for cell in row]
                if not any(c.strip() for c in cells):
                    continue

                if len(cells) == 1:
                    source = cells[0]
                    marking = ""
                    allocation = ""
                elif len(cells) == 2:
                    source = cells[0]
                    marking = cells[1]
                    allocation = cells[1]
                elif len(cells) == 3:
                    source = "\n".join(cells[:2])
                    marking = cells[2]
                    allocation = cells[2]
                else:
                    source = "\n".join(cells[:-2])
                    marking = cells[-2]
                    allocation = cells[-1]

                blocks.append({
                    "kind": "table_row",
                    "source": source,
                    "marking": marking,
                    "allocation": allocation,
                    "cells": cells,
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


def _is_parent_in_same_block(qid: str, qids: list[str]) -> bool:
    prefix = qid + "."
    return any(other != qid and other.startswith(prefix) for other in qids)


def _infer_missing_between(prev_qid: str | None, next_qids: list[str]) -> str | None:
    if prev_qid is None or not next_qids:
        return None
    prev = qtuple(prev_qid)
    nxt = qtuple(next_qids[0])
    if len(prev) >= 2 and len(nxt) >= 2 and prev[0] == nxt[0]:
        if nxt[1] == prev[1] + 2:
            return f"{prev[0]}.{prev[1] + 1}"
    return None


def extract_structure(normalized: dict[str, Any]) -> dict[str, Any]:
    blocks = flatten_units(normalized)
    questions: list[dict[str, Any]] = []
    exceptions: list[dict[str, Any]] = []
    subtotals: list[dict[str, Any]] = []
    unlabeled_mark_blocks: list[dict[str, Any]] = []

    current_major: int | None = None
    previous_leaf_qid: str | None = None
    detected_qids: list[str] = []
    block_qids: dict[int, list[str]] = {}

    for idx, block in enumerate(blocks):
        block_qids[idx] = find_question_ids(block["source"])

    for idx, block in enumerate(blocks):
        source = block["source"]
        marking = block["marking"]
        allocation_text = block["allocation"]
        combined = "\n".join(block["cells"])

        qids = block_qids[idx]
        allocs = printed_allocations(allocation_text)
        subtotal_vals = [int(x) for x in SUBTOTAL_RE.findall(combined)]
        all_points = parse_mark_points(marking)

        for s in subtotal_vals:
            subtotals.append({
                "value": s,
                "after_question": previous_leaf_qid,
                "block_index": idx,
            })

        if not qids:
            if allocs and source.strip():
                next_qids: list[str] = []
                for j in range(idx + 1, len(blocks)):
                    if block_qids[j]:
                        next_qids = block_qids[j]
                        break
                inferred = _infer_missing_between(previous_leaf_qid, next_qids)
                unlabeled_mark_blocks.append({
                    "block_index": idx,
                    "printed_allocations": allocs,
                    "candidate": inferred,
                })
                add_exception(
                    exceptions,
                    level="amber",
                    category="unlabeled_mark_bearing_question",
                    affected_id=inferred,
                    message=(
                        "A mark-bearing memo row has no printed question identifier"
                        + (f"; sequence suggests {inferred}." if inferred else ".")
                    ),
                    suggestions=(
                        [{"kind": "review_numbering", "candidate": inferred}]
                        if inferred else []
                    ),
                )
            continue

        detected_qids.extend(qids)
        leaf_qids = [q for q in qids if not _is_parent_in_same_block(q, qids)]
        context_qids = [q for q in qids if q not in leaf_qids]

        allocation_by_qid: dict[str, int | None] = {q: None for q in qids}
        points_by_qid: dict[str, list[dict[str, Any]]] = {q: [] for q in qids}
        mode_by_qid: dict[str, str] = {q: "none" for q in qids}

        if len(leaf_qids) == len(allocs) and leaf_qids:
            for q, a in zip(leaf_qids, allocs):
                allocation_by_qid[q] = a

            partition = _partition_mark_points(all_points, allocs)
            if partition is not None and len(partition) == len(leaf_qids):
                for q, pts in zip(leaf_qids, partition):
                    points_by_qid[q] = pts
                    mode_by_qid[q] = "partitioned"
            elif len(leaf_qids) == 1:
                points_by_qid[leaf_qids[0]] = all_points
        elif len(leaf_qids) == 1 and len(allocs) == 1:
            q = leaf_qids[0]
            allocation_by_qid[q] = allocs[0]
            points_by_qid[q] = all_points
        else:
            if len(leaf_qids) > 1 and allocs:
                add_exception(
                    exceptions,
                    level="amber",
                    category="question_allocation_pairing_ambiguous",
                    affected_id=",".join(leaf_qids),
                    message="Multiple leaf question identifiers share a row but printed allocations cannot be paired deterministically.",
                )
            if len(leaf_qids) == 1:
                points_by_qid[leaf_qids[0]] = all_points

        for qid in qids:
            qt = qtuple(qid)
            major = qt[0]
            is_context = qid in context_qids

            if not is_context:
                if current_major is not None and major > current_major + 1:
                    add_exception(
                        exceptions,
                        level="red",
                        category="major_question_gap",
                        affected_id=qid,
                        message=f"Question numbering jumps from major question {current_major} to {major}.",
                    )
                current_major = max(current_major or major, major)

                if previous_leaf_qid is not None:
                    prev = qtuple(previous_leaf_qid)
                    if len(prev) == len(qt) and len(qt) >= 2 and prev[0] == qt[0]:
                        for pos in range(1, len(qt)):
                            if qt[:pos] == prev[:pos] and qt[pos] > prev[pos] + 3:
                                candidate = ".".join(
                                    map(str, (*qt[:pos], prev[pos] + 1, *qt[pos + 1:]))
                                )
                                add_exception(
                                    exceptions,
                                    level="amber",
                                    category="numbering_jump",
                                    affected_id=qid,
                                    message=f"Question identifier {qid} contains an unusually large numbering jump after {previous_leaf_qid}.",
                                    suggestions=[{
                                        "kind": "review_numbering",
                                        "candidate": candidate,
                                    }],
                                )
                                break

            printed = allocation_by_qid.get(qid)
            pts = points_by_qid.get(qid, [])
            computed, calc_mode = effective_mark_total(pts, marking)
            if mode_by_qid.get(qid) == "partitioned":
                calc_mode = "partitioned"

            if not is_context and len(leaf_qids) == 1 and len(allocs) > 1:
                add_exception(
                    exceptions,
                    level="red",
                    category="multiple_printed_allocations",
                    affected_id=qid,
                    message=f"Question {qid} has multiple printed mark allocations in one marking cell.",
                )

            if not is_context and printed is not None and computed and printed != computed:
                add_exception(
                    exceptions,
                    level="amber",
                    category="mark_arithmetic_mismatch",
                    affected_id=qid,
                    message=f"Question {qid} prints ({printed}) marks but deterministic shorthand counting yields {computed}.",
                )

            questions.append({
                "question_id": qid,
                "path": list(qt),
                "depth": len(qt),
                "context_only": is_context,
                "source_block_index": idx,
                "printed_marks": printed,
                "computed_shorthand_marks": computed if computed else None,
                "mark_calculation_mode": calc_mode,
                "mark_points": pts,
                "source_preview": source[:240],
            })

            if not is_context:
                previous_leaf_qid = qid

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

    represented: set[tuple[int, ...]] = set()
    for q in detected_qids:
        qt = qtuple(q)
        for n in range(1, len(qt) + 1):
            represented.add(qt[:n])

    by_parent: dict[tuple[int, ...], list[int]] = {}
    for prefix in represented:
        if len(prefix) >= 2:
            by_parent.setdefault(prefix[:-1], []).append(prefix[-1])

    existing_exception_ids = {
        (e["category"], e.get("affected_id")) for e in exceptions
    }

    for parent, children in by_parent.items():
        vals = sorted(set(children))
        for a, b in zip(vals, vals[1:]):
            if b == a + 2:
                missing_tuple = (*parent, a + 1)
                if missing_tuple in represented:
                    continue
                missing = ".".join(map(str, missing_tuple))
                if any(
                    e.get("affected_id") == missing
                    and e["category"] == "unlabeled_mark_bearing_question"
                    for e in exceptions
                ):
                    continue
                key = ("possible_missing_question", missing)
                if key not in existing_exception_ids:
                    add_exception(
                        exceptions,
                        level="amber",
                        category="possible_missing_question",
                        affected_id=missing,
                        message=f"Question sequence suggests that {missing} may be missing.",
                        suggestions=[{"kind": "review_numbering", "candidate": missing}],
                    )
                    existing_exception_ids.add(key)

    subtotal_sum = sum(x["value"] for x in subtotals)
    if subtotals and subtotal_sum != 150:
        add_exception(
            exceptions,
            level="amber",
            category="subtotal_sum_unexpected",
            affected_id=None,
            message=f"Detected question subtotals sum to {subtotal_sum}, not 150.",
        )

    for qid in detected_qids:
        qt = qtuple(qid)
        if len(qt) >= 2 and qt[1] >= 10:
            already_flagged = any(
                e.get("affected_id") == qid and e["category"] == "numbering_jump"
                for e in exceptions
            )
            if not already_flagged:
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
        "schema_version": "1.1",
        "phase": "phase3_structure_calibrated",
        "job_id": normalized["job_id"],
        "questions": questions,
        "subtotals": subtotals,
        "unlabeled_mark_blocks": unlabeled_mark_blocks,
        "summary": {
            "detected_identifier_count": len(questions),
            "leaf_question_count": sum(1 for q in questions if not q["context_only"]),
            "unique_question_count": len(set(detected_qids)),
            "subtotal_count": len(subtotals),
            "subtotal_sum": subtotal_sum,
            "amber_count": amber,
            "red_count": red,
            "review_required": bool(exceptions),
        },
        "exceptions": exceptions,
    }
