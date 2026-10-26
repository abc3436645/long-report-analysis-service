"""Publish four source-audited MOCK budget drafts through the report CLI."""

import json
import subprocess
from hashlib import sha256
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / ".venv/bin/report"
audit = json.loads((ROOT / "projects/four_report_acceptance_2026-10-23.json").read_text(encoding="utf-8"))
delivery_file = ROOT / "projects/four_report_deliveries_2026-10-23.json"
previous = json.loads(delivery_file.read_text(encoding="utf-8")) if delivery_file.exists() else {}
cases = {
    "budget_office": ("real_budget_acceptance_v8", "session.json"),
    "mining": ("real_budget_board_acceptance_v5", "mining.json"),
    "smelting": ("real_budget_board_acceptance_v5", "smelting.json"),
    "processing": ("real_budget_board_acceptance_v5", "processing.json"),
}
deliveries = {}
for label, (directory, session_name) in cases.items():
    checked = audit[label]
    assert not any(checked[key] for key in ("bad_source_values", "bad_calculations", "bad_charts", "missing_units", "unresolved_tokens"))
    work = ROOT / "projects" / directory
    session = json.loads((work / session_name).read_text(encoding="utf-8"))
    workspace = work / "projects"
    draft = workspace / session["project_id"] / "runs" / session["run_id"] / "draft/full_report.md"
    digest = sha256(draft.read_bytes()).hexdigest()
    if label in previous and previous[label]["run_id"] == session["run_id"]:
        revision = previous[label]["revision"]
        assert all(sha256(Path(revision[f"{kind}_path"]).read_bytes()).hexdigest() == revision["file_hashes"][kind] for kind in ("markdown", "docx"))
        deliveries[label] = previous[label]
        print(label, revision["id"], "already published", revision["docx_path"], flush=True)
        continue
    request_file = work / f"{label}_publish_request.json"

    def call(*arguments, request):
        request_file.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
        result = subprocess.run([str(REPORT), *arguments, "--workspace", str(workspace), "--request", str(request_file)],
                                cwd=ROOT, capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError(f"{label} {' '.join(arguments)}: {result.stderr[:1200]}")
        return json.loads(result.stdout)["data"]

    call("review", "submit", request={"project_id": session["project_id"], "run_id": session["run_id"],
                                      "draft_sha256": digest, "reviewer_id": "four-report-technical-audit",
                                      "verdict": "pass", "issues": []})
    validation = call("validate", request={"project_id": session["project_id"], "run_id": session["run_id"]})
    assert validation["hard_checks_passed"] and validation["status"] == "pending_review", (label, validation)
    revision = call("publish", request={"project_id": session["project_id"], "run_id": session["run_id"]})
    assert revision["status"] == "pending_review"
    for kind in ("markdown", "docx"):
        assert sha256(Path(revision[f"{kind}_path"]).read_bytes()).hexdigest() == revision["file_hashes"][kind]
    deliveries[label] = {"project_id": session["project_id"], "run_id": session["run_id"], "revision": revision,
                         "validation": validation}
    print(label, revision["id"], revision["status"], revision["docx_path"], flush=True)
delivery_file.write_text(json.dumps(deliveries, ensure_ascii=False, indent=2), encoding="utf-8")
