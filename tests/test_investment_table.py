"""External investments need a fixed table followed by sourced company profiles."""

import copy
import unittest

from long_report.scenario import ScenarioError, load_scenario, validate_report_outline, validate_section_headings


PARENT = "五、对外投资情况"
COLUMNS = ["持股公司名称", "成立日期", "认缴金额（万元）", "持股占比"]
RULE = dict(subheading=PARENT, columns=COLUMNS)
TABLE = ("| 持股公司名称 | 成立日期 | 认缴金额（万元） | 持股占比 |\n"
         "| --- | --- | --- | --- |\n"
         "| 甲公司 | 待核实 | 未提供（待核实） | 未提供（待核实） |")


class InvestmentTableTests(unittest.TestCase):
    def test_scenario_fixes_the_four_columns_and_requires_company_profiles(self):
        scenario = load_scenario("financial_due_diligence")
        self.assertIn(RULE, scenario.outline["sections"][0]["required_tables"])
        guidance = "\n".join(scenario.analysis["writing_guidance"]["company"])
        for requirement in ("持股公司名称、成立日期、认缴金额（万元）、持股占比四列表格",
                            "逐家介绍持股公司的全称、简称、成立时间和股权构成",
                            "不把被投公司注册资本、已实缴金额或账面投资余额当作认缴金额"):
            with self.subTest(requirement=requirement):
                self.assertIn(requirement, guidance)

    def test_table_needs_one_complete_nonempty_data_row(self):
        section = dict(subheadings=[PARENT], required_tables=[RULE])
        valid = "## " + PARENT + "\n\n" + TABLE + "\n\n1、甲公司的股权构成资料待核实。"
        validate_section_headings(valid, section)
        for invalid in ("## " + PARENT + "\n\n持股公司资料待核实。",
                        valid.replace("持股占比 |", "投资比例 |", 1),
                        valid.replace("\n| 甲公司 | 待核实 | 未提供（待核实） | 未提供（待核实） |", ""),
                        valid.replace("| 甲公司 | 待核实 |", "| 甲公司 |  |"),
                        valid + "\n\n" + TABLE):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(ScenarioError, "required table"):
                validate_section_headings(invalid, section)

    def test_per_run_plan_cannot_drop_the_investment_table(self):
        scenario = load_scenario("financial_due_diligence")
        proposed = copy.deepcopy({"sections": scenario.outline["sections"]})
        proposed["sections"][0]["required_tables"].remove(RULE)
        with self.assertRaisesRegex(ScenarioError, "fixed"):
            validate_report_outline(proposed, scenario.analysis, {}, fixed_outline=scenario.outline)


if __name__ == "__main__":
    unittest.main()
