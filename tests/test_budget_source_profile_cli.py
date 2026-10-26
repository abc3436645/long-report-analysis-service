"""The shipped budget profile can extract the reference workbook without the old repository."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from openpyxl import load_workbook
import yaml


REPORT = Path(sys.executable).with_name("report")
ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data/scenarios/budget_operations/利润计划执行情况表_2026-10-14.xlsx"


class BudgetSourceProfileCliTests(unittest.TestCase):
    def test_reference_profile_submits_traced_budget_candidates(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "projects"
            request_path = root / "request.json"

            def call(*args, request=None):
                command = [REPORT, *args, "--workspace", str(workspace)] if args[0] != "scenario" else [REPORT, *args]
                if request is not None:
                    request_path.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
                    command += ["--request", str(request_path)]
                result = subprocess.run(command, cwd=root, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                return json.loads(result.stdout)["data"]

            profile = yaml.safe_load((ROOT / "tests/fixtures/budget_reference_mapping.yaml").read_text(encoding="utf-8"))["source_profiles"][0]
            self.assertEqual(len(profile["units"]), 42)
            self.assertEqual(len(profile["special_subjects"]), 29)
            project = call("project", "create", request={
                "scenario_id": "budget_operations", "scenario_version": "0.2.0", "report_period": "2026-07",
                "subject_scope": {"organization": profile["organization"], "units": profile["units"],
                                  "special_subjects": profile["special_subjects"]},
            })
            for role in ("actuals", "budget"):
                call("material", "add", request={"project_id": project["id"], "input_id": role, "path": str(SOURCE)})
            run = call("run", "start", request={"project_id": project["id"]})
            task = call("task", "list", "--project", project["id"], "--run", run["id"])[0]
            submitted = call("task", "auto-submit", request={
                "project_id": project["id"], "run_id": run["id"], "task_id": task["id"],
                "mapping": profile, "scope_exclusion_reason": "本项目只纳入已声明的单位和专项，其他汇总与嵌套行另行核对",
            })
            self.assertEqual(len(submitted["candidates"]), 43 * 6)
            group = [item for item in submitted["candidates"] if item["subject_id"] == "集团合并"]
            self.assertEqual(len(group), 6)
            self.assertEqual({item["basis"] for item in group}, {"actuals", "budget"})
            self.assertEqual({item["period"] for item in group}, {"2026-07", "2026-06", "2025-07", "2026"})
            self.assertTrue(all(item["source_locator"].startswith("sheet:Sheet1/cell:") for item in group))

            mining_project = call("project", "create", request={
                "scenario_id": "budget_operations", "scenario_version": "0.2.0", "report_period": "2026-07",
                "subject_scope": {"organization": profile["organization"], "units": ["德兴铜矿（含新技术）"],
                                  "special_subjects": ["矿山板块合计"]},
            })
            for role in ("actuals", "budget"):
                call("material", "add", request={"project_id": mining_project["id"], "input_id": role, "path": str(SOURCE)})
            mining_run = call("run", "start", request={"project_id": mining_project["id"]})
            mining_task = call("task", "list", "--project", mining_project["id"], "--run", mining_run["id"])[0]
            mining_request = {
                "project_id": mining_project["id"], "run_id": mining_run["id"], "task_id": mining_task["id"],
                "mapping": profile,
            }
            request_path.write_text(json.dumps(mining_request, ensure_ascii=False), encoding="utf-8")
            unreviewed_scope = subprocess.run([REPORT, "task", "auto-submit", "--workspace", str(workspace),
                                               "--request", str(request_path)], cwd=root, capture_output=True, text=True)
            self.assertNotEqual(unreviewed_scope.returncode, 0)
            self.assertIn("scope_exclusion_reason", unreviewed_scope.stderr)
            scope_reason = "用户本轮仅要求德兴铜矿及矿山板块合计，其他原表单位不属于项目范围"
            mining_result = call("task", "auto-submit", request={**mining_request,
                "scope_exclusion_reason": scope_reason})
            mining_candidates = mining_result["candidates"]
            self.assertEqual({item["subject_id"] for item in mining_candidates}, {"德兴铜矿（含新技术）", "矿山板块合计", "集团合并"})
            self.assertEqual(len(mining_candidates), 18)
            self.assertIn({"table_id": "profit", "row": 8, "targets": ["永平铜矿"]}, mining_result["excluded_rows"])
            stored_task = call("task", "context", mining_task["id"], "--project", mining_project["id"])["task"]
            self.assertTrue(stored_task["scope_exclusions"])
            self.assertTrue(all(item["reason"] == scope_reason for item in stored_task["scope_exclusions"]))

            altered = root / SOURCE.name
            workbook = load_workbook(SOURCE)
            workbook["Sheet1"]["B6"] = "其他主体"
            workbook.save(altered)
            second_project = call("project", "create", request={
                "scenario_id": "budget_operations", "scenario_version": "0.2.0", "report_period": "2026-07",
                "subject_scope": {"organization": profile["organization"], "units": profile["units"],
                                  "special_subjects": profile["special_subjects"]},
            })
            for role in ("actuals", "budget"):
                call("material", "add", request={"project_id": second_project["id"], "input_id": role, "path": str(altered)})
            second_run = call("run", "start", request={"project_id": second_project["id"]})
            second_task = call("task", "list", "--project", second_project["id"], "--run", second_run["id"])[0]
            request_path.write_text(json.dumps({"project_id": second_project["id"], "run_id": second_run["id"],
                                                "task_id": second_task["id"], "mapping": profile}), encoding="utf-8")
            refused = subprocess.run([REPORT, "task", "auto-submit", "--workspace", str(workspace), "--request", str(request_path)],
                                     cwd=root, capture_output=True, text=True)
            self.assertNotEqual(refused.returncode, 0)
            self.assertIn("row 6 subject changed", json.loads(refused.stderr)["error"])


if __name__ == "__main__":
    unittest.main()
