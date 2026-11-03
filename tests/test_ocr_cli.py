"""OCR must remain recoverable source preparation, never silently accepted evidence."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from email.parser import BytesParser
from email.policy import default
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import yaml
from pypdf import PdfWriter

from long_report.scenario import ScenarioError, load_scenario


REPORT = Path(sys.executable).with_name("report")


def result(pages=(0, 1)):
    return {"code": 0, "message": "success", "warnings": [], "data": {
        "task_id": "synthetic-ocr", "status": "success", "error": None,
        "metadata": {"page_num": 2, "file_type": ".pdf"},
        "result": {"outputs": {"markdown": "# 合成征信资料\n\n合成担保余额 120.50万元",
            "json": {"pages": [{"page_num": page, "page_size": {"w": 600, "h": 800},
                "blocks": [{"idx": 0, "type": "Text", "format": "text", "bbox": [10, 20, 300, 60],
                    "content": "合成担保余额 120.50万元" if page == 0 else "合成记录状态待核实"}]}
                for page in pages]}}}}}


class OcrCliTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.workspace = self.root / "projects"
        self.env = {**os.environ, "SOMARK_API_KEY": "synthetic-key"}
        self.replies = []
        self.seen = []
        self.on_request = None
        owner = self

        class Provider(BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers["Content-Length"]))
                if "multipart/form-data" in self.headers["Content-Type"]:
                    message = BytesParser(policy=default).parsebytes(
                        ("Content-Type: " + self.headers["Content-Type"] + "\r\n\r\n").encode() + body)
                    fields = {}
                    for part in message.iter_parts():
                        fields.setdefault(part.get_param("name", header="content-disposition"), []).append(part.get_payload(decode=True))
                else:
                    from urllib.parse import parse_qs
                    fields = {k: [v.encode() for v in values] for k, values in parse_qs(body.decode()).items()}
                owner.seen.append((self.path, fields))
                if owner.on_request:
                    owner.on_request()
                if owner.replies:
                    path, status, value = owner.replies.pop(0)
                    if path != self.path:
                        status, value = 500, {"code": -1, "message": "unexpected endpoint"}
                else:
                    status, value = 500, {"code": -1, "message": "unexpected extra request"}
                raw = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                try:
                    self.wfile.write(raw)
                except (BrokenPipeError, ConnectionResetError):
                    pass  # Timeout tests intentionally close the client connection first.

            def log_message(self, *_args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.config = self.root / "services.yaml"
        self.config.write_text(yaml.safe_dump({"schema_version": 1,
            "connections": {"local": {"protocol": "http", "endpoint": f"http://127.0.0.1:{self.server.server_port}/v1",
                "auth_ref": "env:SOMARK_API_KEY"}},
            "services": {"somark_ocr": {"enabled": True, "connection_ref": "local", "adapter": "somark_http",
                "capability": "document.ocr", "contract_version": 1, "timeout_seconds": 5,
                "poll_interval_seconds": .01, "max_upload_bytes": 1000000, "max_response_bytes": 1000000}}}))
        self.project = self.call("project", "create", request={
            "scenario_id": "financial_due_diligence", "scenario_version": load_scenario("financial_due_diligence").version,
            "credit_application_id": "OCR-SYN", "subject_scope": {"business_unit": "合成甲公司"}, "evaluation_date": "2026-10-31"})
        self.source = self.root / "scan.pdf"
        writer = PdfWriter()
        for _ in range(2):
            writer.add_blank_page(width=600, height=800)
        writer.write(self.source)
        self.original = self.call("material", "add", request={"project_id": self.project["id"],
            "input_id": "professional_records", "path": str(self.source)})

    def call(self, *args, request=None, fails=None):
        command = [str(REPORT), *args, "--workspace", str(self.workspace)]
        if request is not None:
            path = self.root / "request.json"
            path.write_text(json.dumps(request, ensure_ascii=False))
            command += ["--request", str(path)]
        process = subprocess.run(command, capture_output=True, text=True, env=self.env)
        if fails:
            self.assertNotEqual(process.returncode, 0)
            self.assertIn(fails, process.stderr)
            return
        self.assertEqual(process.returncode, 0, process.stderr)
        return json.loads(process.stdout)["data"]

    def ocr(self, **options):
        return self.call("material", "ocr", request={"project_id": self.project["id"],
            "material_id": self.original["id"], "services_config": str(self.config), **options})

    def derived(self, response):
        return self.call("material", "show", response["call"]["derived_material_id"], "--project", self.project["id"])

    def test_prepare_routes_only_unread_sources_and_reuses_complete_page_coverage(self):
        native = self.call("material", "add", request={"project_id": self.project["id"],
            "input_id": "professional_records", "path": str(Path(__file__).parent / "fixtures/credit_pdf_fixture.pdf")})
        self.replies = [("/v1/parse/sync", 200, result())]
        request = {"project_id": self.project["id"], "services_config": str(self.config),
            "ocr_material_ids": [self.original["id"]]}
        prepared = self.call("material", "prepare", request=request)
        self.assertEqual(prepared["status"], "ready")
        items = {item["material_id"]: item for item in prepared["items"]}
        self.assertEqual(items[native["id"]]["status"], "native_text")
        self.assertEqual(items[self.original["id"]]["unread_pages"], [])
        self.assertFalse(prepared["content_verified"])
        again = self.call("material", "prepare", request=request)
        self.assertEqual(again["status"], "ready")
        self.assertEqual(len(self.seen), 1, "already extracted sources must not be uploaded twice")

    def test_prepare_inspects_without_upload_until_agent_selects_unread_material(self):
        from long_report.application import prepare_materials
        prepared = prepare_materials(self.workspace, {"project_id": self.project["id"]})
        self.assertEqual(prepared["status"], "incomplete")
        self.assertEqual(prepared["items"][0]["status"], "needs_reading_decision")
        self.assertEqual(prepared["items"][0]["native_unread_pages"], [1, 2])
        self.assertEqual(self.seen, [], "page coverage is a hint, not permission to upload every PDF")

    def test_run_preparation_waits_for_async_result_without_freezing_incomplete_inputs(self):
        from long_report.application import start_run, list_tasks
        self.replies = [("/v1/parse/async", 200, {"code": 0, "data": {"task_id": "prepare-job", "status": "queuing"}}),
            ("/v1/parse/async_check", 200, {**result(), "data": {**result()["data"], "task_id": "prepare-job"}})]
        request = {"project_id": self.project["id"], "prepare_materials": True,
            "services_config": str(self.config), "mode": "async", "ocr_material_ids": [self.original["id"]]}
        from unittest.mock import patch
        with patch.dict(os.environ, self.env):
            waiting = start_run(self.workspace, request)
            self.assertEqual(waiting["status"], "awaiting_materials")
            self.assertNotIn("id", waiting)
            run = start_run(self.workspace, request)
        self.assertEqual(run["status"], "active")
        self.assertEqual(len(list_tasks(self.workspace, self.project["id"], run["id"])), 2)
        self.assertEqual([item[0] for item in self.seen], ["/v1/parse/async", "/v1/parse/async_check"])

    def test_scan_added_during_preparation_cannot_enter_an_unchecked_frozen_run(self):
        from long_report.application import start_run, add_material
        from unittest.mock import patch
        path = self.root / "late.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=610, height=800)
        writer.write(path)
        self.on_request = lambda: add_material(self.workspace, {"project_id": self.project["id"],
            "input_id": "professional_records", "path": str(path)})
        self.replies = [("/v1/parse/sync", 200, result())]
        with patch.dict(os.environ, self.env):
            waiting = start_run(self.workspace, {"project_id": self.project["id"], "prepare_materials": True,
                "ocr_material_ids": [self.original["id"]], "services_config": str(self.config)})
        self.assertEqual(waiting["status"], "awaiting_materials")
        self.assertNotIn("id", waiting)
        self.assertEqual(waiting["material_preparation"]["status"], "inputs_changed")

    def test_prepare_reports_partial_and_continues_after_a_file_failure(self):
        from long_report.application import prepare_materials
        from unittest.mock import patch
        writer = PdfWriter()
        writer.add_blank_page(width=610, height=800)
        path = self.root / "another.pdf"
        writer.write(path)
        other = self.call("material", "add", request={"project_id": self.project["id"],
            "input_id": "professional_records", "path": str(path)})
        self.replies = [("/v1/parse/sync", 500, {"detail": "unavailable"}),
            ("/v1/parse/sync", 200, result((0,)))]
        request = {"project_id": self.project["id"], "services_config": str(self.config),
            "ocr_material_ids": [self.original["id"], other["id"]]}
        with patch.dict(os.environ, self.env):
            prepared = prepare_materials(self.workspace, request)
        self.assertEqual(prepared["status"], "incomplete")
        self.assertEqual(len(prepared["items"]), 2)
        self.assertEqual(len(self.seen), 2, "one failing file must not hide other files")
        self.assertTrue(any(item.get("error") for item in prepared["items"]))
        self.assertTrue(any(item["unread_pages"] for item in prepared["items"]))

    def test_prepare_cli_exposes_incomplete_results_with_nonzero_exit(self):
        self.replies = [("/v1/parse/sync", 200, result((0,)))]
        request = self.root / "prepare.json"
        request.write_text(json.dumps({"project_id": self.project["id"], "services_config": str(self.config),
            "ocr_material_ids": [self.original["id"]]}))
        process = subprocess.run([str(REPORT), "material", "prepare", "--workspace", str(self.workspace),
            "--request", str(request)], capture_output=True, text=True, env=self.env)
        self.assertEqual(process.returncode, 1)
        response = json.loads(process.stdout)
        self.assertFalse(response["ok"])
        self.assertEqual(response["data"]["status"], "incomplete")
        self.assertEqual(response["data"]["items"][0]["unread_pages"], [2])

    def test_sync_ocr_archives_raw_and_keeps_original_page_coordinates_before_evidence(self):
        self.replies = [("/v1/parse/sync", 200, result())]
        response = self.ocr(mode="sync")
        self.assertEqual(response["call"]["status"], "succeeded")
        material = self.derived(response)
        self.assertEqual(material["derivation"]["source_id"], self.original["id"])
        self.assertEqual(material["derivation"]["source_sha256"], sha256(self.source.read_bytes()).hexdigest())
        fragment = next(x for x in material["parsed"]["fragments"] if "120.50" in x["value"])
        self.assertEqual(material["derivation"]["locator_map"][fragment["locator"]], "page:1")
        self.assertEqual(material["derivation"]["block_map"][fragment["locator"]]["bbox"], [10, 20, 300, 60])
        self.assertEqual(material["parsed"]["coverage"]["unread_pages"], [])
        self.assertEqual(self.seen[0][1]["output_formats"], [b"markdown", b"json"])
        self.assertEqual(self.seen[0][1]["api_key"], [b"synthetic-key"])
        self.assertEqual(self.seen[0][1]["file"], [self.source.read_bytes()])
        state = (self.workspace / self.project["id"] / "state.sqlite").read_bytes()
        self.assertNotIn(b"synthetic-key", state)
        self.assertEqual(self.ocr(mode="sync")["call"]["id"], response["call"]["id"])
        self.assertEqual(len(self.seen), 1)
        original = self.call("material", "show", self.original["id"], "--project", self.project["id"])
        self.assertEqual(original["parsed"]["coverage"]["unread_pages"], [1, 2])
        self.assertEqual(Path(original["archived_path"]).read_bytes(), self.source.read_bytes())
        run = self.call("run", "start", request={"project_id": self.project["id"]})
        tasks = self.call("task", "list", "--project", self.project["id"], "--run", run["id"])
        self.assertEqual({t["source_id"] for t in tasks}, {self.original["id"], material["id"]})
        raw = Path(response["call"]["responses"][-1]["path"])
        raw.write_bytes(b"damaged")
        self.call("material", "show", material["id"], "--project", self.project["id"], fails="OCR archive checksum")

    def test_async_resume_uses_saved_binding_and_never_uploads_the_file_twice(self):
        self.replies = [("/v1/parse/async", 200, {"code": 0, "data": {"task_id": "job-A", "status": "queuing"}}),
            ("/v1/parse/async_check", 200, {"code": 0, "data": {"task_id": "job-A", "status": "processing"}}),
            ("/v1/parse/async_check", 200, {**result(), "data": {**result()["data"], "task_id": "job-A"}})]
        first = self.ocr(mode="async")
        self.assertEqual(first["call"]["status"], "pending")
        self.assertEqual(first["call"]["provider_task_id"], "job-A")
        self.config.write_text("invalid: no-longer-the-selected-service")
        self.assertEqual(self.ocr(mode="async")["call"]["status"], "pending")
        last = self.ocr(mode="async")
        self.assertEqual(last["call"]["status"], "succeeded")
        self.assertEqual(last["call"]["id"], first["call"]["id"])
        self.assertEqual([x[0] for x in self.seen], ["/v1/parse/async", "/v1/parse/async_check", "/v1/parse/async_check"])
        self.assertEqual(self.seen[1][1]["task_id"], [b"job-A"])
        self.assertTrue(self.derived(last)["parsed"]["fragments"])

    def test_explicit_wait_polls_after_durable_submission(self):
        self.replies = [("/v1/parse/async", 200, {"code": 0, "data": {"task_id": "job-B", "status": "queuing"}}),
            ("/v1/parse/async_check", 200, {**result(), "data": {**result()["data"], "task_id": "job-B"}})]
        response = self.ocr(mode="async", wait_seconds=2)
        self.assertEqual(response["call"]["status"], "succeeded")
        self.assertEqual(len(response["call"]["responses"]), 2)

    def test_default_auto_resume_keeps_an_existing_explicit_async_job(self):
        self.replies = [("/v1/parse/async", 200, {"code": 0, "data": {"task_id": "resume-job", "status": "queuing"}}),
            ("/v1/parse/async_check", 200, {**result(), "data": {**result()["data"], "task_id": "resume-job"}})]
        first = self.ocr(mode="async")
        resumed = self.ocr()
        self.assertEqual(resumed["call"]["status"], "succeeded")
        self.assertEqual(resumed["call"]["id"], first["call"]["id"])
        self.assertEqual(self.ocr()["call"]["id"], first["call"]["id"])
        self.assertEqual([x[0] for x in self.seen], ["/v1/parse/async", "/v1/parse/async_check"])

    def test_poll_transport_failure_preserves_the_job_for_a_later_query(self):
        self.replies = [("/v1/parse/async", 200, {"code": 0, "data": {"task_id": "job-C", "status": "queuing"}}),
            ("/v1/parse/async_check", 503, {"detail": "unavailable"}),
            ("/v1/parse/async_check", 200, {**result(), "data": {**result()["data"], "task_id": "job-C"}})]
        self.ocr(mode="async")
        failed_query = self.ocr(mode="async")
        self.assertEqual(failed_query["call"]["status"], "pending")
        self.assertIn("HTTP 503", failed_query["call"]["last_error"])
        self.assertEqual(self.ocr(mode="async")["call"]["status"], "succeeded")
        self.assertEqual(len(self.seen), 3)

    def test_missing_pages_remain_a_gap_and_ocr_never_claims_full_content_verification(self):
        self.replies = [("/v1/parse/sync", 200, result((0,)))]
        response = self.ocr(mode="sync")
        self.assertEqual(response["call"]["status"], "partial")
        material = self.derived(response)
        self.assertEqual(material["parsed"]["coverage"]["unread_pages"], [2])
        self.assertFalse(material["parsed"]["coverage"]["content_verified"])

    def test_http_business_and_malformed_failures_are_archived_without_derived_facts(self):
        for status, payload in [(500, {"detail": "broken"}), (200, {"code": 1101, "data": None}),
                                (200, b"not-json"), (200, {"code": 0, "data": {"error": "parse failed"}})]:
            with self.subTest(status=status, payload=payload):
                self.replies = [("/v1/parse/sync", status, payload)]
                response = self.ocr(mode="sync", retry=True)
                self.assertEqual(response["call"]["status"], "failed")
                self.assertNotIn("derived_material_id", response["call"])
                self.assertTrue(Path(response["call"]["responses"][-1]["path"]).is_file())
                requests = len(self.seen)
                self.assertEqual(self.ocr(mode="sync")["call"]["id"], response["call"]["id"])
                self.assertEqual(len(self.seen), requests)

    def test_auto_uses_sync_for_short_sources_and_async_for_long_sources(self):
        self.replies = [("/v1/parse/sync", 200, result()),
            ("/v1/parse/async", 200, {"code": 0, "data": {"task_id": "long-job", "status": "queuing"}})]
        self.assertEqual(self.ocr()["call"]["mode"], "sync")
        writer = PdfWriter()
        for _ in range(4):
            writer.add_blank_page(width=600, height=800)
        path = self.root / "long.pdf"
        writer.write(path)
        self.original = self.call("material", "add", request={"project_id": self.project["id"],
            "input_id": "professional_records", "path": str(path)})
        response = self.ocr()
        self.assertEqual(response["call"]["mode"], "async")
        self.assertEqual(response["call"]["status"], "pending")

    def test_mixed_pdf_only_derives_unread_pages_and_keeps_native_text(self):
        from pypdf import PdfReader
        writer = PdfWriter()
        writer.add_page(PdfReader(Path(__file__).parent / "fixtures/credit_pdf_fixture.pdf").pages[0])
        writer.add_blank_page(width=600, height=800)
        path = self.root / "mixed.pdf"
        writer.write(path)
        self.original = self.call("material", "add", request={"project_id": self.project["id"],
            "input_id": "professional_records", "path": str(path)})
        native = self.original["parsed"]["fragments"]
        self.replies = [("/v1/parse/sync", 200, result())]
        derived = self.derived(self.ocr())
        self.assertEqual({x["value"] for x in derived["parsed"]["fragments"]}, {"合成记录状态待核实"})
        self.assertEqual(set(derived["derivation"]["locator_map"].values()), {"page:2"})
        self.assertEqual(self.call("material", "show", self.original["id"], "--project", self.project["id"])["parsed"]["fragments"], native)

    def test_agent_can_select_an_unusable_text_page_without_overwriting_native_parse(self):
        from pypdf import PdfReader
        writer = PdfWriter()
        page = PdfReader(Path(__file__).parent / "fixtures/credit_pdf_fixture.pdf").pages[0]
        writer.add_page(page)
        writer.add_page(page)
        path = self.root / "text-present-but-table-unusable.pdf"
        writer.write(path)
        self.original = self.call("material", "add", request={"project_id": self.project["id"],
            "input_id": "professional_records", "path": str(path)})
        self.assertEqual(self.original["parsed"]["coverage"]["unread_pages"], [])
        self.assertEqual(self.ocr()["status"], "not_needed")
        self.replies = [("/v1/parse/sync", 200, result())]
        response = self.ocr(pages=[2])
        material = self.derived(response)
        self.assertEqual(set(material["derivation"]["locator_map"].values()), {"page:2"})
        self.assertEqual(response["call"]["requested_pages"], [2])
        self.assertEqual(self.call("material", "show", self.original["id"], "--project", self.project["id"])["parsed"], self.original["parsed"])
        self.call("material", "ocr", request={"project_id": self.project["id"],
            "material_id": self.original["id"], "pages": [3]}, fails="OCR pages")

    def test_sync_timeout_does_not_fall_back_to_a_second_async_upload(self):
        config = yaml.safe_load(self.config.read_text())
        config["services"]["somark_ocr"]["timeout_seconds"] = .03
        self.config.write_text(yaml.safe_dump(config))
        self.on_request = lambda: time.sleep(.15)
        self.replies = [("/v1/parse/sync", 200, result())]
        response = self.ocr(mode="sync")
        self.assertEqual(response["call"]["status"], "failed")
        self.assertIn("Timeout", response["call"]["last_error"])
        self.assertEqual(len(self.seen), 1)

    def test_invalid_page_identity_or_coordinates_cannot_become_derived_sources(self):
        for mutation in (lambda r: r["data"]["result"]["outputs"]["json"]["pages"][1].update(page_num=0),
                         lambda r: r["data"]["result"]["outputs"]["json"]["pages"][0]["blocks"][0].update(bbox=[0, 0, 700, 60])):
            payload = result()
            mutation(payload)
            self.replies = [("/v1/parse/sync", 200, payload)]
            response = self.ocr(mode="sync", retry=True)
            self.assertEqual(response["call"]["status"], "failed")
            self.assertNotIn("derived_material_id", response["call"])

    def test_replacing_an_original_removes_its_obsolete_ocr_from_the_next_run(self):
        self.replies = [("/v1/parse/sync", 200, result())]
        derived = self.ocr()["call"]["derived_material_id"]
        path = self.root / "corrected.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=601, height=801)
        writer.write(path)
        replacement = self.call("material", "add", request={"project_id": self.project["id"],
            "input_id": "professional_records", "path": str(path), "replaces_material_id": self.original["id"]})
        run = self.call("run", "start", request={"project_id": self.project["id"]})
        self.assertNotIn(derived, run["material_ids"])
        self.assertEqual(run["material_ids"], [replacement["id"]])

    def test_empty_ocr_cache_still_checks_its_converted_artifact_hashes(self):
        payload = result()
        for page in payload["data"]["result"]["outputs"]["json"]["pages"]:
            page["blocks"] = []
        self.replies = [("/v1/parse/sync", 200, payload)]
        response = self.ocr()
        self.assertEqual(response["call"]["status"], "empty")
        Path(response["call"]["artifacts"][-1]["path"]).write_bytes(b"damaged")
        self.call("material", "ocr", request={"project_id": self.project["id"], "material_id": self.original["id"],
            "services_config": str(self.config)}, fails="OCR archive checksum")

    def test_disabled_slot_makes_no_network_request(self):
        from unittest.mock import patch
        from long_report.application import create_project
        scenario_root = self.root / "disabled_scenarios"
        shutil.copytree(Path(__file__).resolve().parents[1] / "scenarios/financial_due_diligence", scenario_root / "financial_due_diligence")
        path = scenario_root / "financial_due_diligence/scenario.yaml"
        config = yaml.safe_load(path.read_text())
        config["external_services"]["ocr"]["enabled"] = False
        path.write_text(yaml.safe_dump(config, allow_unicode=True))
        with patch("long_report.scenario._root", return_value=scenario_root):
            project = create_project(self.workspace, {"scenario_id": "financial_due_diligence", "scenario_version": config["version"],
                "credit_application_id": "DISABLED", "subject_scope": {"business_unit": "合成公司"}, "evaluation_date": "2026-10-31"})
        self.call("material", "ocr", request={"project_id": project["id"], "material_id": self.original["id"],
            "services_config": str(self.config)}, fails="not enabled")
        self.assertEqual(self.seen, [])

    def test_late_response_cannot_enter_an_active_run_and_can_be_collected_after_cancel(self):
        from long_report.application import start_run
        self.replies = [("/v1/parse/sync", 200, result())]
        started = []
        self.on_request = lambda: started.append(start_run(self.workspace, {"project_id": self.project["id"]}))
        self.call("material", "ocr", request={"project_id": self.project["id"], "material_id": self.original["id"],
            "services_config": str(self.config), "mode": "sync"}, fails="active run")
        self.assertEqual(started[0]["material_ids"], [self.original["id"]])
        self.on_request = None
        self.call("run", "cancel", request={"project_id": self.project["id"], "run_id": started[0]["id"]})
        self.assertEqual(self.ocr(mode="sync")["call"]["status"], "succeeded")
        self.assertEqual(len(self.seen), 1)

    def test_original_corruption_and_active_runs_are_rejected_before_network(self):
        run = self.call("run", "start", request={"project_id": self.project["id"]})
        self.call("material", "ocr", request={"project_id": self.project["id"], "material_id": self.original["id"],
            "services_config": str(self.config)}, fails="active run")
        self.call("run", "cancel", request={"project_id": self.project["id"], "run_id": run["id"]})
        Path(self.original["archived_path"]).write_bytes(b"corrupt")
        self.call("material", "ocr", request={"project_id": self.project["id"], "material_id": self.original["id"],
            "services_config": str(self.config)}, fails="checksum")
        self.assertEqual(self.seen, [])

    def test_ocr_policy_rejects_unknown_modes_and_wrong_capability_at_load(self):
        for mutate in [lambda s: s["ingestion"]["ocr"].update(mode="guessed"),
                       lambda s: s["external_services"]["ocr"].update(capability="search.web")]:
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                shutil.copytree(Path(__file__).resolve().parents[1] / "scenarios/financial_due_diligence", root / "financial_due_diligence")
                path = root / "financial_due_diligence/scenario.yaml"
                config = yaml.safe_load(path.read_text())
                config.setdefault("external_services", {"ocr": {"enabled": True, "service_ref": "somark_ocr",
                    "capability": "document.ocr", "contract_version": 1}})
                config.setdefault("ingestion", {"ocr": {"service_slot": "ocr", "mode": "auto", "sync_max_pages": 3}})
                mutate(config)
                path.write_text(yaml.safe_dump(config, allow_unicode=True))
                with self.assertRaisesRegex(ScenarioError, "OCR|ocr"):
                    load_scenario("financial_due_diligence", root)
