"""Run the current budget CLI against the inspected July mining source rows."""

import json
import os
import subprocess
from hashlib import sha256
from copy import deepcopy
from pathlib import Path

import yaml
from openpyxl import load_workbook
from docx import Document


ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / "projects" / os.environ.get("MINING_WORK", "mining_board_2026_07_acceptance")
SOURCES = ROOT / "data" / "scenarios" / "budget_operations"
REPORT = ROOT / ".venv" / "bin" / "report"
REQUEST = WORK / "request.json"
WORK.mkdir(parents=True, exist_ok=True)


def call(*args, request=None):
    command = [str(REPORT), *args, "--workspace", str(WORK / "projects")]
    if request is not None:
        REQUEST.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
        command += ["--request", str(REQUEST)]
    response = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    if response.returncode:
        raise RuntimeError(f"{' '.join(args)}: {response.stderr[:2000]}")
    return json.loads(response.stdout)["data"]


profile = deepcopy(yaml.safe_load((ROOT / "tests/fixtures/budget_reference_mapping.yaml").read_text(encoding="utf-8"))["source_profiles"][0])
units = profile["units"][:6]
assert units == ["德兴铜矿（含新技术）", "永平铜矿", "武山铜矿", "城门山铜矿", "银山矿业", "银珠山矿业"]
deep = os.environ.get("MINING_DEEP") == "1"
rows = {"profit": set(range(6 if deep else 7, 14)), "cost": {4, 5, 6, 7, 9, 10},
        "cost_inputs": {16, 17, 18, 19, 21, 22},
        "concentrate": {4, 5, 6, 8, 9, 10, 12, 13, 14, 16, 17, 18},
        "sulfur": set(range(4, 11))}
profile["id"] = "inspected_mining_sources_2026_07"
profile["units"] = units
profile["nested_subjects"] = []
profile["aggregate_subjects"] = ["矿山板块合计"]
profile["special_subjects"] = ["sulfur:r9:七宝山"]
profile["tables"] = [table for table in profile["tables"] if table["id"] in rows]
assert set(table["id"] for table in profile["tables"]) == set(rows)
for table in profile["tables"]:
    table["rows"] = [row for row in table["rows"] if row["row"] in rows[table["id"]]]
    assert {row["row"] for row in table["rows"]} == rows[table["id"]]
    sheet = load_workbook(SOURCES / table["filename"], read_only=True, data_only=False)[table["sheet"]]
    cached = load_workbook(SOURCES / table["filename"], read_only=True, data_only=True)[table["sheet"]]
    assert "MOCK" in str(sheet["B1"].value) or "MOCK" in str(sheet["B2"].value)
    for row in table["rows"]:
        assert str(sheet[f"{table['subject_column']}{row['row']}"].value).strip() == row["source_subject"].strip(), (table["id"], row)
        for field in table["fields"]:
            assert isinstance(cached[f"{field['column']}{row['row']}"].value, (int, float)), (table["id"], row["row"], field["column"])

(WORK / "mapping.json").write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
if deep:
    used = {table["filename"] for table in profile["tables"]}
    audit = []
    for path in sorted(SOURCES.iterdir()):
        if not path.is_file() or path.name.startswith(".~lock."):
            continue
        entry = {"filename": path.name, "sha256": sha256(path.read_bytes()).hexdigest(),
                 "usage": "mapped_mining_evidence" if path.name in used else "reviewed_context_only"}
        if path.suffix == ".xlsx":
            workbook = load_workbook(path, read_only=True, data_only=True)
            entry["sheets"] = [sheet.title for sheet in workbook]
            entry["opening_cells"] = [str(value)[:100] for sheet in workbook for row in sheet.iter_rows(min_row=1, max_row=3, values_only=True) for value in row if value is not None][:8]
        elif path.suffix == ".docx":
            entry["opening_text"] = [paragraph.text[:150] for paragraph in Document(path).paragraphs if paragraph.text.strip()][:3]
        audit.append(entry)
    assert len(audit) == 13, len(audit)
    (WORK / "source_audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
project = call("project", "create", request={
    "scenario_id": "budget_operations", "scenario_version": "0.2.0", "report_period": "2026-07",
    "report_title": "江铜集团矿山板块月度经营分析报告（2026年1—7月，技术工作稿）",
    "subject_scope": {"organization": "集团合并", "units": units,
                      "special_subjects": ["矿山板块合计", "sulfur:r9:七宝山"]},
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
if deep:
    for entry in audit:
        if entry["usage"] == "reviewed_context_only":
            call("material", "add", request={"project_id": project["id"], "input_id": "context_materials",
                                            "path": str(SOURCES / entry["filename"])})
run = call("run", "start", request={"project_id": project["id"]})
tasks = call("task", "list", "--project", project["id"], "--run", run["id"])
evidence = []
for task in tasks:
    material = call("task", "context", task["id"], "--project", project["id"])["material"]
    if material["original_name"] in roles:
        submitted = call("task", "auto-submit", request={"project_id": project["id"], "run_id": run["id"],
                                                         "task_id": task["id"], "mapping": profile})
    else:
        assert deep and material["original_name"] in {entry["filename"] for entry in audit}
        submitted = call("task", "submit", request={"project_id": project["id"], "run_id": run["id"],
                                                    "task_id": task["id"], "input_fingerprint": task["input_fingerprint"],
                                                    "candidates": []})
    assert not submitted.get("excluded_rows", []), (material["original_name"], submitted.get("excluded_rows"))
    for candidate in submitted["candidates"]:
        result = call("evidence", "decide", request={"project_id": project["id"], "run_id": run["id"],
                                                     "candidate_id": candidate["id"], "decision": "accept"})
        assert result["status"] == "usable", result
        evidence.append(result)
    print(material["original_name"], len(submitted["candidates"]), flush=True)
snapshot = call("evidence", "freeze", request={"project_id": project["id"], "run_id": run["id"]})
assert len(snapshot["evidence_ids"]) == len(evidence)
calculations = call("calculate", request={"project_id": project["id"], "run_id": run["id"]})
assert len([item for item in calculations if item["status"] == "calculated"]) > 40
for filename, value in (("evidence.json", evidence), ("calculations.json", calculations),
                        ("session.json", {"project_id": project["id"], "run_id": run["id"],
                                          "evidence_count": len(evidence), "calculation_count": len(calculations)})):
    (WORK / filename).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
print("prepared", project["id"], run["id"], len(evidence), len(calculations), flush=True)
