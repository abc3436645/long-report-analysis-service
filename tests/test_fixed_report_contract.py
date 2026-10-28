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
