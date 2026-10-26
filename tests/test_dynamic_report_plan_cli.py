"""A report outline is chosen for the user's current request, not for a fixed board profile."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPORT = Path(sys.executable).with_name("report")


class DynamicReportPlanCliTests(unittest.TestCase):
    def test_budget_plan_cannot_omit_a_requested_unit_or_a_source_decision(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "projects"
            request_file = root / "request.json"

            def invoke(*args, request):
                request_file.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
                return subprocess.run([REPORT, *args, "--workspace", str(workspace), "--request", str(request_file)],
                                      capture_output=True, text=True)

            project_result = invoke("project", "create", request={
                "scenario_id": "budget_operations", "scenario_version": "0.2.0", "report_period": "2026-07",
                "subject_scope": {"organization": "合成集团", "units": ["甲矿", "乙矿"]},
            })
            self.assertEqual(project_result.returncode, 0, project_result.stderr)
            project = json.loads(project_result.stdout)["data"]
            source_ids = []
            for name in ("甲矿", "乙矿"):
                source = root / f"{name}.csv"
                source.write_text(f"单位,说明\n{name},待核对\n", encoding="utf-8")
                result = invoke("material", "add", request={"project_id": project["id"], "input_id": "actuals", "path": str(source)})
                self.assertEqual(result.returncode, 0, result.stderr)
                source_ids.append(json.loads(result.stdout)["data"]["id"])
            result = invoke("run", "start", request={"project_id": project["id"]})
            self.assertEqual(result.returncode, 0, result.stderr)
            run = json.loads(result.stdout)["data"]
            tasks = subprocess.run([REPORT, "task", "list", "--project", project["id"], "--run", run["id"],
                                    "--workspace", str(workspace)], capture_output=True, text=True)
            self.assertEqual(tasks.returncode, 0, tasks.stderr)
            for task in json.loads(tasks.stdout)["data"]:
                result = invoke("task", "submit", request={"project_id": project["id"], "run_id": run["id"],
                                                           "task_id": task["id"], "input_fingerprint": task["input_fingerprint"], "candidates": []})
                self.assertEqual(result.returncode, 0, result.stderr)
            result = invoke("evidence", "freeze", request={"project_id": project["id"], "run_id": run["id"]})
            self.assertEqual(result.returncode, 0, result.stderr)
            plan = {"project_id": project["id"], "run_id": run["id"], "report_request": "分析甲矿和乙矿经营情况",
                    "material_uses": [{"material_id": source_id, "use": "context", "reason": "原表只含待核文字"} for source_id in source_ids],
                    "outline": {"unit_names": ["甲矿"], "sections": [{"id": "units", "title": "逐矿分析", "display_order": 1,
                                                                   "repeat_for": "unit", "depends_on": [], "evidence_refs": [], "analysis_refs": []}]}}
            missing_unit = invoke("draft", "plan", request=plan)
            self.assertNotEqual(missing_unit.returncode, 0)
            self.assertIn("project units", missing_unit.stderr)
            plan["outline"]["unit_names"] = ["甲矿", "乙矿"]
            plan["material_uses"] = plan["material_uses"][:1]
            missing_source = invoke("draft", "plan", request=plan)
            self.assertNotEqual(missing_source.returncode, 0)
            self.assertIn("material_uses", missing_source.stderr)

    def test_same_budget_scenario_accepts_distinct_request_plans(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "projects"
            request_file = root / "request.json"

            def call(*args, request=None):
                command = [REPORT, *args, "--workspace", str(workspace)]
                if request is not None:
                    request_file.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
                    command += ["--request", str(request_file)]
                result = subprocess.run(command, cwd=root, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                return json.loads(result.stdout)["data"]

            for subject, request_text, chapter in (
                ("甲矿", "分析甲矿本月预算差异与成本风险", "矿山经营与成本分析"),
                ("乙加工", "分析乙加工产品效益和订单风险", "铜加工产品效益分析"),
            ):
                project = call("project", "create", request={
                    "scenario_id": "budget_operations", "scenario_version": "0.2.0",
                    "report_period": "2026-07", "subject_scope": {"organization": "合成集团", "units": [subject]},
                })
                source = root / f"{subject}.csv"
                source.write_text(f"单位,利润\n{subject},100\n", encoding="utf-8")
                call("material", "add", request={"project_id": project["id"], "input_id": "actuals", "path": str(source)})
                run = call("run", "start", request={"project_id": project["id"]})
                task = call("task", "list", "--project", project["id"], "--run", run["id"])[0]
                call("task", "submit", request={"project_id": project["id"], "run_id": run["id"],
                                                "task_id": task["id"], "input_fingerprint": task["input_fingerprint"],
                                                "candidates": []})
                call("evidence", "freeze", request={"project_id": project["id"], "run_id": run["id"]})
                call("calculate", request={"project_id": project["id"], "run_id": run["id"]})
                request_file.write_text(json.dumps({"project_id": project["id"], "run_id": run["id"]}), encoding="utf-8")
                missing_plan = subprocess.run([REPORT, "draft", "plan", "--workspace", str(workspace), "--request", str(request_file)],
                                              cwd=root, capture_output=True, text=True)
                self.assertNotEqual(missing_plan.returncode, 0)
                self.assertIn("report_request", missing_plan.stderr)
                plan = {"sections": [
                    {"id": "scope", "title": "资料与口径", "display_order": 1, "repeat_for": None,
                     "evidence_refs": [], "analysis_refs": [], "depends_on": []},
                    {"id": "units", "title": chapter, "display_order": 2, "repeat_for": "unit",
                     "evidence_refs": [], "analysis_refs": ["performance_review"], "depends_on": ["scope"]},
                    {"id": "summary", "title": "管理建议", "display_order": 3, "repeat_for": None,
                     "evidence_refs": [], "analysis_refs": ["performance_review"], "depends_on": ["units"]},
                ], "unit_names": [subject], "unit_levels": {}}
                tasks = call("draft", "plan", request={"project_id": project["id"], "run_id": run["id"],
                                                       "report_request": request_text, "outline": plan,
                                                       "material_uses": [{"material_id": run["material_ids"][0], "use": "context",
                                                                          "reason": "样例只有待确认利润字段"}]})
                self.assertEqual([item["section_id"] for item in tasks], ["scope", f"units:{subject}", "summary"])
                self.assertEqual(tasks[2]["depends_on"], [f"units:{subject}"])
                frozen = call("run", "show", run["id"], "--project", project["id"])
                self.assertEqual(frozen["report_request"], request_text)
                self.assertEqual(frozen["effective_config"]["outline"]["sections"][1]["title"], chapter)
                while any(item["status"] != "submitted" for item in tasks):
                    for ready in (item for item in tasks if item["status"] == "ready"):
                        call("draft", "submit", request={"project_id": project["id"], "run_id": run["id"],
                                                          "task_id": ready["id"], "author_id": "writer", "body": ready["title"] + "按本轮需求分析。"})
                    tasks = call("draft", "plan", request={"project_id": project["id"], "run_id": run["id"]})
                draft = call("draft", "build", request={"project_id": project["id"], "run_id": run["id"]})
                call("review", "submit", request={"project_id": project["id"], "run_id": run["id"],
                                                   "draft_sha256": draft["sha256"], "reviewer_id": "reviewer",
                                                   "verdict": "pass", "issues": []})
                revision = call("publish", request={"project_id": project["id"], "run_id": run["id"]})
                update = call("run", "start", request={"project_id": project["id"], "base_revision_id": revision["id"]})
                call("evidence", "freeze", request={"project_id": project["id"], "run_id": update["id"]})
                call("calculate", request={"project_id": project["id"], "run_id": update["id"]})
                revised_plan = json.loads(json.dumps(plan, ensure_ascii=False))
                revised_plan["sections"][1]["goal"] = "增加用户对成本与原因的分析要点"
                revised = call("draft", "plan", request={"project_id": project["id"], "run_id": update["id"],
                                                         "report_request": request_text + "；增加成本与原因分析",
                                                         "outline": revised_plan,
                                                         "material_uses": [{"material_id": update["material_ids"][0], "use": "context",
                                                                            "reason": "样例只有待确认利润字段"}]})
                by_section = {item["section_id"]: item for item in revised}
                self.assertEqual(by_section["scope"]["status"], "submitted")
                self.assertNotEqual(by_section[f"units:{subject}"]["status"], "submitted")
                self.assertNotEqual(by_section["summary"]["status"], "submitted")


if __name__ == "__main__":
    unittest.main()
