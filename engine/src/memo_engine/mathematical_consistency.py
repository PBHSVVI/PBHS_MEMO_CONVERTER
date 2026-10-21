from __future__ import annotations

import math
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from typing import Any


MAX_INPUT_LENGTH = 512
MAX_TOKENS = 128
MAX_NESTING_DEPTH = 16
MAX_FACTORIAL_OPERAND = 20
MAX_CHECKS = 512

CHECKED_PASS = "checked_pass"
CHECKED_FAIL = "checked_fail"
NOT_CHECKED = "not_checked"


class _UnsupportedExpression(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class _Token:
    kind: str
    text: str


def _fraction_text(value: Fraction) -> str:
    if value.denominator == 1:
        return str(value.numerator)
    return f"{value.numerator}/{value.denominator}"


def _extract_group(value: str, start: int) -> tuple[str, int]:
    if start >= len(value) or value[start] != "{":
        raise _UnsupportedExpression("latex_fraction_shape")
    depth = 0
    for index in range(start, len(value)):
        if value[index] == "{":
            depth += 1
            if depth > MAX_NESTING_DEPTH:
                raise _UnsupportedExpression("nesting_limit")
        elif value[index] == "}":
            depth -= 1
            if depth == 0:
                return value[start + 1:index], index + 1
            if depth < 0:
                break
    raise _UnsupportedExpression("latex_fraction_shape")


def _expand_latex_fractions(value: str) -> str:
    result = value
    for _ in range(MAX_TOKENS):
        match = re.search(r"\\frac\s*\{", result)
        if match is None:
            return result
        numerator, after_numerator = _extract_group(result, result.index("{", match.start()))
        denominator_start = after_numerator
        while denominator_start < len(result) and result[denominator_start].isspace():
            denominator_start += 1
        denominator, after_denominator = _extract_group(result, denominator_start)
        replacement = (
            "((" + _expand_latex_fractions(numerator) + ")/("
            + _expand_latex_fractions(denominator) + "))"
        )
        result = result[:match.start()] + replacement + result[after_denominator:]
    raise _UnsupportedExpression("complexity_limit")


def _normalise_expression(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _UnsupportedExpression("empty")
    if len(value) > MAX_INPUT_LENGTH:
        raise _UnsupportedExpression("input_length_limit")
    text = value.strip()
    if ";" in text:
        raise _UnsupportedExpression("pair_or_interval")
    if re.search(r"\d\s*,\s+\d|\d\s+,\s*\d", text):
        raise _UnsupportedExpression("ambiguous_comma")
    if re.search(r"\d+(?:,\d+){2,}", text):
        raise _UnsupportedExpression("ambiguous_comma")
    text = _expand_latex_fractions(text)
    text = re.sub(r"\\(?:left|right)\b", "", text)
    text = re.sub(r"\\times(?:\{\})?", "*", text)
    text = re.sub(r"\\cdot(?:\{\})?", "*", text)
    text = re.sub(r"\\div(?:\{\})?", "/", text)
    text = re.sub(r"\\approx(?:\{\})?", "≈", text)
    text = text.replace("≃", "≈")
    text = text.replace("×", "*").replace("·", "*").replace("÷", "/")
    text = text.replace(r"\%", "%")
    text = re.sub(r"(?<=\d),(?=\d)", ".", text)
    if "," in text:
        raise _UnsupportedExpression("ambiguous_comma")
    text = text.replace("[", "(").replace("]", ")")
    text = text.replace("{", "(").replace("}", ")")
    if "\\" in text:
        raise _UnsupportedExpression("unsupported_latex")
    return re.sub(r"\s+", "", text)


def _split_chain(value: str) -> tuple[list[str], list[str]]:
    parts: list[str] = []
    operators: list[str] = []
    start = 0
    depth = 0
    for index, char in enumerate(value):
        if char == "(":
            depth += 1
            if depth > MAX_NESTING_DEPTH:
                raise _UnsupportedExpression("nesting_limit")
        elif char == ")":
            depth -= 1
            if depth < 0:
                raise _UnsupportedExpression("unbalanced_parentheses")
        elif depth == 0 and char in {"=", "≈"}:
            parts.append(value[start:index])
            operators.append(char)
            start = index + 1
    if depth:
        raise _UnsupportedExpression("unbalanced_parentheses")
    parts.append(value[start:])
    return parts, operators


def _tokens(value: str) -> list[_Token]:
    result: list[_Token] = []
    index = 0
    while index < len(value):
        char = value[index]
        if value.startswith("...", index):
            result.append(_Token("ellipsis", "..."))
            index += 3
        elif char == "…":
            result.append(_Token("ellipsis", char))
            index += 1
        elif char.isdigit() or char == ".":
            match = re.match(r"(?:\d+(?:\.\d+)?|\.\d+)", value[index:])
            if match is None:
                raise _UnsupportedExpression("invalid_number")
            token = match.group(0)
            result.append(_Token("number", token))
            index += len(match.group(0))
        elif char in "+-*/()!%":
            result.append(_Token(char, char))
            index += 1
        else:
            raise _UnsupportedExpression("unsupported_token")
        if len(result) > MAX_TOKENS:
            raise _UnsupportedExpression("token_limit")
    return result


class _NumericParser:
    def __init__(self, tokens: list[_Token]) -> None:
        self.tokens = tokens
        self.index = 0
        self.depth = 0

    def _peek(self, kind: str | None = None) -> _Token | None:
        token = self.tokens[self.index] if self.index < len(self.tokens) else None
        if kind is None or (token is not None and token.kind == kind):
            return token
        return None

    def _take(self, kind: str) -> _Token:
        token = self._peek(kind)
        if token is None:
            raise _UnsupportedExpression("unexpected_token")
        self.index += 1
        return token

    def parse(self) -> Fraction:
        if not self.tokens:
            raise _UnsupportedExpression("empty_chain_member")
        value = self._sum()
        if self._peek("ellipsis") is not None:
            self.index += 1
        if self.index != len(self.tokens):
            raise _UnsupportedExpression("unsupported_token")
        return value

    def _sum(self) -> Fraction:
        value = self._product()
        while (token := self._peek()) is not None and token.kind in {"+", "-"}:
            self.index += 1
            right = self._product()
            value = value + right if token.kind == "+" else value - right
        return value

    def _product(self) -> Fraction:
        value = self._unary()
        while True:
            token = self._peek()
            implicit = token is not None and token.kind == "("
            if token is None or (token.kind not in {"*", "/"} and not implicit):
                return value
            if implicit:
                right = self._unary()
                value *= right
                continue
            self.index += 1
            right = self._unary()
            if token.kind == "*":
                value *= right
            else:
                if right == 0:
                    raise _UnsupportedExpression("division_by_zero")
                value /= right

    def _unary(self) -> Fraction:
        token = self._peek()
        if token is not None and token.kind in {"+", "-"}:
            self.index += 1
            value = self._unary()
            return value if token.kind == "+" else -value
        return self._postfix()

    def _postfix(self) -> Fraction:
        value = self._primary()
        factorial_seen = False
        percentage_seen = False
        while (token := self._peek()) is not None and token.kind in {"!", "%"}:
            self.index += 1
            if token.kind == "!":
                if factorial_seen or percentage_seen:
                    raise _UnsupportedExpression("unsupported_postfix")
                if value.denominator != 1 or not 0 <= value.numerator <= MAX_FACTORIAL_OPERAND:
                    raise _UnsupportedExpression("factorial_operand")
                value = Fraction(math.factorial(value.numerator), 1)
                factorial_seen = True
            else:
                if percentage_seen:
                    raise _UnsupportedExpression("unsupported_postfix")
                value /= 100
                percentage_seen = True
        return value

    def _primary(self) -> Fraction:
        token = self._peek()
        if token is None:
            raise _UnsupportedExpression("unexpected_end")
        if token.kind == "number":
            self.index += 1
            try:
                return Fraction(Decimal(token.text))
            except (InvalidOperation, ValueError) as exc:
                raise _UnsupportedExpression("invalid_number") from exc
        if token.kind == "(":
            self.index += 1
            self.depth += 1
            if self.depth > MAX_NESTING_DEPTH:
                raise _UnsupportedExpression("nesting_limit")
            value = self._sum()
            self._take(")")
            self.depth -= 1
            return value
        raise _UnsupportedExpression("unexpected_token")


def _evaluate(value: str) -> Fraction:
    return _NumericParser(_tokens(value)).parse()


def _literal_quantum(displayed: str) -> Fraction | None:
    text = displayed.strip().replace("…", "...")
    if text.endswith("..."):
        text = text[:-3]
    match = re.fullmatch(r"([+-]?)(\d+(?:\.\d+)?|\.\d+)(%)?", text)
    if match is None:
        return None
    number = match.group(2)
    decimals = len(number.split(".", 1)[1]) if "." in number else 0
    quantum = Fraction(1, 10**decimals)
    if match.group(3):
        quantum /= 100
    return quantum


def _round_to_quantum(value: Fraction, quantum: Fraction) -> Fraction:
    scaled = value / quantum
    if scaled >= 0:
        rounded = (2 * scaled.numerator + scaled.denominator) // (2 * scaled.denominator)
    else:
        positive = -scaled
        rounded = -((2 * positive.numerator + positive.denominator) // (2 * positive.denominator))
    return Fraction(rounded, 1) * quantum


def _relation(
    left: Fraction,
    right: Fraction,
    right_display: str,
    operator: str,
) -> tuple[bool, str]:
    if left == right:
        return True, "exact"
    quantum = _literal_quantum(right_display)
    if quantum is not None and _round_to_quantum(left, quantum) == right:
        return True, "approximate" if operator == "≈" else "rounding"
    return False, "approximate" if operator == "≈" else "exact"


def check_expression(
    displayed: str,
    *,
    previous_value: Fraction | None = None,
) -> tuple[dict[str, Any], Fraction | None]:
    """Check one displayed numeric expression without evaluating arbitrary code."""
    base = {"displayed_expression": str(displayed)[:MAX_INPUT_LENGTH]}
    try:
        normalized = _normalise_expression(displayed)
        parts, operators = _split_chain(normalized)
        values: list[Fraction] = []
        for index, part in enumerate(parts):
            if not part and index == 0 and operators and previous_value is not None:
                values.append(previous_value)
                continue
            values.append(_evaluate(part))
    except _UnsupportedExpression as exc:
        return ({**base, "status": NOT_CHECKED, "reason": exc.reason, "evaluation_mode": "unsupported"}, None)

    relations: list[dict[str, Any]] = []
    for index, operator in enumerate(operators):
        passed, mode = _relation(values[index], values[index + 1], parts[index + 1], operator)
        relations.append({
            "operator": operator,
            "left_value": _fraction_text(values[index]),
            "right_value": _fraction_text(values[index + 1]),
            "right_display": parts[index + 1],
            "evaluation_mode": mode,
            "passed": passed,
        })
    failed = [relation for relation in relations if not relation["passed"]]
    status = CHECKED_FAIL if failed else CHECKED_PASS
    mode = (
        failed[0]["evaluation_mode"]
        if failed
        else (relations[-1]["evaluation_mode"] if relations else "exact")
    )
    return ({
        **base,
        "status": status,
        "reason": "inconsistent_equality" if failed else "numeric_expression_consistent",
        "normalized_expression": normalized,
        "evaluation_mode": mode,
        "relations": relations,
        "calculated_value": _fraction_text(values[-1]),
    }, values[-1])


def check_canonical_mathematics(memo: dict[str, Any]) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    limit_reached = False
    for question in memo.get("questions") or []:
        for item in _iter_items(question.get("items") or []):
            item_number = str(item.get("number") or "")
            source_question_id = str(
                (item.get("solution_evidence") or {}).get("source_question_id")
                or item_number
            )
            for alternative in item.get("alternatives") or []:
                previous: Fraction | None = None
                previous_block: dict[str, Any] | None = None
                for block in alternative.get("blocks") or []:
                    if len(checks) >= MAX_CHECKS:
                        limit_reached = True
                        break
                    if block.get("type") != "math":
                        previous = None
                        previous_block = None
                        continue
                    math_block = block.get("math") or {}
                    displayed = str(
                        math_block.get("canonical_latex")
                        or math_block.get("plain_text")
                        or math_block.get("source_text")
                        or ""
                    )
                    result, next_value = check_expression(
                        displayed, previous_value=previous
                    )
                    continuation = bool(re.match(
                        r"^\s*(?:=|≈|≃|\\approx\b)", displayed
                    ))
                    participating_blocks = (
                        [previous_block, block]
                        if continuation and previous_block is not None
                        else [block]
                    )
                    block_ids = [
                        candidate.get("block_id") for candidate in participating_blocks
                        if candidate.get("block_id")
                    ]
                    source_refs = [
                        ref
                        for candidate in participating_blocks
                        for ref in candidate.get("source_refs") or []
                    ]
                    result.update({
                        "question_id": item_number,
                        "source_question_id": source_question_id,
                        "alternative_id": alternative.get("alternative_id"),
                        "block_ids": block_ids,
                        "source_refs": source_refs,
                    })
                    checks.append(result)
                    previous = next_value
                    previous_block = block if next_value is not None else None
                    if result["status"] == CHECKED_FAIL:
                        failed = next(
                            relation for relation in result["relations"]
                            if not relation["passed"]
                        )
                        issues.append({
                            "level": "red",
                            "category": "mathematical_consistency_conflict",
                            "affected_id": item_number,
                            "message": (
                                "Displayed mathematical working is internally "
                                "inconsistent."
                            ),
                            "suggestions": [{
                                "source_question_id": source_question_id,
                                "alternative_id": alternative.get("alternative_id"),
                                "block_ids": block_ids,
                                "source_refs": source_refs,
                                "displayed_expression": result["displayed_expression"],
                                "normalized_expression": result["normalized_expression"],
                                "calculated_left": failed["left_value"],
                                "displayed_right": failed["right_display"],
                                "calculated_right": failed["right_value"],
                                "operator": failed["operator"],
                                "evaluation_mode": failed["evaluation_mode"],
                                "failure_reason": result["reason"],
                            }],
                        })
                if limit_reached:
                    break
            if limit_reached:
                break
        if limit_reached:
            break
    counts = {
        CHECKED_PASS: sum(check["status"] == CHECKED_PASS for check in checks),
        CHECKED_FAIL: sum(check["status"] == CHECKED_FAIL for check in checks),
        NOT_CHECKED: sum(check["status"] == NOT_CHECKED for check in checks),
    }
    return {
        "checker_version": "bounded-numeric-v1",
        "checks": checks,
        "issues": issues,
        "counts": counts,
        "checked_expression_count": counts[CHECKED_PASS] + counts[CHECKED_FAIL],
        "conflict_count": counts[CHECKED_FAIL],
        "limit_reached": limit_reached,
    }


def _iter_items(items: list[dict[str, Any]]):
    for item in items:
        yield item
        yield from _iter_items(item.get("children") or [])

