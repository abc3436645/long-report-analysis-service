import shutil
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

import yaml

from long_report.application import get_scenario, list_scenarios
from long_report.operators import difference
from long_report.scenario import ScenarioError, load_scenario


SOURCE = Path(__file__).resolve().parents[1] / "scenarios"


class ScenarioTests(unittest.TestCase):
    def test_three_installed_scenarios_match_business_scope(self):
        summaries = list_scenarios()
        self.assertEqual(
            {item["id"] for item in summaries},
            {"budget_operations", "credit_review", "compensation_analysis"},
        )
        for item in summaries:
            with self.subTest(item=item["id"]):
                detail = get_scenario(item["id"], "0.1.0")
                self.assertEqual(detail["fingerprint"], item["fingerprint"])
                self.assertEqual(set(detail["quality"]["required_sections"]),
                                 {section["id"] for section in detail["outline"]["sections"]})
                self.assertTrue(detail["definition_missing"])
        self.assertEqual(len(get_scenario("budget_operations")["outline"]["sections"]), 6)
        self.assertEqual(len(get_scenario("credit_review")["outline"]["sections"]), 7)
        self.assertEqual(len(get_scenario("compensation_analysis")["outline"]["sections"]), 7)

    def test_version_mismatch_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "requested version"):
            get_scenario("budget_operations", "9.9.9")

    def test_difference_preserves_decimal_and_zero(self):
        self.assertEqual(difference(Decimal("0"), Decimal("1.20")), Decimal("-1.20"))

    def test_invalid_references_cycle_and_resource_are_rejected(self):
        cases = (
            ("analysis.yaml", lambda data: data["metrics"][0].update(operator="unknown"), "unknown operator"),
            ("outline.yaml", lambda data: data["sections"][1].update(depends_on=["summary"]), "cycle"),
            ("scenario.yaml", lambda data: data.update(template="templates/../../private.docx"), "unsafe template"),
            ("quality.yaml", lambda data: data["checks"].remove("numeric_binding"), "required checks missing"),
        )
        for filename, mutate, message in cases:
            with self.subTest(filename=filename), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                shutil.copytree(SOURCE / "budget_operations", root / "budget_operations")
                path = root / "budget_operations" / filename
                data = yaml.safe_load(path.read_text(encoding="utf-8"))
                mutate(data)
                path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
                with self.assertRaisesRegex(ScenarioError, message):
                    load_scenario("budget_operations", root)

    def test_incomplete_new_scenario_is_not_silently_skipped(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            shutil.copytree(SOURCE / "budget_operations", root / "budget_operations")
            (root / "incomplete").mkdir()
            from long_report.scenario import scenario_ids
            self.assertIn("incomplete", scenario_ids(root))
            with self.assertRaisesRegex(ScenarioError, "incomplete/scenario.yaml"):
                load_scenario("incomplete", root)


if __name__ == "__main__":
    unittest.main()
