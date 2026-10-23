"""Operators permitted in versioned scenario definitions."""

from decimal import Decimal


def difference(actual: Decimal, baseline: Decimal) -> Decimal:
    return actual - baseline


OPERATORS = {"difference": difference}
