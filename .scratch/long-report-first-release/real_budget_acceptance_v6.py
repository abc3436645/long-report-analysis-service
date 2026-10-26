"""Exercise per-run workbook mapping against the supplied budget files via report CLI."""

import json
import os
import subprocess
from pathlib import Path
import yaml


ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / "projects" / os.environ.get("BUDGET_WORK", "real_budget_acceptance_v6")
WORK.mkdir(parents=True, exist_ok=True)
REPORT = ROOT / ".venv" / "bin" / "report"
REQUEST = WORK / "request.json"
SOURCES = ROOT / "data" / "scenarios" / "budget_operations"


def call(*arguments, request=None):
    command = [str(REPORT), *arguments]
    if arguments[0] != "scenario":
        command += ["--workspace", str(WORK / "projects")]
    if request is not None:
        REQUEST.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
        command += ["--request", str(REQUEST)]
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f"{' '.join(arguments)}: {result.stderr[:1000]}")
    return json.loads(result.stdout)["data"]


profile = yaml.safe_load((ROOT / "tests/fixtures/budget_reference_mapping.yaml").read_text(encoding="utf-8"))["source_profiles"][0]
nested_after = {
    "母公司（冶炼）": ["贵冶", "贸易事业部"],
    "加工事业部": ["铜业铜材", "集团铜材", "江铜龙昌", "江铜台意", "华东铜材", "华东电工", "江铜嘉磁", "江铜川禾"],
}
units = [subject for name in profile["units"] for subject in [name, *nested_after.get(name, [])]]
assert set(units) == set(profile["units"]) | set(profile["nested_subjects"])
project = call("project", "create", request={
    "scenario_id": "budget_operations", "scenario_version": "0.2.0", "report_period": "2026-07",
    "report_title": "江铜集团预算办月度经营分析报告（二〇二六年七月）",
    "subject_scope": {"organization": profile["organization"], "units": units,
                      "special_subjects": profile["special_subjects"]},
    "overrides": {"business_definitions.measurement_unit": "万元",
                  "business_definitions.budget_version_rule": "time_plan"},
})
roles = {}
for table in profile["tables"]:
    roles.setdefault(table["filename"], set()).update(table["input_ids"])
for filename, declared in roles.items():
    for role in sorted(declared):
        call("material", "add", request={"project_id": project["id"], "input_id": role,
                                        "path": str(SOURCES / filename)})
market = SOURCES / "当前国际与国内贵金属市场主要品种行情与价格走势如下.docx"
call("material", "add", request={"project_id": project["id"], "input_id": "explanations", "path": str(market)})
run = call("run", "start", request={"project_id": project["id"]})
tasks = call("task", "list", "--project", project["id"], "--run", run["id"])
accepted = 0
for task in tasks:
    material = call("task", "context", task["id"], "--project", project["id"])["material"]
    if material["original_name"] in roles:
        submitted = call("task", "auto-submit", request={"project_id": project["id"], "run_id": run["id"],
                                                        "task_id": task["id"], "mapping": profile})
    else:
        submitted = call("task", "submit", request={"project_id": project["id"], "run_id": run["id"],
                                                   "task_id": task["id"], "input_fingerprint": task["input_fingerprint"],
                                                   "candidates": []})
    for candidate in submitted["candidates"]:
        call("evidence", "decide", request={"project_id": project["id"], "run_id": run["id"],
                                            "candidate_id": candidate["id"], "decision": "accept"})
        accepted += 1
    print(material["original_name"], len(submitted["candidates"]), flush=True)
snapshot = call("evidence", "freeze", request={"project_id": project["id"], "run_id": run["id"]})
calculations = call("calculate", request={"project_id": project["id"], "run_id": run["id"]})
calculated = sum(item["status"] == "calculated" for item in calculations)
assert accepted == len(snapshot["evidence_ids"]) == 6 * (len(units) + 1) + 702, (accepted, len(snapshot["evidence_ids"]))
assert calculated > 3 * len(units) + 2, calculated
(WORK / "session.json").write_text(json.dumps({"project_id": project["id"], "run_id": run["id"],
                                               "evidence_count": accepted, "calculated_count": calculated},
                                              ensure_ascii=False, indent=2), encoding="utf-8")
print("complete", project["id"], run["id"], accepted, calculated, flush=True)
