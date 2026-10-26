import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile


REPORT = Path(sys.executable).with_name("report")
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "budget_minimal.xlsx"


class MaterialCliTests(unittest.TestCase):
    def test_one_workbook_can_supply_actual_and_budget_roles_without_duplicate_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "projects"
            request = root / "request.json"
            request.write_text(json.dumps({
                "scenario_id": "budget_operations", "scenario_version": "0.2.0",
                "subject_scope": {"organization": "合成集团", "units": ["甲单位"]}, "report_period": "2026-07",
            }, ensure_ascii=False), encoding="utf-8")
            created = subprocess.run([REPORT, "project", "create", "--workspace", str(workspace), "--request", str(request)], cwd=root, capture_output=True, text=True)
            self.assertEqual(created.returncode, 0, created.stderr)
            project_id = json.loads(created.stdout)["data"]["id"]
            ids = []
            for input_id in ("actuals", "budget"):
                request.write_text(json.dumps({"project_id": project_id, "input_id": input_id, "path": str(FIXTURE)}), encoding="utf-8")
                added = subprocess.run([REPORT, "material", "add", "--workspace", str(workspace), "--request", str(request)], cwd=root, capture_output=True, text=True)
                self.assertEqual(added.returncode, 0, added.stderr)
                material = json.loads(added.stdout)["data"]
                ids.append(material["id"])
            self.assertEqual(ids[0], ids[1])
            self.assertEqual(material["input_ids"], ["actuals", "budget"])

            request.write_text(json.dumps({"project_id": project_id}), encoding="utf-8")
            started = subprocess.run([REPORT, "run", "start", "--workspace", str(workspace), "--request", str(request)], cwd=root, capture_output=True, text=True)
            self.assertEqual(started.returncode, 0, started.stderr)
            run = json.loads(started.stdout)["data"]
            self.assertEqual(run["material_ids"], ids[:1])
            listed = subprocess.run([REPORT, "task", "list", "--workspace", str(workspace), "--project", project_id, "--run", run["id"]], cwd=root, capture_output=True, text=True)
            task = json.loads(listed.stdout)["data"][0]
            request.write_text(json.dumps({"project_id": project_id, "run_id": run["id"], "task_id": task["id"], "input_fingerprint": task["input_fingerprint"], "candidates": []}), encoding="utf-8")
            submitted = subprocess.run([REPORT, "task", "submit", "--workspace", str(workspace), "--request", str(request)], cwd=root, capture_output=True, text=True)
            self.assertEqual(submitted.returncode, 0, submitted.stderr)
            request.write_text(json.dumps({"project_id": project_id, "run_id": run["id"]}), encoding="utf-8")
            frozen = subprocess.run([REPORT, "evidence", "freeze", "--workspace", str(workspace), "--request", str(request)], cwd=root, capture_output=True, text=True)
            self.assertEqual(frozen.returncode, 0, frozen.stderr)
            self.assertEqual(json.loads(frozen.stdout)["data"]["missing_inputs"], [])
    def test_formula_cache_is_usable_only_after_independent_recalculation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "projects"
            request = root / "request.json"
            request.write_text(json.dumps({
                "scenario_id": "budget_operations", "scenario_version": "0.2.0",
                "subject_scope": {"organization": "合成集团", "units": ["甲单位"]}, "report_period": "2026-07",
            }, ensure_ascii=False), encoding="utf-8")
            created = subprocess.run([REPORT, "project", "create", "--workspace", str(workspace), "--request", str(request)], cwd=root, capture_output=True, text=True)
            self.assertEqual(created.returncode, 0, created.stderr)
            project_id = json.loads(created.stdout)["data"]["id"]
            unsupported_material = None
            for cached_value, formula, expected_state, expected_value in (("241", "B2*2", "verified", "241"), ("250", "B2*2", "cache_mismatch", None), ("241", "AVERAGE(B2:B2)", "cached_unverified", "241")):
                source_path = root / f"formula_{expected_state}.xlsx"
                with ZipFile(FIXTURE) as original, ZipFile(source_path, "w") as changed:
                    for item in original.infolist():
                        data = original.read(item.filename)
                        if item.filename == "xl/worksheets/sheet1.xml":
                            data = data.replace(b"<f>B2*2</f><v></v>", f"<f>{formula}</f><v>{cached_value}</v>".encode())
                        changed.writestr(item, data)
                request.write_text(json.dumps({"project_id": project_id, "input_id": "actuals", "path": str(source_path)}), encoding="utf-8")
                added = subprocess.run([REPORT, "material", "add", "--workspace", str(workspace), "--request", str(request)], cwd=root, capture_output=True, text=True)
                self.assertEqual(added.returncode, 0, added.stderr)
                formula_cell = json.loads(added.stdout)["data"]["parsed"]["sheets"]["利润"]["cells"]["C2"]
                self.assertEqual((formula_cell["state"], formula_cell["value"]), (expected_state, expected_value))
                if expected_state == "cached_unverified":
                    unsupported_material = json.loads(added.stdout)["data"]

            request.write_text(json.dumps({"project_id": project_id}), encoding="utf-8")
            started = subprocess.run([REPORT, "run", "start", "--workspace", str(workspace), "--request", str(request)], cwd=root, capture_output=True, text=True)
            self.assertEqual(started.returncode, 0, started.stderr)
            run_id = json.loads(started.stdout)["data"]["id"]
            listed = subprocess.run([REPORT, "task", "list", "--workspace", str(workspace), "--project", project_id, "--run", run_id], cwd=root, capture_output=True, text=True)
            task = next(item for item in json.loads(listed.stdout)["data"] if item["source_id"] == unsupported_material["id"])
            request.write_text(json.dumps({
                "project_id": project_id, "run_id": run_id, "task_id": task["id"], "input_fingerprint": task["input_fingerprint"],
                "candidates": [{"subject_id": "甲单位", "metric_id": "profit_total", "period": "2026-07", "value": "241", "source_locator": "sheet:利润/cell:C2", "source_value": "241"}],
            }, ensure_ascii=False), encoding="utf-8")
            submitted = subprocess.run([REPORT, "task", "submit", "--workspace", str(workspace), "--request", str(request)], cwd=root, capture_output=True, text=True)
            self.assertEqual(submitted.returncode, 0, submitted.stderr)
            candidate_id = json.loads(submitted.stdout)["data"]["candidates"][0]["id"]
            request.write_text(json.dumps({"project_id": project_id, "run_id": run_id, "candidate_id": candidate_id, "decision": "accept"}), encoding="utf-8")
            decided = subprocess.run([REPORT, "evidence", "decide", "--workspace", str(workspace), "--request", str(request)], cwd=root, capture_output=True, text=True)
            self.assertNotEqual(decided.returncode, 0)
            self.assertIn("unverified", json.loads(decided.stderr)["error"])

    def test_budget_csv_is_archived_and_cells_have_source_locations(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "projects"
            project_request = root / "project.json"
            project_request.write_text(json.dumps({
                "scenario_id": "budget_operations", "scenario_version": "0.2.0",
                "subject_scope": {"organization": "合成集团", "units": ["甲单位"]},
                "report_period": "2026-07",
            }, ensure_ascii=False), encoding="utf-8")
            created = subprocess.run([REPORT, "project", "create", "--workspace", str(workspace), "--request", str(project_request)], cwd=root, capture_output=True, text=True)
            self.assertEqual(created.returncode, 0, created.stderr)
            project_id = json.loads(created.stdout)["data"]["id"]

            source = root / "actuals.csv"
            source.write_text("单位,本期利润\n甲单位,120.50\n", encoding="utf-8")
            material_request = root / "material.json"
            material_request.write_text(json.dumps({"project_id": project_id, "input_id": "actuals", "path": str(source)}, ensure_ascii=False), encoding="utf-8")
            added = subprocess.run([REPORT, "material", "add", "--workspace", str(workspace), "--request", str(material_request)], cwd=root, capture_output=True, text=True)
            self.assertEqual(added.returncode, 0, added.stderr)
            material = json.loads(added.stdout)["data"]
            self.assertEqual(material["fingerprint"], "f8d72bddc832ce6214f681b5c891ffdcbbf234dc598be8575bab12d61490bdde")
            self.assertEqual(material["status"], "parsed")

            shown = subprocess.run([REPORT, "material", "show", material["id"], "--project", project_id, "--workspace", str(workspace)], cwd=root, capture_output=True, text=True)
            self.assertEqual(shown.returncode, 0, shown.stderr)
            cells = json.loads(shown.stdout)["data"]["parsed"]["sheets"]["CSV"]["cells"]
            self.assertEqual(cells["B2"], {"value": "120.50", "locator": "sheet:CSV/cell:B2"})

    def test_budget_excel_is_archived_with_sheet_and_cell_location(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "projects"
            project_request = root / "project.json"
            project_request.write_text(json.dumps({
                "scenario_id": "budget_operations", "scenario_version": "0.2.0",
                "subject_scope": {"organization": "合成集团", "units": ["甲单位"]},
                "report_period": "2026-07",
            }, ensure_ascii=False), encoding="utf-8")
            created = subprocess.run([REPORT, "project", "create", "--workspace", str(workspace), "--request", str(project_request)], cwd=root, capture_output=True, text=True)
            self.assertEqual(created.returncode, 0, created.stderr)
            project_id = json.loads(created.stdout)["data"]["id"]

            material_request = root / "material.json"
            material_request.write_text(json.dumps({"project_id": project_id, "input_id": "actuals", "path": str(FIXTURE)}), encoding="utf-8")
            added = subprocess.run([REPORT, "material", "add", "--workspace", str(workspace), "--request", str(material_request)], cwd=root, capture_output=True, text=True)
            self.assertEqual(added.returncode, 0, added.stderr)
            material = json.loads(added.stdout)["data"]
            self.assertEqual(material["status"], "parsed")
            self.assertEqual(material["parsed"]["sheets"]["利润"]["cells"]["B2"], {"value": "120.5", "locator": "sheet:利润/cell:B2"})

    def test_uncached_excel_formula_is_not_exposed_as_a_numeric_fact(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "projects"
            request = root / "request.json"
            request.write_text(json.dumps({
                "scenario_id": "budget_operations", "scenario_version": "0.2.0",
                "subject_scope": {"organization": "合成集团", "units": ["甲单位"]},
                "report_period": "2026-07",
            }, ensure_ascii=False), encoding="utf-8")
            created = subprocess.run([REPORT, "project", "create", "--workspace", str(workspace), "--request", str(request)], cwd=root, capture_output=True, text=True)
            self.assertEqual(created.returncode, 0, created.stderr)
            project_id = json.loads(created.stdout)["data"]["id"]
            request.write_text(json.dumps({"project_id": project_id, "input_id": "actuals", "path": str(FIXTURE)}), encoding="utf-8")
            added = subprocess.run([REPORT, "material", "add", "--workspace", str(workspace), "--request", str(request)], cwd=root, capture_output=True, text=True)
            self.assertEqual(added.returncode, 0, added.stderr)
            cell = json.loads(added.stdout)["data"]["parsed"]["sheets"]["利润"]["cells"]["C2"]
            self.assertEqual(cell, {"value": None, "formula": "=B2*2", "state": "pending_verify", "locator": "sheet:利润/cell:C2"})

    def test_corrupted_archived_original_is_reported_instead_of_reused(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "projects"
            request = root / "request.json"
            request.write_text(json.dumps({
                "scenario_id": "budget_operations", "scenario_version": "0.2.0",
                "subject_scope": {"organization": "合成集团", "units": ["甲单位"]},
                "report_period": "2026-07",
            }, ensure_ascii=False), encoding="utf-8")
            created = subprocess.run([REPORT, "project", "create", "--workspace", str(workspace), "--request", str(request)], cwd=root, capture_output=True, text=True)
            project_id = json.loads(created.stdout)["data"]["id"]
            source = root / "actuals.csv"
            source.write_text("单位,本期利润\n甲单位,120.50\n", encoding="utf-8")
            request.write_text(json.dumps({"project_id": project_id, "input_id": "actuals", "path": str(source)}), encoding="utf-8")
            added = subprocess.run([REPORT, "material", "add", "--workspace", str(workspace), "--request", str(request)], cwd=root, capture_output=True, text=True)
            self.assertEqual(added.returncode, 0, added.stderr)
            material = json.loads(added.stdout)["data"]
            Path(material["archived_path"]).write_bytes(b"corrupted")

            shown = subprocess.run([REPORT, "material", "show", material["id"], "--project", project_id, "--workspace", str(workspace)], cwd=root, capture_output=True, text=True)
            self.assertNotEqual(shown.returncode, 0)
            self.assertIn("archive", json.loads(shown.stderr)["error"])


if __name__ == "__main__":
    unittest.main()
