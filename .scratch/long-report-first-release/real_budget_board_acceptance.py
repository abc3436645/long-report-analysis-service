"""Ingest the supplied MOCK workbooks for three budget board reports through report CLI."""

import json
import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / "projects" / os.environ.get("BUDGET_BOARD_WORK", "real_budget_board_acceptance")
WORK.mkdir(parents=True, exist_ok=True)
REPORT = ROOT / ".venv/bin/report"
SOURCES = ROOT / "data/scenarios/budget_operations"
REQUEST = WORK / "request.json"


def call(*arguments, request=None):
    command = [str(REPORT), *arguments]
    if arguments[0] != "scenario":
        command += ["--workspace", str(WORK / "projects")]
    if request is not None:
        REQUEST.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
        command += ["--request", str(REQUEST)]
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f"{arguments}: {result.stderr[:1000]}")
    return json.loads(result.stdout)["data"]


scenario = call("scenario", "budget_operations")
source_profile = next(item for item in scenario["analysis"]["source_profiles"] if item["id"] == "reference_2026_07")
roles = {}
for table in source_profile["tables"]:
    roles.setdefault(table["filename"], set()).update(table["input_ids"])

for profile_id, title, aggregate, special in (
    ("mining", "江铜集团矿山板块月度经营分析报告（2026年1—7月）", "矿山板块合计", ["sulfur:r9:七宝山"]),
    ("smelting", "江铜集团冶炼板块经营分析报告（2026年1—7月）", "冶炼板块合计", ["acid:r8:铅锌公司"]),
    ("processing", "江铜集团铜加工板块经营分析报告（2026年1—7月）", "加工板块", [item for item in source_profile["special_subjects"] if item.startswith("processing:")]),
):
    session_path = WORK / f"{profile_id}.json"
    if session_path.exists():
        print("existing", profile_id, session_path, flush=True)
        continue
    project = call("project", "create", request={
        "scenario_id": "budget_operations", "scenario_version": "0.1.0", "report_period": "2026-07",
        "report_profile": profile_id, "report_title": title,
        "subject_scope": {"organization": source_profile["organization"],
                          "units": scenario["outline"]["profiles"][profile_id]["unit_names"],
                          "special_subjects": [aggregate, *special]},
        "overrides": {"business_definitions.measurement_unit": "万元",
                      "business_definitions.budget_version_rule": "time_plan"},
    })
    for filename, declared in roles.items():
        for role in sorted(declared):
            call("material", "add", request={"project_id": project["id"], "input_id": role,
                                            "path": str(SOURCES / filename)})
    market = SOURCES / "当前国际与国内贵金属市场主要品种行情与价格走势如下.docx"
    call("material", "add", request={"project_id": project["id"], "input_id": "explanations", "path": str(market)})
    run = call("run", "start", request={"project_id": project["id"]})
    accepted = 0
    excluded = 0
    for task in call("task", "list", "--project", project["id"], "--run", run["id"]):
        material = call("task", "context", task["id"], "--project", project["id"])["material"]
        if material["original_name"] in roles:
            submitted = call("task", "auto-submit", request={"project_id": project["id"], "run_id": run["id"],
                                                            "task_id": task["id"], "profile_id": source_profile["id"]})
            excluded += len(submitted["excluded_rows"])
        else:
            submitted = call("task", "submit", request={"project_id": project["id"], "run_id": run["id"],
                                                       "task_id": task["id"], "input_fingerprint": task["input_fingerprint"],
                                                       "candidates": []})
        for candidate in submitted["candidates"]:
            call("evidence", "decide", request={"project_id": project["id"], "run_id": run["id"],
                                                "candidate_id": candidate["id"], "decision": "accept"})
            accepted += 1
    snapshot = call("evidence", "freeze", request={"project_id": project["id"], "run_id": run["id"]})
    calculations = call("calculate", request={"project_id": project["id"], "run_id": run["id"]})
    calculated = sum(item["status"] == "calculated" for item in calculations)
    assert accepted == len(snapshot["evidence_ids"]) and accepted > 0 and calculated == 3 * len(project["subject_scope"]["units"]) + 5
    session_path.write_text(json.dumps({"project_id": project["id"], "run_id": run["id"],
                                        "accepted": accepted, "calculated": calculated, "excluded_rows": excluded},
                                       ensure_ascii=False, indent=2), encoding="utf-8")
    print("prepared", profile_id, accepted, calculated, excluded, flush=True)
