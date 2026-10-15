from __future__ import annotations

import re
from typing import Any


SUPPORTED_LATEX_COMMANDS = frozenset({
    "leq", "geq", "neq", "in", "notin", "infty", "pm", "times", "cdot",
    "div", "to", "Rightarrow", "therefore", "theta", "pi", "sigma", "circ",
    "sum", "int", "prod", "frac", "sqrt", "left", "right", "text", "hat",
    "bar", "vec", "cup", "cap", "setminus",
})

VISUAL_COMMAND_ALIASES = {
    "le": "leq",
    "ge": "geq",
}

VISUAL_UNICODE_MATH = {
    "≤": r"\leq{}",
    "≥": r"\geq{}",
    "≠": r"\neq{}",
    "∈": r"\in{}",
    "∉": r"\notin{}",
    "∪": r"\cup{}",
    "∩": r"\cap{}",
    "∞": r"\infty{}",
    "±": r"\pm{}",
    "×": r"\times{}",
    "÷": r"\div{}",
    "→": r"\to{}",
    "⇒": r"\Rightarrow{}",
    "∴": r"\therefore{}",
    "θ": r"\theta{}",
    "π": r"\pi{}",
    "σ": r"\sigma{}",
    "°": r"^{\circ}",
}


def latex_commands(value: str) -> list[str]:
    return re.findall(r"\\([A-Za-z]+)", value)


def unsupported_latex_commands(value: str) -> list[str]:
    return sorted({
        command
        for command in latex_commands(value)
        if command not in SUPPORTED_LATEX_COMMANDS
    })


def _balanced_braces(value: str) -> bool:
    depth = 0
    for index, char in enumerate(value):
        escaped = index > 0 and value[index - 1] == "\\"
        if char == "{" and not escaped:
            depth += 1
        elif char == "}" and not escaped:
            depth -= 1
            if depth < 0:
                return False
    return depth == 0


def normalize_visual_math(value: Any) -> tuple[str | None, str | None]:
    """Normalize the model's decoded math through a closed, deterministic subset."""
    if not isinstance(value, str):
        return None, None
    normalized = re.sub(r"\s+", " ", value).strip()
    if not normalized:
        return None, None

    # JSON decoding has already converted `\\frac` in JSON to `\frac` in memory.
    # Some models nevertheless double the in-memory slash; collapse it only when
    # it introduces a known command or a supported alias.
    safe_names = SUPPORTED_LATEX_COMMANDS | frozenset(VISUAL_COMMAND_ALIASES)
    doubled = re.compile(
        r"\\\\(?=(?:" + "|".join(sorted(map(re.escape, safe_names), key=len, reverse=True)) + r")\b)"
    )
    for _ in range(2):
        repaired = doubled.sub(r"\\", normalized)
        if repaired == normalized:
            break
        normalized = repaired

    for source, target in VISUAL_COMMAND_ALIASES.items():
        normalized = re.sub(rf"\\{source}\b", rf"\\{target}", normalized)
    for symbol, latex in VISUAL_UNICODE_MATH.items():
        normalized = normalized.replace(symbol, latex)

    # A model sometimes describes a set-difference glyph as the word-command
    # `\backslash`. Convert only the unambiguous binary set form A \ B.
    normalized = re.sub(
        r"(?<=[A-Z}])\s*\\backslash(?:\{\})?\s*(?=[A-Z{])",
        r" \\setminus ",
        normalized,
    )
    if re.search(r"\\backslash\b", normalized):
        return None, "VISUAL_MATH_BACKSLASH_AMBIGUOUS"

    unsupported = unsupported_latex_commands(normalized)
    if unsupported:
        return None, "VISUAL_MATH_COMMAND_UNSUPPORTED"
    if not _balanced_braces(normalized):
        return None, "VISUAL_MATH_BRACES_INVALID"
    return normalized, None
