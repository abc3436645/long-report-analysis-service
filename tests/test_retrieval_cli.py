"""Synthetic professional retrieval exercises the installed CLI boundary."""

import json
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


from credit_test_support import synthetic_credit_cli, registration_table, equity_details

REPORT = Path(sys.executable).with_name("report")


class RetrievalCliTests(unittest.TestCase):
    def test_mcp_partial_mismatch_empty_and_error_keep_distinct_gaps(self):
        replies = [
            {"status": "partial", "subject_id": "甲公司", "as_of": "2026-07-31", "source_ref": "SYN-2",
             "records": ["案件状态待补充。"], "limitations": ["仅返回第一页"]},
            {"status": "success", "subject_id": "乙公司", "as_of": "2026-07-31", "source_ref": "SYN-3",
             "records": ["乙公司记录。"], "limitations": []},
            {"status": "empty", "subject_id": "甲公司", "as_of": "2026-07-31", "source_ref": "SYN-4",
             "records": [], "limitations": []},
            {"tool_error": "synthetic service unavailable"},
        ]
        seen = []

        class Provider(BaseHTTPRequestHandler):
            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                seen.append((payload, dict(self.headers)))
                reply = replies.pop(0)
                message = {"jsonrpc": "2.0", "id": 1, "result": {"structuredContent": reply}}
                if "tool_error" in reply:
                    message = {"jsonrpc": "2.0", "id": 1, "error": {"code": -32000, "message": reply["tool_error"]}}
                body = json.dumps(message, ensure_ascii=False).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                workspace = root / "projects"
                request_path = root / "request.json"

                def call(*args, request=None):
                    command = [REPORT, *args, "--workspace", str(workspace)]
                    if request is not None:
                        request_path.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
                        command += ["--request", str(request_path)]
                    result = subprocess.run(command, cwd=root, capture_output=True, text=True)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    return json.loads(result.stdout)["data"]

                for expected in ("partial", "mismatch", "empty", "failed"):
                    project = call("project", "create", request={
                        "scenario_id": "financial_due_diligence", "scenario_version": "0.2.0", "credit_application_id": "SYN-1",
                        "subject_scope": {"business_unit": "甲公司"}, "evaluation_date": "2026-07-31",
                        "overrides": {"retrieval.enabled": True},
                    })
                    run = call("run", "start", request={"project_id": project["id"], "retrieval_provider_id": "synthetic"})
                    task = call("task", "list", "--project", project["id"], "--run", run["id"])[0]
                    fetched = call("retrieval", "execute", request={
                        "project_id": project["id"], "run_id": run["id"], "task_id": task["id"],
                        "provider": {"id": "synthetic", "kind": "mcp", "url": f"http://127.0.0.1:{server.server_port}/mcp", "tool": "enterprise_events"},
                    })
                    self.assertEqual(fetched["result_status"], expected)
                    self.assertTrue(Path(fetched["raw_path"]).is_file())
                    extractions = [item for item in call("task", "list", "--project", project["id"], "--run", run["id"])
                                   if item["kind"] == "extract_candidate_facts"]
                    self.assertEqual(len(extractions), 1 if expected == "partial" else 0)
                    for item in extractions:
                        call("task", "submit", request={"project_id": project["id"], "run_id": run["id"],
                            "task_id": item["id"], "input_fingerprint": item["input_fingerprint"], "candidates": []})
                    snapshot = call("evidence", "freeze", request={"project_id": project["id"], "run_id": run["id"]})
                    self.assertEqual(snapshot["retrieval_gaps"], ["enterprise_events:" + expected])
                    self.assertEqual(snapshot["evidence_ids"], [])
                self.assertEqual(seen[0][0]["method"], "tools/call")
                self.assertEqual(seen[0][0]["params"]["name"], "enterprise_events")
                self.assertEqual(seen[0][1]["Mcp-Method"], "tools/call")
        finally:
            server.shutdown()
            server.server_close()

    def test_http_result_is_archived_before_it_can_become_evidence(self):
        received = []

        class Provider(BaseHTTPRequestHandler):
            def do_POST(self):
                received.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                record = "担保合同待核实。" if len(received) == 1 else "新诉讼记录待核实。"
                body = json.dumps({"status": "success", "subject_id": "甲公司", "as_of": "2026-07-31",
                                   "source_ref": f"synthetic-record-{len(received)}", "records": [record],
                                   "limitations": []}, ensure_ascii=False).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                workspace = root / "projects"
                request_path = root / "request.json"
                cli = synthetic_credit_cli(root)

                def call(*args, request=None):
                    command = [*cli, *args, "--workspace", str(workspace)]
                    if request is not None:
                        request_path.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
                        command += ["--request", str(request_path)]
                    result = subprocess.run(command, cwd=root, capture_output=True, text=True)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    return json.loads(result.stdout)["data"]

                project = call("project", "create", request={
                    "scenario_id": "financial_due_diligence", "scenario_version": "0.2.0",
                    "subject_scope": {"business_unit": "甲公司"}, "evaluation_date": "2026-07-31",
                    "credit_application_id": "SYN-001", "overrides": {"retrieval.enabled": True},
                })
                outline = {"sections": project["effective_config"]["outline"]["sections"]}
                run = call("run", "start", request={"project_id": project["id"], "retrieval_provider_id": "synthetic"})
                task = next(item for item in call("task", "list", "--project", project["id"], "--run", run["id"])
                            if item["kind"] == "retrieve")
                fetched = call("retrieval", "execute", request={
                    "project_id": project["id"], "run_id": run["id"], "task_id": task["id"],
                    "provider": {"id": "synthetic", "kind": "http", "url": f"http://127.0.0.1:{server.server_port}/search"},
                })
                self.assertEqual(fetched["result_status"], "success")
                self.assertEqual(received[0]["subject_id"], "甲公司")
                self.assertTrue(Path(fetched["raw_path"]).is_file())
                extraction = next(item for item in call("task", "list", "--project", project["id"], "--run", run["id"])
                                  if item["kind"] == "extract_candidate_facts")
                source = call("task", "context", extraction["id"], "--project", project["id"])["material"]
                fragment = next(item for item in source["parsed"]["fragments"] if item["value"] == "担保合同待核实。")
                submitted = call("task", "submit", request={
                    "project_id": project["id"], "run_id": run["id"], "task_id": extraction["id"],
                    "input_fingerprint": extraction["input_fingerprint"], "candidates": [{
                        "subject_id": "甲公司", "metric_id": "guarantee", "period": "2026-07-31",
                        "value": fragment["value"], "source_value": fragment["value"], "source_locator": fragment["locator"],
                        "basis": "professional_records",
                    }],
                })
                evidence = call("evidence", "decide", request={
                    "project_id": project["id"], "run_id": run["id"],
                    "candidate_id": submitted["candidates"][0]["id"], "decision": "accept",
                })
                self.assertEqual(evidence["source_id"], fetched["material_id"])
                snapshot = call("evidence", "freeze", request={"project_id": project["id"], "run_id": run["id"]})
                self.assertEqual(snapshot["retrieval_gaps"], [])
                self.assertEqual(snapshot["evidence_ids"], [evidence["id"]])

                def deliver(active_run, records):
                    call("calculate", request={"project_id": project["id"], "run_id": active_run["id"]})
                    if not active_run.get("report_plan"):
                        call("draft", "plan", request={"project_id": project["id"], "run_id": active_run["id"],
                                                      "report_request": "评审甲公司授信风险与专业记录",
                                                      "outline": outline})
                    event_lines = "；".join("{{fact:" + item["id"] + "}}（{{ev:" + item["id"] + "}}）" for item in records)
                    bodies = {}
                    for definition in outline["sections"]:
                        text = "本小节材料待补，结论待核实；未取得外部授信结果，不作授信决定。"
                        if definition["id"] == "company":
                            text = "本次评审对象为甲公司；申请原件尚缺，专业记录不能代替申请材料。"
                        elif definition["id"] == "risks":
                            text = "专业来源记载：" + event_lines + "。事件状态和影响仍待核验，建议核对合同与后续状态。"
                        elif definition["id"] == "conclusion":
                            text = "本稿依据归档专业记录提示担保和诉讼线索；必要材料及政策缺失，结论待复核。"
                        bodies[definition["id"]] = "\n\n".join("## " + heading + "\n\n" + text
                            for heading in definition["subheadings"]) if definition["subheadings"] else text
                    bodies["company"] = bodies["company"].replace("## 一、工商信息\n\n",
                        "## 一、工商信息\n\n" + registration_table(outline["sections"][0]) + "\n\n", 1)
                    bodies["company"] = bodies["company"].replace("## 四、股权、股东及投资情况\n\n",
                        "## 四、股权、股东及投资情况\n\n" + equity_details(outline["sections"][0]) + "\n\n", 1)
                    for section_id in (item["id"] for item in outline["sections"]):
                        section = next(item for item in call("draft", "plan", request={"project_id": project["id"], "run_id": active_run["id"]})
                                       if item["section_id"] == section_id)
                        if section["status"] != "submitted":
                            call("draft", "submit", request={"project_id": project["id"], "run_id": active_run["id"],
                                "task_id": section["id"], "author_id": "retrieval-writer", "body": bodies[section_id]})
                    draft = call("draft", "build", request={"project_id": project["id"], "run_id": active_run["id"]})
                    call("review", "submit", request={"project_id": project["id"], "run_id": active_run["id"],
                        "draft_sha256": draft["sha256"], "reviewer_id": "retrieval-reviewer", "verdict": "pass", "issues": []})
                    return call("publish", request={"project_id": project["id"], "run_id": active_run["id"]})

                first_revision = deliver(run, [evidence])
                self.assertEqual(first_revision["status"], "pending_review")
                second = call("run", "start", request={"project_id": project["id"], "base_revision_id": first_revision["id"],
                                                       "retrieval_provider_id": "synthetic"})
                reused = next(item for item in call("task", "list", "--project", project["id"], "--run", second["id"])
                              if item["kind"] == "retrieve")
                self.assertEqual(reused["status"], "submitted")
                self.assertEqual(reused["reused_from_task_id"], task["id"])
                self.assertEqual(len(received), 1)
                call("run", "cancel", request={"project_id": project["id"], "run_id": second["id"]})
                refreshed = call("run", "start", request={"project_id": project["id"], "base_revision_id": first_revision["id"],
                                                          "retrieval_provider_id": "synthetic", "refresh_retrieval": True})
                refreshing_task = next(item for item in call("task", "list", "--project", project["id"], "--run", refreshed["id"])
                                       if item["kind"] == "retrieve")
                self.assertEqual(refreshing_task["status"], "ready")
                second_fetch = call("retrieval", "execute", request={"project_id": project["id"], "run_id": refreshed["id"],
                    "task_id": refreshing_task["id"], "provider": {"id": "synthetic", "kind": "http",
                    "url": f"http://127.0.0.1:{server.server_port}/search"}})
                self.assertEqual(len(received), 2)
                next_extraction = next(item for item in call("task", "list", "--project", project["id"], "--run", refreshed["id"])
                                       if item["kind"] == "extract_candidate_facts")
                next_source = call("task", "context", next_extraction["id"], "--project", project["id"])["material"]
                next_fragment = next(item for item in next_source["parsed"]["fragments"] if item["value"] == "新诉讼记录待核实。")
                next_submitted = call("task", "submit", request={"project_id": project["id"], "run_id": refreshed["id"],
                    "task_id": next_extraction["id"], "input_fingerprint": next_extraction["input_fingerprint"],
                    "candidates": [{"subject_id": "甲公司", "metric_id": "lawsuit", "period": "2026-07-31",
                        "value": next_fragment["value"], "source_value": next_fragment["value"],
                        "source_locator": next_fragment["locator"], "basis": "professional_records"}]})
                second_evidence = call("evidence", "decide", request={"project_id": project["id"], "run_id": refreshed["id"],
                    "candidate_id": next_submitted["candidates"][0]["id"], "decision": "accept"})
                next_snapshot = call("evidence", "freeze", request={"project_id": project["id"], "run_id": refreshed["id"]})
                self.assertEqual(set(next_snapshot["evidence_ids"]), {evidence["id"], second_evidence["id"]})
                updated_revision = deliver(refreshed, [evidence, second_evidence])
                self.assertIn("新诉讼记录待核实", Path(updated_revision["markdown_path"]).read_text(encoding="utf-8"))
                self.assertNotIn("新诉讼记录待核实", Path(first_revision["markdown_path"]).read_text(encoding="utf-8"))
                Path(second_fetch["raw_path"]).write_text("changed", encoding="utf-8")
                stale = call("run", "start", request={"project_id": project["id"], "base_revision_id": updated_revision["id"],
                                                     "retrieval_provider_id": "synthetic"})
                stale_task = next(item for item in call("task", "list", "--project", project["id"], "--run", stale["id"])
                                  if item["kind"] == "retrieve")
                self.assertEqual(stale_task["status"], "ready")
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
