"""Display conversion must preserve the frozen financial evidence and its scale."""
import copy
import json
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

import yaml

from long_report import application as app
from long_report.scenario import ScenarioError, load_scenario
from long_report.amounts import display_amount, convert_chart_point
from credit_test_support import registration_table, background_details, equity_details, investment_details, credit_rating_table


class AmountConversionTests(unittest.TestCase):
    def test_table_grouping_is_opt_in_and_preserves_source_and_prose(self):
        rule = load_scenario("financial_due_diligence").manifest["presentation"]["amount_display"]
        item = {"value": "-123456789", "unit": "元"}
        self.assertEqual(display_amount(item, {**rule, "table_grouping": True}, "table"), ("-12,345.68", "万元"))
        old = {k: v for k, v in rule.items() if k != "table_grouping"}
        self.assertEqual(display_amount(item, old, "table"), ("-12345.68", "万元"))
        self.assertEqual(display_amount(item, rule, "text"), ("-1.23", "亿元"))
        self.assertEqual(item["value"], "-123456789")

    def test_all_supported_source_scales_share_the_same_display_magnitude(self):
        rule = load_scenario("financial_due_diligence").manifest["presentation"]["amount_display"]
        for value, unit in [("125000000", "元"), ("12500", "万元"), ("1.25", "亿元"), ("1.25亿元", "text"), ("1.25e8", "元")]:
            with self.subTest(value=value, unit=unit):
                item = {"value": value, "unit": unit}
                self.assertEqual(display_amount(item, rule, "text"), ("1.25", "亿元"))
                self.assertEqual(display_amount(item, rule, "table"), ("12,500.00", "万元"))
                self.assertEqual(convert_chart_point(item, "万元")["unit"], "万元")

    def test_unit_selection_never_rounds_source_precision_at_the_boundary(self):
        rule = load_scenario("financial_due_diligence").manifest["presentation"]["amount_display"]
        self.assertEqual(display_amount({"value": "99999999.9999999999999999999999999999", "unit": "元"}, rule, "text"),
                         ("10000.00", "万元"))

    def test_conflicting_source_unit_and_nonfinite_money_fail_instead_of_guessing(self):
        rule = load_scenario("financial_due_diligence").manifest["presentation"]["amount_display"]
        for item in ({"value": "1亿元", "unit": "万元"}, {"value": "NaN", "unit": "元"}, {"value": "未提供", "unit": "万元"}):
            with self.subTest(item=item), self.assertRaisesRegex(ValueError, "monetary reference"):
                display_amount(item, rule, "text")


class AmountDisplayTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.workspace = self.root / "projects"
        self.project = app.create_project(self.workspace, {
            "scenario_id": "financial_due_diligence", "scenario_version": "0.3.34",
            "subject_scope": {"business_unit": "甲公司"}, "evaluation_date": "2026-06-30",
            "credit_application_id": "SYN-UNITS"})
        source = self.root / "amounts.txt"
        source.write_text("99999999\n100000000\n100000001\n-125000000\n0\n12345.67\n2.5\n5000\n10\n", encoding="utf-8")
        material = app.add_material(self.workspace, {"project_id": self.project["id"], "input_id": "application", "path": str(source)})
        self.run = app.start_run(self.workspace, {"project_id": self.project["id"]})
        self.request = {"project_id": self.project["id"], "run_id": self.run["id"]}
        task = app.list_tasks(self.workspace, self.project["id"], self.run["id"])[0]
        candidates = []
        for i, fragment in enumerate(material["parsed"]["fragments"]):
            candidates.append({"subject_id": "甲公司", "metric_id": "amount" + str(i),
                "period": "2026-06-30", "value": fragment["value"], "source_value": fragment["value"],
                "source_locator": fragment["locator"],
                "unit": "元" if i < 6 else ["%", "元/吨", "人"][i - 6], "basis": "application"})
        submitted = app.submit_task(self.workspace, {**self.request, "task_id": task["id"],
            "input_fingerprint": task["input_fingerprint"], "candidates": candidates})
        self.facts = [app.decide_evidence(self.workspace, {**self.request, "candidate_id": c["id"], "decision": "accept"})
                      for c in submitted["candidates"]]
        app.freeze_evidence(self.workspace, self.request)
        app.calculate_run(self.workspace, self.request)
        self.run = app.get_run(self.workspace, self.project["id"], self.run["id"])
        self.material = material

    def ref(self, index, precision=""):
        return "{{fact:" + self.facts[index]["id"] + ("|" + precision if precision else "") + "}}"

    def test_prose_and_tables_convert_at_original_precision_without_scaling_other_units(self):
        tasks = app.plan_draft(self.workspace, {**self.request, "report_request": "金额展示回归",
            "outline": {"sections": self.project["effective_config"]["outline"]["sections"]},
            "material_uses": [{"material_id": self.material["id"], "use": "analysis", "reason": "金额换算核验"}]})
        for section, task in zip(self.project["effective_config"]["outline"]["sections"], tasks):
            body = "\n\n".join("## " + heading + "\n\n资料待核实。" for heading in section.get("subheadings", [])) or "融资资料待核实。"
            if section["id"] == "company":
                body = body.replace("## 一、工商信息\n\n", "## 一、工商信息\n\n" + registration_table(section) + "\n\n")
                body = body.replace("## 二、背景情况\n\n", "## 二、背景情况\n\n" + background_details(section) + "\n\n")
                body = body.replace("## 四、股权、股东及投资情况\n\n", "## 四、股权、股东及投资情况\n\n" + equity_details(section) + "\n\n")
                body = body.replace("## 五、对外投资情况\n\n", "## 五、对外投资情况\n\n" + investment_details(section) + "\n\n")
            if section["id"] == "credit":
                body = body.replace("## 一、信用评级\n\n", "## 一、信用评级\n\n" + credit_rating_table(section) + "\n\n", 1)
            body += "".join("\n\n资料缺口：" + asset + "：未取得完整资料。" for asset in section["required_assets"] if section["id"] != "credit")
            if section["id"] == "financials":
                body += "\n\n" + "；".join("金额为" + self.ref(i) + "元" for i in range(6)) + "。"
                body += "\n\n比例" + self.ref(6) + "%，单价" + self.ref(7) + "元/吨，人数" + self.ref(8) + "人。"
                body += "\n\n精度展示" + self.ref(5, "4") + "元。"
                body += "\n\n表3-2 金额明细（单位：元）\n\n| 项目 | 金额（元） |\n| --- | --- |\n| 大额 | " + self.ref(2) + " |\n| 损失 | " + self.ref(3) + "元 |"
            context = app.get_draft_context(self.workspace, self.project["id"], task["id"])
            app.submit_draft(self.workspace, {**self.request, "task_id": task["id"], "author_id": "writer", "body": body,
                                              "dependency_fingerprint": context["dependency_fingerprint"]})
        draft = app.build_draft(self.workspace, self.request)
        text = Path(draft["markdown_path"]).read_text(encoding="utf-8")
        self.assertIn("金额为10000.00万元；金额为1.00亿元；金额为1.00亿元；金额为-1.25亿元；金额为0.00万元；金额为1.23万元", text)
        self.assertIn("比例2.5%，单价5000元/吨，人数10人", text)
        self.assertIn("精度展示1.2346万元", text)
        self.assertIn("| 项目 | 金额（万元） |", text)
        self.assertIn("表3-2 金额明细（单位：万元）", text)
        self.assertIn("| 大额 | 10,000.00 |", text)
        self.assertIn("| 损失 | -12,500.00 |", text)
        context = app.get_draft_context(self.workspace, self.project["id"], tasks[0]["id"])
        self.assertEqual(context["amount_display"]["table_unit"], "万元")
        with sqlite3.connect(self.workspace / self.project["id"] / "state.sqlite") as connection:
            frozen = [json.loads(row[0]) for row in connection.execute("SELECT data FROM evidence")]
        self.assertEqual({f["id"]: (f["value"], f["unit"]) for f in frozen},
                         {f["id"]: (f["value"], f["unit"]) for f in self.facts})

    def test_chart_values_and_monetary_annotations_use_wan_yuan(self):
        # Isolate the chart display boundary with two same-dimension points.
        with sqlite3.connect(self.workspace / self.project["id"] / "state.sqlite") as connection:
            for fact in self.facts[:2]:
                fact = {**fact, "metric_id": "assets"}
                connection.execute("UPDATE evidence SET data = ? WHERE id = ?", (json.dumps(fact), fact["id"]))
            for calculation in [
                {"id": "amount-change", "metric_id": "change", "label": "金额差额", "value": "-125000000", "unit": "元"},
                {"id": "rate", "metric_id": "rate", "label": "变化率", "value": "2.5", "unit": "%"}]:
                record = {**calculation, "status": "calculated", "subject_id": "甲公司",
                          "input_evidence_ids": [f["id"] for f in self.facts[:2]]}
                connection.execute("INSERT INTO calculation VALUES (?, ?, ?)", (record["id"], self.run["id"], json.dumps(record)))
        chart = app.create_chart(self.workspace, {**self.request, "title": "规模比较", "series": [
            {"label": "本期", "evidence_id": self.facts[0]["id"]}, {"label": "比较期", "evidence_id": self.facts[1]["id"]}]})
        self.assertEqual(chart["unit"], "万元")
        self.assertEqual([p["value"] for p in chart["display_series"]], ["9999.9999", "10000"])
        self.assertEqual([(p["value"], p["unit"]) for p in chart["annotations"]], [("-12500", "万元"), ("2.5", "%")])
        self.assertTrue(Path(chart["path"]).is_file())

    def test_cover_amount_follows_the_prose_scale(self):
        point = {**self.facts[0], "metric_id": "credit_amount", "value": "50000000"}
        metadata = app._cover_metadata(self.project, self.run, [point], [], [])
        self.assertEqual(metadata["授信额度"], "5000万元")

    def test_invalid_amount_display_config_fails_at_load(self):
        source = Path(__file__).resolve().parents[1] / "scenarios/financial_due_diligence"
        for invalid in ({"table_grouping": "true"}, {"chart_unit": "美元"}, {"decimal_places": True}, {"text_large_threshold": "NaN"}, {"typo": "万元"}):
            with self.subTest(invalid=invalid), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                shutil.copytree(source, root / "financial_due_diligence")
                path = root / "financial_due_diligence/scenario.yaml"
                manifest = yaml.safe_load(path.read_text(encoding="utf-8"))
                rule = copy.deepcopy(manifest["presentation"].get("amount_display", {
                    "table_unit": "万元", "chart_unit": "万元", "text_unit": "万元", "text_large_unit": "亿元",
                    "text_large_threshold": "100000000", "decimal_places": 2}))
                rule.update(invalid)
                manifest["presentation"]["amount_display"] = rule
                path.write_text(yaml.safe_dump(manifest, allow_unicode=True), encoding="utf-8")
                with self.assertRaisesRegex(ScenarioError, "amount_display"):
                    load_scenario("financial_due_diligence", root)
