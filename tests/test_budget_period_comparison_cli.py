"""Budget period differences are calculated from the corresponding frozen source cells."""

import json
import subprocess
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path


REPORT = Path(sys.executable).with_name("report")


class BudgetPeriodComparisonCliTests(unittest.TestCase):
    def test_december_has_no_remaining_monthly_target(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "projects"
            request_path = root / "request.json"

            def call(*args, request=None):
                command = [REPORT, *args, "--workspace", str(workspace)]
                if request is not None:
                    request_path.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
                    command += ["--request", str(request_path)]
                result = subprocess.run(command, cwd=root, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                return json.loads(result.stdout)["data"]

            project = call("project", "create", request={
                "scenario_id": "budget_operations", "scenario_version": "0.2.0", "report_period": "2026-12",
                "subject_scope": {"organization": "集团合并", "units": ["甲单位"]},
                "overrides": {"business_definitions.measurement_unit": "万元",
                              "business_definitions.budget_version_rule": "time_plan"},
            })
            source = root / "profit.csv"
            source.write_text("主体,累计,年度计划\n甲单位,320,300\n", encoding="utf-8")
            for role in ("actuals", "budget"):
                call("material", "add", request={"project_id": project["id"], "input_id": role, "path": str(source)})
            run = call("run", "start", request={"project_id": project["id"]})
            task = call("task", "list", "--project", project["id"], "--run", run["id"])[0]
            submitted = call("task", "submit", request={"project_id": project["id"], "run_id": run["id"],
                                                       "task_id": task["id"], "input_fingerprint": task["input_fingerprint"],
                                                       "candidates": [
                                                           {"subject_id": "甲单位", "metric_id": "profit_total",
                                                            "period": period, "window": window, "unit": "万元",
                                                            "basis": basis, "budget_version": version,
                                                            "value": value, "source_value": value,
                                                            "source_locator": "sheet:CSV/cell:" + cell}
                                                           for cell, value, period, window, basis, version in (
                                                               ("B2", "320", "2026-12", "ytd", "actuals", None),
                                                               ("C2", "300", "2026", "annual", "budget", "annual_plan"))]})
            for candidate in submitted["candidates"]:
                call("evidence", "decide", request={"project_id": project["id"], "run_id": run["id"],
                                                   "candidate_id": candidate["id"], "decision": "accept"})
            call("evidence", "freeze", request={"project_id": project["id"], "run_id": run["id"]})
            target = next(item for item in call("calculate", request={"project_id": project["id"], "run_id": run["id"]})
                          if item["metric_id"] == "remaining_monthly_target")
            self.assertEqual((target["status"], target["value"]), ("no_remaining_months", None))

    def test_month_and_ytd_differences_use_their_own_baselines(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "projects"
            request_path = root / "request.json"

            def call(*args, request=None):
                command = [REPORT, *args, "--workspace", str(workspace)]
                if request is not None:
                    request_path.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
                    command += ["--request", str(request_path)]
                result = subprocess.run(command, cwd=root, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                return json.loads(result.stdout)["data"]

            project = call("project", "create", request={
                "scenario_id": "budget_operations", "scenario_version": "0.2.0", "report_period": "2026-07",
                "subject_scope": {"organization": "集团合并", "units": ["甲单位"]},
                "overrides": {"business_definitions.measurement_unit": "万元", "business_definitions.budget_version_rule": "time_plan"},
            })
            source = root / "profit.csv"
            source.write_text("主体,本月,上月,累计,同期,年度计划\n甲单位,30,45,120,90,300\n", encoding="utf-8")
            call("material", "add", request={"project_id": project["id"], "input_id": "actuals", "path": str(source)})
            call("material", "add", request={"project_id": project["id"], "input_id": "budget", "path": str(source)})
            run = call("run", "start", request={"project_id": project["id"]})
            task = call("task", "list", "--project", project["id"], "--run", run["id"])[0]
            values = [("B2", "30", "2026-07", "month", "actuals", None),
                      ("C2", "45", "2026-06", "month", "actuals", None),
                      ("D2", "120", "2026-07", "ytd", "actuals", None),
                      ("E2", "90", "2025-07", "ytd", "actuals", None),
                      ("F2", "300", "2026", "annual", "budget", "annual_plan")]
            submitted = call("task", "submit", request={"project_id": project["id"], "run_id": run["id"],
                                                       "task_id": task["id"], "input_fingerprint": task["input_fingerprint"],
                                                       "candidates": [{"subject_id": "甲单位", "metric_id": "profit_total", "period": period,
                                                                       "window": window, "unit": "万元", "basis": basis,
                                                                       "budget_version": version,
                                                                       "value": value, "source_value": value,
                                                                       "source_locator": f"sheet:CSV/cell:{cell}"}
                                                                      for cell, value, period, window, basis, version in values]})
            evidence = {}
            for candidate in submitted["candidates"]:
                item = call("evidence", "decide", request={"project_id": project["id"], "run_id": run["id"],
                                                       "candidate_id": candidate["id"], "decision": "accept"})
                evidence[(item["period"], item["window"])] = item["id"]
            call("evidence", "freeze", request={"project_id": project["id"], "run_id": run["id"]})
            results = {item["metric_id"]: item for item in call("calculate", request={"project_id": project["id"], "run_id": run["id"]}) if item["status"] == "calculated"}
            self.assertEqual(results["month_change"]["value"], "-15")
            self.assertEqual(results["ytd_change"]["value"], "30")
            self.assertEqual(Decimal(results["month_change_rate"]["value"]).quantize(Decimal("0.01")), Decimal("-33.33"))
            self.assertEqual(Decimal(results["ytd_change_rate"]["value"]).quantize(Decimal("0.01")), Decimal("33.33"))
            self.assertEqual(results["remaining_monthly_target"]["value"], "36")
            self.assertEqual(results["remaining_monthly_target"]["input_evidence_ids"],
                             [evidence["2026-07", "ytd"], evidence["2026", "annual"]])
            self.assertEqual(results["month_change"]["input_evidence_ids"], [evidence["2026-07", "month"], evidence["2026-06", "month"]])
            self.assertEqual(results["ytd_change"]["input_evidence_ids"], [evidence["2026-07", "ytd"], evidence["2025-07", "ytd"]])
            chart = call("chart", "create", request={"project_id": project["id"], "run_id": run["id"],
                                                      "title": "甲单位累计利润同比",
                                                      "series": [{"label": "本年累计", "evidence_id": evidence["2026-07", "ytd"]},
                                                                 {"label": "上年同期", "evidence_id": evidence["2025-07", "ytd"]}]})
            self.assertEqual({item["metric_id"] for item in chart["annotations"]}, {"ytd_change", "ytd_change_rate"})


if __name__ == "__main__":
    unittest.main()
