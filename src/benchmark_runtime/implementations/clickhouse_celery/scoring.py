"""Безопасный runtime-движок вычисления и валидации score-expression через simpleeval."""

from __future__ import annotations

import ast
import math
import operator
from typing import Any, Callable, Dict, Mapping, Sequence

from simpleeval import InvalidExpression, SimpleEval


class ScoreEvaluationError(ValueError):
    """Ошибка валидации/вычисления score expression."""


_ALLOWED_SCORE_EXPRESSION_ROOT_NAMES = frozenset(
    {
        "measured_percentiles",
        "source",
        "tested",
        "speedup",
        "compression",
        "compression_overall_coef",
        "source_insert_time_ms_percentiles",
        "source_insert_time_ms_by_percentile",
        "tested_insert_time_ms_percentiles",
        "tested_insert_time_ms_by_percentile",
        "insert_time_speedup_percentiles",
        "insert_time_speedup_by_percentile",
        "source_select_time_ms_percentiles",
        "source_select_time_ms_by_percentile",
        "tested_select_time_ms_percentiles",
        "tested_select_time_ms_by_percentile",
        "select_time_speedup_percentiles",
        "select_time_speedup_by_percentile",
        "select_time_speedup_by_query",
    }
)

_ALLOWED_LITERAL_NAMES = frozenset({"True", "False", "None"})


class _ExpressionAstValidator(ast.NodeVisitor):
    """AST-валидатор scoring expression для ранней проверки до запуска benchmark."""

    def __init__(self) -> None:
        self.issues: list[str] = []
        self.used_names: set[str] = set()

    def visit_Name(self, node: ast.Name) -> None:
        """Запоминает использованные имена и запрещает private-подобные идентификаторы."""
        if node.id.startswith("_"):
            self.issues.append(
                f"Имя {node.id!r} запрещено: идентификаторы, начинающиеся с '_' не допускаются"
            )
        self.used_names.add(node.id)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        """Разрешает только прямые вызовы whitelist-функций."""
        if not isinstance(node.func, ast.Name):
            self.issues.append(
                "Разрешены только прямые вызовы функций whitelist (например safe_div(...))"
            )
            self.generic_visit(node)
            return

        func_name = node.func.id
        if func_name not in _ALLOWED_FUNCTIONS:
            self.issues.append(
                f"Функция {func_name!r} не поддерживается. "
                f"Разрешены: {', '.join(sorted(_ALLOWED_FUNCTIONS))}"
            )
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        """Запрещает доступ к private-подобным атрибутам."""
        if node.attr.startswith("_"):
            self.issues.append(
                f"Доступ к атрибуту {node.attr!r} запрещён (private-поле)"
            )
        self.generic_visit(node)

    def visit_BinOp(self, node: ast.BinOp) -> None:
        """Проверяет поддерживаемость бинарного оператора."""
        if type(node.op) not in _ALLOWED_OPERATORS:
            self.issues.append(
                f"Оператор {type(node.op).__name__!r} не поддерживается"
            )
        self.generic_visit(node)

    def visit_UnaryOp(self, node: ast.UnaryOp) -> None:
        """Проверяет поддерживаемость унарного оператора."""
        if type(node.op) not in _ALLOWED_OPERATORS:
            self.issues.append(
                f"Унарный оператор {type(node.op).__name__!r} не поддерживается"
            )
        self.generic_visit(node)

    def visit_Compare(self, node: ast.Compare) -> None:
        """Проверяет поддерживаемость операторов сравнения."""
        for op in node.ops:
            if type(op) not in _ALLOWED_OPERATORS:
                self.issues.append(
                    f"Оператор сравнения {type(op).__name__!r} не поддерживается"
                )
        self.generic_visit(node)

    def visit_BoolOp(self, node: ast.BoolOp) -> None:
        """Разрешает только `and`/`or`."""
        if not isinstance(node.op, (ast.And, ast.Or)):
            self.issues.append(f"Булевый оператор {type(node.op).__name__!r} не поддерживается")
        self.generic_visit(node)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        self.issues.append("Lambda-выражения не поддерживаются")
        self.generic_visit(node)

    def visit_ListComp(self, node: ast.ListComp) -> None:
        self.issues.append("Comprehensions не поддерживаются")
        self.generic_visit(node)

    def visit_SetComp(self, node: ast.SetComp) -> None:
        self.issues.append("Comprehensions не поддерживаются")
        self.generic_visit(node)

    def visit_DictComp(self, node: ast.DictComp) -> None:
        self.issues.append("Comprehensions не поддерживаются")
        self.generic_visit(node)

    def visit_GeneratorExp(self, node: ast.GeneratorExp) -> None:
        self.issues.append("Generator expressions не поддерживаются")
        self.generic_visit(node)

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
        self.issues.append("Оператор ':=' не поддерживается")
        self.generic_visit(node)


def validate_score_expression(expression: str) -> list[str]:
    """
    Выполняет статическую валидацию scoring expression.

    Возвращает список проблем. Пустой список означает, что формула выглядит валидной
    с точки зрения поддерживаемого синтаксиса и известных root-имен.
    """
    cleaned = (expression or "").strip()
    if not cleaned:
        return ["Формула пуста"]

    try:
        parsed = SimpleEval.parse(cleaned)
    except (InvalidExpression, SyntaxError, ValueError) as exc:
        return [f"Синтаксическая ошибка expression: {exc}"]

    expression_node: ast.AST
    if isinstance(parsed, ast.Expr):
        expression_node = parsed.value
    else:
        expression_node = parsed

    validator = _ExpressionAstValidator()
    validator.visit(expression_node)

    unknown_names = sorted(
        name
        for name in validator.used_names
        if name not in _ALLOWED_FUNCTIONS
        and name not in _ALLOWED_SCORE_EXPRESSION_ROOT_NAMES
        and name not in _ALLOWED_LITERAL_NAMES
    )
    for name in unknown_names:
        validator.issues.append(
            f"Неизвестное имя {name!r}. "
            f"Разрешённые root-имена: {', '.join(sorted(_ALLOWED_SCORE_EXPRESSION_ROOT_NAMES))}"
        )

    return validator.issues


def build_percentile_lookup(
    measured_percentiles: Sequence[int],
    values: Sequence[float],
) -> Dict[Any, float]:
    """
    Строит lookup по перцентилям.

    Ключи:
      - числовой перцентиль (`95`);
      - строка перцентиля (`"95"`);
      - префиксная строка (`"p95"`).
    """
    lookup: dict[Any, float] = {}
    for percentile, value in zip(measured_percentiles, values):
        percentile_int = int(percentile)
        numeric_value = float(value)
        lookup[percentile_int] = numeric_value
        lookup[str(percentile_int)] = numeric_value
        lookup[f"p{percentile_int}"] = numeric_value
    return lookup


def evaluate_score_expression(
    expression: str,
    context: Mapping[str, Any],
) -> float:
    """Вычисляет score expression через simpleeval в sandbox-режиме."""
    evaluator = SimpleEval(
        names=dict(context),
        functions=_ALLOWED_FUNCTIONS,
        operators=_ALLOWED_OPERATORS,
    )
    evaluator.ATTR_INDEX_FALLBACK = True

    try:
        result = evaluator.eval(expression)
    except InvalidExpression as exc:
        raise ScoreEvaluationError(f"Некорректное expression: {exc}") from exc
    except Exception as exc:
        raise ScoreEvaluationError(f"Ошибка вычисления expression: {exc}") from exc

    try:
        score = float(result)
    except Exception as exc:
        raise ScoreEvaluationError(
            f"expression вернуло нечисловой результат: {result!r}"
        ) from exc

    if not math.isfinite(score):
        raise ScoreEvaluationError("expression вернуло NaN/Inf")
    return score


def _safe_div(a: Any, b: Any, default: float = 0.0) -> float:
    """Безопасное деление с fallback при делении на 0/NaN/Inf."""
    try:
        num = float(a)
        den = float(b)
    except Exception:
        return float(default)
    if not math.isfinite(num) or not math.isfinite(den) or den == 0.0:
        return float(default)
    return num / den


def _safe_at(container: Any, key: Any, default: Any = None) -> Any:
    """Безопасный доступ к элементу списка/словаря."""
    try:
        if isinstance(container, (list, tuple)):
            index = int(key)
            return container[index]
        if isinstance(container, Mapping):
            return container.get(key, default)
    except Exception:
        return default
    return default


def _safe_pct(values_by_percentile: Any, percentile: Any, default: Any = None) -> Any:
    """Безопасный доступ к значению по перцентилю."""
    if not isinstance(values_by_percentile, Mapping):
        return default

    try:
        percentile_int = int(percentile)
    except Exception:
        percentile_int = None

    if percentile_int is not None:
        for key in (percentile_int, str(percentile_int), f"p{percentile_int}"):
            if key in values_by_percentile:
                return values_by_percentile[key]

    if percentile in values_by_percentile:
        return values_by_percentile[percentile]
    return default


def _safe_coalesce(*values: Any) -> Any:
    """Возвращает первое значение, которое не None/NaN/Inf."""
    for value in values:
        if value is None:
            continue
        if isinstance(value, (int, float)):
            numeric = float(value)
            if not math.isfinite(numeric):
                continue
        return value
    return None


def _safe_clamp(value: Any, low: Any, high: Any) -> float:
    """Ограничивает значение в диапазоне [low, high]."""
    numeric = float(value)
    low_f = float(low)
    high_f = float(high)
    return max(low_f, min(high_f, numeric))


_ALLOWED_FUNCTIONS: Dict[str, Callable[..., Any]] = {
    "safe_div": _safe_div,
    "at": _safe_at,
    "pct": _safe_pct,
    "coalesce": _safe_coalesce,
    "clamp": _safe_clamp,
    "abs": abs,
    "min": min,
    "max": max,
    "round": round,
    "sqrt": math.sqrt,
    "log": math.log,
    "ln": math.log,
    "pow": math.pow,
}

_ALLOWED_OPERATORS: Dict[type[ast.AST], Callable[..., Any]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
    ast.Not: operator.not_,
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
}
