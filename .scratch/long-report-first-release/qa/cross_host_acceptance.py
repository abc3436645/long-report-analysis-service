"""Audit the retained three-host wheel acceptance workspaces."""

import hashlib
import json
import sqlite3
from pathlib import Path

from docx import Document


ROOT = Path(__file__).resolve().parents[3]
HOSTS = ("codex", "claude", "dsh")
CASES = {
    "budget_operations": ("cross_host_wheel_acceptance", "test_confirmed_actual_and_matching_budget_produce_traced_difference"),
    "credit_review": ("cross_host_credit_fixed", "test_application_financials_and_professional_records_yield_a_reviewable_full_report"),
    "compensation_analysis": ("cross_host_wheel_acceptance", "test_accrual_groups_and_small_sample_suppression_reach_the_full_report"),
}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def records(connection: sqlite3.Connection, table: str) -> list[dict]:
    return [json.loads(row[0]) for row in connection.execute(f"SELECT data FROM {table}")]


def audit_case(host: str, scene: str) -> dict:
    area, name = CASES[scene]
    case = ROOT / "projects" / area / host / name
    databases = list(case.glob("projects/*/state.sqlite"))
    assert len(databases) == 1, (host, scene, databases)
    connection = sqlite3.connect(databases[0])
    project = records(connection, "project")[0]
    assert project["scenario_id"] == scene
    revisions = records(connection, "revision")
    assert len(revisions) == 4, (host, scene, len(revisions))
    latest_id = connection.execute("SELECT revision_id FROM latest").fetchone()[0]
    latest = next(item for item in revisions if item["id"] == latest_id)
    for revision in revisions:
        for kind in ("markdown", "docx"):
            path = Path(revision[f"{kind}_path"])
            assert path.is_file(), path
            assert digest(path.read_bytes()) == revision["file_hashes"][kind], path
    markdown = Path(latest["markdown_path"])
    word = Document(latest["docx_path"])
    assert markdown.stat().st_size > 0 and word.paragraphs
    headings = [line[2:] for line in markdown.read_text(encoding="utf-8").splitlines() if line.startswith("# ")]
    expected = {item["title"] for item in project["effective_config"]["outline"]["sections"]}
    assert set(headings) == expected, (host, scene, headings, expected)
    facts = sorted(
        (str(item.get("subject_id")), str(item.get("metric_id")), str(item.get("period")),
         str(item.get("window")), str(item.get("value")), str(item.get("status")))
        for item in records(connection, "evidence")
    )
    metrics = sorted(
        (str(item.get("metric_id")), str(item.get("subject_id")), str(item.get("period")),
         str(item.get("window")), str(item.get("value")), str(item.get("status")))
        for item in records(connection, "calculation")
    )
    inputs = {path.name: digest(path.read_bytes()) for path in case.iterdir()
              if path.is_file() and path.name != "request.json"}
    if scene == "credit_review":
        inputs["credit_pdf_fixture.pdf"] = digest((ROOT / "tests/fixtures/credit_pdf_fixture.pdf").read_bytes())
    return {
        "scenario_fingerprint": project["scenario_fingerprint"],
        "effective_config_fingerprint": project["effective_config_fingerprint"],
        "template_sha256": digest((ROOT / "scenarios" / scene / project["effective_config"]["scenario"]["template"]).read_bytes()),
        "input_sha256": inputs,
        "facts_sha256": digest(json.dumps(facts, ensure_ascii=False).encode()),
        "calculations_sha256": digest(json.dumps(metrics, ensure_ascii=False).encode()),
        "revision_count": len(revisions),
        "revision_statuses": [item["status"] for item in revisions],
        "latest_markdown": str(markdown),
        "latest_docx": latest["docx_path"],
        "latest_file_sha256": latest["file_hashes"],
        "word_table_count": len(word.tables),
        "major_sections": len(headings),
    }


def main() -> None:
    wheel = ROOT / "dist" / "long_report_agent-0.1.0-py3-none-any.whl"
    manifest = {
        "wheel_sha256": digest(wheel.read_bytes()),
        "master_skill_sha256": digest((ROOT / ".agents/skills/long-report/SKILL.md").read_bytes()),
        "hosts": {host: {scene: audit_case(host, scene) for scene in CASES} for host in HOSTS},
    }
    for scene in CASES:
        rows = [manifest["hosts"][host][scene] for host in HOSTS]
        for key in ("scenario_fingerprint", "effective_config_fingerprint", "template_sha256", "input_sha256", "facts_sha256", "calculations_sha256", "revision_count", "revision_statuses", "word_table_count", "major_sections"):
            assert all(row[key] == rows[0][key] for row in rows), (scene, key)
        assert all(row["revision_statuses"] == ["pending_review"] * 4 for row in rows), scene
    destination = ROOT / "projects" / "cross_host_acceptance_manifest.json"
    destination.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "pass", "hosts": list(HOSTS), "scenarios": list(CASES),
                      "revisions_per_scenario": 4, "manifest": str(destination)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
