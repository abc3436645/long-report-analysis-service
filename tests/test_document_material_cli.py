import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from docx import Document


REPORT = Path(sys.executable).with_name("report")
PDF_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "credit_pdf_fixture.pdf"


class DocumentMaterialCliTests(unittest.TestCase):
    def test_text_pdf_retains_page_location_and_damaged_pdf_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "projects"
            request_file = root / "request.json"
            request_file.write_text(json.dumps({
                "scenario_id": "financial_due_diligence", "scenario_version": "0.3.34",
                "subject_scope": {"business_unit": "合成单位"},
                "evaluation_date": "2026-07-31", "credit_application_id": "申请-001",
            }, ensure_ascii=False), encoding="utf-8")
            created = subprocess.run([REPORT, "project", "create", "--workspace", str(workspace), "--request", str(request_file)], cwd=root, capture_output=True, text=True)
            self.assertEqual(created.returncode, 0, created.stderr)
            project_id = json.loads(created.stdout)["data"]["id"]

            request_file.write_text(json.dumps({"project_id": project_id, "input_id": "application", "path": str(PDF_FIXTURE)}), encoding="utf-8")
            added = subprocess.run([REPORT, "material", "add", "--workspace", str(workspace), "--request", str(request_file)], cwd=root, capture_output=True, text=True)
            self.assertEqual(added.returncode, 0, added.stderr)
            fragments = json.loads(added.stdout)["data"]["parsed"]["fragments"]
            self.assertTrue(any("Requested amount 100 units" in item["value"] and item["locator"].startswith("page:1/") for item in fragments))

            damaged = root / "damaged.pdf"
            damaged.write_bytes(b"not a PDF")
            request_file.write_text(json.dumps({"project_id": project_id, "input_id": "application", "path": str(damaged)}), encoding="utf-8")
            rejected = subprocess.run([REPORT, "material", "add", "--workspace", str(workspace), "--request", str(request_file)], cwd=root, capture_output=True, text=True)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("PDF", json.loads(rejected.stderr)["error"])

    def test_credit_application_text_and_word_keep_paragraph_and_table_locations(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "projects"
            request_file = root / "request.json"

            def call(*args, request):
                request_file.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
                result = subprocess.run([REPORT, *args, "--workspace", str(workspace), "--request", str(request_file)], cwd=root, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                return json.loads(result.stdout)["data"]

            project = call("project", "create", request={
                "scenario_id": "financial_due_diligence", "scenario_version": "0.3.34",
                "subject_scope": {"business_unit": "合成单位"}, "evaluation_date": "2026-07-31",
                "credit_application_id": "申请-001",
            })
            note = root / "application.txt"
            note.write_text("授信申请说明\n申请额度为 100 万元。\n", encoding="utf-8")
            text_material = call("material", "add", request={"project_id": project["id"], "input_id": "application", "path": str(note)})
            self.assertEqual(text_material["parsed"]["fragments"][1], {"value": "申请额度为 100 万元。", "locator": "line:2"})

            word = root / "application.docx"
            document = Document()
            document.add_heading("授信申请", level=1)
            document.add_paragraph("本次申请用于流动资金周转。")
            table = document.add_table(rows=1, cols=2)
            table.cell(0, 0).text = "申请额度"
            table.cell(0, 1).text = "100 万元"
            document.save(word)
            word_material = call("material", "add", request={"project_id": project["id"], "input_id": "application", "path": str(word)})
            fragments = word_material["parsed"]["fragments"]
            self.assertIn({"value": "授信申请", "locator": "paragraph:1", "style": "Heading 1"}, fragments)
            self.assertIn({"value": "100 万元", "locator": "table:1/row:1/cell:2"}, fragments)
            self.assertNotEqual(word_material["id"], text_material["id"])

            run = call("run", "start", request={"project_id": project["id"]})
            listed = subprocess.run([REPORT, "task", "list", "--workspace", str(workspace), "--project", project["id"], "--run", run["id"]], cwd=root, capture_output=True, text=True)
            self.assertEqual(listed.returncode, 0, listed.stderr)
            word_task = next(item for item in json.loads(listed.stdout)["data"] if item["source_id"] == word_material["id"])
            submitted = call("task", "submit", request={
                "project_id": project["id"], "run_id": run["id"], "task_id": word_task["id"],
                "input_fingerprint": word_task["input_fingerprint"],
                "candidates": [{
                    "subject_id": "合成单位", "metric_id": "requested_amount", "period": "2026-07-31",
                    "value": "100 万元", "source_locator": "table:1/row:1/cell:2", "source_value": "100 万元",
                }],
            })
            self.assertEqual(submitted["candidates"][0]["status"], "candidate")


if __name__ == "__main__":
    unittest.main()
