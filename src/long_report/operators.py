"""Operators permitted in versioned scenario definitions."""

from decimal import Decimal


def difference(actual: Decimal, baseline: Decimal) -> Decimal:
    return actual - baseline


def positive_base_change_rate(actual: Decimal, baseline: Decimal) -> Decimal:
    return (actual - baseline) / baseline * 100


def positive_base_completion_rate(actual: Decimal, baseline: Decimal) -> Decimal:
    return actual / baseline * 100


def remaining_monthly_target(actual: Decimal, annual_plan: Decimal, remaining_months: int) -> Decimal:
    return (annual_plan - actual) / remaining_months


OPERATORS = {"difference": difference, "positive_base_change_rate": positive_base_change_rate,
             "positive_base_completion_rate": positive_base_completion_rate,
             "remaining_monthly_target": remaining_monthly_target}
