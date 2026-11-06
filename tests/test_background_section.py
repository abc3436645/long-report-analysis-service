"""Background coverage must survive the fixed chapter plan and draft submission."""

import copy
import unittest

from long_report.scenario import ScenarioError, load_scenario, validate_report_outline, validate_section_headings


PARENT = "二、背景情况"
CHILDREN = ["（一）公司概况", "（二）发展历程", "（三）近三年经营业绩"]


class BackgroundSectionTests(unittest.TestCase):
    def test_fixed_structure_and_guidance_cover_company_history_and_three_year_results(self):
        scenario = load_scenario("financial_due_diligence")
        section = scenario.outline["sections"][0]
        self.assertEqual(section["required_subsections"][PARENT],
                         [dict(title=title, content="narrative") for title in CHILDREN])
        guidance = "\n".join(scenario.analysis["writing_guidance"]["company"])
        for requirement in ("全称、简称、成立时间", "是否合资及合资各方", "当前股东和股权结构",
                            "发展历程按时间顺序", "最近三个完整会计年度的营业收入和利润总额",
                            "利润总额不得用净利润代替"):
            with self.subTest(requirement=requirement):
                self.assertIn(requirement, guidance)
        self.assertIn("只有三级标题或笼统规模描述而遗漏已知事实时退回修改",
                      "\n".join(scenario.analysis["writing_guidance"]["review_checklist"]))

    def test_three_parts_are_required_in_order_even_when_evidence_is_missing(self):
        scenario = load_scenario("financial_due_diligence")
        section = dict(subheadings=[PARENT], required_subsections={PARENT: scenario.outline["sections"][0]["required_subsections"][PARENT]})
        parts = ["### " + title + "\n\n对应资料未提供（待核实）。" for title in CHILDREN]
        body = "## " + PARENT + "\n\n" + "\n\n".join(parts)
        validate_section_headings(body, section)
        for invalid in ("## " + PARENT + "\n\n" + "\n\n".join(parts[:-1]),
                        "## " + PARENT + "\n\n" + "\n\n".join(reversed(parts)),
                        body.replace("### " + CHILDREN[1] + "\n\n对应资料未提供（待核实）。",
                                     "### " + CHILDREN[1])):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(ScenarioError, "subsection"):
                validate_section_headings(invalid, section)

    def test_per_run_plan_cannot_remove_background_parts(self):
        scenario = load_scenario("financial_due_diligence")
        proposed = copy.deepcopy({"sections": scenario.outline["sections"]})
        proposed["sections"][0]["required_subsections"][PARENT].pop()
        with self.assertRaisesRegex(ScenarioError, "fixed"):
            validate_report_outline(proposed, scenario.analysis, {}, fixed_outline=scenario.outline)


if __name__ == "__main__":
    unittest.main()
