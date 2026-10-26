"""Render a reviewed Markdown body with the scenario's Word styles."""

from pathlib import Path
import os
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from hashlib import sha256
from io import BytesIO
from zipfile import ZipFile

from docx import Document
from PIL import Image, ImageStat
from pypdf import PdfReader
from docx.shared import Cm, RGBColor, Pt
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.text import WD_TAB_ALIGNMENT, WD_TAB_LEADER


def _headings(markdown: str) -> list[tuple[int, str]]:
    return [(len(match[1]), match[2].strip()) for line in markdown.splitlines()
            if (match := re.fullmatch(r"(#{1,3}) (.+)", line))]


def render_docx(markdown: str, template: Path, output: Path, title: str, toc_units: dict[str, int] | None = None,
                presentation: dict | None = None, toc_entries: list[tuple[int, str, int]] | None = None,
                metadata: dict | None = None) -> None:
    document = Document(template)
    presentation = presentation or {"body_font": "宋体", "heading_font": "黑体", "latin_font": "Times New Roman"}
    section = document.sections[0]
    section.page_width, section.page_height = Cm(21), Cm(29.7)
    section.left_margin = section.right_margin = Cm(2.3)
    section.top_margin, section.bottom_margin = Cm(2.15), Cm(2.0)
    for name in ("Normal", "Title", "Heading 1", "Heading 2", "Heading 3", "Heading 4",
                 "TOC Heading", "TOC 1", "TOC 2", "TOC 3", "Caption"):
        if name.startswith("TOC ") and name not in document.styles:
            document.styles.add_style(name, WD_STYLE_TYPE.PARAGRAPH)
        style = document.styles[name]
        font = presentation["body_font"] if name == "Normal" or name.startswith("TOC ") or name == "Caption" else presentation["heading_font"]
        style.font.name = presentation["latin_font"]
        style.font.color.rgb = RGBColor(0, 0, 0)
        fonts = style.element.get_or_add_rPr().get_or_add_rFonts()
        for key, value in (("eastAsia", font), ("ascii", presentation["latin_font"]),
                           ("hAnsi", presentation["latin_font"]), ("cs", presentation["latin_font"])):
            fonts.set(qn("w:" + key), value)
        for theme in ("asciiTheme", "hAnsiTheme", "eastAsiaTheme", "cstheme"):
            fonts.attrib.pop(qn("w:" + theme), None)
    for name, points in {"Normal": 10.5, "Title": 24, "Heading 1": 15, "Heading 2": 12.5,
                         "Heading 3": 12, "Heading 4": 11, "Caption": 9, "TOC 1": 10.5,
                         "TOC 2": 10.5, "TOC 3": 10.5}.items():
        document.styles[name].font.size = Pt(points)
    for name in ("Title", "Heading 1", "Heading 2", "Heading 3", "Heading 4", "Caption"):
        document.styles[name].paragraph_format.keep_with_next = True
    document.styles["Normal"].paragraph_format.line_spacing = 1.3
    document.styles["Normal"].paragraph_format.space_after = Pt(6)
    title_properties = document.styles["Title"].element.pPr
    if title_properties is not None:
        for border in title_properties.findall(qn("w:pBdr")):
            title_properties.remove(border)
    body = document._element.body
    for child in list(body):
        if child.tag.rsplit("}", 1)[-1] != "sectPr":
            body.remove(child)
    document.core_properties.title = title
    document.add_paragraph(title, style="Title")
    for label, value in (metadata or {}).items():
        document.add_paragraph(f"{label}：{value}")
    document.add_page_break()
    document.add_paragraph("目录", style="TOC Heading")
    entries = toc_entries if toc_entries is not None else [(level, name, 0) for level, name in _headings(markdown)]
    width = section.page_width - section.left_margin - section.right_margin
    for level, name, page in entries:
        paragraph = document.add_paragraph(style=f"TOC {level}")
        paragraph.paragraph_format.tab_stops.add_tab_stop(width, WD_TAB_ALIGNMENT.RIGHT, WD_TAB_LEADER.DOTS)
        paragraph.add_run(name + "\t" + str(page))
    document.add_page_break()
    first_heading = True
    for block in markdown.strip().split("\n\n"):
        lines = block.splitlines()
        chart = re.fullmatch(r"!\[([^\]]+)\]\((assets/chart_[0-9a-f]{24}\.png)\)", block.strip())
        if chart:
            section = document.sections[0]
            document.add_picture(str(output.parent / chart[2]), width=section.page_width - section.left_margin - section.right_margin)
            document.add_paragraph(chart[1], style="Caption")
        elif len(lines) >= 3 and all(line.startswith("|") and line.endswith("|") for line in lines) and all(set(cell.strip()) <= {"-", ":"} for cell in lines[1].strip("|").split("|")):
            rows = [[cell.strip() for cell in line.strip("|").split("|")] for line in (lines[0], *lines[2:])]
            if any(len(row) != len(rows[0]) for row in rows):
                raise ValueError("Markdown table has inconsistent columns")
            table = document.add_table(rows=1, cols=len(rows[0]))
            table.style = "Table Grid"
            borders = OxmlElement("w:tblBorders")
            for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
                border = OxmlElement("w:" + side)
                border.set(qn("w:val"), "single")
                border.set(qn("w:sz"), "4")
                border.set(qn("w:color"), "C8D0D8")
                borders.append(border)
            table._tbl.tblPr.append(borders)
            table.rows[0]._tr.get_or_add_trPr().append(OxmlElement("w:tblHeader"))
            for index, row in enumerate(rows):
                cells = table.rows[0].cells if index == 0 else table.add_row().cells
                for cell, value in zip(cells, row):
                    cell.text = value
                    if index == 0:
                        shade = OxmlElement("w:shd")
                        shade.set(qn("w:fill"), "E9EFF5")
                        cell._tc.get_or_add_tcPr().append(shade)
                        for run in cell.paragraphs[0].runs:
                            run.bold = True
            for row in table.rows:
                row._tr.get_or_add_trPr().append(OxmlElement("w:cantSplit"))
        elif block.startswith("#### "):
            document.add_paragraph(block[5:].strip(), style="Heading 4")
        elif block.startswith("### "):
            document.add_paragraph(block[4:].strip(), style="Heading 3")
        elif block.startswith("## "):
            document.add_paragraph(block[3:].strip(), style="Heading 2")
        elif block.startswith("# "):
            heading = document.add_paragraph(block[2:].strip(), style="Heading 1")
            if not first_heading:
                heading.paragraph_format.page_break_before = True
            first_heading = False
        elif re.match(r"^表\d+-\d+", block):
            document.add_paragraph(block.strip(), style="Caption")
        else:
            paragraph = document.add_paragraph()
            # shortcut: inline Markdown supports simple bold spans; extend only when report prompts need more syntax.
            for part in re.split(r"(\*\*[^*\n]+\*\*)", block.strip()):
                if part:
                    bold = part.startswith("**") and part.endswith("**")
                    paragraph.add_run(part[2:-2] if bold else part).bold = bold
    document.save(output)


def _pdf_outline(pdf: Path) -> list[tuple[int, str, int]]:
    reader = PdfReader(pdf)
    result = []
    def visit(items, level):
        for item in items:
            if isinstance(item, list):
                visit(item, level + 1)
            else:
                result.append((level, item.title, reader.get_destination_page_number(item) + 1))
    visit(reader.outline, 1)
    return result


def _convert_pdf(docx: Path) -> Path:
    office = shutil.which("soffice") or shutil.which("libreoffice")
    if office is None:
        raise ValueError("LibreOffice is required for measured Word directory pages")
    pdf = docx.with_suffix(".pdf")
    pdf.unlink(missing_ok=True)
    with tempfile.TemporaryDirectory(prefix="long-report-office-") as temporary:
        profile = Path(temporary)
        config = ET.Element("fontconfig")
        for directory in ("/System/Library/Fonts", "/System/Library/Fonts/Supplemental", "/Library/Fonts"):
            if Path(directory).is_dir():
                ET.SubElement(config, "dir").text = directory
        ET.SubElement(config, "cachedir").text = str(profile / "font-cache")
        font_config = profile / "fonts.conf"
        ET.ElementTree(config).write(font_config, encoding="utf-8", xml_declaration=True)
        environment = {**os.environ, "FONTCONFIG_FILE": str(font_config)}
        result = subprocess.run([office, "-env:UserInstallation=" + (profile / "user").as_uri(),
                                 "--headless", "--convert-to", "pdf", "--outdir", str(docx.parent), str(docx)],
                                capture_output=True, text=True, timeout=180, env=environment)
    if result.returncode or not pdf.is_file():
        raise ValueError("Word page render failed: " + (result.stderr or result.stdout)[-800:])
    return pdf


def render_paginated_docx(markdown: str, template: Path, output: Path, title: str,
                          toc_units: dict[str, int] | None = None, presentation: dict | None = None,
                          metadata: dict | None = None) -> tuple[Path, list[tuple[int, str, int]]]:
    """Settle visible directory page numbers against the rendered final DOCX."""
    titles = _headings(markdown)
    if not titles:
        raise ValueError("report has no headings for directory")
    entries = [(level, name, 0) for level, name in titles]
    for _ in range(4):
        render_docx(markdown, template, output, title, toc_units, presentation, entries, metadata)
        pdf = _convert_pdf(output)
        outline = _pdf_outline(pdf)
        cursor, measured = 0, []
        for level, name in titles:
            index = next((i for i in range(cursor, len(outline))
                          if " ".join(outline[i][1].split()) == " ".join(name.split())), None)
            if index is None:
                raise ValueError("rendered PDF directory heading missing: " + name)
            measured.append((level, name, outline[index][2]))
            cursor = index + 1
        if measured == entries:
            return pdf, entries
        entries = measured
    raise ValueError("Word directory page numbers did not converge")


def verify_docx(markdown: str, path: Path, chart_hashes: dict[str, str]) -> dict:
    """Read the delivered Word body back before the revision becomes visible."""
    document = Document(path)
    headings = [block.lstrip("#").strip() for block in markdown.strip().split("\n\n")
                if re.match(r"^#{1,4} ", block)]
    rendered_headings = [paragraph.text for paragraph in document.paragraphs
                         if re.fullmatch(r"Heading [1-4]", paragraph.style.name)]
    if headings != rendered_headings:
        raise ValueError("rendered Word headings differ from reviewed Markdown")
    table_blocks = []
    for block in markdown.strip().split("\n\n"):
        lines = block.splitlines()
        if len(lines) >= 3 and all(line.startswith("|") and line.endswith("|") for line in lines) and all(
            set(cell.strip()) <= {"-", ":"} for cell in lines[1].strip("|").split("|")
        ):
            table_blocks.append([[cell.strip() for cell in line.strip("|").split("|")]
                                 for line in (lines[0], *lines[2:])])
    rendered_tables = [[[cell.text for cell in row.cells] for row in table.rows] for table in document.tables]
    if table_blocks != rendered_tables:
        raise ValueError("rendered Word tables differ from reviewed Markdown")
    chart_mentions = re.findall(r"!\[[^\]]*\]\(assets/(chart_[0-9a-f]{24})\.png\)", markdown)
    if len(document.inline_shapes) != len(chart_mentions) or set(chart_mentions) != set(chart_hashes):
        raise ValueError("rendered Word chart count differs from reviewed Markdown")
    with ZipFile(path) as archive:
        media = {sha256(data).hexdigest(): data for name in archive.namelist()
                 if name.startswith("word/media/") for data in [archive.read(name)]}
    if not set(chart_hashes.values()) <= set(media):
        raise ValueError("rendered Word chart bytes differ from reviewed assets")
    for chart_hash in chart_hashes.values():
        with Image.open(BytesIO(media[chart_hash])) as chart:
            # shortcut: pixel variance catches blank charts; semantic chart review remains a separate gate.
            if max(ImageStat.Stat(chart.convert("RGB")).stddev) == 0:
                raise ValueError("rendered Word chart is blank")
    return {"docx_openable": True, "headings_match": True, "tables_match": True,
            "heading_count": len(rendered_headings), "table_count": len(rendered_tables),
            "embedded_chart_count": len(document.inline_shapes), "chart_count": len(chart_hashes),
            "verified_chart_hashes": chart_hashes, "charts_nonblank": True}


def verify_pdf_charts(path: Path, chart_ids: dict[str, str]) -> dict:
    """Confirm each reviewed chart raster is actually painted on a PDF page."""
    reader = PdfReader(path)
    if not reader.pages:
        raise ValueError("rendered PDF has no pages")
    def pixels(data):
        with Image.open(BytesIO(data)) as original:
            rendered = original.convert("RGB")
            return rendered.size, sha256(rendered.tobytes()).hexdigest()
    expected = {identifier: pixels((path.parent / "assets" / (identifier + ".png")).read_bytes())
                for identifier in chart_ids}
    pages = {identifier: [] for identifier in chart_ids}
    for number, page in enumerate(reader.pages, 1):
        stream = page.get_contents()
        content = stream.get_data() if stream is not None else b""
        for item in page.images:
            name = item.name.rsplit(".", 1)[0].encode()
            if not re.search(rb"/" + re.escape(name) + rb"\s+Do\b", content):
                continue
            image_pixels = pixels(item.data)
            for identifier, expected_pixels in expected.items():
                if image_pixels == expected_pixels:
                    pages[identifier].append(number)
    # shortcut: verifies drawn raster XObjects; upgrade if a converter rasterizes whole pages.
    missing = [identifier for identifier, shown in pages.items() if not shown]
    if missing:
        raise ValueError("rendered PDF chart missing: " + ", ".join(missing))
    return {"pdf_openable": True, "pdf_page_count": len(reader.pages), "pdf_chart_pages": pages}
