import copy
import unittest

from long_report.financials import validate_financial_body
from long_report.scenario import ScenarioError, load_scenario, validate_report_outline, validate_section_headings


COLUMNS = ["序号", "评级指标", "标准分", "评级得分"]
ROWS = [[str(i), label, None, None] for i, label in enumerate([
    "偿债能力评价", "盈利能力评价", "营运能力评价", "经营管理分析", "发展前景分析", "征信情况",
    "附加指标－股东管控程度"], 1)] + [["合计", "-", None, None], ["信用等级评定", None, "-", "-"]]


def rating_body():
    table = "| " + " | ".join(COLUMNS) + " |\n| --- | --- | --- | --- |\n"
    table += "\n".join("| " + " | ".join(cell if cell is not None else "未提供（待核实）" for cell in row) + " |" for row in ROWS)
    return ("## 一、信用评级\n\n评级对象：本公司（审计年度及评级状态待核实）。\n\n"
            "表7-1 信用等级评定表\n\n" + table + "\n\n"
            "## 二、征信情况\n\n资料待核实。\n\n## 三、涉诉情况\n\n资料待核实。")


class CreditRatingTableTests(unittest.TestCase):
    def setUp(self):
        self.section = {"subheadings": ["一、信用评级", "二、征信情况", "三、涉诉情况"],
                        "required_assets": ["信用等级评定表"],
                        "required_tables": [{"subheading": "一、信用评级", "asset": "信用等级评定表",
                                             "columns": COLUMNS, "fixed_rows": ROWS}]}

    def test_missing_scores_keep_the_full_table_instead_of_replacing_it_with_a_gap(self):
        body = rating_body()
        validate_section_headings(body, self.section)
        supplement = "表7-2 评级依据说明\n\n| 事项 | 说明 |\n| --- | --- |\n| 认定状态 | 待核实 |"
        validate_section_headings(body.replace("## 二、征信情况", supplement + "\n\n## 二、征信情况"), self.section)
        for invalid in (body.replace("| 序号 | 评级指标 | 标准分 | 评级得分 |", "| 排名 | 评级指标 | 标准分 | 评级得分 |"),
                        body.replace("| 2 | 盈利能力评价", "| 2 | 盈利分析"),
                        body.replace("| 2 | 盈利能力评价", "| 1 | 盈利能力评价"),
                        body.replace("| 信用等级评定 |", "| 其他结论 |"),
                        body.replace("未提供（待核实）", "", 1),
                        "## 一、信用评级\n\n资料缺口：信用等级评定表：结果未提供。\n\n"
                        "## 二、征信情况\n\n待核实。\n\n## 三、涉诉情况\n\n待核实。"):
            with self.subTest(body=invalid), self.assertRaises(ScenarioError):
                validate_section_headings(invalid, self.section)

    def test_only_fixed_serials_are_exempt_from_financial_evidence_binding(self):
        body = rating_body().replace("未提供（待核实）", "{{fact:score}}", 1)
        validate_financial_body(body, self.section)
        validate_financial_body(body.replace("{{fact:score}}", "{{calc:score|2}}"), self.section)
        for score in ("25", "1"):
            with self.subTest(score=score), self.assertRaisesRegex(ValueError, "unbound financial number"):
                validate_financial_body(body.replace("{{fact:score}}", score), self.section)
        with self.assertRaisesRegex(ValueError, "unbound financial number"):
            validate_financial_body(body + "\n\n总分87。", self.section)

    def test_scenario_keeps_the_rating_template_and_cannot_be_weakened_per_run(self):
        scenario = load_scenario("financial_due_diligence")
        section = next(item for item in scenario.outline["sections"] if item["id"] == "credit")
        self.assertEqual(section["required_tables"], self.section["required_tables"])
        validate_section_headings(rating_body(), section)
        validate_financial_body(rating_body(), section)
        for field in ("required_tables", "required_assets"):
            proposed = copy.deepcopy(scenario.outline)
            next(item for item in proposed["sections"] if item["id"] == "credit")[field] = []
            with self.subTest(field=field), self.assertRaises(ScenarioError):
                validate_report_outline({"sections": proposed["sections"]}, scenario.analysis, {},
                                        fixed_outline=scenario.outline)

    def test_malformed_fixed_row_definitions_fail_at_the_plan_boundary(self):
        scenario = load_scenario("financial_due_diligence")
        for rows in ([], ["not a row"], [["1", "项目"]], [[None] * 4], [[1, "项目", None, None]]):
            proposed = copy.deepcopy(scenario.outline)
            section = next(item for item in proposed["sections"] if item["id"] == "credit")
            section["required_tables"][0]["fixed_rows"] = rows
            with self.subTest(rows=rows), self.assertRaisesRegex(ScenarioError, "fixed rows"):
                validate_report_outline({"sections": proposed["sections"]}, scenario.analysis, {})
        section["required_tables"][0]["required_fields"] = ["项目"]
        with self.assertRaisesRegex(ScenarioError, "table definition"):
            validate_report_outline({"sections": proposed["sections"]}, scenario.analysis, {})


if __name__ == "__main__":
    unittest.main()
