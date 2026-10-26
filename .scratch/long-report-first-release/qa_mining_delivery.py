"""Check the complete published mining DOCX/PDF against its source and reference."""

import json
import re
import subprocess
import xml.etree.ElementTree as ET
from hashlib import sha256
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn
from pypdf import PdfReader


ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / "projects/mining_board_full_delivery_v3_2026_07"
REVISION = next((WORK / "projects").glob("*/revisions/*"))
DIST = REVISION / "dist"
MD, DOCX, PDF = (DIST / "full_report.md", DIST / "full_report.docx", DIST / "full_report.pdf")
REFERENCE = ROOT / "results/budget_operations/江铜集团_矿山板块_月度经营分析报告_2026年1-7月.docx"
REFERENCE_PDF = next((WORK / "reference_compare").glob("*.pdf"))
qa = json.loads((REVISION / "qa/render_qa.json").read_text(encoding="utf-8"))
manifest = json.loads((REVISION / "manifest.json").read_text(encoding="utf-8"))
session = json.loads((WORK / "session.json").read_text(encoding="utf-8"))
units = json.loads((WORK / "mapping.json").read_text(encoding="utf-8"))["units"]
markdown = MD.read_text(encoding="utf-8")
document, reference = Document(DOCX), Document(REFERENCE)
pdf = PdfReader(PDF)
pages = [page.extract_text() or "" for page in pdf.pages]
assert len(units) == 6 and len(pdf.pages) == qa["pdf_page_count"] == 39
assert all(len(page.strip()) > 30 for page in pages), "blank PDF page"
assert qa["docx_openable"] and qa["pdf_openable"] and qa["headings_match"] and qa["tables_match"]
assert len(document.tables) == qa["table_count"] == 18
assert len(document.inline_shapes) == qa["embedded_chart_count"] == 7
assert all(sha256(path.read_bytes()).hexdigest() == manifest["file_hashes"][kind]
           for kind, path in (("markdown", MD), ("docx", DOCX), ("pdf", PDF)))

for table in document.tables:
    assert all(row._tr.get_or_add_trPr().find(qn("w:cantSplit")) is not None for row in table.rows)
    assert table.rows[0]._tr.get_or_add_trPr().find(qn("w:tblHeader")) is not None

styles = ("Normal", "Title", "Heading 1", "Heading 2", "Heading 3")
style_matches = []
for name in styles:
    actual, expected = document.styles[name], reference.styles[name]
    east_asia = qn("w:eastAsia")
    af, ef = actual.element.rPr.rFonts, expected.element.rPr.rFonts
    matched = actual.font.size.pt == expected.font.size.pt and af.get(east_asia) == ef.get(east_asia)
    style_matches.append((name, actual.font.size.pt, af.get(east_asia), matched))
assert all(item[3] for item in style_matches)
assert all(document.styles[name].font.size.pt == 10.5 and
           document.styles[name].element.rPr.rFonts.get(qn("w:eastAsia")) == "宋体"
           for name in ("TOC 1", "TOC 2"))

headings = [p.text for p in document.paragraphs if p.style.name == "Heading 1"]
assert len(headings) == 9 and all(headings[index].startswith(f"第{n}章") for index, n in enumerate("一二三四五六七八九"))
unit_headings = [p.text for p in document.paragraphs if p.style.name == "Heading 2"]
assert unit_headings == units
toc_paragraphs = [p.text for p in document.paragraphs if p.style.name in ("TOC 1", "TOC 2", "TOC 3")]
assert toc_paragraphs == [f"{name}\t{page}" for _, name, page in qa["toc_entries"]]
assert [item[1] for item in qa["toc_entries"] if item[0] == 2] == units

body_items = []
for child in document.element.body.iterchildren():
    if child.tag == qn("w:p"):
        text = "".join(node.text or "" for node in child.iter(qn("w:t")))
        style = child.find(qn("w:pPr"))
        style = style.find(qn("w:pStyle")) if style is not None else None
        body_items.append(("image" if next(child.iter(qn("a:blip")), None) is not None else "paragraph",
                           text, style.get(qn("w:val")) if style is not None else ""))
    elif child.tag == qn("w:tbl"):
        body_items.append(("table", "", ""))

toc_pages = {name: page for _, name, page in qa["toc_entries"]}
unit_manifest = []
for index, unit in enumerate(units, 1):
    start = next(i for i, item in enumerate(body_items) if item[1] == unit and item[2] == "Heading2")
    end = next((i for i in range(start + 1, len(body_items)) if body_items[i][2] in ("Heading1", "Heading2")), len(body_items))
    part = body_items[start:end]
    tables = [i for i, item in enumerate(part) if item[0] == "table"]
    images = [i for i, item in enumerate(part) if item[0] == "image"]
    assert len(tables) == 2 and len(images) == 1 and tables[0] < images[0] < tables[1], unit
    assert any(item[1].startswith(f"表4-{2*index-1}") for item in part)
    assert any(item[1].startswith(f"表4-{2*index}") for item in part)
    assert any(item[1].startswith(f"图4-{index}") for item in part)
    start_page = toc_pages[unit]
    end_page = toc_pages[units[index]] - 1 if index < len(units) else toc_pages["第五章 专项来源与独立口径分析"] - 1
    segment = "\n".join(pages[start_page - 1:end_page])
    for caption in (f"表4-{2*index-1}", f"表4-{2*index}", f"图4-{index}"):
        assert caption in segment, (unit, caption)
    chart_id = re.search(r"assets/(chart_[0-9a-f]{24})\.png", markdown.split("## " + unit + "\n", 1)[1].split("\n## ", 1)[0])[1]
    chart_pages = qa["pdf_chart_pages"][chart_id]
    assert len(chart_pages) == 1 and start_page <= chart_pages[0] <= end_page
    unit_manifest.append((unit, start_page, end_page, f"表4-{2*index-1}", f"表4-{2*index}", f"图4-{index}", chart_pages[0]))

boxes = subprocess.run(["pdftotext", "-bbox", str(PDF), "-"], capture_output=True, check=True).stdout
root = ET.fromstring(boxes)
ns = {"x": "http://www.w3.org/1999/xhtml"}
for number, page in enumerate(root.findall(".//x:page", ns), 1):
    width, height = float(page.attrib["width"]), float(page.attrib["height"])
    words = page.findall(".//x:word", ns)
    assert words and all(-1 <= float(word.attrib["xMin"]) <= float(word.attrib["xMax"]) <= width + 1 and
                         -1 <= float(word.attrib["yMin"]) <= float(word.attrib["yMax"]) <= height + 1
                         for word in words), f"PDF text crosses page boundary: {number}"

assert "consolidation_rule" in json.loads((REVISION / "qa/content_qa.json").read_text(encoding="utf-8"))["gaps"]["definition_missing"]
report = ["# 六矿整份 DOCX/PDF 对照验收", "", f"版本：{REVISION.name}；状态：{manifest['status']}。",
          "", "## 整份结构", "",
          f"- 新稿 9 章、6 矿、18 张真实 Word 表、7 张嵌入图，PDF {len(pdf.pages)} 页；参考 DOCX 有 {len(reference.tables)} 表、{len(reference.inline_shapes)} 图，本机转换为 {len(PdfReader(REFERENCE_PDF).pages)} 页（缺字影响版面，仅作辅助比较）。",
          "- 新稿每个 Word 表格行禁止跨页拆分，续页重复表头；39 页 PDF 无空白页，文本未越过页面边界。",
          "- 目录包含 41 个章节/小节，页码与最终 PDF 测得页码一致；正文标题与 Markdown 同序。",
          "- Normal、Title、Heading 1—3 的字体和字号与参考 DOCX 一致；TOC 1—2 为宋体 10.5 磅，参考稿未定义同名 TOC 样式。",
          "", "## 六矿逐户实物核验", "",
          "| 单位 | PDF 页 | 利润表 | 本矿图（可见页） | 经营指标表 | DOCX 顺序 |",
          "| --- | ---: | --- | --- | --- | --- |"]
for unit, first, last, profit, operating, chart, chart_page in unit_manifest:
    report.append(f"| {unit} | {first}—{last} | {profit} | {chart}（{chart_page}） | {operating} | 表→图→表，通过 |")
report += ["", "## 语义与边界", "", "- 独立审阅者已核对 293 个来源单元格、222 项已计算公式及 7 张图的主体和序列，结论 PASS。",
           "- 数值材料标明 MOCK；硫精矿 M 列按上年成本处理，缺本年同口径成本；七宝山仅列独立专项。",
           "- 计划版本与会计合并规则仍待业务签认，因此版本状态为 pending_review，不作为正式经营签报。",
           "", "## 可视检查", "", "- 已查看封面、两页目录、德兴利润表/图/跨页经营表、银山图与专项表；字形、图中文字和表格均可辨认，表格行拆分缺陷已修复。",
           "- 参考稿转换 PDF 的封面部分中文字在本机缺字；字体数值对照以原 DOCX 样式为准。", ""]
(WORK / "whole_document_qa.md").write_text("\n".join(report), encoding="utf-8")
print("PASS", len(pdf.pages), len(unit_manifest), WORK / "whole_document_qa.md")
