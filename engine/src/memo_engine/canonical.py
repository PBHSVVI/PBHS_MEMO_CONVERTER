from __future__ import annotations

import hashlib
import io
import os
import re
import zipfile
from typing import Any
from xml.etree import ElementTree as ET

from .structure import find_question_ids, parse_mark_points

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
M_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"
NS = {"w": W_NS, "m": M_NS}
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PR_NS = "http://schemas.openxmlformats.org/package/2006/relationships"

MARK_TYPES = {
    "method", "accuracy", "answer", "consistent_accuracy", "formula",
    "factorisation", "substitution", "simplification", "statement", "reason",
    "statement_reason", "conclusion", "construction", "given", "graph_feature",
    "selection", "progressive", "other",
}

DEFAULT_DESCRIPTOR = {
    "method": "method",
    "accuracy": "accuracy",
    "answer": "answer",
    "consistent_accuracy": "answer (CA)",
    "formula": "formula",
    "factorisation": "factorisation",
    "substitution": "substitution",
    "simplification": "simplification",
    "statement": "statement",
    "reason": "reason",
    "statement_reason": "statement / reason",
    "conclusion": "conclusion",
    "construction": "Construction",
    "given": "Given",
    "graph_feature": "graph feature",
    "selection": "selection",
    "progressive": "progressive step",
    "other": "reviewed mark",
}

SUPPORTED_LATEX_COMMANDS = {
    "leq", "geq", "neq", "in", "infty", "pm", "times", "div", "to",
    "therefore", "theta", "pi", "circ", "sum", "int", "prod", "frac",
    "sqrt", "left", "right", "text", "hat", "bar", "vec",
}

QUESTION_TOKEN_RE = re.compile(
    r"(?m)(?:^|\n)[ \t]*(\d{1,2}(?:\.\d{1,2}){0,2})\.?(?=\s|$|\t)"
)
OR_LINE_RE = re.compile(r"(?im)^\s*OR\s*$")
TOTAL_RE = re.compile(r"(?i)\bTOTAL\s*[:=-]?\s*(\d{1,3})\b")
YEAR_RE = re.compile(r"\b(20\d{2})\b")
PAPER_RE = re.compile(r"(?i)\bPAPER\s*([12])\b")
GRADE_RE = re.compile(r"(?i)\b(?:FORM|GRADE)\s*([0-9]{1,2})\b")
DURATION_RE = re.compile(r"(?i)\bTIME\s*[:=-]?\s*(\d+(?:[.,]\d+)?)\s*HOURS?\b")


class CanonicalizationError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.public_message = message


def _attr(ns: str, name: str) -> str:
    return f"{{{ns}}}{name}"


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _mchild(node: ET.Element | None, name: str) -> ET.Element | None:
    if node is None:
        return None
    return node.find(f"{{{M_NS}}}{name}")


def _collapse(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("\u00a0", " ")).strip()


def _text_to_latex(text: str) -> str:
    text = _collapse(text)
    replacements = {
        "≤": r"\leq{}", "≥": r"\geq{}", "≠": r"\neq{}", "∈": r"\in{}",
        "∞": r"\infty{}", "±": r"\pm{}", "×": r"\times{}", "÷": r"\div{}",
        "→": r"\to{}", "∴": r"\therefore{}", "θ": r"\theta{}", "π": r"\pi{}",
        "°": r"^{\circ}",
    }
    literal_escapes = {
        "\\": r"\backslash{}",
        "%": r"\%",
        "#": r"\#",
        "{": r"\{",
        "}": r"\}",
    }

    # Escape only characters that existed in the source. Generated LaTeX
    # commands must keep their own structural braces intact.
    pieces: list[str] = []
    for char in text:
        if char in replacements:
            pieces.append(replacements[char])
        elif char in literal_escapes:
            pieces.append(literal_escapes[char])
        else:
            pieces.append(char)

    value = "".join(pieces)
    value = re.sub(r"(?i)\bor\b", r"\\text{ or }", value)
    return value.strip()


def _omml_node_to_latex(node: ET.Element) -> str:
    tag = _local(node.tag)

    if tag in {"oMath", "e", "num", "den", "sup", "sub", "deg", "lim", "fName"}:
        ignored = {
            "ctrlPr", "rPr", "sSupPr", "sSubPr", "sSubSupPr", "fPr", "radPr",
            "dPr", "funcPr", "limLowPr", "limUppPr", "naryPr", "accPr", "barPr",
        }
        return "".join(
            _omml_node_to_latex(child)
            for child in list(node)
            if _local(child.tag) not in ignored
        )

    if tag == "r":
        return "".join(
            _omml_node_to_latex(child)
            for child in list(node)
            if _local(child.tag) == "t"
        )

    if tag == "t":
        return _text_to_latex(node.text or "")

    if tag == "sSup":
        base = _omml_node_to_latex(_mchild(node, "e")) if _mchild(node, "e") is not None else ""
        sup = _omml_node_to_latex(_mchild(node, "sup")) if _mchild(node, "sup") is not None else ""
        return f"{{{base}}}^{{{sup}}}"

    if tag == "sSub":
        base = _omml_node_to_latex(_mchild(node, "e")) if _mchild(node, "e") is not None else ""
        sub = _omml_node_to_latex(_mchild(node, "sub")) if _mchild(node, "sub") is not None else ""
        return f"{{{base}}}_{{{sub}}}"

    if tag == "sSubSup":
        base = _omml_node_to_latex(_mchild(node, "e")) if _mchild(node, "e") is not None else ""
        sub = _omml_node_to_latex(_mchild(node, "sub")) if _mchild(node, "sub") is not None else ""
        sup = _omml_node_to_latex(_mchild(node, "sup")) if _mchild(node, "sup") is not None else ""
        return f"{{{base}}}_{{{sub}}}^{{{sup}}}"

    if tag == "f":
        num = _mchild(node, "num")
        den = _mchild(node, "den")
        return rf"\frac{{{_omml_node_to_latex(num) if num is not None else ''}}}{{{_omml_node_to_latex(den) if den is not None else ''}}}"

    if tag == "rad":
        expr = _mchild(node, "e")
        deg = _mchild(node, "deg")
        deg_hide = node.find(f".//{{{M_NS}}}degHide")
        expr_latex = _omml_node_to_latex(expr) if expr is not None else ""
        if deg is not None and deg_hide is None:
            degree = _omml_node_to_latex(deg).strip()
            if degree:
                return rf"\sqrt[{degree}]{{{expr_latex}}}"
        return rf"\sqrt{{{expr_latex}}}"

    if tag == "d":
        expr = _mchild(node, "e")
        props = _mchild(node, "dPr")
        beg, end = "(", ")"
        if props is not None:
            beg_node = _mchild(props, "begChr")
            end_node = _mchild(props, "endChr")
            if beg_node is not None:
                beg = beg_node.get(_attr(M_NS, "val")) or beg
            if end_node is not None:
                end = end_node.get(_attr(M_NS, "val")) or end
        escaped = {"{": r"\{", "}": r"\}"}
        return (
            rf"\left{escaped.get(beg, beg)}"
            + (_omml_node_to_latex(expr) if expr is not None else "")
            + rf"\right{escaped.get(end, end)}"
        )

    if tag == "func":
        fname = _mchild(node, "fName")
        expr = _mchild(node, "e")
        return (
            (_omml_node_to_latex(fname) if fname is not None else "")
            + (_omml_node_to_latex(expr) if expr is not None else "")
        )

    if tag == "limLow":
        expr = _mchild(node, "e")
        lim = _mchild(node, "lim")
        return f"{{{_omml_node_to_latex(expr) if expr is not None else ''}}}_{{{_omml_node_to_latex(lim) if lim is not None else ''}}}"

    if tag == "limUpp":
        expr = _mchild(node, "e")
        lim = _mchild(node, "lim")
        return f"{{{_omml_node_to_latex(expr) if expr is not None else ''}}}^{{{_omml_node_to_latex(lim) if lim is not None else ''}}}"

    if tag == "nary":
        props = _mchild(node, "naryPr")
        symbol = "∑"
        if props is not None:
            chr_node = _mchild(props, "chr")
            if chr_node is not None:
                symbol = chr_node.get(_attr(M_NS, "val")) or symbol
        operator = {"∑": r"\sum", "∫": r"\int", "∏": r"\prod"}.get(symbol, _text_to_latex(symbol))
        sub = _mchild(node, "sub")
        sup = _mchild(node, "sup")
        expr = _mchild(node, "e")
        value = operator
        if sub is not None and _omml_node_to_latex(sub).strip():
            value += f"_{{{_omml_node_to_latex(sub)}}}"
        if sup is not None and _omml_node_to_latex(sup).strip():
            value += f"^{{{_omml_node_to_latex(sup)}}}"
        if expr is not None:
            value += " " + _omml_node_to_latex(expr)
        return value

    if tag == "acc":
        props = _mchild(node, "accPr")
        symbol = None
        if props is not None:
            chr_node = _mchild(props, "chr")
            if chr_node is not None:
                symbol = chr_node.get(_attr(M_NS, "val"))
        expr = _mchild(node, "e")
        content = _omml_node_to_latex(expr) if expr is not None else ""
        if symbol in {"¯", "‾"}:
            return rf"\bar{{{content}}}"
        if symbol == "→":
            return rf"\vec{{{content}}}"
        return rf"\hat{{{content}}}"

    if tag == "bar":
        expr = _mchild(node, "e")
        return rf"\bar{{{_omml_node_to_latex(expr) if expr is not None else ''}}}"

    if tag.endswith("Pr") or tag in {
        "ctrlPr", "sty", "scr", "chr", "begChr", "endChr", "degHide", "limLoc"
    }:
        return ""

    raise CanonicalizationError(
        "MATH_OMML_UNSUPPORTED",
        f"Unsupported Office Math element {tag!r} was encountered.",
    )


def omml_to_latex(omml: str) -> str:
    try:
        root = ET.fromstring(omml)
    except ET.ParseError as exc:
        raise CanonicalizationError(
            "MATH_OMML_INVALID",
            "An Office Math expression could not be parsed.",
        ) from exc
    latex = _collapse(_omml_node_to_latex(root))
    validate_latex_subset(latex)
    return latex


def validate_latex_subset(latex: str) -> None:
    if not latex.strip():
        raise CanonicalizationError("MATH_EMPTY", "Canonical mathematics is empty.")
    depth = 0
    for index, ch in enumerate(latex):
        escaped = index > 0 and latex[index - 1] == "\\"
        if ch == "{" and not escaped:
            depth += 1
        elif ch == "}" and not escaped:
            depth -= 1
            if depth < 0:
                raise CanonicalizationError("MATH_BRACES", "Canonical mathematics has unbalanced braces.")
    if depth:
        raise CanonicalizationError("MATH_BRACES", "Canonical mathematics has unbalanced braces.")

    for command in re.findall(r"\\([A-Za-z]+)", latex):
        if command not in SUPPORTED_LATEX_COMMANDS:
            raise CanonicalizationError(
                "MATH_COMMAND_UNSUPPORTED",
                f"Canonical mathematics contains unsupported command \\{command}.",
            )


def _looks_math_like(text: str) -> bool:
    value = _collapse(text)
    if not value:
        return False
    if any(symbol in value for symbol in ["=", "≤", "≥", "≠", "∈", "±", "√", "∞"]):
        return True
    return bool(re.search(r"\b\d+[xykabcp]\b|[xykabcp]\s*[+\-*/]\s*\d", value, re.I))


def plain_math_to_latex(text: str) -> str:
    latex = _text_to_latex(text)
    latex = latex.replace("²", "^{2}").replace("³", "^{3}")
    validate_latex_subset(latex)
    return latex


def _docx_page_map(source_bytes: bytes) -> tuple[dict[tuple[int, int | None, int | None, int], int], int]:
    page_map: dict[tuple[int, int | None, int | None, int], int] = {}
    try:
        with zipfile.ZipFile(io.BytesIO(source_bytes)) as archive:
            root = ET.fromstring(archive.read("word/document.xml"))
    except Exception:
        return page_map, 1

    body = root.find("w:body", NS)
    if body is None:
        return page_map, 1

    page = 1
    unit_index = 0
    for child in list(body):
        if child.tag == _attr(W_NS, "p"):
            page_map[(unit_index, None, None, 0)] = page
            page += len(child.findall(".//w:lastRenderedPageBreak", NS))
            unit_index += 1
        elif child.tag == _attr(W_NS, "tbl"):
            for row_index, row in enumerate(child.findall("./w:tr", NS)):
                for cell_index, cell in enumerate(row.findall("./w:tc", NS)):
                    for paragraph_index, paragraph in enumerate(cell.findall("./w:p", NS)):
                        page_map[(unit_index, row_index, cell_index, paragraph_index)] = page
                        page += len(paragraph.findall(".//w:lastRenderedPageBreak", NS))
            unit_index += 1
    return page_map, max(1, page)


def _docx_asset_map(
    source_bytes: bytes,
) -> tuple[dict[tuple[int, int | None, int | None, int], list[str]], list[dict[str, Any]]]:
    drawing_map: dict[tuple[int, int | None, int | None, int], list[str]] = {}
    assets: dict[str, dict[str, Any]] = {}
    try:
        with zipfile.ZipFile(io.BytesIO(source_bytes)) as archive:
            root = ET.fromstring(archive.read("word/document.xml"))
            rel_root = ET.fromstring(archive.read("word/_rels/document.xml.rels"))
            rel_map = {
                rel.get("Id"): rel.get("Target")
                for rel in list(rel_root)
                if rel.get("Id") and rel.get("Target")
            }
            body = root.find("w:body", NS)
            if body is None:
                return drawing_map, []

            unit_index = 0
            for child in list(body):
                if child.tag == _attr(W_NS, "p"):
                    anchors = [(None, None, 0, child)]
                elif child.tag == _attr(W_NS, "tbl"):
                    anchors = []
                    for row_index, row in enumerate(child.findall("./w:tr", NS)):
                        for cell_index, cell in enumerate(row.findall("./w:tc", NS)):
                            for paragraph_index, paragraph in enumerate(cell.findall("./w:p", NS)):
                                anchors.append((row_index, cell_index, paragraph_index, paragraph))
                else:
                    continue

                for row_index, cell_index, paragraph_index, paragraph in anchors:
                    ids: list[str] = []
                    for blip in paragraph.findall(f".//{{{A_NS}}}blip"):
                        rel_id = blip.get(_attr(R_NS, "embed"))
                        target = rel_map.get(rel_id)
                        if not rel_id or not target:
                            continue
                        package_path = "word/" + target.lstrip("/")
                        try:
                            blob = archive.read(package_path)
                        except KeyError:
                            continue
                        digest = hashlib.sha256(blob).hexdigest()
                        asset_id = "asset_" + digest[:16]
                        suffix = package_path.rsplit(".", 1)[-1].lower() if "." in package_path else "bin"
                        mime = {
                            "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
                            "gif": "image/gif", "bmp": "image/bmp", "tif": "image/tiff", "tiff": "image/tiff",
                            "emf": "image/emf", "wmf": "image/wmf",
                        }.get(suffix, "application/octet-stream")
                        assets[asset_id] = {
                            "asset_id": asset_id,
                            "source_file_id": "source_1",
                            "relationship_id": rel_id,
                            "package_path": package_path,
                            "sha256": digest,
                            "size_bytes": len(blob),
                            "mime_type": mime,
                        }
                        ids.append(asset_id)
                    if ids:
                        drawing_map[(unit_index, row_index, cell_index, paragraph_index)] = ids
                unit_index += 1
    except Exception:
        return {}, []
    return drawing_map, list(assets.values())


def _source_records(
    normalized: dict[str, Any],
    source_bytes: bytes,
) -> tuple[list[dict[str, Any]], int, list[dict[str, Any]]]:
    content = normalized["content"]
    units = content.get("units")
    if units is None:
        records = []
        for block_index, page in enumerate(content.get("pages", [])):
            text = page.get("effective_text", "")
            if not text.strip():
                continue
            records.append({
                "block_index": block_index,
                "source_text": text,
                "marking_text": "",
                "allocation_text": "",
                "paragraphs": [{
                    "text": text,
                    "equations": [],
                    "source_ref": {"file_id": "source_1", "page": int(page.get("page") or 1)},
                }],
            })
        return records, max([p.get("page", 1) for p in content.get("pages", [])] or [1]), []

    page_map, page_count = _docx_page_map(source_bytes)
    drawing_map, assets = _docx_asset_map(source_bytes)
    records: list[dict[str, Any]] = []
    block_index = 0

    for unit_index, unit in enumerate(units):
        if unit.get("type") == "paragraph":
            text = unit.get("text", "")
            if text.strip():
                records.append({
                    "block_index": block_index,
                    "source_text": text,
                    "marking_text": "",
                    "allocation_text": "",
                    "paragraphs": [{
                        "text": text,
                        "segments": unit.get("segments") or [],
                        "equations": unit.get("equations") or [],
                        "drawing_assets": drawing_map.get((unit_index, None, None, 0), []),
                        "source_ref": {
                            "file_id": "source_1",
                            "page": page_map.get((unit_index, None, None, 0), 1),
                            "docx_anchor": {"unit_index": unit_index, "paragraph_index": 0},
                        },
                    }],
                })
                block_index += 1
            continue

        if unit.get("type") != "table":
            continue

        for row_index, row in enumerate(unit.get("rows", [])):
            cells = [cell.get("text", "") for cell in row]
            if not any(cell.strip() for cell in cells):
                continue

            if len(cells) == 1:
                source_cell_indexes = [0]
                marking_text = ""
                allocation_text = ""
            elif len(cells) == 2:
                source_cell_indexes = [0]
                marking_text = cells[1]
                allocation_text = cells[1]
            elif len(cells) == 3:
                source_cell_indexes = [0, 1]
                marking_text = cells[2]
                allocation_text = cells[2]
            else:
                source_cell_indexes = list(range(0, len(cells) - 2))
                marking_text = cells[-2]
                allocation_text = cells[-1]

            paragraphs: list[dict[str, Any]] = []
            for cell_index in source_cell_indexes:
                cell = row[cell_index]
                for paragraph_index, paragraph in enumerate(cell.get("paragraphs", [])):
                    text = paragraph.get("text", "")
                    drawing_assets = drawing_map.get((unit_index, row_index, cell_index, paragraph_index), [])
                    if not text.strip() and not paragraph.get("equations") and not drawing_assets:
                        continue
                    paragraphs.append({
                        "text": text,
                        "segments": paragraph.get("segments") or [],
                        "equations": paragraph.get("equations") or [],
                        "drawing_assets": drawing_assets,
                        "source_ref": {
                            "file_id": "source_1",
                            "page": page_map.get((unit_index, row_index, cell_index, paragraph_index), 1),
                            "docx_anchor": {
                                "unit_index": unit_index,
                                "row_index": row_index,
                                "cell_index": cell_index,
                                "paragraph_index": paragraph_index,
                            },
                        },
                    })

            records.append({
                "block_index": block_index,
                "source_text": "\n".join(cells[i] for i in source_cell_indexes),
                "marking_text": marking_text,
                "allocation_text": allocation_text,
                "paragraphs": paragraphs,
            })
            block_index += 1

    return records, page_count, assets


def _all_normalized_text(normalized: dict[str, Any]) -> str:
    content = normalized["content"]
    if content.get("units") is None:
        return "\n".join(page.get("effective_text", "") for page in content.get("pages", []))
    chunks: list[str] = []
    for unit in content.get("units", []):
        if unit.get("type") == "paragraph":
            chunks.append(unit.get("text", ""))
        elif unit.get("type") == "table":
            for row in unit.get("rows", []):
                chunks.extend(cell.get("text", "") for cell in row)
    return "\n".join(chunks)


def _slice_ordered_segments(
    segments: list[dict[str, Any]],
    start: int,
    end: int,
) -> list[dict[str, Any]]:
    if end <= start:
        return []
    result: list[dict[str, Any]] = []
    cursor = 0
    for segment in segments:
        value = str(segment.get("text") or "")
        seg_start = cursor
        seg_end = cursor + len(value)
        cursor = seg_end
        if seg_end <= start or seg_start >= end:
            continue
        left = max(start, seg_start) - seg_start
        right = min(end, seg_end) - seg_start
        if segment.get("type") == "math":
            # Question identifiers live in ordinary text in the controlled
            # benchmarks. If a boundary ever cuts an equation, preserve the
            # complete equation rather than fabricate partial mathematics.
            if left == 0 and right == len(value):
                result.append(dict(segment))
            else:
                result.append(dict(segment))
        else:
            piece = value[left:right]
            if piece:
                item = dict(segment)
                item["text"] = piece
                result.append(item)
    return result


def _paragraph_from_slice(
    paragraph: dict[str, Any],
    start: int,
    end: int,
    *,
    keep_drawings: bool,
) -> dict[str, Any] | None:
    ordered = paragraph.get("segments") or []
    if not ordered:
        text = str(paragraph.get("text") or "")[start:end]
        if not text.strip() and not (keep_drawings and paragraph.get("drawing_assets")):
            return None
        return {
            **paragraph,
            "text": text,
            "drawing_assets": paragraph.get("drawing_assets") or [] if keep_drawings else [],
        }

    sliced = _slice_ordered_segments(ordered, start, end)
    text = "".join(str(item.get("text") or "") for item in sliced)
    equations = [
        {"text": item.get("text") or "", "omml": item.get("omml") or ""}
        for item in sliced
        if item.get("type") == "math"
    ]
    drawings = paragraph.get("drawing_assets") or [] if keep_drawings else []
    if not text.strip() and not equations and not drawings:
        return None
    return {
        **paragraph,
        "text": text,
        "segments": sliced,
        "equations": equations,
        "drawing_assets": drawings,
    }


def _qid_segments(record: dict[str, Any], qids: list[str]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {qid: [] for qid in qids}
    deepest = sorted(qids, key=lambda value: (value.count("."), len(value)), reverse=True)
    current: str | None = qids[0] if len(qids) == 1 else None

    for paragraph in record["paragraphs"]:
        text = paragraph.get("text", "")
        matches = list(QUESTION_TOKEN_RE.finditer(text))
        if not matches:
            if current is not None:
                result.setdefault(current, []).append(paragraph)
            continue

        if current is not None and matches[0].start() > 0:
            prefix = _paragraph_from_slice(
                paragraph,
                0,
                matches[0].start(),
                keep_drawings=False,
            )
            if prefix is not None:
                result.setdefault(current, []).append(prefix)

        last_matched: str | None = None
        for idx, match in enumerate(matches):
            qid = match.group(1)
            if qid not in result:
                continue
            last_matched = qid
            start = match.end()
            end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
            sliced = _paragraph_from_slice(
                paragraph,
                start,
                end,
                keep_drawings=idx == len(matches) - 1,
            )
            if sliced is not None:
                result[qid].append(sliced)

        if last_matched is not None:
            descendants = [candidate for candidate in deepest if candidate.startswith(last_matched + ".")]
            current = descendants[0] if descendants else last_matched

    return result


def _split_alternative_segments(segments: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    branches: list[list[dict[str, Any]]] = [[]]
    for segment in segments:
        raw_text = str(segment.get("text") or "")
        collapsed = _collapse(raw_text)

        # A source-side OR is structural only when it occupies the whole
        # paragraph or starts the paragraph as a standalone word. This avoids
        # confusing ordinary inline "or" answer notation with competing
        # solution paths.
        match = re.match(r"(?i)^\s*OR\b", raw_text)
        if collapsed.upper() == "OR" or match is not None:
            branches.append([])
            if match is not None and match.end() < len(raw_text):
                remainder = _paragraph_from_slice(
                    segment,
                    match.end(),
                    len(raw_text),
                    keep_drawings=True,
                )
                if remainder is not None and _collapse(remainder.get("text", "")):
                    branches[-1].append(remainder)
            continue

        branches[-1].append(segment)

    return [branch for branch in branches if branch] or [[]]


def _source_ref(segment: dict[str, Any]) -> list[dict[str, Any]]:
    ref = segment.get("source_ref")
    return [ref] if isinstance(ref, dict) else []


def _blocks_from_segments(
    qid: str,
    alternative_label: str,
    segments: list[dict[str, Any]],
    issues: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    safe_qid = qid.replace(".", "_")

    def add_block(payload: dict[str, Any]) -> None:
        payload["block_id"] = f"b_{safe_qid}_{alternative_label.lower()}_{len(blocks) + 1}"
        blocks.append(payload)

    def add_text_block(value: str, refs: list[dict[str, Any]]) -> None:
        text = _collapse(value)
        if not text or re.fullmatch(r"\d{1,2}(?:\.\d{1,2}){0,2}\.?", text):
            return
        if _looks_math_like(text):
            try:
                latex = plain_math_to_latex(text)
                add_block({
                    "type": "math",
                    "semantic_role": "working",
                    "math": {
                        "source_text": text,
                        "canonical_latex": latex,
                        "presentation_mathml": None,
                        "plain_text": text,
                        "display_mode": "display",
                    },
                    "source_refs": refs,
                    "confidence": {"score": 0.95, "band": "green", "rationale": "Plain mathematical text used only within the approved deterministic subset."},
                    "warnings": ["PLAIN_MATH_SOURCE"],
                })
            except CanonicalizationError as exc:
                issues.append({
                    "level": "amber",
                    "category": "math_plain_text_ambiguous",
                    "affected_id": qid,
                    "message": exc.public_message,
                })
            return
        add_block({
            "type": "prose",
            "semantic_role": "working",
            "text": text,
            "source_refs": refs,
            "confidence": {"score": 1.0, "band": "green", "rationale": "Source prose preserved verbatim apart from whitespace normalization."},
            "warnings": [],
        })

    for segment in segments:
        text = _collapse(segment.get("text", ""))
        if text.upper() == "OR" and not segment.get("equations"):
            continue
        drawings = segment.get("drawing_assets") or []
        refs = _source_ref(segment)

        for asset_id in drawings:
            add_block({
                "type": "figure",
                "semantic_role": "diagram",
                "figure": {"asset_id": asset_id},
                "source_refs": refs,
                "confidence": {"score": 1.0, "band": "green", "rationale": "Drawing relationship resolved from the DOCX package."},
                "warnings": [],
            })

        ordered = segment.get("segments") or []
        if ordered:
            for inline in ordered:
                inline_type = inline.get("type")
                inline_text = str(inline.get("text") or "")
                if inline_type == "math":
                    source_text = _collapse(inline_text)
                    try:
                        latex = omml_to_latex(str(inline.get("omml") or ""))
                    except CanonicalizationError as exc:
                        issues.append({
                            "level": "red",
                            "category": "math_canonicalization_failed",
                            "affected_id": qid,
                            "message": exc.public_message,
                        })
                        continue
                    add_block({
                        "type": "math",
                        "semantic_role": "working",
                        "math": {
                            "source_text": source_text,
                            "canonical_latex": latex,
                            "presentation_mathml": None,
                            "plain_text": source_text,
                            "display_mode": "display",
                        },
                        "source_refs": refs,
                        "confidence": {"score": 1.0, "band": "green", "rationale": "Derived deterministically from Office Math in original inline order."},
                        "warnings": [],
                    })
                else:
                    add_text_block(inline_text, refs)
            continue

        equations = segment.get("equations") or []
        if equations:
            residual = text
            for equation in equations:
                source_text = _collapse(equation.get("text", ""))
                try:
                    latex = omml_to_latex(equation.get("omml", ""))
                except CanonicalizationError as exc:
                    issues.append({
                        "level": "red",
                        "category": "math_canonicalization_failed",
                        "affected_id": qid,
                        "message": exc.public_message,
                    })
                    continue
                add_block({
                    "type": "math",
                    "semantic_role": "working",
                    "math": {
                        "source_text": source_text,
                        "canonical_latex": latex,
                        "presentation_mathml": None,
                        "plain_text": source_text,
                        "display_mode": "display",
                    },
                    "source_refs": refs,
                    "confidence": {"score": 1.0, "band": "green", "rationale": "Derived deterministically from Office Math."},
                    "warnings": [],
                })
                if source_text and source_text in residual:
                    residual = residual.replace(source_text, "", 1).strip()
            add_text_block(residual, refs)
            continue

        add_text_block(text, refs)

    if blocks:
        for block in reversed(blocks):
            if block["type"] == "math":
                block["semantic_role"] = "answer"
                break
    return blocks


def _semantic_lookup(semantic: dict[str, Any]) -> dict[tuple[str, int], dict[str, Any]]:
    lookup: dict[tuple[str, int], dict[str, Any]] = {}
    for item in semantic.get("deterministic_results", []) + semantic.get("ai_results", []):
        try:
            lookup[(str(item["question_id"]), int(item["mark_index"]))] = item
        except Exception:
            continue
    return lookup


def _mark_links(mark_type: str, blocks: list[dict[str, Any]]) -> list[str]:
    if not blocks:
        return []
    math_blocks = [b for b in blocks if b["type"] == "math"]
    prose_blocks = [b for b in blocks if b["type"] != "math"]
    preferred = math_blocks or blocks

    if mark_type in {"answer", "consistent_accuracy", "conclusion", "graph_feature", "selection"}:
        return [preferred[-1]["block_id"]]
    if mark_type == "formula":
        for block in math_blocks:
            latex = block.get("math", {}).get("canonical_latex", "")
            if "\\frac" in latex or "\\sqrt" in latex:
                return [block["block_id"]]
        return [preferred[0]["block_id"]]
    if mark_type == "factorisation":
        factor_blocks = [
            b for b in math_blocks
            if "\\left(" in b.get("math", {}).get("canonical_latex", "")
            or ")(" in b.get("math", {}).get("source_text", "")
        ]
        return [b["block_id"] for b in factor_blocks[-2:]] or [b["block_id"] for b in preferred]
    if mark_type in {"reason", "statement_reason"} and prose_blocks:
        return [prose_blocks[-1]["block_id"]]
    return [b["block_id"] for b in preferred]


def _marking_points_for_alternatives(
    qid: str,
    qdata: dict[str, Any],
    marking_text: str,
    alternative_blocks: list[list[dict[str, Any]]],
    semantic_lookup: dict[tuple[str, int], dict[str, Any]],
    issues: list[dict[str, Any]],
) -> list[list[dict[str, Any]]]:
    """
    Build mark points for explicit solution alternatives without conflating
    marking-side partial-credit rules with genuine solution alternatives.

    Three cases are intentionally distinguished:
    1. source and marking both expose OR branches -> pair branch-to-branch;
    2. source exposes OR, marking has one scheme -> apply the shared scheme
       independently to each competing solution branch;
    3. marking exposes OR but source has one solution -> treat lower-mark
       branches as conditional partial-credit rules when Phase 3 already
       established alternative_max arithmetic. Do not manufacture a second
       mathematical solution.
    """
    source_branch_count = max(1, len(alternative_blocks))

    if OR_LINE_RE.search(marking_text):
        raw_mark_branches = [
            branch for branch in OR_LINE_RE.split(marking_text)
            if _collapse(branch)
        ]
        parsed_mark_branches = [parse_mark_points(branch) for branch in raw_mark_branches]
    else:
        raw_mark_branches = [marking_text]
        parsed_mark_branches = [qdata.get("mark_points") or []]

    partial_credit_rules: list[dict[str, Any]] = []
    if (
        source_branch_count == 1
        and len(parsed_mark_branches) > 1
        and qdata.get("mark_calculation_mode") == "alternative_max"
    ):
        totals = [
            sum(int(point.get("count") or 1) for point in branch)
            for branch in parsed_mark_branches
        ]
        max_total = max(totals or [0])
        observed = qdata.get("printed_marks")
        expected_max = (
            int(observed)
            if observed is not None
            else int(qdata.get("computed_shorthand_marks") or 0)
        )

        if max_total and (not expected_max or max_total == expected_max):
            primary_index = totals.index(max_total)
            primary_points = parsed_mark_branches[primary_index]

            for branch_index, (branch, total) in enumerate(
                zip(parsed_mark_branches, totals)
            ):
                if branch_index == primary_index:
                    continue
                if total <= 0 or total >= max_total:
                    continue
                partial_credit_rules.append({
                    "count": total,
                    "descriptor": "; ".join(
                        _collapse(point.get("descriptor", ""))
                        for point in branch
                        if _collapse(point.get("descriptor", ""))
                    ) or _collapse(raw_mark_branches[branch_index]),
                    "source": _collapse(raw_mark_branches[branch_index]),
                })

            parsed_mark_branches = [primary_points]
            raw_mark_branches = [raw_mark_branches[primary_index]]
        else:
            issues.append({
                "level": "amber",
                "category": "alternative_source_marking_conflict",
                "affected_id": qid,
                "message": (
                    "Marking-side alternatives cannot be represented safely as "
                    "conditional partial credit for this single source solution."
                ),
            })

    shared_marking_scheme = (
        source_branch_count > 1
        and len(parsed_mark_branches) == 1
    )
    if shared_marking_scheme:
        parsed_mark_branches = [
            [dict(point) for point in parsed_mark_branches[0]]
            for _ in range(source_branch_count)
        ]
        raw_mark_branches = [
            raw_mark_branches[0]
            for _ in range(source_branch_count)
        ]

    if len(parsed_mark_branches) != source_branch_count:
        issues.append({
            "level": "amber",
            "category": "alternative_source_marking_conflict",
            "affected_id": qid,
            "message": (
                "Source solution and marking columns expose incompatible "
                "alternative structures and require review."
            ),
        })

    result: list[list[dict[str, Any]]] = []
    safe_qid = qid.replace(".", "_")

    for branch_index in range(source_branch_count):
        points = (
            parsed_mark_branches[branch_index]
            if branch_index < len(parsed_mark_branches)
            else []
        )
        blocks = (
            alternative_blocks[branch_index]
            if branch_index < len(alternative_blocks)
            else []
        )
        built: list[dict[str, Any]] = []
        branch_key = "primary" if branch_index == 0 else f"or{branch_index}"

        for point_index, point in enumerate(points):
            if shared_marking_scheme:
                semantic_index = point_index
            else:
                semantic_index = (
                    sum(len(branch) for branch in parsed_mark_branches[:branch_index])
                    + point_index
                )

            sem = semantic_lookup.get((qid, semantic_index), {})
            mark_type = sem.get("semantic_type") or point.get("semantic") or "other"

            raw_descriptor = _collapse(point.get("descriptor", ""))
            # CA wording is itself deterministic marking evidence. Preserve the
            # Phase 4 decision unless the source explicitly marks the point as
            # consistent accuracy, in which case source evidence is authoritative.
            if point.get("code") == "CA" or re.search(r"(?i)\bCA\b", raw_descriptor):
                mark_type = "consistent_accuracy"

            if mark_type not in MARK_TYPES:
                mark_type = "other"

            descriptor = (
                raw_descriptor
                or DEFAULT_DESCRIPTOR[mark_type]
            )
            descriptor = descriptor.replace("✓", "").strip()

            warnings: list[str] = []
            source_shorthand = point.get("source") or None
            if branch_index == 0 and point_index == 0 and partial_credit_rules:
                rule_texts = []
                for rule in partial_credit_rules:
                    desc = _collapse(rule.get("descriptor", ""))
                    count = int(rule.get("count") or 0)
                    if desc and count:
                        plural = "mark" if count == 1 else "marks"
                        rule_texts.append(f"{count} {plural} for {desc}")
                if rule_texts:
                    descriptor = (
                        f"{descriptor}; partial credit: "
                        + "; ".join(rule_texts)
                    )
                    warnings.append("PARTIAL_CREDIT_RULE")
                    raw_rules = [
                        str(rule.get("source") or "")
                        for rule in partial_credit_rules
                        if rule.get("source")
                    ]
                    if raw_rules:
                        source_shorthand = (
                            (source_shorthand + " OR " if source_shorthand else "")
                            + " OR ".join(raw_rules)
                        )

            mark_id = f"m_{safe_qid}_{branch_key}_{point_index + 1}"
            built.append({
                "mark_id": mark_id,
                "type": mark_type,
                "count": int(point.get("count") or 1),
                "descriptor": descriptor,
                "applies_to_block_ids": _mark_links(mark_type, blocks),
                "source_shorthand": source_shorthand,
                "consistent_accuracy": {
                    "enabled": mark_type == "consistent_accuracy",
                    "dependency_item_ids": (
                        [
                            _canonical_id_for_qid(match.group(1))
                            for match in re.finditer(
                                r"(?i)\bCA\s+from\s+(\d{1,2}(?:\.\d{1,2}){0,2})\b",
                                descriptor,
                            )
                        ]
                        if mark_type == "consistent_accuracy"
                        else []
                    ),
                },
                "acceptable_variants": [],
                "source_refs": (
                    blocks[-1].get("source_refs", []) if blocks else []
                ),
                "confidence": {
                    "score": float(sem.get("confidence_score", 1.0)),
                    "band": sem.get("band", "green"),
                    "rationale": sem.get(
                        "rationale",
                        "Preserved from interpreted mark semantics.",
                    ),
                },
                "warnings": warnings,
            })
            if not blocks:
                issues.append({
                    "level": "red",
                    "category": "mark_link_missing",
                    "affected_id": qid,
                    "message": (
                        f"Mark {mark_id} has no solution block that it can reference."
                    ),
                })
        result.append(built)

    return result


def _canonical_id_for_qid(qid: str) -> str:
    return "q" + qid.replace(".", "_")


def _exception_record(item: dict[str, Any]) -> dict[str, Any]:
    affected = item.get("affected_id")
    affected_ids = []
    if affected:
        for token in str(affected).split(","):
            token = token.strip()
            if re.fullmatch(r"\d{1,2}(?:\.\d{1,2}){0,2}", token):
                affected_ids.append(_canonical_id_for_qid(token))
            elif token:
                affected_ids.append(token)
    key = f"{item.get('level')}|{item.get('category')}|{affected}|{item.get('message')}"
    exception_id = "ex_" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
    suggestions = item.get("suggestions") or []
    actions = ["type_edit", "take_photo", "upload_file"]
    if item.get("level") == "amber" and suggestions:
        actions.insert(0, "select_suggestion")
    return {
        "exception_id": exception_id,
        "level": item.get("level", "amber"),
        "category": item.get("category", "other"),
        "affected_ids": affected_ids,
        "message": item.get("message", "Review is required."),
        "suggestions": suggestions,
        "allowed_user_actions": actions,
        "status": "open",
        "resolved_by_correction_id": None,
    }


def _dedupe_issues(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str | None, str]] = set()
    result: list[dict[str, Any]] = []
    for item in items:
        key = (str(item.get("category")), item.get("affected_id"), str(item.get("message")))
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _build_item_tree(
    major: int,
    qmap: dict[str, dict[str, Any]],
    segments_by_qid: dict[str, list[dict[str, Any]]],
    record_by_block: dict[int, dict[str, Any]],
    semantic_lookup: dict[tuple[str, int], dict[str, Any]],
    issues: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    qids = sorted(
        [qid for qid in qmap if int(qid.split(".")[0]) == major],
        key=lambda value: tuple(int(part) for part in value.split(".")),
    )
    paths = {qid: tuple(int(part) for part in qid.split(".")) for qid in qids}
    represented = set(paths.values())
    for path in list(represented):
        for depth in range(2, len(path)):
            represented.add(path[:depth])

    children: dict[tuple[int, ...], list[tuple[int, ...]]] = {}
    for path in represented:
        if len(path) >= 2:
            children.setdefault(path[:-1], []).append(path)
    for values in children.values():
        values.sort()

    def build_path(path: tuple[int, ...]) -> dict[str, Any]:
        qid = ".".join(map(str, path))
        qdata = qmap.get(qid)
        child_paths = children.get(path, [])
        item_id = _canonical_id_for_qid(qid)
        context_blocks: list[dict[str, Any]] = []
        alternatives: list[dict[str, Any]] = []

        if qdata is not None:
            segments = segments_by_qid.get(qid, [])
            if child_paths:
                context_blocks = _blocks_from_segments(qid, "context", segments, issues)
            else:
                source_branches = _split_alternative_segments(segments)
                alt_blocks = [
                    _blocks_from_segments(qid, "primary" if idx == 0 else f"or{idx}", branch, issues)
                    for idx, branch in enumerate(source_branches)
                ]
                record = record_by_block.get(int(qdata.get("source_block_index", -1)), {})
                mark_branches = _marking_points_for_alternatives(
                    qid,
                    qdata,
                    record.get("marking_text", ""),
                    alt_blocks,
                    semantic_lookup,
                    issues,
                )
                for idx, blocks in enumerate(alt_blocks):
                    label = "PRIMARY" if idx == 0 else "OR"
                    marks = mark_branches[min(idx, len(mark_branches) - 1)] if mark_branches else []
                    alternatives.append({
                        "alternative_id": f"{item_id}_{'primary' if idx == 0 else 'or' + str(idx)}",
                        "label": label,
                        "blocks": blocks,
                        "marking_points": marks,
                        "marks_computed": sum(mark["count"] for mark in marks),
                        "source_refs": blocks[0].get("source_refs", []) if blocks else [],
                    })

        child_items = [build_path(child) for child in child_paths]
        if child_items:
            computed = sum(int(child["marks"]["computed"] or 0) for child in child_items)
        else:
            computed = max([int(alt["marks_computed"]) for alt in alternatives] or [0])
        observed = qdata.get("printed_marks") if qdata else None
        status = "not_applicable"
        if observed is not None:
            status = "match" if int(observed) == computed else "mismatch"
        elif computed:
            status = "missing_observed"

        return {
            "item_id": item_id,
            "number": qid,
            "context_blocks": context_blocks,
            "children": child_items,
            "alternatives": alternatives,
            "marks": {"observed": observed, "computed": computed, "status": status},
            "source_refs": (context_blocks[0].get("source_refs", []) if context_blocks else (alternatives[0].get("source_refs", []) if alternatives else [])),
            "confidence": {"score": 1.0, "band": "green", "rationale": "Question hierarchy is deterministic after Phase 3 gates."},
            "warnings": [],
        }

    top_paths = sorted(children.get((major,), []))
    return [build_path(path) for path in top_paths]


def _iter_items(items: list[dict[str, Any]]):
    for item in items:
        yield item
        yield from _iter_items(item.get("children", []))


def _iter_blocks(items: list[dict[str, Any]]):
    for item in _iter_items(items):
        for block in item.get("context_blocks", []):
            yield block
        for alt in item.get("alternatives", []):
            for block in alt.get("blocks", []):
                yield block


def _iter_marks(items: list[dict[str, Any]]):
    for item in _iter_items(items):
        for alt in item.get("alternatives", []):
            for mark in alt.get("marking_points", []):
                yield mark


def validate_canonical(memo: dict[str, Any]) -> dict[str, Any]:
    """
    Deterministic validator for the controlled Interpretation Schema v1.0.

    The explanatory Drive schema is currently the controlled baseline; the
    machine-readable companion JSON file is not available. These checks
    therefore implement the named cross-object invariants without pretending to
    replace the missing normative JSON Schema.
    """
    issues: list[dict[str, Any]] = []
    ids: list[str] = []

    required_root = {
        "schema_version", "document_id", "status", "source", "document_metadata",
        "render_profile", "notes", "questions", "totals", "exceptions",
        "corrections", "audit",
    }
    missing_root = sorted(required_root - set(memo))
    if missing_root:
        issues.append({
            "level": "red",
            "category": "schema_shape_invalid",
            "affected_id": None,
            "message": "Canonical root is missing required fields: " + ", ".join(missing_root) + ".",
        })

    source = memo.get("source") or {}
    source_files = source.get("files") or []
    file_ids = {
        str(item.get("file_id"))
        for item in source_files
        if item.get("file_id")
    }
    ids.extend(sorted(file_ids))
    page_limits = {
        str(item.get("file_id")): int(item.get("page_count") or 0)
        for item in source_files
        if item.get("file_id")
    }

    asset_ids: set[str] = set()
    for asset in source.get("assets") or []:
        asset_id = asset.get("asset_id")
        if asset_id:
            ids.append(str(asset_id))
            asset_ids.add(str(asset_id))
        source_file_id = asset.get("source_file_id")
        if source_file_id and source_file_id not in file_ids:
            issues.append({
                "level": "red",
                "category": "asset_source_unresolved",
                "affected_id": str(asset_id) if asset_id else None,
                "message": "A figure asset refers to an unknown source file.",
            })

    def validate_source_refs(
        refs: list[dict[str, Any]] | None,
        *,
        affected_id: str | None,
    ) -> None:
        for ref in refs or []:
            file_id = ref.get("file_id")
            if file_id not in file_ids:
                issues.append({
                    "level": "red",
                    "category": "source_ref_unresolved",
                    "affected_id": affected_id,
                    "message": "A canonical source reference points to an unknown source file.",
                })
                continue
            page = ref.get("page")
            limit = page_limits.get(str(file_id), 0)
            if page is not None:
                try:
                    page_num = int(page)
                except Exception:
                    page_num = 0
                if page_num < 1 or (limit and page_num > limit):
                    issues.append({
                        "level": "red",
                        "category": "source_ref_page_invalid",
                        "affected_id": affected_id,
                        "message": "A canonical source reference contains an invalid page number.",
                    })

    ordered_items: list[dict[str, Any]] = []
    item_question_major: dict[str, str] = {}
    for question in memo.get("questions", []):
        for item in _iter_items(question.get("items", [])):
            ordered_items.append(item)
            item_question_major[item["item_id"]] = str(question.get("number"))

    item_order = {
        str(item["item_id"]): index
        for index, item in enumerate(ordered_items)
    }
    item_ids = set(item_order)

    for question in memo.get("questions", []):
        question_id = str(question["question_id"])
        question_number = str(question["number"])
        ids.append(question_id)
        validate_source_refs(question.get("source_refs"), affected_id=question_number)

        try:
            major_number = int(question_number)
        except Exception:
            major_number = None

        top_items = question.get("items", [])
        for item in _iter_items(top_items):
            item_id = str(item["item_id"])
            item_number = str(item["number"])
            ids.append(item_id)
            validate_source_refs(item.get("source_refs"), affected_id=item_number)

            if major_number is not None:
                try:
                    number_parts = tuple(int(part) for part in item_number.split("."))
                except Exception:
                    number_parts = ()
                if not number_parts or number_parts[0] != major_number:
                    issues.append({
                        "level": "red",
                        "category": "number_tree_invalid",
                        "affected_id": item_number,
                        "message": f"Item {item_number} does not belong to Question {major_number}.",
                    })

            children = item.get("children", [])
            for child in children:
                child_number = str(child.get("number") or "")
                if not child_number.startswith(item_number + "."):
                    issues.append({
                        "level": "red",
                        "category": "number_tree_invalid",
                        "affected_id": child_number or item_number,
                        "message": (
                            f"Child item {child_number or '[missing]'} does not match "
                            f"parent hierarchy {item_number}."
                        ),
                    })

            alternatives = item.get("alternatives", [])
            computed = int(item.get("marks", {}).get("computed") or 0)
            if not children and computed > 0 and not alternatives:
                issues.append({
                    "level": "red",
                    "category": "leaf_solution_missing",
                    "affected_id": item_number,
                    "message": f"Scored leaf {item_number} has no solution alternative.",
                })

            alt_marks = [
                int(alt.get("marks_computed") or 0)
                for alt in alternatives
                if alt.get("label") != "NOTE_ONLY"
            ]
            if len(set(alt_marks)) > 1:
                issues.append({
                    "level": "amber",
                    "category": "alternative_mark_conflict",
                    "affected_id": item_number,
                    "message": (
                        f"Scored alternatives for {item_number} do not have "
                        "the same maximum."
                    ),
                })

            canonical_item_computed = (
                sum(int(child.get("marks", {}).get("computed") or 0) for child in children)
                if children
                else max(alt_marks or [0])
            )
            if canonical_item_computed != computed:
                issues.append({
                    "level": "red",
                    "category": "item_computed_inconsistent",
                    "affected_id": item_number,
                    "message": (
                        f"Item {item_number} stores computed marks {computed} but "
                        f"its canonical children/alternatives compute to {canonical_item_computed}."
                    ),
                })

            observed = item.get("marks", {}).get("observed")
            if observed is not None and int(observed) != computed:
                issues.append({
                    "level": "red",
                    "category": "item_total_mismatch",
                    "affected_id": item_number,
                    "message": (
                        f"Item {item_number} prints ({observed}) but canonical "
                        f"marks compute to {computed}."
                    ),
                })

            for block in item.get("context_blocks", []):
                block_id = str(block["block_id"])
                ids.append(block_id)
                validate_source_refs(block.get("source_refs"), affected_id=item_number)
                if block.get("type") == "figure":
                    asset_id = block.get("figure", {}).get("asset_id")
                    if asset_id not in asset_ids:
                        issues.append({
                            "level": "red",
                            "category": "asset_unresolved",
                            "affected_id": item_number,
                            "message": (
                                f"Figure block {block_id} references an unknown asset."
                            ),
                        })
                if block.get("type") == "math":
                    math = block.get("math") or {}
                    for field in ("source_text", "canonical_latex", "plain_text", "display_mode"):
                        if not math.get(field):
                            issues.append({
                                "level": "red",
                                "category": "math_shape_invalid",
                                "affected_id": item_number,
                                "message": f"Math block {block_id} is missing required field {field}.",
                            })
                    try:
                        validate_latex_subset(str(math.get("canonical_latex") or ""))
                    except CanonicalizationError as exc:
                        issues.append({
                            "level": "red",
                            "category": "math_parse_failed",
                            "affected_id": item_number,
                            "message": exc.public_message,
                        })

            for alt in alternatives:
                alternative_id = str(alt["alternative_id"])
                ids.append(alternative_id)
                validate_source_refs(alt.get("source_refs"), affected_id=item_number)
                alt_blocks = alt.get("blocks", [])
                alt_block_ids = {
                    str(block["block_id"])
                    for block in alt_blocks
                    if block.get("block_id")
                }

                for block in alt_blocks:
                    block_id = str(block["block_id"])
                    ids.append(block_id)
                    validate_source_refs(block.get("source_refs"), affected_id=item_number)

                    if block.get("type") == "figure":
                        asset_id = block.get("figure", {}).get("asset_id")
                        if asset_id not in asset_ids:
                            issues.append({
                                "level": "red",
                                "category": "asset_unresolved",
                                "affected_id": item_number,
                                "message": (
                                    f"Figure block {block_id} references an unknown asset."
                                ),
                            })

                    if block.get("type") == "math":
                        math = block.get("math") or {}
                        for field in ("source_text", "canonical_latex", "plain_text", "display_mode"):
                            if not math.get(field):
                                issues.append({
                                    "level": "red",
                                    "category": "math_shape_invalid",
                                    "affected_id": item_number,
                                    "message": f"Math block {block_id} is missing required field {field}.",
                                })
                        try:
                            validate_latex_subset(str(math.get("canonical_latex") or ""))
                        except CanonicalizationError as exc:
                            issues.append({
                                "level": "red",
                                "category": "math_parse_failed",
                                "affected_id": item_number,
                                "message": exc.public_message,
                            })

                mark_sum = 0
                for mark in alt.get("marking_points", []):
                    mark_id = str(mark["mark_id"])
                    ids.append(mark_id)
                    mark_sum += int(mark.get("count") or 0)
                    validate_source_refs(mark.get("source_refs"), affected_id=item_number)

                    descriptor = _collapse(mark.get("descriptor", ""))
                    if not descriptor or "✓" in descriptor:
                        issues.append({
                            "level": "red",
                            "category": "mark_descriptor_invalid",
                            "affected_id": item_number,
                            "message": f"Mark {mark_id} has an invalid descriptor.",
                        })

                    linked = mark.get("applies_to_block_ids") or []
                    if not linked:
                        issues.append({
                            "level": "amber",
                            "category": "mark_link_missing",
                            "affected_id": item_number,
                            "message": f"Mark {mark_id} is not linked to a solution block.",
                        })
                    for block_id in linked:
                        if block_id not in alt_block_ids:
                            issues.append({
                                "level": "red",
                                "category": "mark_link_invalid",
                                "affected_id": item_number,
                                "message": (
                                    f"Mark {mark_id} references a block outside "
                                    "its alternative."
                                ),
                            })

                    ca = mark.get("consistent_accuracy") or {}
                    enabled = bool(ca.get("enabled"))
                    if mark.get("type") == "consistent_accuracy" and not enabled:
                        issues.append({
                            "level": "red",
                            "category": "ca_flag_invalid",
                            "affected_id": item_number,
                            "message": f"CA mark {mark_id} is not flagged as consistent accuracy.",
                        })
                    if mark.get("type") != "consistent_accuracy" and enabled:
                        issues.append({
                            "level": "red",
                            "category": "ca_flag_invalid",
                            "affected_id": item_number,
                            "message": f"Non-CA mark {mark_id} is incorrectly flagged as consistent accuracy.",
                        })

                    for dependency in ca.get("dependency_item_ids") or []:
                        dependency = str(dependency)
                        if dependency not in item_ids:
                            issues.append({
                                "level": "red",
                                "category": "ca_dependency_unresolved",
                                "affected_id": item_number,
                                "message": (
                                    f"CA mark {mark_id} refers to unknown dependency "
                                    f"{dependency}."
                                ),
                            })
                        elif item_order[dependency] >= item_order.get(item_id, 10**9):
                            issues.append({
                                "level": "amber",
                                "category": "ca_dependency_not_earlier",
                                "affected_id": item_number,
                                "message": (
                                    f"CA dependency {dependency} is not earlier than "
                                    f"item {item_number}."
                                ),
                            })

                if int(alt.get("marks_computed") or 0) != mark_sum:
                    issues.append({
                        "level": "red",
                        "category": "alternative_total_inconsistent",
                        "affected_id": item_number,
                        "message": (
                            f"Alternative {alternative_id} stores "
                            f"{alt.get('marks_computed')} marks but its marking "
                            f"points sum to {mark_sum}."
                        ),
                    })

        subtotal = question.get("subtotal", {})
        stored_subtotal = int(subtotal.get("computed") or 0)
        computed_subtotal = sum(
            int(item.get("marks", {}).get("computed") or 0)
            for item in top_items
        )
        if stored_subtotal != computed_subtotal:
            issues.append({
                "level": "red",
                "category": "question_computed_inconsistent",
                "affected_id": question_number,
                "message": (
                    f"Question {question_number} stores subtotal {stored_subtotal} "
                    f"but its canonical items compute to {computed_subtotal}."
                ),
            })
        if subtotal.get("observed") is not None and int(subtotal["observed"]) != stored_subtotal:
            issues.append({
                "level": "red",
                "category": "question_total_mismatch",
                "affected_id": question_number,
                "message": (
                    f"Question {question_number} observed subtotal "
                    f"{subtotal['observed']} does not equal computed {stored_subtotal}."
                ),
            })

    for exception in memo.get("exceptions") or []:
        if exception.get("exception_id"):
            ids.append(str(exception["exception_id"]))
    for correction in memo.get("corrections") or []:
        if correction.get("correction_id"):
            ids.append(str(correction["correction_id"]))

    duplicates = sorted({
        value
        for value in ids
        if ids.count(value) > 1
    })
    for duplicate in duplicates:
        issues.append({
            "level": "red",
            "category": "id_not_unique",
            "affected_id": duplicate,
            "message": f"Canonical identifier {duplicate} is not unique.",
        })

    totals = memo.get("totals", {})
    stored_document_total = int(totals.get("computed") or 0)
    computed_document_total = sum(
        int(question.get("subtotal", {}).get("computed") or 0)
        for question in memo.get("questions", [])
    )
    if stored_document_total != computed_document_total:
        issues.append({
            "level": "red",
            "category": "document_computed_inconsistent",
            "affected_id": None,
            "message": (
                f"Document stores computed total {stored_document_total} but "
                f"question subtotals compute to {computed_document_total}."
            ),
        })

    expected = totals.get("expected")
    if expected is not None and int(expected) != stored_document_total:
        issues.append({
            "level": "red",
            "category": "document_total_mismatch",
            "affected_id": None,
            "message": (
                f"Document expected total {expected} does not equal computed "
                f"total {stored_document_total}."
            ),
        })

    for correction in memo.get("corrections") or []:
        if correction.get("applied"):
            confirmation = correction.get("confirmation") or {}
            confirmation_status = (
                confirmation.get("status")
                or correction.get("confirmation_status")
            )
            if confirmation_status != "confirmed":
                issues.append({
                    "level": "red",
                    "category": "correction_not_confirmed",
                    "affected_id": str(correction.get("correction_id") or ""),
                    "message": "A correction was applied before user confirmation.",
                })

    issues = _dedupe_issues(issues)
    open_red = sum(
        1
        for exception in memo.get("exceptions") or []
        if exception.get("status") == "open" and exception.get("level") == "red"
    )
    open_amber = sum(
        1
        for exception in memo.get("exceptions") or []
        if exception.get("status") == "open" and exception.get("level") == "amber"
    )
    core_passed = not issues
    handoff_ready = core_passed and open_red == 0 and open_amber == 0

    error_codes = {issue["category"] for issue in issues}
    if open_red:
        error_codes.add("NO_OPEN_RED")
    if open_amber:
        error_codes.add("NO_PENDING_REVIEW")

    return {
        "validator_version": "phase5.0",
        "passed": handoff_ready,
        "core_invariants_passed": core_passed,
        "handoff_ready": handoff_ready,
        "open_red_count": open_red,
        "open_amber_count": open_amber,
        "issue_count": len(issues),
        "red_count": sum(1 for issue in issues if issue["level"] == "red"),
        "amber_count": sum(1 for issue in issues if issue["level"] == "amber"),
        "error_codes": sorted(error_codes),
        "issues": issues,
        "gates": {
            "ID_UNIQUE": "id_not_unique" not in error_codes,
            "REF_RESOLVES": not any(
                code in error_codes
                for code in {
                    "source_ref_unresolved",
                    "source_ref_page_invalid",
                    "asset_source_unresolved",
                }
            ),
            "NUMBER_TREE": "number_tree_invalid" not in error_codes,
            "LEAF_SOLUTION": "leaf_solution_missing" not in error_codes,
            "ALT_MAX": "alternative_mark_conflict" not in error_codes,
            "MARK_DESCRIPTOR": "mark_descriptor_invalid" not in error_codes,
            "MARK_LINK": not any(
                code in error_codes
                for code in {"mark_link_missing", "mark_link_invalid"}
            ),
            "ITEM_TOTAL": not any(
                code in error_codes
                for code in {"item_total_mismatch", "item_computed_inconsistent"}
            ),
            "QUESTION_TOTAL": not any(
                code in error_codes
                for code in {
                    "question_total_mismatch",
                    "question_computed_inconsistent",
                }
            ),
            "DOCUMENT_TOTAL": not any(
                code in error_codes
                for code in {
                    "document_total_mismatch",
                    "document_computed_inconsistent",
                }
            ),
            "CA_DEPENDENCY": not any(
                code in error_codes
                for code in {
                    "ca_flag_invalid",
                    "ca_dependency_unresolved",
                    "ca_dependency_not_earlier",
                }
            ),
            "CORRECTION_CONFIRMED": "correction_not_confirmed" not in error_codes,
            "NO_OPEN_RED": open_red == 0,
            "NO_PENDING_REVIEW": open_amber == 0,
            "MATH_PARSE": not any(
                code in error_codes
                for code in {"math_parse_failed", "math_shape_invalid"}
            ),
            "ASSET_RESOLVES": "asset_unresolved" not in error_codes,
        },
    }


def build_canonical_memo(
    job: dict[str, Any],
    ingestion: dict[str, Any],
    normalized: dict[str, Any],
    structure: dict[str, Any],
    semantic: dict[str, Any],
    source_bytes: bytes,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    records, page_count, assets = _source_records(normalized, source_bytes)
    record_by_block = {record["block_index"]: record for record in records}
    qmap = {str(q["question_id"]): q for q in structure.get("questions", [])}

    segments_by_qid: dict[str, list[dict[str, Any]]] = {qid: [] for qid in qmap}
    for record in records:
        qids = [qid for qid, qdata in qmap.items() if int(qdata.get("source_block_index", -1)) == record["block_index"]]
        if not qids:
            continue
        segmented = _qid_segments(record, qids)
        for qid, segments in segmented.items():
            segments_by_qid.setdefault(qid, []).extend(segments)

    issues: list[dict[str, Any]] = []
    sem_lookup = _semantic_lookup(semantic)
    majors = sorted({int(qid.split(".")[0]) for qid in qmap})

    subtotal_by_major: dict[int, int] = {}
    question_positions = [
        (int(q.get("source_block_index", -1)), str(q["question_id"]))
        for q in structure.get("questions", [])
    ]
    for subtotal in structure.get("subtotals", []):
        block_index = int(subtotal.get("block_index", -1))
        eligible = [item for item in question_positions if item[0] <= block_index]
        if eligible:
            latest_block = max(item[0] for item in eligible)
            same_block = [qid for pos, qid in eligible if pos == latest_block]
            # Prefer the shallowest identifier on the latest source row. This
            # correctly associates a same-row major question subtotal such as Q3 [4].
            chosen = sorted(same_block, key=lambda value: (value.count("."), len(value)))[0]
            subtotal_by_major[int(chosen.split(".")[0])] = int(subtotal["value"])

    questions: list[dict[str, Any]] = []
    for major in majors:
        items = _build_item_tree(major, qmap, segments_by_qid, record_by_block, sem_lookup, issues)
        # A scored major question such as "3" has no child path. Represent it as a
        # synthetic item while keeping the printed number unchanged.
        major_qid = str(major)
        if major_qid in qmap and not items:
            qdata = qmap[major_qid]
            source_branches = _split_alternative_segments(segments_by_qid.get(major_qid, []))
            alt_blocks = [
                _blocks_from_segments(major_qid, "primary" if idx == 0 else f"or{idx}", branch, issues)
                for idx, branch in enumerate(source_branches)
            ]
            record = record_by_block.get(int(qdata.get("source_block_index", -1)), {})
            mark_branches = _marking_points_for_alternatives(
                major_qid, qdata, record.get("marking_text", ""), alt_blocks, sem_lookup, issues
            )
            alternatives = []
            for idx, blocks in enumerate(alt_blocks):
                marks = mark_branches[min(idx, len(mark_branches) - 1)] if mark_branches else []
                alternatives.append({
                    "alternative_id": f"q{major}_root_{'primary' if idx == 0 else 'or' + str(idx)}",
                    "label": "PRIMARY" if idx == 0 else "OR",
                    "blocks": blocks,
                    "marking_points": marks,
                    "marks_computed": sum(m["count"] for m in marks),
                    "source_refs": blocks[0].get("source_refs", []) if blocks else [],
                })
            computed = max([a["marks_computed"] for a in alternatives] or [0])
            observed = qdata.get("printed_marks")
            items = [{
                "item_id": f"q{major}_root",
                "number": major_qid,
                "context_blocks": [],
                "children": [],
                "alternatives": alternatives,
                "marks": {
                    "observed": observed,
                    "computed": computed,
                    "status": "match" if observed is not None and int(observed) == computed else ("mismatch" if observed is not None else "missing_observed"),
                },
                "source_refs": alternatives[0].get("source_refs", []) if alternatives else [],
                "confidence": {"score": 1.0, "band": "green", "rationale": "Standalone scored major question represented as a canonical leaf item."},
                "warnings": [],
            }]

        computed_subtotal = sum(int(item.get("marks", {}).get("computed") or 0) for item in items)
        observed_subtotal = subtotal_by_major.get(major)
        subtotal_status = "missing_observed" if observed_subtotal is None else ("match" if observed_subtotal == computed_subtotal else "mismatch")
        questions.append({
            "question_id": f"q{major}",
            "number": str(major),
            "heading": f"QUESTION {major}",
            "context_blocks": [],
            "items": items,
            "subtotal": {
                "observed": observed_subtotal,
                "computed": computed_subtotal,
                "status": subtotal_status,
            },
            "source_refs": items[0].get("source_refs", []) if items else [],
            "confidence": {"score": 1.0, "band": "green", "rationale": "Major question grouping is deterministic."},
            "warnings": [],
        })

    all_text = _all_normalized_text(normalized)
    totals_found = [int(value) for value in TOTAL_RE.findall(all_text)]
    observed_final = totals_found[-1] if totals_found else None
    computed_final = sum(int(q["subtotal"]["computed"] or 0) for q in questions)
    expected_final = observed_final

    source = ingestion.get("source", {})
    document_id = "memo_" + str(source.get("sha256", normalized.get("job_id", "unknown")))[:24]

    year_match = YEAR_RE.search(all_text)
    paper_match = PAPER_RE.search(all_text)
    grade_match = GRADE_RE.search(all_text)
    duration_match = DURATION_RE.search(all_text)

    inherited_exceptions = (
        structure.get("exceptions", []) + semantic.get("exceptions", [])
    )
    new_issues = _dedupe_issues(issues)

    memo: dict[str, Any] = {
        "schema_version": "1.0",
        "document_id": document_id,
        "status": "interpreted",
        "source": {
            "files": [{
                "file_id": "source_1",
                "original_filename": job.get("source_filename"),
                "mime_type": source.get("detected_mime") or job.get("source_mime"),
                "sha256": source.get("sha256"),
                "acquisition_kind": "upload",
                "page_count": page_count,
            }],
            "assets": assets,
        },
        "document_metadata": {
            "exam_type": "PREPARATORY EXAMINATION" if "PREPARATORY" in all_text.upper() else None,
            "year": int(year_match.group(1)) if year_match else None,
            "subject": "MATHEMATICS",
            "paper": f"PAPER {paper_match.group(1)}" if paper_match else None,
            "grade_label": f"FORM {grade_match.group(1)}" if grade_match and "FORM" in grade_match.group(0).upper() else (f"GRADE {grade_match.group(1)}" if grade_match else None),
            "language": "en-ZA",
            "exam_code": None,
            "expected_total_marks": expected_final,
            "duration_minutes": (
                int(round(float(duration_match.group(1).replace(",", ".")) * 60))
                if duration_match else None
            ),
            "observed_page_count_text": None,
        },
        "render_profile": os.environ.get("MEMO_RENDER_PROFILE", "PBHS_GDE_INTERNAL_V1"),
        "notes": [],
        "questions": questions,
        "totals": {
            "observed": observed_final,
            "computed": computed_final,
            "expected": expected_final,
            "status": "missing_observed" if expected_final is None else ("match" if expected_final == computed_final else "mismatch"),
        },
        "exceptions": [_exception_record(item) for item in inherited_exceptions + new_issues],
        "corrections": [],
        "audit": {
            "job_id": normalized["job_id"],
            "interpreter_runs": semantic.get("interpreter_runs", []),
            "validation_runs": [],
            "decisions": [],
        },
    }

    validation = validate_canonical(memo)
    validation_issue_records = _dedupe_issues(validation["issues"])
    existing_keys = {(ex["category"], tuple(ex["affected_ids"]), ex["message"]) for ex in memo["exceptions"]}
    for item in validation_issue_records:
        record = _exception_record(item)
        key = (record["category"], tuple(record["affected_ids"]), record["message"])
        if key not in existing_keys:
            memo["exceptions"].append(record)
            new_issues.append(item)
            existing_keys.add(key)

    open_red = [ex for ex in memo["exceptions"] if ex["status"] == "open" and ex["level"] == "red"]
    open_amber = [ex for ex in memo["exceptions"] if ex["status"] == "open" and ex["level"] == "amber"]
    if open_red:
        memo["status"] = "blocked"
    elif open_amber:
        memo["status"] = "needs_review"
    elif validation["passed"]:
        memo["status"] = "render_ready"
    else:
        memo["status"] = "blocked"

    memo["audit"]["validation_runs"].append({
        "validator_version": validation["validator_version"],
        "passed": validation["passed"],
        "error_codes": validation["error_codes"],
    })

    new_exceptions = _dedupe_issues(new_issues)
    return memo, validation, new_exceptions
