import copy
import unittest

from long_report.financials import validate_financial_body
from long_report.scenario import ScenarioError, load_scenario, validate_report_outline


class CreditPolicyContractTests(unittest.TestCase):
    def setUp(self):
        self.scenario = load_scenario("financial_due_diligence")
        self.sections = {item["id"]: item for item in self.scenario.outline["sections"]}

    def test_credit_judgment_waits_for_operating_financial_and_risk_analysis(self):
        self.assertEqual(set(self.sections["credit"]["depends_on"]),
                         {"company", "operations", "financials", "financing", "industry", "risks"})
        self.assertIn("credit", self.sections["terms"]["depends_on"])
        self.assertEqual(set(self.sections["conclusion"]["depends_on"]), {"credit", "terms"},
                         "The final opinion must wait for both credit findings and proposed terms")
        self.assertEqual(self.scenario.analysis["metrics"], [],
                         "Evidence review must not silently become an authority to calculate credit limits")

    def test_policy_tables_require_actual_evidence_or_an_explicit_limit_on_judgment(self):
        for section_id, names in {
            "terms": ["额度测算核对表", "授信要素依据表"],
        }.items():
            section = self.sections[section_id]
            self.assertEqual(section["required_assets"], names)
            with self.subTest(section=section_id):
                with self.assertRaisesRegex(ValueError, "required financial asset"):
                    validate_financial_body("经营稳定，建议支持授信。", section)
                gaps = "\n\n".join("资料缺口：" + name + "：仅有空白规则，结果尚未认定。" for name in names)
                validate_financial_body(gaps, section)
                tables = "\n\n".join(
                    f"表8-{i} {name}\n\n| 项目 | 结果状态 |\n| --- | --- |\n| 已提供结果 | {{{{fact:current}}}} |"
                    for i, name in enumerate(names, 1))
                validate_financial_body(tables, section)
                with self.assertRaisesRegex(ValueError, "unbound financial number"):
                    validate_financial_body(tables.replace("{{fact:current}}", "87"), section)

    def test_per_run_outline_cannot_remove_the_policy_evidence_tables(self):
        for section_id, field in (("terms", "required_assets"), ("credit", "depends_on"),
                                  ("conclusion", "depends_on")):
            outline = {"sections": copy.deepcopy(self.scenario.outline["sections"])}
            next(item for item in outline["sections"] if item["id"] == section_id)[field] = []
            with self.subTest(field=field), self.assertRaises(ScenarioError):
                validate_report_outline(outline, self.scenario.analysis, {"business_unit": "其他公司"},
                                        fixed_outline=self.scenario.outline)
