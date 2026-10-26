"""Recalculate the small, explicit Excel formula subset used by source checks."""

import ast
import math
import re
from decimal import Decimal

from openpyxl.utils.cell import range_boundaries


def recalculate(sheet, coordinate: str) -> Decimal:
    active = set()
    memo = {}

    def cell(reference):
        reference = reference.replace("$", "")
        if reference in memo:
            return memo[reference]
        if reference in active:
            raise ValueError("circular formula")
        active.add(reference)
        value = sheet[reference].value
        if value is None:
            result = Decimal(0)
        elif isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
            result = Decimal(str(value))
        elif isinstance(value, str) and value.startswith("="):
            result = formula(value)
        else:
            raise ValueError("formula references nonnumeric cell")
        active.remove(reference)
        memo[reference] = result
        return result

    def area(reference):
        left, top, right, bottom = range_boundaries(reference.replace("$", ""))
        return [cell(sheet.cell(row, column).coordinate) for row in range(top, bottom + 1) for column in range(left, right + 1)]

    def visit(node):
        if isinstance(node, ast.Expression):
            return visit(node.body)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, str):
                return node.value
            if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
                return Decimal(str(node.value))
        if isinstance(node, ast.BinOp):
            left, right = visit(node.left), visit(node.right)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if isinstance(node.op, ast.Div):
                return left / right
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            return -visit(node.operand)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            values = [visit(argument) for argument in node.args]
            if node.func.id == "V" and len(values) == 1:
                return cell(values[0])
            if node.func.id == "R" and len(values) == 1:
                return area(values[0])
            if node.func.id == "SUM":
                return sum((sum(value, Decimal(0)) if isinstance(value, list) else value for value in values), Decimal(0))
            if node.func.id == "SUMPRODUCT" and values and all(isinstance(value, list) for value in values) and len({len(value) for value in values}) == 1:
                return sum((math.prod(items) for items in zip(*values)), Decimal(0))
        raise ValueError("unsupported formula")

    def formula(expression):
        references = []

        def hide(match):
            references.append(match.group())
            return f"PLACEHOLDER_{len(references) - 1}"

        source = re.sub(r"\$?[A-Z]+\$?\d+(?::\$?[A-Z]+\$?\d+)?", hide, expression[1:])
        source = re.sub(r"PLACEHOLDER_(\d+)", lambda match: f"{'R' if ':' in references[int(match[1])] else 'V'}({references[int(match[1])]!r})", source)
        return visit(ast.parse(source, mode="eval"))

    return cell(coordinate)
