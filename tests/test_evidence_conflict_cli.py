import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPORT = Path(sys.executable).with_name("report")


class EvidenceConflictCliTests(unittest.TestCase):
    def test_conflicting_sources_need_an_explicit_decision_before_freeze(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "projects"
            request_file = root / "request.json"

            def call(*args, request=None):
                command = [REPORT, *args, "--workspace", str(workspace)]
                if request is not None:
                    request_file.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
                    command += ["--request", str(request_file)]
                result = subprocess.run(command, cwd=root, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                return json.loads(result.stdout)["data"]

            project = call("project", "create", request={
                "scenario_id": "budget_operations", "scenario_version": "0.2.0",
                "subject_scope": {"organization": "合成集团", "units": ["甲单位"]}, "report_period": "2026-07",
            })
            for name, amount in (("source_a.csv", "120"), ("source_b.csv", "135")):
                source = root / name
                source.write_text(f"单位,累计利润\n甲单位,{amount}\n", encoding="utf-8")
                call("material", "add", request={"project_id": project["id"], "input_id": "actuals", "path": str(source)})
            run = call("run", "start", request={"project_id": project["id"]})
            tasks = call("task", "list", "--project", project["id"], "--run", run["id"])
            candidates = []
            for task in tasks:
                material = call("task", "context", task["id"], "--project", project["id"])["material"]
                cell = material["parsed"]["sheets"]["CSV"]["cells"]["B2"]
                if not candidates:
                    request_file.write_text(json.dumps({
                        "project_id": project["id"], "run_id": run["id"], "task_id": task["id"],
                        "input_fingerprint": task["input_fingerprint"], "candidates": [{
                            "subject_id": "甲单位", "metric_id": "profit_total", "period": "2026-07",
                            "value": "999", "source_value": cell["value"], "source_locator": cell["locator"],
                        }],
                    }, ensure_ascii=False), encoding="utf-8")
                    invented = subprocess.run([REPORT, "task", "submit", "--workspace", str(workspace), "--request", str(request_file)], cwd=root, capture_output=True, text=True)
                    self.assertNotEqual(invented.returncode, 0)
                submitted = call("task", "submit", request={
                    "project_id": project["id"], "run_id": run["id"], "task_id": task["id"],
                    "input_fingerprint": task["input_fingerprint"], "candidates": [{
                        "subject_id": "甲单位", "metric_id": "profit_total", "period": "2026-07",
                        "window": "ytd", "unit": "万元", "basis": "actuals",
                        "value": cell["value"], "source_value": cell["value"], "source_locator": cell["locator"],
                    }],
                })
                candidates.append(submitted["candidates"][0])
            accepted = call("evidence", "decide", request={
                "project_id": project["id"], "run_id": run["id"],
                "candidate_id": candidates[0]["id"], "decision": "accept",
            })
            conflict = call("evidence", "decide", request={
                "project_id": project["id"], "run_id": run["id"],
                "candidate_id": candidates[1]["id"], "decision": "accept",
            })
            self.assertEqual(conflict["status"], "conflict")
            self.assertEqual(conflict["conflicts_with"], [accepted["id"]])
            request_file.write_text(json.dumps({"project_id": project["id"], "run_id": run["id"]}), encoding="utf-8")
            blocked = subprocess.run([REPORT, "evidence", "freeze", "--workspace", str(workspace), "--request", str(request_file)], cwd=root, capture_output=True, text=True)
            self.assertNotEqual(blocked.returncode, 0)
            self.assertIn("unresolved", blocked.stderr)
            replaced = call("evidence", "decide", request={
                "project_id": project["id"], "run_id": run["id"],
                "candidate_id": candidates[1]["id"], "decision": "replace",
                "supersedes_evidence_id": accepted["id"], "reason": "第二来源是业务确认的更正版本",
            })
            self.assertEqual(replaced["status"], "usable")
            self.assertEqual(replaced["supersedes_evidence_id"], accepted["id"])
            frozen = call("evidence", "freeze", request={"project_id": project["id"], "run_id": run["id"]})
            self.assertEqual(frozen["evidence_ids"], [replaced["id"]])


if __name__ == "__main__":
    unittest.main()
