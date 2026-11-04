"""MCP Server: eng_calc
Exposes engineering calculation and mathematical formula evaluation to agents.
"""

from __future__ import annotations

import ast
import math
import operator
from typing import Any

from mcp.server.mcpserver import MCPServer

server = MCPServer("eng_calc")

# Allowed operators in math evaluation
_OPERATORS: dict[type[ast.AST], Any] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}

# Allowed functions and constants
_MATH_ENV = {
    "sqrt": math.sqrt,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "log": math.log,
    "log10": math.log10,
    "exp": math.exp,
    "ceil": math.ceil,
    "floor": math.floor,
    "abs": abs,
    "round": round,
    "pow": math.pow,
    "pi": math.pi,
    "e": math.e,
}


def _eval_node(node: ast.AST) -> float | int:
    """Safely evaluate an AST node containing mathematical expressions."""
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return node.value
        raise ValueError(f"Literal constant of type {type(node.value).__name__} is not allowed")

    if isinstance(node, ast.Name):
        if node.id in _MATH_ENV:
            val = _MATH_ENV[node.id]
            if isinstance(val, (int, float)):
                return val
            raise ValueError(f"Constant '{node.id}' must be evaluated as a function call")
        raise ValueError(f"Undefined variable or unauthorized identifier: '{node.id}'")

    if isinstance(node, ast.UnaryOp):
        op_type = type(node.op)
        if op_type in _OPERATORS:
            operand = _eval_node(node.operand)
            return _OPERATORS[op_type](operand)
        raise ValueError(f"Unsupported unary operator: {op_type.__name__}")

    if isinstance(node, ast.BinOp):
        op_type = type(node.op)
        if op_type in _OPERATORS:
            left = _eval_node(node.left)
            right = _eval_node(node.right)
            # Prevent excessive powers (denial of service)
            if op_type is ast.Pow and (right > 1000 or (left > 10 and right > 100)):
                raise OverflowError("Exponentiation exceeds maximum safe limit")
            return _OPERATORS[op_type](left, right)
        raise ValueError(f"Unsupported binary operator: {op_type.__name__}")

    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name):
            raise ValueError("Dynamic or nested function calls are not allowed")
        func_name = node.func.id
        if func_name not in _MATH_ENV or not callable(_MATH_ENV[func_name]):
            raise ValueError(f"Function '{func_name}' is not in the allowed math environment")
        args = [_eval_node(arg) for arg in node.args]
        return _MATH_ENV[func_name](*args)

    raise ValueError(f"Unsupported syntax expression: {type(node).__name__}")


def calculate(expression: str) -> str:
    """Evaluate a mathematical expression or engineering calculation safely."""
    clean_expr = (expression or "").strip()
    if not clean_expr:
        return "Error: Empty expression"

    try:
        parsed = ast.parse(clean_expr, mode="eval")
        result = _eval_node(parsed.body)
        if isinstance(result, float) and result.is_integer():
            return str(int(result))
        if isinstance(result, float):
            return f"{result:.6f}".rstrip("0").rstrip(".")
        return str(result)
    except OverflowError as oe:
        return f"Calculation error: Exceeds numerical limits ({oe})"
    except ZeroDivisionError:
        return "Calculation error: Division by zero"
    except Exception as exc:
        return f"Calculation error: Invalid expression '{clean_expr}' ({exc})"


@server.tool()
def eng_calc(expression: str) -> str:
    """Perform engineering calculations, arithmetic evaluations, and unit conversions."""
    return calculate(expression)


if __name__ == "__main__":
    server.run(transport="stdio")
