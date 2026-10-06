from __future__ import annotations

import re
from typing import Any


GRADIENT_PRODUCT_RE = re.compile(
    r"(?i)m\s*([A-Z]{2,})\s*(?:×|\*|x)\s*m\s*([A-Z]{2,})\s*=\s*[−-]\s*1"
)
PERPENDICULAR_RE = re.compile(
    r"(?i)\b([A-Z]{2,})\s*(?:⊥|perp(?:endicular)?(?:\s+to)?)\s*([A-Z]{2,})\b"
)
PARALLEL_RE = re.compile(
    r"(?i)\b([A-Z]{2,})\s*(?:∥|//|parallel(?:\s+to)?)\s*([A-Z]{2,})\b"
)


def _block_text(block: dict[str, Any]) -> str:
    if block.get("type") == "math":
        math = block.get("math") or {}
        return str(math.get("plain_text") or math.get("source_text") or "")
    return str(block.get("text") or "")


def _nearby_gradient_pair(text: str, relation_start: int) -> tuple[str, str] | None:
    matches = [match for match in GRADIENT_PRODUCT_RE.finditer(text) if match.end() <= relation_start]
    if not matches:
        return None
    match = matches[-1]
    if relation_start - match.end() > 180:
        return None
    first, second = match.group(1).upper(), match.group(2).upper()
    return (first, second) if first != second else None


def geometry_consistency_issues(memo: dict[str, Any]) -> list[dict[str, Any]]:
    """Detect only bounded contradictions in named-line conclusions."""
    issues: list[dict[str, Any]] = []

    def inspect(item: dict[str, Any]) -> None:
        qid = str(item.get("number") or "")
        for alternative in item.get("alternatives", []):
            text = " ".join(
                value for block in alternative.get("blocks", [])
                if (value := _block_text(block).strip())
            )
            for relation in PERPENDICULAR_RE.finditer(text):
                left, right = relation.group(1).upper(), relation.group(2).upper()
                evidence = _nearby_gradient_pair(text, relation.start())
                if left == right:
                    message = f"The conclusion says {left} is perpendicular to {right}."
                    if evidence:
                        message = (
                            f"Earlier working compares {evidence[0]} and {evidence[1]}, "
                            f"but the conclusion says {left} is perpendicular to {right}."
                        )
                    issues.append({
                        "level": "amber",
                        "category": "geometry_line_relationship_conflict",
                        "affected_id": qid,
                        "message": message + " Confirm or edit the named lines.",
                    })
                    continue
                if evidence and {left, right} != set(evidence):
                    issues.append({
                        "level": "amber",
                        "category": "geometry_line_relationship_conflict",
                        "affected_id": qid,
                        "message": (
                            f"Earlier working compares {evidence[0]} and {evidence[1]}, "
                            f"but the perpendicular conclusion names {left} and {right}. "
                            "Confirm or edit the named lines."
                        ),
                    })

            for relation in PARALLEL_RE.finditer(text):
                left, right = relation.group(1).upper(), relation.group(2).upper()
                evidence = _nearby_gradient_pair(text, relation.start())
                if left == right and evidence:
                    issues.append({
                        "level": "amber",
                        "category": "geometry_line_relationship_conflict",
                        "affected_id": qid,
                        "message": (
                            f"Earlier working compares {evidence[0]} and {evidence[1]}, "
                            f"but the conclusion says {left} is parallel to {right}. "
                            "Confirm or edit the named lines."
                        ),
                    })
        for child in item.get("children", []):
            inspect(child)

    for question in memo.get("questions", []):
        for item in question.get("items", []):
            inspect(item)
    return issues

