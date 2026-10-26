import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPORT = Path(sys.executable).with_name("report")


class RunCliTests(unittest.TestCase):
    def test_start_run_freezes_materials_and_lists_extraction_tasks(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "projects"
            request = root / "request.json"
            request.write_text(json.dumps({
                "scenario_id": "budget_operations", "scenario_version": "0.2.0",
                "subject_scope": {"organization": "合成集团", "units": ["甲单位"], "special_subjects": ["专项产品"]},
                "report_period": "2026-07",
            }, ensure_ascii=False), encoding="utf-8")
            created = subprocess.run([REPORT, "project", "create", "--workspace", str(workspace), "--request", str(request)], cwd=root, capture_output=True, text=True)
            self.assertEqual(created.returncode, 0, created.stderr)
            project = json.loads(created.stdout)["data"]

            source = root / "actuals.csv"
            source.write_text("单位,本期利润\n甲单位,120.50\n", encoding="utf-8")
            request.write_text(json.dumps({"project_id": project["id"], "input_id": "actuals", "path": str(source)}), encoding="utf-8")
            added = subprocess.run([REPORT, "material", "add", "--workspace", str(workspace), "--request", str(request)], cwd=root, capture_output=True, text=True)
            self.assertEqual(added.returncode, 0, added.stderr)
            material = json.loads(added.stdout)["data"]

            request.write_text(json.dumps({"project_id": project["id"]}), encoding="utf-8")
            started = subprocess.run([REPORT, "run", "start", "--workspace", str(workspace), "--request", str(request)], cwd=root, capture_output=True, text=True)
            self.assertEqual(started.returncode, 0, started.stderr)
            run = json.loads(started.stdout)["data"]
            self.assertEqual(run["material_ids"], [material["id"]])
            self.assertEqual(run["effective_config_fingerprint"], project["effective_config_fingerprint"])
            self.assertEqual(run["effective_config"], project["effective_config"])

            request.write_text(json.dumps({"project_id": project["id"], "input_id": "budget", "path": str(source)}), encoding="utf-8")
            second_role = subprocess.run([REPORT, "material", "add", "--workspace", str(workspace), "--request", str(request)], cwd=root, capture_output=True, text=True)
            self.assertEqual(second_role.returncode, 0, second_role.stderr)
            self.assertEqual(json.loads(second_role.stdout)["data"]["id"], material["id"])

            listed = subprocess.run([REPORT, "task", "list", "--workspace", str(workspace), "--project", project["id"], "--run", run["id"]], cwd=root, capture_output=True, text=True)
            self.assertEqual(listed.returncode, 0, listed.stderr)
            tasks = json.loads(listed.stdout)["data"]
            self.assertEqual([(task["kind"], task["source_id"]) for task in tasks], [("extract_candidate_facts", material["id"])])

            context = subprocess.run([REPORT, "task", "context", tasks[0]["id"], "--workspace", str(workspace), "--project", project["id"]], cwd=root, capture_output=True, text=True)
            self.assertEqual(context.returncode, 0, context.stderr)
            task_context = json.loads(context.stdout)["data"]
            self.assertEqual(task_context["material"]["parsed"]["sheets"]["CSV"]["cells"]["B2"]["value"], "120.50")
            self.assertEqual(task_context["material"]["input_ids"], ["actuals"])
            self.assertEqual(task_context["run"]["material_ids"], [material["id"]])
            self.assertEqual(task_context["effective_config"]["scenario"]["id"], "budget_operations")

            request.write_text(json.dumps({
                "project_id": project["id"], "run_id": run["id"], "task_id": tasks[0]["id"],
                "input_fingerprint": tasks[0]["input_fingerprint"],
                "candidates": [{
                    "subject_id": "甲单位", "metric_id": "profit_total", "period": "2026-07",
                    "value": "120.50", "source_locator": "sheet:CSV/cell:B2", "source_value": "120.50",
                }, {
                    "subject_id": "专项产品", "metric_id": "special_amount", "period": "2026-07",
                    "value": "120.50", "source_locator": "sheet:CSV/cell:B2", "source_value": "120.50",
                }],
            }, ensure_ascii=False), encoding="utf-8")
            submitted = subprocess.run([REPORT, "task", "submit", "--workspace", str(workspace), "--request", str(request)], cwd=root, capture_output=True, text=True)
            self.assertEqual(submitted.returncode, 0, submitted.stderr)
            candidate = json.loads(submitted.stdout)["data"]["candidates"][0]
            self.assertEqual(candidate["source_id"], material["id"])
            self.assertEqual(candidate["status"], "candidate")
            repeated = subprocess.run([REPORT, "task", "submit", "--workspace", str(workspace), "--request", str(request)], cwd=root, capture_output=True, text=True)
            self.assertEqual(repeated.returncode, 0, repeated.stderr)
            self.assertEqual(json.loads(repeated.stdout)["data"]["candidates"][0]["id"], candidate["id"])

            request.write_text(json.dumps({
                "project_id": project["id"], "run_id": run["id"],
                "candidate_id": candidate["id"], "decision": "accept",
            }), encoding="utf-8")
            decided = subprocess.run([REPORT, "evidence", "decide", "--workspace", str(workspace), "--request", str(request)], cwd=root, capture_output=True, text=True)
            self.assertEqual(decided.returncode, 0, decided.stderr)
            evidence = json.loads(decided.stdout)["data"]
            self.assertEqual(evidence["status"], "usable")
            self.assertEqual(evidence["source_locator"], "sheet:CSV/cell:B2")
            request.write_text(json.dumps({"project_id": project["id"], "run_id": run["id"], "candidate_id": json.loads(submitted.stdout)["data"]["candidates"][1]["id"], "decision": "accept"}), encoding="utf-8")
            special = subprocess.run([REPORT, "evidence", "decide", "--workspace", str(workspace), "--request", str(request)], cwd=root, capture_output=True, text=True)
            self.assertEqual(special.returncode, 0, special.stderr)

            request.write_text(json.dumps({"project_id": project["id"], "run_id": run["id"]}), encoding="utf-8")
            frozen = subprocess.run([REPORT, "evidence", "freeze", "--workspace", str(workspace), "--request", str(request)], cwd=root, capture_output=True, text=True)
            self.assertEqual(frozen.returncode, 0, frozen.stderr)
            snapshot = json.loads(frozen.stdout)["data"]
            self.assertEqual(set(snapshot["evidence_ids"]), {evidence["id"], json.loads(special.stdout)["data"]["id"]})
            self.assertEqual(snapshot["missing_inputs"], ["budget"])
            self.assertIn("budget_version_rule", snapshot["definition_missing"])


if __name__ == "__main__":
    unittest.main()
