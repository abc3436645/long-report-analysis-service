"""Independent source and artifact audit of the selected MOCK budget run."""

import json
import re
import sqlite3
from collections import Counter
from decimal import Decimal
from pathlib import Path

import openpyxl
from docx import Document

from long_report.rendering import render_docx


root = Path(__file__).resolve().parents[3]
work = root / "projects" / "real_budget_acceptance_v4"
session = json.loads((work / "session.json").read_text(encoding="utf-8"))
draft = json.loads((work / "draft.json").read_text(encoding="utf-8"))
markdown = Path(draft["markdown_path"]).read_text(encoding="utf-8")
word_path = work / "candidate_final.docx"
render_docx(markdown, root / "scenarios/budget_operations/templates/default-v0.1.0.docx", word_path, "预算经营分析 2026 年 7 月 技术工作稿")
document = Document(word_path)

db = work / "projects" / session["project_id"] / "state.sqlite"
with sqlite3.connect(db) as connection:
    evidence = [json.loads(row[0]) for row in connection.execute("SELECT data FROM evidence WHERE run_id = ?", (session["run_id"],))]
    calculations = [json.loads(row[0]) for row in connection.execute("SELECT data FROM calculation WHERE run_id = ?", (session["run_id"],))]
    materials = {item["id"]: item for row in connection.execute("SELECT data FROM material") if (item := json.loads(row[0]))}
    bodies = "\n".join(row[0] for row in connection.execute("SELECT body FROM section_body"))
    project = json.loads(connection.execute("SELECT data FROM project").fetchone()[0])

books = {}
mismatched_source_values = []
for item in evidence:
    source = root / "data/scenarios/budget_operations" / materials[item["source_id"]]["original_name"]
    if source not in books:
        books[source] = openpyxl.load_workbook(source, data_only=True, read_only=True)
    sheet, cell = re.fullmatch(r"sheet:(.*)/cell:([A-Z]+\d+)", item["source_locator"]).groups()
    raw = books[source][sheet][cell].value
    if Decimal(str(raw)) != Decimal(item["value"]):
        mismatched_source_values.append(item["id"])
for book in books.values():
    book.close()

used = set(re.findall(r"\{\{(?:fact|ev):([^}|]+)", bodies))
unused = [item["id"] for item in evidence if item["id"] not in used]
profit = {(item["subject_id"], item["source_locator"].rsplit("cell:", 1)[1][0]): item for item in evidence if item["metric_id"] == "profit_total"}
calculation_mismatch = [item["id"] for item in calculations if Decimal(item["value"]) != Decimal(profit[item["subject_id"], "F"]["value"]) - Decimal(profit[item["subject_id"], "I"]["value"])]

markdown_sections = re.findall(r"^# (.*)$", markdown, re.M)
markdown_units = re.findall(r"^## (.*)$", markdown, re.M)
table_count = len(document.tables)
result = {
    "source_count": len(books), "evidence_count": len(evidence), "calculation_count": len(calculations),
    "mismatched_source_values": mismatched_source_values,
    "unused_evidence": unused, "calculation_mismatch": calculation_mismatch,
    "major_sections": len(markdown_sections), "unit_sections": len(markdown_units),
    "expected_units_missing": sorted(set(project["subject_scope"]["units"]) - set(markdown_units)),
    "word_tables": table_count, "markdown_tables": len(re.findall(r"^\| ---", markdown, re.M)),
    "unresolved_placeholders": markdown.count("{{"),
    "literal_markdown_headings_in_word": [p.text[:80] for p in document.paragraphs if p.text.startswith("#")],
    "word_size": word_path.stat().st_size,
}
(work / "quality_audit.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
assert result["source_count"] == 11 and result["evidence_count"] == 960 and result["calculation_count"] == 42
assert not any(result[key] for key in ("mismatched_source_values", "unused_evidence", "calculation_mismatch", "expected_units_missing", "unresolved_placeholders", "literal_markdown_headings_in_word"))
assert result["major_sections"] == 7 and result["unit_sections"] == 42
assert result["word_tables"] == result["markdown_tables"]
print(json.dumps(result, ensure_ascii=False))
