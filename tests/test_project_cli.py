import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPORT = Path(sys.executable).with_name("report")


class ProjectCliTests(unittest.TestCase):
    def test_cover_metadata_preserves_user_scope_but_rejects_forged_generation_fields(self):
        from long_report.application import create_project

        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            request = {"scenario_id": "budget_operations", "scenario_version": "0.2.0", "report_period": "2026-07",
                       "subject_scope": {"organization": "合成集团", "units": ["甲矿"]},
                       "report_metadata": {"analysis_subject": "矿山板块", "prepared_by": "预算办", "confidentiality": "内部资料"}}
            self.assertEqual(create_project(workspace, request)["report_metadata"], request["report_metadata"])
            for value in ({"generation_date": "2026-01-01"}, {"prepared_by": "甲\n乙"}, {"analysis_subject": ""}, []):
                with self.subTest(value=value), self.assertRaisesRegex(ValueError, "report_metadata"):
                    create_project(workspace, {**request, "report_metadata": value})

    def test_budget_project_can_be_created_and_reopened(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            request = root / "request.json"
            request.write_text(json.dumps({
                "scenario_id": "budget_operations",
                "scenario_version": "0.2.0",
                "subject_scope": {"organization": "合成集团", "units": ["甲单位", "乙单位"]},
                "report_period": "2026-07",
            }, ensure_ascii=False), encoding="utf-8")
            created = subprocess.run(
                [REPORT, "project", "create", "--workspace", str(root / "projects"), "--request", str(request)],
                cwd=root, capture_output=True, text=True,
            )
            self.assertEqual(created.returncode, 0, created.stderr)
            project = json.loads(created.stdout)["data"]
            self.assertEqual(project["scenario_id"], "budget_operations")
            self.assertEqual(project["subject_scope"]["units"], ["甲单位", "乙单位"])
            self.assertEqual(project["report_period"], "2026-07")
            self.assertEqual(project["scenario_version"], "0.2.0")
            self.assertIn("budget_version_rule", project["definition_missing"])

            reopened = subprocess.run(
                [REPORT, "project", "show", project["id"], "--workspace", str(root / "projects")],
                cwd=root, capture_output=True, text=True,
            )
            self.assertEqual(reopened.returncode, 0, reopened.stderr)
            self.assertEqual(json.loads(reopened.stdout)["data"], project)

    def test_credit_project_uses_application_and_evaluation_date(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            request = root / "request.json"
            request.write_text(json.dumps({
                "scenario_id": "financial_due_diligence",
                "scenario_version": "0.3.0",
                "subject_scope": {"business_unit": "合成单位"},
                "evaluation_date": "2026-07-31",
                "credit_application_id": "申请-001",
            }, ensure_ascii=False), encoding="utf-8")
            created = subprocess.run(
                [REPORT, "project", "create", "--workspace", str(root / "projects"), "--request", str(request)],
                cwd=root, capture_output=True, text=True,
            )
            self.assertEqual(created.returncode, 0, created.stderr)
            project = json.loads(created.stdout)["data"]
            self.assertEqual(project["scenario_id"], "financial_due_diligence")
            self.assertEqual(project["evaluation_date"], "2026-07-31")
            self.assertEqual(project["credit_application_id"], "申请-001")
            self.assertNotIn("report_period", project)

    def test_declared_project_override_fills_only_its_business_definition(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            request = root / "request.json"
            request.write_text(json.dumps({
                "scenario_id": "budget_operations",
                "scenario_version": "0.2.0",
                "subject_scope": {"organization": "合成集团", "units": ["甲单位"]},
                "report_period": "2026-07",
                "overrides": {"business_definitions.measurement_unit": "万元"},
            }, ensure_ascii=False), encoding="utf-8")
            created = subprocess.run(
                [REPORT, "project", "create", "--workspace", str(root / "projects"), "--request", str(request)],
                cwd=root, capture_output=True, text=True,
            )
            self.assertEqual(created.returncode, 0, created.stderr)
            project = json.loads(created.stdout)["data"]
            self.assertEqual(project["effective_config"]["scenario"]["business_definitions"]["measurement_unit"], "万元")
            self.assertEqual(project["definition_missing"], ["budget_version_rule", "consolidation_rule"])
            self.assertNotEqual(project["effective_config_fingerprint"], project["scenario_fingerprint"])

    def test_project_scope_cannot_omit_all_budget_units(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            request = root / "request.json"
            request.write_text(json.dumps({
                "scenario_id": "budget_operations",
                "scenario_version": "0.2.0",
                "subject_scope": {"organization": "合成集团", "units": []},
                "report_period": "2026-07",
            }, ensure_ascii=False), encoding="utf-8")
            created = subprocess.run(
                [REPORT, "project", "create", "--workspace", str(root / "projects"), "--request", str(request)],
                cwd=root, capture_output=True, text=True,
            )
            self.assertNotEqual(created.returncode, 0)
            self.assertFalse(json.loads(created.stderr)["ok"])
            self.assertFalse((root / "projects").exists())

    def test_new_report_period_is_a_related_project(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "projects"
            request = root / "request.json"
            base = {
                "scenario_id": "budget_operations",
                "scenario_version": "0.2.0",
                "subject_scope": {"organization": "合成集团", "units": ["甲单位"]},
            }
            request.write_text(json.dumps({**base, "report_period": "2026-07"}, ensure_ascii=False), encoding="utf-8")
            first = subprocess.run([REPORT, "project", "create", "--workspace", str(workspace), "--request", str(request)], cwd=root, capture_output=True, text=True)
            self.assertEqual(first.returncode, 0, first.stderr)
            first_id = json.loads(first.stdout)["data"]["id"]

            request.write_text(json.dumps({**base, "report_period": "2026-08", "related_project_id": first_id}, ensure_ascii=False), encoding="utf-8")
            second = subprocess.run([REPORT, "project", "create", "--workspace", str(workspace), "--request", str(request)], cwd=root, capture_output=True, text=True)
            self.assertEqual(second.returncode, 0, second.stderr)
            second_project = json.loads(second.stdout)["data"]
            self.assertNotEqual(second_project["id"], first_id)
            self.assertEqual(second_project["related_project_id"], first_id)
            self.assertEqual(second_project["report_period"], "2026-08")

    def test_invalid_report_period_does_not_create_project(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            request = root / "request.json"
            request.write_text(json.dumps({
                "scenario_id": "budget_operations",
                "scenario_version": "0.2.0",
                "subject_scope": {"organization": "合成集团", "units": ["甲单位"]},
                "report_period": "2026-13",
            }, ensure_ascii=False), encoding="utf-8")
            created = subprocess.run(
                [REPORT, "project", "create", "--workspace", str(root / "projects"), "--request", str(request)],
                cwd=root, capture_output=True, text=True,
            )
            self.assertNotEqual(created.returncode, 0)
            self.assertIn("report_period", json.loads(created.stderr)["error"])
            self.assertFalse((root / "projects").exists())


if __name__ == "__main__":
    unittest.main()
