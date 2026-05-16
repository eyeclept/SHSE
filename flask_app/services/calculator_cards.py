"""
Author: Richard Baldwin
Date:   2026
Email: eyeclept@pm.me

Description:
    Calculator answer card service. Detects mathematical expressions in search
    queries and evaluates them locally using Python's ast module for safe
    expression parsing. eval() is never called directly. Supports standard
    arithmetic operators (+, -, *, /, //, **, %) plus common math functions
    (sqrt, abs, round, floor, ceil, factorial, log, log10, sin, cos, tan).
"""
# Imports
import ast
import logging
import math
import re
from typing import Optional, Union

# Globals
logger = logging.getLogger(__name__)

# Preamble phrases that indicate a calc intent when followed by an expression
_PREAMBLE = re.compile(
    r"^\s*(what\s+is|calculate|compute|eval(?:uate)?)\s+",
    re.IGNORECASE,
)

# Trailing = sign (e.g. "12 / 4 =")
_TRAILING_EQ = re.compile(r"\s*=\s*$")

# Must contain at least one digit and one operator / math function to qualify
_HAS_DIGIT = re.compile(r"\d")
_HAS_OP = re.compile(
    r"[+\-*/^%]|"
    r"\b(sqrt|abs|round|floor|ceil|factorial|log10?|sin|cos|tan)\b",
    re.IGNORECASE,
)

# Factorial shorthand: "10 factorial" or "10!"
_RE_FACTORIAL_WORD = re.compile(r"(\d+(?:\.\d+)?)\s+factorial\b", re.IGNORECASE)
_RE_FACTORIAL_BANG = re.compile(r"(\d+(?:\.\d+)?)!")

# Safe AST node types
_SAFE_NODES = (
    ast.Module, ast.Expr,
    ast.Expression,
    ast.BinOp,
    ast.UnaryOp,
    ast.Call,
    ast.Constant,
    # Operators
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod,
    ast.Pow, ast.FloorDiv,
    ast.USub, ast.UAdd,
    # Name is allowed only for whitelisted math functions resolved below
    ast.Name,
    ast.Load,
)

_ALLOWED_FUNCS = {
    "sqrt":      math.sqrt,
    "abs":       abs,
    "round":     round,
    "floor":     math.floor,
    "ceil":      math.ceil,
    "factorial": math.factorial,
    "log":       math.log,
    "log10":     math.log10,
    "sin":       math.sin,
    "cos":       math.cos,
    "tan":       math.tan,
}

_ALLOWED_NAMES = {
    "pi":  math.pi,
    "e":   math.e,
    "tau": math.tau,
    "inf": math.inf,
}


# Functions
def _preprocess(expr: str) -> str:
    """
    Input: raw expression string
    Output: normalised expression ready for ast.parse
    Details:
        Expands factorial shorthand, replaces ^ with **, lower-cases function
        names. Does NOT modify the string beyond these safe substitutions.
    """
    # "10 factorial" → "factorial(10)"
    expr = _RE_FACTORIAL_WORD.sub(lambda m: f"factorial({int(float(m.group(1)))})", expr)
    # "10!" → "factorial(10)"
    expr = _RE_FACTORIAL_BANG.sub(lambda m: f"factorial({int(float(m.group(1)))})", expr)
    # "^" → "**" (common calculator convention)
    expr = expr.replace("^", "**")
    return expr


class _SafeVisitor(ast.NodeVisitor):
    """Raises ValueError for any AST node not on the whitelist."""

    def generic_visit(self, node):
        if not isinstance(node, _SAFE_NODES):
            raise ValueError(f"Forbidden node type: {type(node).__name__}")
        super().generic_visit(node)


def _safe_eval(expr: str) -> Union[float, int]:
    """
    Input: expression string (already preprocessed)
    Output: numeric result (int or float)
    Details:
        Parses with ast.parse, walks the tree to reject any non-whitelisted
        nodes, then evaluates by recursively interpreting the AST — never
        calling eval(). Raises ValueError for disallowed constructs or
        ZeroDivisionError for division by zero.
    """
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as e:
        raise ValueError(f"Syntax error: {e}") from e

    _SafeVisitor().visit(tree)

    return _eval_node(tree.body)


def _eval_node(node) -> Union[float, int]:
    """
    Input: ast node
    Output: numeric value
    Details:
        Recursive AST interpreter. Only handles the node types on the whitelist.
    """
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return node.value
        raise ValueError(f"Non-numeric constant: {node.value!r}")

    if isinstance(node, ast.Name):
        if node.id in _ALLOWED_NAMES:
            return _ALLOWED_NAMES[node.id]
        raise ValueError(f"Unknown name: {node.id!r}")

    if isinstance(node, ast.BinOp):
        left  = _eval_node(node.left)
        right = _eval_node(node.right)
        ops = {
            ast.Add:      lambda a, b: a + b,
            ast.Sub:      lambda a, b: a - b,
            ast.Mult:     lambda a, b: a * b,
            ast.Div:      lambda a, b: a / b,
            ast.Mod:      lambda a, b: a % b,
            ast.Pow:      lambda a, b: a ** b,
            ast.FloorDiv: lambda a, b: a // b,
        }
        fn = ops.get(type(node.op))
        if fn is None:
            raise ValueError(f"Unsupported operator: {type(node.op).__name__}")
        return fn(left, right)

    if isinstance(node, ast.UnaryOp):
        operand = _eval_node(node.operand)
        if isinstance(node.op, ast.USub):
            return -operand
        if isinstance(node.op, ast.UAdd):
            return operand
        raise ValueError(f"Unsupported unary operator: {type(node.op).__name__}")

    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name):
            raise ValueError("Only named function calls are allowed")
        func_name = node.func.id
        fn = _ALLOWED_FUNCS.get(func_name)
        if fn is None:
            raise ValueError(f"Function not allowed: {func_name!r}")
        args = [_eval_node(a) for a in node.args]
        return fn(*args)

    raise ValueError(f"Unsupported node: {type(node).__name__}")


def detect_calc_query(q: str) -> Optional[str]:
    """
    Input: q — raw search query string
    Output: extracted expression string, or None
    Details:
        Strips leading preamble phrases and trailing '='. Returns the
        expression if it contains a digit and at least one operator or
        recognised math function, otherwise returns None.
    """
    expr = q.strip()
    expr = _TRAILING_EQ.sub("", expr)
    expr = _PREAMBLE.sub("", expr).strip()

    if not _HAS_DIGIT.search(expr):
        return None
    if not _HAS_OP.search(expr):
        return None

    return expr


def evaluate_expression(expr: str) -> Optional[dict]:
    """
    Input: expr — expression string from detect_calc_query
    Output: dict {expression, result, source} or None
    Details:
        Preprocesses the expression, evaluates it safely, and returns a
        structured dict. Returns None on ValueError or ZeroDivisionError.
        Logs a warning on unexpected exceptions.
    """
    try:
        processed = _preprocess(expr)
        raw_result = _safe_eval(processed)
    except (ValueError, ZeroDivisionError):
        return None
    except Exception:
        logger.warning("Unexpected error evaluating expression: %s", expr, exc_info=True)
        return None

    # Format: int stays int, float drops unnecessary .0 for whole numbers
    if isinstance(raw_result, float) and raw_result == int(raw_result) and not math.isinf(raw_result):
        result_str = str(int(raw_result)) if raw_result < 1e15 else f"{raw_result:.6g}"
    elif isinstance(raw_result, float):
        result_str = f"{raw_result:.10g}"
    else:
        result_str = str(raw_result)

    return {"expression": expr, "result": result_str, "source": "Python"}


def build_calculator_card(q: str) -> tuple:
    """
    Input: q — raw search query string
    Output: (answer_card dict, ai_context str) or (None, None)
    Details:
        Entry point for the inline dispatcher. Detects, evaluates, and returns
        a structured answer_card and ai_context string.
    """
    expr = detect_calc_query(q)
    if expr is None:
        return None, None

    result = evaluate_expression(expr)
    if result is None:
        return None, None

    body = f"{expr} = {result['result']}"
    answer_card = {
        "type":   "calculator",
        "label":  "Calculator",
        "body":   body,
        "source": "Python",
    }
    ai_context = f"Calculator: {body}"
    return answer_card, ai_context


if __name__ == "__main__":
    pass
