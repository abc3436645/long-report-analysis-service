"""Presentation-only money conversion; source values and calculations stay unchanged."""
import re
from decimal import Decimal, ROUND_HALF_UP, localcontext


UNITS = {"元": Decimal(1), "万元": Decimal(10000), "亿元": Decimal(100000000)}
NUMBER = r"[+-]?(?:(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?"


def validate_amount_display(rule: object) -> None:
    keys = {"table_unit", "chart_unit", "text_unit", "text_large_unit", "text_large_threshold", "decimal_places"}
    if (not isinstance(rule, dict) or set(rule) != keys
            or any(not isinstance(rule[k], str) or rule[k] not in UNITS
                   for k in ("table_unit", "chart_unit", "text_unit", "text_large_unit"))
            or type(rule["decimal_places"]) is not int or not 0 <= rule["decimal_places"] <= 6
            or not isinstance(rule["text_large_threshold"], str)
            or not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", rule["text_large_threshold"])
            or Decimal(rule["text_large_threshold"]) <= 0):
        raise ValueError("invalid presentation.amount_display definition")


def amount_in_yuan(item: dict) -> Decimal | None:
    raw, declared = str(item.get("value", "")).strip(), item.get("unit")
    match = re.fullmatch("(" + NUMBER + r")(亿元|万元|元)?", raw)
    if declared not in UNITS and not (match and match[2] and declared in (None, "", "text")):
        return None
    if not match or match[2] and declared not in (None, "", "text", match[2]):
        raise ValueError("monetary reference has an invalid value or conflicting unit")
    with localcontext() as arithmetic:
        arithmetic.prec = max(120, len(raw) + 20)
        return Decimal(match[1].replace(",", "")) * UNITS[match[2] or declared]


def display_amount(item: dict, rule: dict, medium: str, precision: str | None = None) -> tuple[str, str] | None:
    value = amount_in_yuan(item)
    if value is None:
        return None
    unit = rule[medium + "_unit"]
    # Test the unrounded magnitude; losses follow the same scale as positive amounts.
    if medium == "text" and value.copy_abs() >= Decimal(rule["text_large_threshold"]):
        unit = rule["text_large_unit"]
    with localcontext() as arithmetic:
        arithmetic.prec = max(120, len(value.as_tuple().digits) + 20)
        shown = value / UNITS[unit]
        shown = shown.quantize(Decimal(1).scaleb(-int(precision if precision is not None else rule["decimal_places"])), rounding=ROUND_HALF_UP)
    return format(shown, "f"), unit


def convert_chart_point(item: dict, unit: str) -> dict:
    value = amount_in_yuan(item)
    if value is None:
        return dict(item)
    with localcontext() as arithmetic:
        arithmetic.prec = max(120, len(value.as_tuple().digits) + 20)
        converted = format(value / UNITS[unit], "f")
    return {**item, "value": converted, "unit": unit}
