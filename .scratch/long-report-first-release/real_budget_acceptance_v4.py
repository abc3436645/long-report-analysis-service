"""Read-only use of prior mapping to exercise the new CLI on the selected budget case."""

import json
import re
import subprocess
from decimal import Decimal, InvalidOperation
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
OLD = ROOT.parent / "jxcc_analysis_report_project" / "scenarios" / "jxcc-budget-monthly"
WORK = ROOT / "projects" / "real_budget_acceptance_v4"
REPORT = ROOT / ".venv" / "bin" / "report"
SOURCES = ROOT / "data" / "scenarios" / "budget_operations"
WORK.mkdir(parents=True, exist_ok=True)
REQUEST = WORK / "request.json"


def call(*arguments, request=None):
    command = [str(REPORT), *arguments, "--workspace", str(WORK / "projects")]
    if request is not None:
        REQUEST.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
        command += ["--request", str(REQUEST)]
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f"{' '.join(arguments)}: {result.stderr[:1000]}")
    return json.loads(result.stdout)["data"]


mapping = yaml.safe_load((OLD / "mapping.yaml").read_text(encoding="utf-8"))
template = yaml.safe_load((OLD / "template.yaml").read_text(encoding="utf-8"))
profit = next(item for item in mapping["tables"] if item["id"] == "profit")
unit_rows = [item["unit"]["profit_row"] for item in template["sections"] if item["id"].startswith("unit_")]
units = [profit["expected_subjects"][str(row)].strip() for row in unit_rows]
assert len(unit_rows) == len(set(unit_rows)) == 42
units_by_row = dict(zip(unit_rows, units))
related_units = {}
for section in template["sections"]:
    if section["id"].startswith("unit_"):
        unit_name = units_by_row[section["unit"]["profit_row"]]
        for selector in section.get("fact_filters", []):
            rows = [selector["row"]] if "row" in selector else next((table["rows"] for table in mapping["tables"] if table["id"] == selector["table"]), []) if "metric" not in selector else []
            for row in rows:
                related_units.setdefault((selector["table"], row), set()).add(unit_name)
special_subjects = sorted({
    f"{table['id']}:r{row}:{table['expected_subjects'][str(row)].strip()}"
    for table in mapping["tables"] if table["id"] != "profit"
    for row in table["rows"]
    if (table["id"], row) not in related_units and table["expected_subjects"][str(row)].strip() != "集团合并"
})
project = call("project", "create", request={
    "scenario_id": "budget_operations", "scenario_version": "0.1.0",
    "subject_scope": {"organization": "集团合并", "units": units, "special_subjects": special_subjects}, "report_period": "2026-07",
    "overrides": {"business_definitions.measurement_unit": "万元", "business_definitions.budget_version_rule": "time_plan"},
})
print("project", project["id"], flush=True)
material_ids = []
for table in mapping["tables"]:
    source = SOURCES / table["filename"]
    if not source.is_file():
        raise FileNotFoundError(source)
    roles = ("actuals", "budget") if table["id"] in {"profit", "tc", "acid", "sulfur", "price_plan"} else ("actuals",)
    for role in roles:
        material = call("material", "add", request={"project_id": project["id"], "input_id": role, "path": str(source)})
    if material["id"] not in material_ids:
        material_ids.append(material["id"])
market_source = SOURCES / "当前国际与国内贵金属市场主要品种行情与价格走势如下.docx"
market_material = call("material", "add", request={"project_id": project["id"], "input_id": "explanations", "path": str(market_source)})
material_ids.append(market_material["id"])
print("materials", len(material_ids), flush=True)
run = call("run", "start", request={"project_id": project["id"]})
tasks = call("task", "list", "--project", project["id"], "--run", run["id"])
accepted = {}
gaps = []
for task in tasks:
    context = call("task", "context", task["id"], "--project", project["id"])
    material = context["material"]
    candidates = []
    if material["original_name"] == profit["filename"]:
        cells = material["parsed"]["sheets"][profit["sheet"]]["cells"]
        for row in [6, *unit_rows]:
            subject = profit["expected_subjects"][str(row)].strip()
            for label, column, basis, period, window, version in (
                ("month", "D", "actuals", "2026-07", "month", None),
                ("previous", "E", "actuals", "2026-06", "month", None),
                ("ytd", "F", "actuals", "2026-07", "ytd", None),
                ("prior", "G", "actuals", "2025-07", "ytd", None),
                ("annual", "H", "budget", "2026", "annual", "annual_plan"),
                ("time_plan", "I", "budget", "2026-07", "ytd", "time_plan"),
            ):
                cell = cells.get(f"{column}{row}")
                if cell is None or cell["value"] is None or cell.get("state") not in (None, "verified"):
                    gaps.append([subject, label])
                    continue
                try:
                    Decimal(cell["value"])
                except InvalidOperation:
                    gaps.append([subject, label])
                    continue
                candidates.append({
                    "subject_id": subject, "metric_id": "profit_total", "period": period, "window": window,
                    "unit": "万元", "basis": basis, "budget_version": version,
                    "value": cell["value"], "source_value": cell["value"], "source_locator": cell["locator"],
                })
    else:
        for table in (item for item in mapping["tables"] if item["filename"] == material["original_name"]):
            cells = material["parsed"]["sheets"][table["sheet"]]["cells"]
            for row in table["rows"]:
                source_subject = table["expected_subjects"][str(row)]
                subject_cell = cells.get(f"{table['subject_column']}{row}")
                if subject_cell is None or subject_cell["value"] != source_subject:
                    raise RuntimeError(f"source row changed: {table['id']} {row}")
                targets = sorted(related_units.get((table["id"], row), []))
                if not targets:
                    targets = ["集团合并" if source_subject.strip() == "集团合并" else f"{table['id']}:r{row}:{source_subject.strip()}"]
                for name, column in table["columns"].items():
                    cell = cells.get(f"{column['column']}{row}")
                    if cell is None or cell["value"] is None or cell.get("state") not in (None, "verified"):
                        gaps.append([table["id"], row, name])
                        continue
                    try:
                        Decimal(cell["value"])
                    except InvalidOperation:
                        gaps.append([table["id"], row, name])
                        continue
                    if table["id"] == "price_plan":
                        period, window, basis, version = "2026", "annual", "budget", "annual_plan"
                    elif table["id"] == "equity":
                        period = "2026-06" if name == "previous" else "2026-01" if name == "initial" else "2026-07"
                        window, basis, version = ("ytd" if name == "ytd_gain" else "month"), "actuals", None
                    else:
                        period = "2025-07" if "prior" in name else "2026-07"
                        window = "ytd"
                        basis = "budget" if "plan" in name else "actuals"
                        version = "time_plan" if basis == "budget" else None
                    for subject in targets:
                        candidates.append({
                            "subject_id": subject, "source_subject": source_subject.strip(),
                            "metric_id": f"{table['id']}.r{row}.{name}", "period": period,
                            "window": window, "unit": column.get("unit"),
                            "basis": basis, "budget_version": version,
                            "value": cell["value"], "source_value": cell["value"], "source_locator": cell["locator"],
                            "mapping_basis": f"reference_mapping:{table['id']}:r{row}",
                        })
    submitted = call("task", "submit", request={
        "project_id": project["id"], "run_id": run["id"], "task_id": task["id"],
        "input_fingerprint": task["input_fingerprint"], "candidates": candidates,
    })
    for candidate in submitted["candidates"]:
        evidence = call("evidence", "decide", request={
            "project_id": project["id"], "run_id": run["id"], "candidate_id": candidate["id"], "decision": "accept",
        })
        match = re.search(r"cell:([A-Z]+)(\d+)", candidate["source_locator"])
        accepted[(candidate["subject_id"], match.group(1))] = evidence["id"]
    print("task", material["original_name"], len(candidates), flush=True)
snapshot = call("evidence", "freeze", request={"project_id": project["id"], "run_id": run["id"]})
calculations = call("calculate", request={"project_id": project["id"], "run_id": run["id"]})
assert len(snapshot["evidence_ids"]) == 960
assert sum(item["status"] == "calculated" for item in calculations) == 42
assert not gaps
print("evidence", len(snapshot["evidence_ids"]), "calculated", sum(item["status"] == "calculated" for item in calculations), "gaps", len(gaps), flush=True)
(WORK / "session.json").write_text(json.dumps({
    "project_id": project["id"], "run_id": run["id"], "source_ids": material_ids,
    "evidence_count": len(snapshot["evidence_ids"]), "calculated_count": sum(item["status"] == "calculated" for item in calculations),
    "gaps": gaps,
}, ensure_ascii=False, indent=2), encoding="utf-8")
