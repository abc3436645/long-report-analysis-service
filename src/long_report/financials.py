"""Deterministic financial descriptions and review coverage; never a credit model."""

import json
import re
from datetime import date
from decimal import Decimal, InvalidOperation, localcontext
from hashlib import sha256

from long_report.scenario import markdown_table_rows


# Inputs are current-period facts; opening/closing balances retain that period's identity.
FINANCIAL_METRICS = {
    "net_margin": ("net_profit", "revenue"),
    "gross_margin": ("revenue", "cost"),
    "debt_asset_ratio": ("liabilities", "assets"),
    "current_ratio": ("current_assets", "current_liabilities"),
    "quick_ratio": ("current_assets", "inventory", "current_liabilities"),
    "receivables_turnover": ("revenue", "receivables_open", "receivables_close"),
    "receivables_days": ("revenue", "receivables_open", "receivables_close"),
    "inventory_turnover": ("cost", "inventory_open", "inventory_close"),
    "inventory_days": ("cost", "inventory_open", "inventory_close"),
    "roe": ("net_profit", "equity_open", "equity_close"),
}
PERCENT_METRICS = {"net_margin", "gross_margin", "debt_asset_ratio", "roe"}
MONEY_UNITS = {"元": Decimal("1"), "万元": Decimal("10000"), "亿元": Decimal("100000000")}
REFERENCE = r"\{\{(?:fact|calc|ev):[^}|]+(?:\|[0-6])?\}\}"


def calculate_financials(evidence: list[dict], metric_ids: list[str]) -> list[dict]:
    groups = {}
    dimensions = ("subject_id", "period", "period_start", "period_days", "financial_scope", "financial_version")
    for fact in evidence:
        if fact["metric_id"].startswith("fin."):
            groups.setdefault(tuple(fact.get(key) for key in dimensions), []).append(fact)
    results = []
    for key, facts in sorted(groups.items(), key=lambda item: repr(item[0])):
        context = dict(zip(dimensions, key))
        for metric_id in metric_ids:
            fields = FINANCIAL_METRICS[metric_id]
            selected = [[f for f in facts if f["metric_id"] == "fin." + field] for field in fields]
            result = {**context, "metric_id": metric_id, "status": "calculated", "value": None,
                      "input_evidence_ids": [f["id"] for items in selected for f in items],
                      "formula_version": "financial-descriptions-v1", "formula_inputs": list(fields),
                      "annualization": "none", "precision": 34, "unit": "%" if metric_id in PERCENT_METRICS else "天" if metric_id.endswith("_days") else "倍" if metric_id in ("current_ratio", "quick_ratio") else "次"}
            try:
                valid_period = date.fromisoformat(context["period_start"]) <= date.fromisoformat(context["period"])
            except (ValueError, TypeError):
                valid_period = False
            if context["financial_scope"] not in ("standalone", "consolidated"):
                result["status"] = "unknown_scope"
            elif not valid_period or type(context["period_days"]) is not int or not 1 <= context["period_days"] <= 366:
                result["status"] = "unknown_period_basis"
            elif any(not items for items in selected):
                result["status"] = "missing_inputs"
            elif any(len(items) != 1 for items in selected):
                result["status"] = "conflicting_inputs"
            elif any(items[0].get("unit") not in MONEY_UNITS for items in selected):
                result["status"] = "unknown_unit"
            else:
                try:
                    with localcontext() as ctx:
                        ctx.prec = 34
                        values = [Decimal(items[0]["value"]) * MONEY_UNITS[items[0]["unit"]] for items in selected]
                        if not all(value.is_finite() for value in values):
                            raise InvalidOperation
                        if metric_id == "gross_margin":
                            numerator, denominator = values[0] - values[1], values[0]
                        elif metric_id == "quick_ratio":
                            numerator, denominator = values[0] - values[1], values[2]
                        elif len(values) == 3:
                            numerator, denominator = values[0], (values[1] + values[2]) / 2
                        else:
                            numerator, denominator = values
                        if metric_id.endswith("_days"):
                            numerator, denominator = context["period_days"] * denominator, numerator
                        if denominator <= 0:
                            result["status"] = "zero_denominator" if denominator == 0 else "nonpositive_denominator"
                        else:
                            value = numerator / denominator * (100 if metric_id in PERCENT_METRICS else 1)
                            result["value"] = format(value, "f")
                except (InvalidOperation, ValueError, TypeError):
                    result["status"] = "non_numeric_input"
            result["id"] = "calc_" + sha256(json.dumps(result, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:24]
            results.append(result)
    return results


def material_coverage(materials: list[dict], evidence: list[dict]) -> list[dict]:
    sources = {item["source_id"] for item in evidence}
    return [{"material_id": m["id"], "original_name": m["original_name"],
             "has_accepted_evidence": m["id"] in sources, "extraction": m["parsed"].get("coverage"),
             "derivation": m.get("derivation"),
             "status": "not_extracted" if m["id"] not in sources else "partial" if m["parsed"].get("coverage", {}).get("unread_pages") else "extracted_not_full_content_verified"}
            for m in materials]


def validate_financial_body(body: str, section: dict) -> None:
    """Check binding before expansion; structural dates/captions are explicit exceptions."""
    blocks = body.strip().split("\n\n")
    for asset in section.get("required_assets", []):
        gap = re.search(r"(?m)^资料缺口：" + re.escape(asset) + r"：\S.+$", body)
        table = any(asset in block and re.match(r"^表[0-9]+-[0-9]+[ 　]", block)
                    and i + 1 < len(blocks) and markdown_table_rows(blocks[i + 1]) is not None
                    for i, block in enumerate(blocks))
        if not gap and not table:
            raise ValueError("required financial asset needs a table or named gap: " + asset)
    clean = re.sub(REFERENCE, "", body)
    clean = re.sub(r"(?m)^#{1,6} +", "", clean)
    clean = re.sub(r"(?m)^表[0-9]+-[0-9]+[ 　]", "表 ", clean)
    clean = re.sub(r"(?<!\d)(?:19|20)\d{2}[—–至-](?:19|20)\d{2}年", "年份区间", clean)
    clean = re.sub(r"(?<!\d)(?:19|20)\d{2}年[0-9]{1,2}[—–至-][0-9]{1,2}月", "月度期间", clean)
    clean = re.sub(r"(?<!\d)(?:19|20)\d{2}(?:年(?:\d{1,2}月(?:\d{1,2}日)?)?|-[0-9]{2}(?:-[0-9]{2})?)(?!\d)", "日期", clean)
    if re.search(r"\d", clean):
        raise ValueError("unbound financial number: use current fact/calc references, including table values")


def review_requirements(markdown: str, outline: dict) -> list[dict]:
    requirements, section, table_index = [], None, 0
    by_title = {item["title"]: item for item in outline["sections"]}
    lines = markdown.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("# "):
            section = by_title.get(line[2:])
            table_index = 0
            if section and not section.get("subheadings"):
                requirements.append({"id": section["id"] + ":body", "kind": "section", "locator": f"line:{i+1}"})
        elif section and line.startswith("## "):
            requirements.append({"id": section["id"] + ":" + line[3:], "kind": "section", "locator": f"line:{i+1}"})
        if section and line.startswith("|") and i + 1 < len(lines) and re.fullmatch(r"\|[ :|\-]+\|", lines[i+1]):
            table_index += 1
            requirements.append({"id": section["id"] + f":table:{table_index}", "kind": "table", "locator": f"line:{i+1}"})
    for category in ("capability", "risk", "mitigation", "credit_terms"):
        requirements.append({"id": "claim:" + category, "kind": "claim", "locator": f"line:{next((i+1 for i, line in enumerate(lines) if line.strip() and not line.startswith(('#', '|'))), 1)}"})
    return requirements


def validate_review_coverage(entries: object, requirements: list[dict], markdown: str, permitted: set[str]) -> None:
    expected = {item["id"]: item for item in requirements}
    if (not isinstance(entries, list) or any(not isinstance(item, dict) for item in entries)
            or len(entries) != len(expected) or {item.get("id") for item in entries} != set(expected)):
        raise ValueError("financial review coverage must include every subsection, table and decision category")
    lines = markdown.splitlines()
    for entry in entries:
        match = re.fullmatch(r"line:([1-9][0-9]*)", str(entry.get("locator", "")))
        line = int(match[1]) if match else 0
        if not 1 <= line <= len(lines) or not entry.get("quote") or entry["quote"] not in lines[line-1]:
            raise ValueError("financial review location must quote the current draft")
        requirement = expected[entry["id"]]
        if requirement["kind"] != "claim" and entry["locator"] != requirement["locator"]:
            raise ValueError("financial review location does not match the required section/table")
        refs = entry.get("evidence_refs")
        if (entry.get("result") not in ("passed", "gap", "needs_changes")
                or not isinstance(entry.get("assessment"), str) or not entry["assessment"].strip()
                or not isinstance(refs, list) or any(not isinstance(ref, str) or ref not in permitted for ref in refs)
                or entry["result"] == "passed" and not refs):
            raise ValueError("financial review needs assessment and current evidence/calculation references or an explicit gap")
