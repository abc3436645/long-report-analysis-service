"""The supplied workbook, not a stored evidence profile, drives the budget figures."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import nullcontext
from decimal import Decimal
from pathlib import Path

import yaml
from openpyxl import load_workbook


ROOT = Path(__file__).resolve().parents[1]
REPORT = Path(sys.executable).with_name("report")
SOURCE = ROOT / "data/scenarios/budget_operations/利润计划执行情况表_2026-10-14.xlsx"
COST_SOURCE = ROOT / "data/scenarios/budget_operations/矿山成本指标完成情况_2026-10-14.xlsx"
SULFUR_SOURCE = ROOT / "data/scenarios/budget_operations/硫精矿增减利分析_2026-10-14.xlsx"
CONCENTRATE_SOURCE = ROOT / "data/scenarios/budget_operations/四矿铜精矿产销增减利情况_2026-10-14.xlsx"
MAPPING = ROOT / "tests/fixtures/budget_reference_mapping.yaml"


class BudgetReferenceIndicatorsCliTests(unittest.TestCase):
    def test_sulfur_source_column_is_prior_cost_not_current_cost(self):
        profile = yaml.safe_load(MAPPING.read_text(encoding="utf-8"))["source_profiles"][0]
        sulfur = next(table for table in profile["tables"] if table["id"] == "sulfur")
        column = next(field for field in sulfur["fields"] if field["column"] == "M")
        workbook = load_workbook(SULFUR_SOURCE, read_only=True, data_only=True)
        self.assertEqual(workbook.active["M2"].value, "上年成本")
        self.assertEqual((column["id"], column["period"]), ("cost_prior", "2025-07"))

    def test_uploaded_mining_cost_workbook_calculates_unit_cost_changes(self):
        profile = yaml.safe_load(MAPPING.read_text(encoding="utf-8"))["source_profiles"][0]
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

            name = "德兴铜矿（含新技术）"
            project = call("project", "create", request={
                "scenario_id": "budget_operations", "scenario_version": "0.2.0", "report_period": "2026-07",
                "subject_scope": {"organization": "集团合并", "units": [name]},
            })
            call("material", "add", request={"project_id": project["id"], "input_id": "actuals", "path": str(COST_SOURCE)})
            run = call("run", "start", request={"project_id": project["id"]})
            task = call("task", "list", "--project", project["id"], "--run", run["id"])[0]
            candidates = call("task", "auto-submit", request={"project_id": project["id"], "run_id": run["id"],
                                                              "task_id": task["id"], "mapping": profile,
                                                              "scope_exclusion_reason": "本轮仅分析德兴铜矿，其他原表单位不在项目范围"})["candidates"]
            self.assertGreater(len(candidates), 8)
            for candidate in candidates:
                call("evidence", "decide", request={"project_id": project["id"], "run_id": run["id"],
                                                    "candidate_id": candidate["id"], "decision": "accept"})
            call("evidence", "freeze", request={"project_id": project["id"], "run_id": run["id"]})
            results = {item["metric_id"]: item for item in call("calculate", request={"project_id": project["id"], "run_id": run["id"]})
                       if item["subject_id"] == name and item["status"] == "calculated"}
            self.assertEqual(Decimal(results["cost.r4.ore_cost_yoy_difference"]["value"]).quantize(Decimal("0.01")), Decimal("7.27"))
            self.assertEqual(Decimal(results["cost.r4.metal_cost_yoy_difference"]["value"]).quantize(Decimal("0.01")), Decimal("1037.57"))
            tasks = call("draft", "plan", request={"project_id": project["id"], "run_id": run["id"],
                                                   "report_request": "分析德兴铜矿成本同比变化",
                                                   "material_uses": [{"material_id": identifier, "use": "analysis", "reason": "已确认成本数据"} for identifier in run["material_ids"]],
                                                   "outline": {"unit_names": [name], "sections": [{
                                                       "id": "mining_cost", "title": "矿山成本分析", "display_order": 1,
                                                       "repeat_for": "unit", "depends_on": [], "evidence_refs": [],
                                                       "analysis_refs": ["cost.r4.ore_cost_yoy_difference", "cost.r4.metal_cost_yoy_difference"],
                                                   }]}})
            self.assertEqual(tasks[0]["section_id"], "mining_cost:" + name)

    def test_de_xing_profit_rates_and_three_series_chart_use_uploaded_cells(self):
        profile = yaml.safe_load(MAPPING.read_text(encoding="utf-8"))["source_profiles"][0]
        acceptance = os.environ.get("LONG_REPORT_ACCEPTANCE_ROOT")
        directory = Path(acceptance).resolve() / self._testMethodName if acceptance else None
        if directory:
            directory.mkdir(parents=True, exist_ok=True)
        with nullcontext(directory) if directory else tempfile.TemporaryDirectory() as temporary:
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

            name = "德兴铜矿（含新技术）"
            project = call("project", "create", request={
                "scenario_id": "budget_operations", "scenario_version": "0.2.0", "report_period": "2026-07",
                "subject_scope": {"organization": "集团合并", "units": [name]},
                "overrides": {"business_definitions.measurement_unit": "万元",
                              "business_definitions.budget_version_rule": "time_plan"},
            })
            for role in ("actuals", "budget"):
                call("material", "add", request={"project_id": project["id"], "input_id": role, "path": str(SOURCE)})
            call("material", "add", request={"project_id": project["id"], "input_id": "actuals", "path": str(COST_SOURCE)})
            call("material", "add", request={"project_id": project["id"], "input_id": "actuals", "path": str(SULFUR_SOURCE)})
            call("material", "add", request={"project_id": project["id"], "input_id": "budget", "path": str(SULFUR_SOURCE)})
            call("material", "add", request={"project_id": project["id"], "input_id": "actuals", "path": str(CONCENTRATE_SOURCE)})
            call("material", "add", request={"project_id": project["id"], "input_id": "budget", "path": str(CONCENTRATE_SOURCE)})
            run = call("run", "start", request={"project_id": project["id"]})
            candidates = []
            for task in call("task", "list", "--project", project["id"], "--run", run["id"]):
                candidates += call("task", "auto-submit", request={"project_id": project["id"], "run_id": run["id"],
                                                                   "task_id": task["id"], "mapping": profile,
                                                                   "scope_exclusion_reason": "本轮仅分析德兴铜矿，其他原表单位不在项目范围"})["candidates"]
            self.assertGreater(len(candidates), 26)
            evidence = [call("evidence", "decide", request={"project_id": project["id"], "run_id": run["id"],
                                                             "candidate_id": candidate["id"], "decision": "accept"}) for candidate in candidates]
            call("evidence", "freeze", request={"project_id": project["id"], "run_id": run["id"]})
            results = {item["metric_id"]: item for item in call("calculate", request={"project_id": project["id"], "run_id": run["id"]})
                       if item["subject_id"] == name and item["status"] == "calculated"}
            self.assertEqual(Decimal(results["month_change"]["value"]).quantize(Decimal("0.01")), Decimal("4288.49"))
            self.assertEqual(Decimal(results["ytd_change_rate"]["value"]).quantize(Decimal("0.01")), Decimal("12.64"))
            self.assertEqual(Decimal(results["budget_difference"]["value"]).quantize(Decimal("0.01")), Decimal("-26915.45"))
            self.assertEqual(Decimal(results["annual_plan_completion_rate"]["value"]).quantize(Decimal("0.01")), Decimal("55.18"))
            points = {(item["period"], item["window"], item.get("basis"), item.get("budget_version")): item["id"]
                      for item in evidence if item["subject_id"] == name and item["metric_id"] == "profit_total"}
            cost = {item["metric_id"]: item["id"] for item in evidence if item["metric_id"].startswith("cost.")}
            cost_inputs = {item["metric_id"]: item["id"] for item in evidence if item["metric_id"].startswith("cost_inputs.")}
            chart = call("chart", "create", request={"project_id": project["id"], "run_id": run["id"],
                                                      "title": "图4-1 德兴铜矿累计利润与同期及序时计划",
                                                      "series": [
                                                          {"label": "本年累计", "evidence_id": points["2026-07", "ytd", "actuals", None]},
                                                          {"label": "上年同期", "evidence_id": points["2025-07", "ytd", "actuals", None]},
                                                          {"label": "累计序时计划", "evidence_id": points["2026-07", "ytd", "budget", "time_plan"]},
                                                      ]})
            self.assertEqual(len(chart["series"]), 3)
            self.assertEqual({item["metric_id"] for item in chart["annotations"]},
                             {"budget_difference", "budget_completion_rate", "ytd_change", "ytd_change_rate"})
            self.assertIn(SOURCE.name, chart["source_caption"])
            self.assertEqual(chart["source_caption"].count(SOURCE.name), 1)
            self.assertIn("Sheet1!F7", chart["source_caption"])
            self.assertTrue(Path(chart["path"]).is_file())
            plan = {"sections": [
                {"id": "scope", "title": "资料与口径", "display_order": 1, "repeat_for": None,
                 "depends_on": [], "evidence_refs": [], "analysis_refs": []},
                {"id": "unit_analysis", "title": "矿山单位分析", "display_order": 2, "repeat_for": "unit",
                 "depends_on": ["scope"], "evidence_refs": ["actual_amount", "budget_amount"],
                 "analysis_refs": ["budget_difference", "ytd_change_rate", "annual_plan_completion_rate"]},
                {"id": "summary", "title": "结论与待核事项", "display_order": 3, "repeat_for": None,
                 "depends_on": ["unit_analysis"], "evidence_refs": [], "analysis_refs": []},
            ], "unit_names": [name]}
            tasks = call("draft", "plan", request={"project_id": project["id"], "run_id": run["id"],
                                                     "report_request": "仅分析德兴铜矿累计利润、计划进度与待核成本原因",
                                                     "material_uses": [{"material_id": identifier, "use": "analysis", "reason": "已确认利润或成本数据"} for identifier in run["material_ids"]],
                                                     "outline": plan})
            tasks = {item["section_id"]: item for item in tasks}
            context = call("draft", "context", tasks["unit_analysis:" + name]["id"], "--project", project["id"])
            self.assertTrue(any("经营变化" in item for item in context["writing_guidance"]["unit_sequence"]))
            def token(kind, identifier, precision=None):
                return "{{" + kind + ":" + identifier + ("|" + str(precision) if precision is not None else "") + "}}"
            call("draft", "submit", request={"project_id": project["id"], "run_id": run["id"],
                                                     "task_id": tasks["scope"]["id"], "author_id": "writer",
                                                     "body": "本稿只使用本轮上传的利润计划执行原表。集团合并规则、成本和产销台账未获确认，相关原因仅列为核查事项。"})
            current = points["2026-07", "ytd", "actuals", None]
            month = points["2026-07", "month", "actuals", None]
            previous = points["2026-06", "month", "actuals", None]
            prior = points["2025-07", "ytd", "actuals", None]
            time_plan = points["2026-07", "ytd", "budget", "time_plan"]
            annual = points["2026", "annual", "budget", "annual_plan"]
            unit_body = ("经营综述：本月较上月增加 " + token("calc", results["month_change"]["id"], 2) + " 万元。累计利润同比增长 " + token("calc", results["ytd_change_rate"]["id"], 2) + "% ，但较序时计划差额为 "
                         + token("calc", results["budget_difference"]["id"], 2) + " 万元；年度计划完成率为 "
                         + token("calc", results["annual_plan_completion_rate"]["id"], 2)
                         + "% 。同比改善与计划缺口同时存在，需核对成本、产销和结算明细，不能仅凭利润表判断成因。\n\n"
                         + "表4-1 德兴铜矿利润比较情况表\n\n"
                         + "| 利润比较项目 | 本期或累计实际 | 比较基准 | 差额或完成率 |\n| --- | ---: | ---: | ---: |\n"
                         + "| 本月与上月（万元） | " + token("fact", month, 2) + " | " + token("fact", previous, 2) + " | " + token("calc", results["month_change"]["id"], 2) + " |\n"
                         + "| 累计同比利润（万元） | " + token("fact", current, 2) + " | " + token("fact", prior, 2) + " | "
                         + token("calc", results["ytd_change"]["id"], 2) + "；" + token("calc", results["ytd_change_rate"]["id"], 2) + "% |\n"
                         + "| 累计序时计划（万元） | " + token("fact", current, 2) + " | " + token("fact", time_plan, 2) + " | "
                         + token("calc", results["budget_difference"]["id"], 2) + " |\n"
                         + "| 年度计划完成率 | " + token("fact", current, 2) + " | " + token("fact", annual, 2) + " | "
                         + token("calc", results["annual_plan_completion_rate"]["id"], 2) + "% |\n\n"
                         + token("chart", chart["id"]) + "\n\n"
                         + "经营变化分析：吨矿成本与金属成本同比上升，处理量和品位资料需进一步核对。\n\n"
                         + "表4-2 德兴铜矿主要经营指标表\n\n"
                         + "| 经营指标 | 本期 | 同期 | 同比差额 |\n| --- | ---: | ---: | ---: |\n"
                         + "| 吨矿成本（元/吨） | " + token("fact", cost["cost.r4.ore_cost"], 2) + " | "
                         + token("fact", cost["cost.r4.ore_cost_prior"], 2) + " | "
                         + token("calc", results["cost.r4.ore_cost_yoy_difference"]["id"], 2) + " |\n"
                         + "| 金属成本（元/吨） | " + token("fact", cost["cost.r4.metal_cost"], 2) + " | "
                         + token("fact", cost["cost.r4.metal_cost_prior"], 2) + " | "
                         + token("calc", results["cost.r4.metal_cost_yoy_difference"]["id"], 2) + " |\n"
                         + "| 吨矿成本同比率 | — | — | " + token("calc", results["cost.r4.ore_cost_yoy_rate"]["id"], 2) + "% |\n"
                         + "| 金属成本同比率 | — | — | " + token("calc", results["cost.r4.metal_cost_yoy_rate"]["id"], 2) + "% |\n"
                         + "| 变动吨矿成本同比差额 | — | — | " + token("calc", results["cost.r4.variable_yoy_difference"]["id"], 2) + " |\n"
                         + "| 变动金属成本同比差额 | — | — | " + token("calc", results["cost.r4.variable_metal_yoy_difference"]["id"], 2) + " |\n\n"
                         + "管理关注：成本上升可能影响后续目标，先核对生产量和成本归集，再形成降本措施。\n\n"
                         + "人工确认：请财务与生产岗位确认利润和成本统计范围。利润来源 " + token("ev", current)
                         + "；成本来源 " + token("ev", cost["cost.r4.ore_cost"]) + "。")
            request_file.write_text(json.dumps({"project_id": project["id"], "run_id": run["id"],
                                                "task_id": tasks["unit_analysis:" + name]["id"], "author_id": "writer",
                                                "body": "经营综述：利润改善。\n\n| 利润比较项目 | 实际 |\n| --- | ---: |\n| 累计 | " + token("fact", current) + " |\n\n" + token("chart", chart["id"]) + "\n\n| 经营指标 | 状态 |\n| --- | --- |\n| 成本 | 待核 |"}, ensure_ascii=False), encoding="utf-8")
            rejected = subprocess.run([REPORT, "draft", "submit", "--workspace", str(workspace), "--request", str(request_file)], cwd=root, capture_output=True, text=True)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("budget unit", rejected.stderr)
            shallow_body = unit_body.replace("经营综述：", "").replace("经营变化分析：", "").replace("管理关注：", "").replace("人工确认：", "")
            request_file.write_text(json.dumps({"project_id": project["id"], "run_id": run["id"],
                                                "task_id": tasks["unit_analysis:" + name]["id"], "author_id": "writer",
                                                "body": shallow_body}, ensure_ascii=False), encoding="utf-8")
            shallow = subprocess.run([REPORT, "draft", "submit", "--workspace", str(workspace), "--request", str(request_file)],
                                     cwd=root, capture_output=True, text=True)
            self.assertNotEqual(shallow.returncode, 0)
            self.assertIn("analysis block missing", shallow.stderr)
            request_file.write_text(json.dumps({"project_id": project["id"], "run_id": run["id"],
                                                "task_id": tasks["unit_analysis:" + name]["id"], "author_id": "writer",
                                                "body": unit_body}, ensure_ascii=False), encoding="utf-8")
            table_only = subprocess.run([REPORT, "draft", "submit", "--workspace", str(workspace), "--request", str(request_file)],
                                        cwd=root, capture_output=True, text=True)
            self.assertNotEqual(table_only.returncode, 0)
            self.assertIn("operating analysis needs calculated evidence", table_only.stderr)
            unit_body = unit_body.replace(
                "经营变化分析：吨矿成本与金属成本同比上升，处理量和品位资料需进一步核对。",
                "经营变化分析：吨矿成本同比增加 " + token("calc", results["cost.r4.ore_cost_yoy_difference"]["id"], 2)
                + " 元/吨，金属成本同比增加 " + token("calc", results["cost.r4.metal_cost_yoy_difference"]["id"], 2)
                + " 元/吨，两者分母不同，不得相加；处理量和回收率资料需进一步核对。")
            request_file.write_text(json.dumps({"project_id": project["id"], "run_id": run["id"],
                                                "task_id": tasks["unit_analysis:" + name]["id"], "author_id": "writer",
                                                "body": unit_body}, ensure_ascii=False), encoding="utf-8")
            omitted_operations = subprocess.run([REPORT, "draft", "submit", "--workspace", str(workspace), "--request", str(request_file)],
                                                cwd=root, capture_output=True, text=True)
            self.assertNotEqual(omitted_operations.returncode, 0)
            self.assertIn("mining_operations", omitted_operations.stderr)
            operations_change = results["cost_inputs.r16.processed_yoy_difference"]["id"]
            unit_body = unit_body.replace("经营变化分析：", "经营变化分析：选矿处理量同比差额为 " + token("calc", operations_change, 0)
                                          + " 吨，需与金属量和成本分母交叉复核；")
            unit_body = unit_body.replace("\n\n管理关注：", "\n| 选矿处理量同比差额（吨） | — | — | " + token("calc", operations_change, 0) + " |\n\n管理关注：")
            unit_body += " 选矿处理量来源 " + token("ev", cost_inputs["cost_inputs.r16.processed"]) + "。"
            request_file.write_text(json.dumps({"project_id": project["id"], "run_id": run["id"],
                                                "task_id": tasks["unit_analysis:" + name]["id"], "author_id": "writer",
                                                "body": unit_body}, ensure_ascii=False), encoding="utf-8")
            omitted_copper = subprocess.run([REPORT, "draft", "submit", "--workspace", str(workspace), "--request", str(request_file)],
                                            cwd=root, capture_output=True, text=True)
            self.assertNotEqual(omitted_copper.returncode, 0)
            self.assertIn("copper_concentrate", omitted_copper.stderr)
            copper_change = results["concentrate.r4.sales_yoy_difference"]["id"]
            copper_source = next(item["id"] for item in evidence if item["subject_id"] == name and item["metric_id"] == "concentrate.r4.sales")
            unit_body = unit_body.replace("经营变化分析：", "经营变化分析：铜精矿含铜销量同比差额为 " + token("calc", copper_change, 2)
                                          + " 吨，需核对产品销售结算；")
            unit_body = unit_body.replace("\n\n管理关注：", "\n| 铜精矿含铜销量同比差额（吨） | — | — | " + token("calc", copper_change, 2) + " |\n\n管理关注：")
            unit_body += " 铜精矿来源 " + token("ev", copper_source) + "。"
            request_file.write_text(json.dumps({"project_id": project["id"], "run_id": run["id"],
                                                "task_id": tasks["unit_analysis:" + name]["id"], "author_id": "writer",
                                                "body": unit_body}, ensure_ascii=False), encoding="utf-8")
            omitted_sulfur = subprocess.run([REPORT, "draft", "submit", "--workspace", str(workspace), "--request", str(request_file)],
                                            cwd=root, capture_output=True, text=True)
            self.assertNotEqual(omitted_sulfur.returncode, 0)
            self.assertIn("sulfur_concentrate", omitted_sulfur.stderr)
            sulfur_change = results["sulfur.r4.sales_yoy_difference"]["id"]
            sulfur_source = next(item["id"] for item in evidence if item["subject_id"] == name and item["metric_id"] == "sulfur.r4.sales")
            unit_body = unit_body.replace("经营变化分析：", "经营变化分析：硫精矿销量同比差额为 " + token("calc", sulfur_change, 2)
                                          + " 万吨，需核对副产品销售及结算期间；")
            unit_body = unit_body.replace("\n\n管理关注：", "\n| 硫精矿销量同比差额（万吨） | — | — | " + token("calc", sulfur_change, 2) + " |\n\n管理关注：")
            unit_body += " 硫精矿来源 " + token("ev", sulfur_source) + "。"
            call("draft", "submit", request={"project_id": project["id"], "run_id": run["id"],
                                                     "task_id": tasks["unit_analysis:" + name]["id"], "author_id": "writer",
                                                     "body": unit_body})
            call("draft", "submit", request={"project_id": project["id"], "run_id": run["id"],
                                                     "task_id": tasks["summary"]["id"], "author_id": "writer",
                                                     "body": "该单位累计同比改善，但序时计划尚有缺口。请核对利润桥与生产成本资料，再讨论追赶措施。"})
            draft = call("draft", "build", request={"project_id": project["id"], "run_id": run["id"]})
            call("review", "submit", request={"project_id": project["id"], "run_id": run["id"],
                                               "draft_sha256": draft["sha256"], "reviewer_id": "reviewer",
                                               "verdict": "pass", "issues": []})
            revision = call("publish", request={"project_id": project["id"], "run_id": run["id"]})
            from docx import Document
            delivered = Document(revision["docx_path"])
            self.assertEqual((len(delivered.tables), len(delivered.inline_shapes)), (2, 1))
            self.assertEqual([item.text for item in delivered.paragraphs if item.text.startswith("数据性质：")],
                             ["数据性质：技术工作稿（来源含模拟数据）"])
            self.assertIn("55.18", " ".join(item.text for item in delivered.paragraphs))
            self.assertEqual(delivered.styles["Title"].font.size.pt, 24)
            self.assertEqual(delivered.styles["Heading 1"].font.size.pt, 15)
            render_qa = json.loads((Path(revision["docx_path"]).parents[1] / "qa/render_qa.json").read_text(encoding="utf-8"))
            self.assertTrue(render_qa["headings_match"])
            self.assertTrue(render_qa["tables_match"])
            self.assertEqual(render_qa["embedded_chart_count"], 1)
            self.assertEqual(render_qa["verified_chart_hashes"], {chart["id"]: chart["sha256"]})
            self.assertTrue(render_qa["charts_nonblank"])
            self.assertTrue(render_qa["pdf_chart_pages"][chart["id"]])


if __name__ == "__main__":
    unittest.main()
