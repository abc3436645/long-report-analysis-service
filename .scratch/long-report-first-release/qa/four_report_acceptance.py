"""Independently check four MOCK budget drafts against source cells and reference structure."""

import json
import re
import sqlite3
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

import openpyxl
from docx import Document
from PIL import Image

from long_report.rendering import render_docx


ROOT = Path(__file__).resolve().parents[3]
OUTPUT = ROOT / "projects/four_report_acceptance_2026-10-23.json"
CASES = (
    ("budget_office", "real_budget_acceptance_v8", "session.json", "预算办经营快报分析报告_2026年7月_技术工作稿_v0.1.0.docx", 7, 42, 10, 0),
    ("mining", "real_budget_board_acceptance_v5", "mining.json", "江铜集团_矿山板块_月度经营分析报告_2026年1-7月.docx", 11, 6, 0, 6),
    ("smelting", "real_budget_board_acceptance_v5", "smelting.json", "江铜集团冶炼板块经营分析报告_2026年1—7月_V2.docx", 9, 8, 2, 11),
    ("processing", "real_budget_board_acceptance_v5", "processing.json", "江铜集团铜加工板块经营分析报告_2026年1—7月_V2.docx", 10, 10, 8, 19),
)


def records(connection, table, run_id=None):
    sql = f"SELECT data FROM {table}" + (" WHERE run_id = ?" if run_id else "")
    return [json.loads(row[0]) for row in connection.execute(sql, (run_id,) if run_id else ())]


results = {}
for label, directory, session_name, reference_name, chapters, main_units, nested_units, charts_expected in CASES:
    work = ROOT / "projects" / directory
    session = json.loads((work / session_name).read_text(encoding="utf-8"))
    project_dir = work / "projects" / session["project_id"]
    draft = project_dir / "runs" / session["run_id"] / "draft/full_report.md"
    markdown = draft.read_text(encoding="utf-8")
    with sqlite3.connect(project_dir / "state.sqlite") as connection:
        project = records(connection, "project")[0]
        evidence = records(connection, "evidence", session["run_id"])
        calculations = records(connection, "calculation", session["run_id"])
        materials = {item["id"]: item for item in records(connection, "material")}
        registered_charts = {item["id"]: item for item in records(connection, "chart")} if connection.execute("SELECT name FROM sqlite_master WHERE name = 'chart'").fetchone() else {}
    by_id = {item["id"]: item for item in evidence}
    books = {}
    bad_source = []
    for item in evidence:
        source = ROOT / "data/scenarios/budget_operations" / materials[item["source_id"]]["original_name"]
        if source not in books:
            books[source] = openpyxl.load_workbook(source, data_only=True, read_only=True)
        location = re.fullmatch(r"sheet:(.*)/cell:([A-Z]+\d+)", item["source_locator"])
        if location is None or Decimal(str(books[source][location[1]][location[2]].value)) != Decimal(item["value"]):
            bad_source.append(item["id"])
    for book in books.values():
        book.close()
    expected_columns = {"budget_difference": ("F", "I"), "month_change": ("D", "E"), "ytd_change": ("F", "G")}
    bad_calculation = []
    for item in calculations:
        if item["status"] != "calculated":
            continue
        inputs = [by_id[identifier] for identifier in item["input_evidence_ids"]]
        columns = tuple(source["source_locator"].rsplit("cell:", 1)[1][0] for source in inputs)
        if columns != expected_columns[item["metric_id"]] or any(source["subject_id"] != item["subject_id"] for source in inputs) or Decimal(item["value"]) != Decimal(inputs[0]["value"]) - Decimal(inputs[1]["value"]):
            bad_calculation.append(item["id"])
    image_ids = re.findall(r"!\[[^\]]*\]\(assets/(chart_[0-9a-f]{24})\.png\)", markdown)
    bad_charts = []
    for identifier in image_ids:
        chart = registered_charts.get(identifier)
        asset = draft.parent / "assets" / f"{identifier}.png"
        if chart is None or not asset.is_file() or sha256(asset.read_bytes()).hexdigest() != chart["sha256"] or any(evidence_id not in by_id for evidence_id in chart["source_evidence_ids"]):
            bad_charts.append(identifier)
        else:
            with Image.open(asset) as image:
                image.verify()
    outline = project["effective_config"]["outline"]
    unit_names = outline.get("unit_names", project["subject_scope"]["units"])
    levels = outline.get("unit_levels", {})
    word_path = draft.parent / "candidate_qa.docx"
    render_docx(markdown, ROOT / "scenarios/budget_operations/templates/default-v0.1.0.docx", word_path,
                project["report_title"], {name: levels.get(name, 2) for name in unit_names})
    word = Document(word_path)
    reference = Document(ROOT / "results/budget_operations" / reference_name)
    headings = [(p.text, p.style.name) for p in word.paragraphs]
    missing_units = [name for name in unit_names if (name, f"Heading {levels.get(name, 2)}") not in headings]
    result = {
        "source_books": len(books), "evidence": len(evidence), "calculated": sum(item["status"] == "calculated" for item in calculations),
        "bad_source_values": bad_source, "bad_calculations": bad_calculation, "bad_charts": bad_charts,
        "missing_units": missing_units, "chapters": len(re.findall(r"^# ", markdown, re.M)),
        "main_units": sum(levels.get(name, 2) == 2 for name in unit_names),
        "nested_units": sum(levels.get(name, 2) == 3 for name in unit_names),
        "charts": len(image_ids), "word_charts": len(word.inline_shapes),
        "tables": len(word.tables), "reference_tables": len(reference.tables),
        "word_paragraphs": len(word.paragraphs), "reference_paragraphs": len(reference.paragraphs),
        "unresolved_tokens": markdown.count("{{"), "title": word.paragraphs[0].text, "candidate_docx": str(word_path),
    }
    results[label] = result
    assert not any((bad_source, bad_calculation, bad_charts, missing_units, result["unresolved_tokens"])), (label, result)
    assert "2026" in result["title"] or "二〇二六" in result["title"], (label, result["title"])
    assert (result["chapters"], result["main_units"], result["nested_units"], result["charts"], result["word_charts"]) == (chapters, main_units, nested_units, charts_expected, charts_expected), (label, result)
    assert len(word.tables) == len(re.findall(r"^\| ---", markdown, re.M)), (label, result)
OUTPUT.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({name: {key: value for key, value in result.items() if key in ("evidence", "calculated", "chapters", "main_units", "nested_units", "charts", "tables", "reference_tables")} for name, result in results.items()}, ensure_ascii=False))
