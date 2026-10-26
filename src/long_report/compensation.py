"""Deterministic, privacy-aware group totals for the payroll scenario."""

import re
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from hashlib import sha256


def _rows(material: dict, columns: dict) -> list[dict]:
    sheets = material["parsed"].get("sheets", {})
    if len(sheets) != 1:
        raise ValueError("payroll and roster inputs need exactly one sheet")
    cells = next(iter(sheets.values()))["cells"]
    headers = {match[1]: cell["value"] for address, cell in cells.items() if (match := re.fullmatch(r"([A-Z]+)1", address))}
    if not set(columns.values()) <= set(headers.values()):
        raise ValueError("payroll or roster columns do not match scenario configuration")
    rows = []
    for number in sorted({int(match[2]) for address in cells if (match := re.fullmatch(r"([A-Z]+)(\d+)", address)) and int(match[2]) > 1}):
        row = {key: cells.get(column + str(number), {}).get("value", "") for column, title in headers.items() for key, configured in columns.items() if title == configured}
        if any(value != "" for value in row.values()):
            rows.append(row)
    return rows


def _source(run: dict, materials: list[dict], role: str) -> dict | None:
    matches = [item for item in materials if item["id"] in run["material_ids"] and role in run["material_input_ids"][item["id"]]]
    if len(matches) > 1:
        raise ValueError(f"ambiguous {role} sources; select a replacement explicitly")
    return matches[0] if matches else None


def private_terms(run: dict, materials: list[dict]) -> set[str]:
    roster = _source(run, materials, "roster")
    if roster is None:
        return set()
    columns = run["effective_config"]["analysis"]["group_aggregation"]["roster_columns"]
    return {row["person"] for row in _rows(roster, columns) if row["person"]}


def calculate_groups(project: dict, run: dict, materials: list[dict]) -> list[dict]:
    payroll, roster = (_source(run, materials, role) for role in ("payroll", "roster"))
    if payroll is None or roster is None:
        return []
    config = run["effective_config"]["analysis"]["group_aggregation"]
    definitions = run["effective_config"]["scenario"]["business_definitions"]
    basis = definitions["accounting_basis"]
    headcount = definitions["headcount_or_fte_rule"]
    if basis not in (None, "accrual", "payment") or headcount not in (None, "distinct_people_at_period_end"):
        raise ValueError("unsupported compensation accounting or headcount rule")
    components = set(definitions["pay_components"].split(",")) if definitions["pay_components"] else set()
    if "" in components:
        raise ValueError("pay_components contains an empty component")
    threshold = definitions["minimum_group_size"]
    period = project["report_period"]
    membership = {}
    for row in _rows(roster, config["roster_columns"]):
        person, group, effective = row["person"], row["group"], row["effective_period"]
        if not person or not group or not re.fullmatch(r"\d{4}-\d{2}", effective):
            raise ValueError("invalid roster person, group or effective period")
        if effective > period:
            continue
        previous = membership.get(person)
        if previous and previous[0] == effective and previous[1] != group:
            raise ValueError("ambiguous same-period group assignment")
        if previous is None or effective > previous[0]:
            membership[person] = (effective, group)
    groups = project["subject_scope"]["groups"]
    sizes = {group: sum(assigned[1] == group for assigned in membership.values()) for group in groups}
    totals = defaultdict(Decimal)
    for row in _rows(payroll, config["payroll_columns"]):
        if not row["person"] or not row["component"]:
            raise ValueError("invalid payroll person or component")
        if row["component"] not in components or basis is None or row[basis + "_period"] != period:
            continue
        assigned = membership.get(row["person"])
        if assigned is None:
            raise ValueError("payroll person has no effective roster assignment")
        if assigned[1] not in groups:
            continue
        try:
            totals[assigned[1]] += Decimal(row["amount"])
        except InvalidOperation as error:
            raise ValueError("payroll amount is not numeric") from error
    results = []
    for group in groups:
        safe = threshold is not None and sizes[group] >= threshold and bool(components) and basis is not None and headcount is not None
        result = {"metric_id": config["metric_id"], "subject_id": group, "period": period,
                  "unit": config["unit"], "status": "calculated" if safe else "suppressed",
                  "value": str(totals[group]) if safe else None,
                  "source_ids": [payroll["id"], roster["id"]]}
        if safe:
            result["sample_size"] = sizes[group]
            result["id"] = "calc_" + sha256((run["id"] + group + period + result["value"]).encode()).hexdigest()[:24]
        results.append(result)
    overall_safe = all(item["status"] == "calculated" for item in results)
    total = {"metric_id": config["metric_id"], "subject_id": project["subject_scope"]["organization"],
             "period": period, "unit": config["unit"], "status": "calculated" if overall_safe else "suppressed",
             "value": str(sum(totals.values(), Decimal(0))) if overall_safe else None,
             "source_ids": [payroll["id"], roster["id"]]}
    if overall_safe:
        total["sample_size"] = sum(sizes.values())
        total["id"] = "calc_" + sha256((run["id"] + "total" + period + total["value"]).encode()).hexdigest()[:24]
    results.append(total)
    return results
