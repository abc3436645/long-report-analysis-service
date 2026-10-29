"""An enterprise's fixed report structure must survive planning and chapter submission."""

import copy
import unittest
from unittest.mock import patch

from long_report.application import submit_draft
from long_report.rendering import report_fonts
from long_report.scenario import ScenarioError, load_scenario, validate_report_outline


class FixedReportContractTests(unittest.TestCase):
    def test_financial_scenario_declares_standard_chapters_and_fangsong(self):
        scenario = load_scenario("financial_due_diligence")
        self.assertTrue(scenario.outline.get("fixed"))
        self.assertEqual(len(scenario.outline["sections"]), 9)
        self.assertEqual(sum(len(s["subheadings"]) for s in scenario.outline["sections"]), 31)
        self.assertEqual(scenario.outline["sections"][2]["subheadings"],
                         ["资产负债表", "利润表：", "现金流量表：", "财务比率及分析"])
        self.assertEqual(scenario.outline["sections"][3]["subheadings"], [])
        self.assertEqual({key: scenario.manifest["presentation"][key] for key in ("body_font", "heading_font", "latin_font", "allow_font_fallback")},
                         dict(body_font="仿宋", heading_font="仿宋", latin_font="仿宋", allow_font_fallback=False))

    def test_per_run_plan_cannot_replace_a_fixed_heading_or_omit_a_chapter(self):
        scenario = load_scenario("financial_due_diligence")
        original = {"sections": [dict(id="credit", title="信用能力评估", display_order=1, repeat_for=None,
                                      subheadings=["一、信用评级", "二、征信情况"], evidence_refs=[], analysis_refs=[], depends_on=[])]}
        fixed = {**original, "fixed": True}
        for mutation in ("title", "subheading", "omit", "reorder", "repeat", "empty"):
            proposed = copy.deepcopy(original)
            if mutation == "empty":
                proposed["sections"] = []
            elif mutation == "omit":
                proposed["sections"].pop()
            elif mutation == "reorder":
                proposed["sections"][0]["display_order"] = 10
            elif mutation == "repeat":
                proposed["sections"][0]["repeat_for"] = "unit"
            elif mutation == "subheading":
                proposed["sections"][0]["subheadings"] = ["自定标题"]
            else:
                proposed["sections"][0]["title"] = "自定章节"
            with self.subTest(mutation=mutation), self.assertRaisesRegex(ScenarioError, "fixed|requires sections"):
                validate_report_outline(proposed, scenario.analysis, {"units": ["甲公司"]},
                                        fixed_outline=fixed)
        accepted = validate_report_outline(original, scenario.analysis, {}, fixed_outline=fixed)
        self.assertEqual(accepted["sections"], original["sections"])

    def test_every_fixed_subheading_has_a_business_question_and_chapter_guidance(self):
        scenario = load_scenario("financial_due_diligence")
        guidance = scenario.analysis["writing_guidance"]
        for shared in ("business_adaptation", "report_expression", "cross_chapter_consistency", "comprehensive_assessment"):
            self.assertTrue(guidance[shared], "Company-specific reports need reusable evidence and expression requirements")
        for section in scenario.outline["sections"]:
            with self.subTest(section=section["id"]):
                self.assertIn(section["id"], guidance)
                self.assertTrue(section["questions"])
                self.assertNotIn(section["goal"], section["questions"])
                self.assertIn("report_expression", "\n".join(guidance[section["id"]]),
                              "The expression requirements must apply to all nine chapters")
                self.assertIn("comprehensive_assessment", "\n".join(guidance[section["id"]]),
                              "Identifying strengths and warning signs is a whole-report objective, not a risk-only appendix")
                for heading in section["subheadings"]:
                    self.assertTrue(any(question.startswith(heading.rstrip("：") + "：") for question in section["questions"]),
                                    "Each retained heading must answer its own review question: " + heading)
        self.assertTrue(guidance["review_checklist"])
        self.assertTrue(guidance["management_profiles"], "Known career histories must not collapse into a shared manager summary")
        self.assertIn("management_profiles", "\n".join(guidance["company"]))

    def test_reference_company_facts_do_not_become_reusable_scenario_requirements(self):
        scenario = load_scenario("financial_due_diligence")
        requirements = repr((scenario.analysis, scenario.outline))
        for value in ("江铜华北", "天津大无缝", "魏斌", "周泓睿", "左带发", "SCR4500", "T1R",
                      "64020.41", "100138.66", "91.59%", "92.88%"):
            with self.subTest(value=value):
                self.assertNotIn(value, requirements, "A reference fact must be supplied by each project's own evidence")

    def test_chapters_two_to_five_declare_tables_with_matching_writing_instructions(self):
        scenario = load_scenario("financial_due_diligence")
        guidance = scenario.analysis["writing_guidance"]
        for name in ("table_interpretation", "counterparty_assessment", "operating_stability"):
            self.assertTrue(guidance[name], "Table presence alone does not establish business capability or risk")
        for section in scenario.outline["sections"][1:5]:
            with self.subTest(section=section["id"]):
                self.assertTrue(section["required_assets"], "Table requirements must reach each chapter plan")
                table_guidance = "\n".join(guidance[section["id"] + "_tables"])
                for name in section["required_assets"]:
                    self.assertIn(name, table_guidance, "A named table needs field and analysis instructions")
                self.assertIn("table_interpretation", "\n".join(guidance[section["id"]]),
                              "Every table-bearing chapter must use the per-table interpretation requirements")
                self.assertTrue(any("每张" in question and "表" in question for question in section["questions"]),
                                "Each chapter plan must ask for interpretation of every actual table")
        self.assertIn("其他应付款", "\n".join(guidance["current_accounts_focus"]))
        self.assertIn("长期股权投资", "\n".join(guidance["equity_investment_focus"]))
        self.assertTrue(guidance["materiality_selection"])

    def test_missing_or_reordered_subheadings_are_rejected_before_storage(self):
        context = {"task": {}, "section": {"subheadings": ["一、信用评级", "二、征信情况"]}}
        bodies = (" ## 一、信用评级\n\n缺资料。\n\n ## 二、征信情况\n\n缺资料。", "## 一、信用评级\n缺资料。\n\n## 二、征信情况\n缺资料。", "评级资料缺失。", "## 二、征信情况\n缺资料。\n## 一、信用评级\n缺资料。",
                  "## 一、信用评级\n## 二、征信情况\n缺资料。",
                  "# 额外一级标题\n## 一、信用评级\n缺资料。\n## 二、征信情况\n缺资料。")
        with patch("long_report.application.get_draft_context", return_value=context):
            for body in bodies:
                with self.subTest(body=body), self.assertRaisesRegex(ValueError, "fixed.*heading|empty.*subheading"):
                    submit_draft(None, dict(project_id="p", task_id="t", body=body))

    def test_fixed_font_is_never_silently_substituted(self):
        presentation = dict(body_font="仿宋", heading_font="仿宋", latin_font="仿宋", allow_font_fallback=False)
        with patch("long_report.rendering._installed_fonts", return_value={"songti sc", "heiti sc", "times new roman"}):
            with self.assertRaisesRegex(ValueError, "required report font unavailable.*仿宋"):
                report_fonts(presentation)
        with patch("long_report.rendering._installed_fonts", return_value={"仿宋"}):
            self.assertEqual(set(report_fonts(presentation).values()), {"仿宋"})


if __name__ == "__main__":
    unittest.main()
