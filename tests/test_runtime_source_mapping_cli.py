"""A source mapping is made for the uploaded workbook and checked against that workbook."""

import json
import subprocess
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from openpyxl import Workbook


REPORT = Path(sys.executable).with_name("report")


class RuntimeSourceMappingCliTests(unittest.TestCase):
    def test_uploaded_workbook_values_are_extracted_with_this_runs_mapping(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "projects"
            request_file = root / "request.json"

            def call(*args, request=None):
                command = [REPORT, *args, "--workspace", str(workspace)] if args[0] != "scenario" else [REPORT, *args]
                if request is not None:
                    request_file.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
                    command += ["--request", str(request_file)]
                result = subprocess.run(command, cwd=root, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                return json.loads(result.stdout)["data"]

            scenario = call("scenario", "budget_operations")
            self.assertNotIn("source_profiles", scenario["analysis"])
            mapping = {"id": "uploaded_monthly", "report_period": "2026-07", "organization": "合成集团",
                       "units": ["甲矿"], "special_subjects": [], "tables": [{
                           "id": "profit", "filename": "monthly.xlsx", "sheet": "数据", "subject_column": "A",
                           "input_ids": ["actuals", "budget"],
                           "rows": [{"row": 2, "source_subject": "甲矿", "targets": ["甲矿"]}],
                           "fields": [
                               {"id": "current", "column": "B", "period": "2026-07", "window": "ytd", "basis": "actuals", "unit": "万元", "budget_version": None},
                               {"id": "plan", "column": "C", "period": "2026-07", "window": "ytd", "basis": "budget", "unit": "万元", "budget_version": "time_plan"},
                               {"id": "annual", "column": "D", "period": "2026", "window": "annual", "basis": "budget", "unit": "万元", "budget_version": "annual_plan"},
                           ],
                       }, {
                           "id": "cost", "filename": "monthly.xlsx", "sheet": "数据", "subject_column": "A",
                           "input_ids": ["actuals"],
                           "rows": [{"row": 3, "source_subject": "甲矿", "targets": ["甲矿"]}],
                           "fields": [
                               {"id": "ore_cost", "column": "B", "period": "2026-07", "window": "ytd", "basis": "actuals", "unit": "元/吨", "budget_version": None},
                               {"id": "ore_cost_prior", "column": "C", "period": "2025-07", "window": "ytd", "basis": "actuals", "unit": "元/吨", "budget_version": None},
                           ],
                       }]}
            for actual, time_plan, annual_plan, expected in ((27, 20, 100, "7"), (31, 20, 100, "11"), (5, 0, 0, "5")):
                project = call("project", "create", request={
                    "scenario_id": "budget_operations", "scenario_version": "0.2.0", "report_period": "2026-07",
                    "subject_scope": {"organization": "合成集团", "units": ["甲矿"]},
                    "overrides": {"business_definitions.measurement_unit": "万元",
                                  "business_definitions.budget_version_rule": "time_plan"},
                })
                path = root / "monthly.xlsx"
                book = Workbook()
                sheet = book.active
                sheet.title = "数据"
                sheet.append(["单位", "实际利润", "序时计划", "年度计划"])
                sheet.append(["甲矿", actual, time_plan, annual_plan])
                sheet.append(["甲矿", 111.35, 104.07])
                book.save(path)
                for role in ("actuals", "budget"):
                    call("material", "add", request={"project_id": project["id"], "input_id": role, "path": str(path)})
                run = call("run", "start", request={"project_id": project["id"]})
                task = call("task", "list", "--project", project["id"], "--run", run["id"])[0]
                candidates = call("task", "auto-submit", request={"project_id": project["id"], "run_id": run["id"],
                                                                  "task_id": task["id"], "mapping": mapping})["candidates"]
                self.assertEqual([item["value"] for item in candidates], [str(actual), str(time_plan), str(annual_plan), "111.35", "104.07"])
                evidence = [call("evidence", "decide", request={"project_id": project["id"], "run_id": run["id"],
                                                                 "candidate_id": item["id"], "decision": "accept"}) for item in candidates]
                call("evidence", "freeze", request={"project_id": project["id"], "run_id": run["id"]})
                results = call("calculate", request={"project_id": project["id"], "run_id": run["id"]})
                self.assertEqual(next(item["value"] for item in results if item["metric_id"] == "budget_difference"), expected)
                cost_change = next(item for item in results if item["metric_id"] == "cost.r3.ore_cost_yoy_difference")
                cost_rate = next(item for item in results if item["metric_id"] == "cost.r3.ore_cost_yoy_rate")
                self.assertEqual((Decimal(cost_change["value"]), cost_change["input_evidence_ids"]),
                                 (Decimal("7.28"), [evidence[3]["id"], evidence[4]["id"]]))
                self.assertEqual(Decimal(cost_rate["value"]).quantize(Decimal("0.01")), Decimal("7.00"))
                annual_rate = next(item for item in results if item["metric_id"] == "annual_plan_completion_rate")
                if annual_plan:
                    self.assertEqual(Decimal(annual_rate["value"]), Decimal(actual))
                else:
                    self.assertEqual((annual_rate["status"], annual_rate["value"]), ("non_comparable_rate", None))
                    budget_rate = next(item for item in results if item["metric_id"] == "budget_completion_rate")
                    self.assertEqual((budget_rate["status"], budget_rate["value"]), ("non_comparable_rate", None))


if __name__ == "__main__":
    unittest.main()
