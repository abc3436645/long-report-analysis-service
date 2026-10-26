"""Read-only use of prior mapping to exercise the new CLI on the selected budget case."""

import json
import re
import subprocess
from decimal import Decimal, InvalidOperation
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
OLD = ROOT.parent / "jxcc_analysis_report_project" / "scenarios" / "jxcc-budget-monthly"
WORK = ROOT / "projects" / "real_budget_acceptance"
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
project = call("project", "create", request={
    "scenario_id": "budget_operations", "scenario_version": "0.1.0",
    "subject_scope": {"organization": "集团合并", "units": units}, "report_period": "2026-07",
    "overrides": {"business_definitions.measurement_unit": "万元", "business_definitions.budget_version_rule": "time_plan"},
})
print("project", project["id"], flush=True)
material_ids = []
for table in mapping["tables"]:
    source = SOURCES / table["filename"]
    if not source.is_file():
        raise FileNotFoundError(source)
    roles = ("actuals", "budget") if table["id"] == "profit" else ("actuals",)
    for role in roles:
        material = call("material", "add", request={"project_id": project["id"], "input_id": role, "path": str(source)})
    if material["id"] not in material_ids:
        material_ids.append(material["id"])
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
print("evidence", len(snapshot["evidence_ids"]), "calculated", sum(item["status"] == "calculated" for item in calculations), "gaps", len(gaps), flush=True)
(WORK / "session.json").write_text(json.dumps({
    "project_id": project["id"], "run_id": run["id"], "source_ids": material_ids,
    "evidence_count": len(snapshot["evidence_ids"]), "calculated_count": sum(item["status"] == "calculated" for item in calculations),
    "gaps": gaps,
}, ensure_ascii=False, indent=2), encoding="utf-8")
