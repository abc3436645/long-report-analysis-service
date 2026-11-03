"""Render a reviewed Markdown body with the scenario's Word styles."""

from datetime import date
from functools import lru_cache
from unicodedata import east_asian_width
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
from PIL import Image, ImageFont, ImageStat
from pypdf import PdfReader
from docx.shared import Cm, RGBColor, Pt, Twips
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT, WD_TAB_LEADER
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT

from long_report.scenario import markdown_table_rows
from long_report.annotations import annotated_blocks, verify_comments
from docx.enum.section import WD_ORIENT, WD_SECTION_START


def _headings(markdown: str) -> list[tuple[int, str]]:
    return [(len(match[1]), match[2].strip()) for line in markdown.splitlines()
            if (match := re.fullmatch(r"(#{1,3}) (.+)", line))]


STYLE_SIZES = {"Normal": 10.5, "Title": 22, "Heading 1": 16, "Heading 2": 14,
               "Heading 3": 12, "Heading 4": 11, "Caption": 10.5, "TOC Heading": 16,
               "TOC 1": 10.5, "TOC 2": 10.5, "TOC 3": 10.5, "Table Body": 10,
               "Table Header": 10, "Header": 9, "Footer": 9, "Cover Metadata": 11}


@lru_cache(maxsize=1)
def _installed_fonts() -> set[str]:
    command = shutil.which("fc-list")
    if command:
        result = subprocess.run([command, "--format", "%{family}\n"], capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise ValueError("cannot inspect installed report fonts: " + result.stderr[-400:])
        return {name.strip().casefold() for line in result.stdout.splitlines() for name in line.split(",")}
    # Font files also make the renderer usable on hosts without fontconfig's CLI.
    names = set()
    for path in ("/System/Library/Fonts/Supplemental/Songti.ttc", "/System/Library/Fonts/STHeiti Medium.ttc",
                 "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
                 "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",
                 "/usr/share/fonts/truetype/liberation2/LiberationSerif-Regular.ttf",
                 "/System/Library/Fonts/Supplemental/Times New Roman.ttf"):
        if Path(path).is_file():
            names.add(ImageFont.truetype(path, 12).getname()[0].casefold())
    return names


def report_fonts(presentation: dict | None = None) -> dict[str, str]:
    requested = presentation or {"body_font": "宋体", "heading_font": "黑体", "latin_font": "Times New Roman"}
    installed = _installed_fonts()
    if not requested.get("allow_font_fallback", True):
        missing = [requested[key] for key in ("body_font", "heading_font", "latin_font")
                   if requested[key].casefold() not in installed]
        if missing:
            raise ValueError("required report font unavailable: " + ", ".join(sorted(set(missing))))
        return {key: requested[key] for key in ("body_font", "heading_font", "latin_font")}
    result = {}
    for key, fallback in (("body_font", ("Noto Serif CJK SC", "Source Han Serif SC", "Songti SC")),
                          ("heading_font", ("Noto Sans CJK SC", "Source Han Sans SC", "Heiti SC", "Hiragino Sans GB")),
                          ("latin_font", ("Liberation Serif", "Times"))):
        result[key] = next((name for name in (requested[key], *fallback) if name.casefold() in installed), None)
        if result[key] is None:
            raise ValueError("reliable installed report font unavailable: " + key)
    return result


def _set_fonts(properties, chinese: str, latin: str) -> None:
    fonts = properties.get_or_add_rFonts()
    for key, value in (("eastAsia", chinese), ("ascii", latin), ("hAnsi", latin), ("cs", latin)):
        fonts.set(qn("w:" + key), value)
    for theme in ("asciiTheme", "hAnsiTheme", "eastAsiaTheme", "csTheme", "cstheme"):
        fonts.attrib.pop(qn("w:" + theme), None)
    language = properties.find(qn("w:lang"))
    if language is None:
        language = OxmlElement("w:lang")
        properties.append(language)
    language.set(qn("w:eastAsia"), "zh-CN")
    language.set(qn("w:val"), "en-US")


def _cover_items(metadata: dict | None, presentation: dict | None) -> list[tuple[str, str]]:
    if metadata is None:
        return []
    profile = (presentation or {}).get("cover")
    return [(field["label"], metadata[field["label"]]) for field in profile["fields"]] if profile else list(metadata.items())


def _validate_cover(title: str, metadata: dict, presentation: dict | None = None) -> None:
    required = ("统计期间", "报告生成日期", "分析对象", "编制部门", "数据性质", "报告版本", "数据版本", "保密说明")
    required += tuple(field["label"] for field in (presentation or {}).get("cover", {}).get("fields", []))
    if any(not isinstance(metadata.get(key), str) or not metadata[key].strip() for key in required):
        raise ValueError("report cover metadata is incomplete")
    if not re.fullmatch(r"V[1-9][0-9]*\.[0-9]+", metadata["报告版本"]):
        raise ValueError("report cover version must be readable Vmajor.minor")
    try:
        date.fromisoformat(metadata["报告生成日期"])
    except ValueError as error:
        raise ValueError("report cover generation date is invalid") from error
    periods = re.findall(r"[0-9]{4}年(?:[0-9]{1,2}[—–－至-])?[0-9]{1,2}月", title)
    normalize = lambda value: re.sub(r"[—–－至-]", "-", value)
    if any(normalize(period) not in normalize(metadata["统计期间"]) for period in periods):
        raise ValueError("report cover period conflicts with report title")


def _page_setup(section, landscape: bool = False) -> int:
    section.orientation = WD_ORIENT.LANDSCAPE if landscape else WD_ORIENT.PORTRAIT
    section.page_width, section.page_height = (Cm(29.7), Cm(21)) if landscape else (Cm(21), Cm(29.7))
    section.left_margin = section.right_margin = Cm(2.3)
    section.top_margin, section.bottom_margin = Cm(2.15), Cm(2.0)
    return section.page_width - section.left_margin - section.right_margin


def _effective(paragraph, name):
    value = getattr(paragraph.paragraph_format, name)
    return getattr(paragraph.style.paragraph_format, name) if value is None else value


def _table_section(document, landscape: bool) -> int:
    preceding = []
    while len(document._element.body) > 1 and document._element.body[-2].tag == qn("w:p"):
        paragraph = document.paragraphs[-1]
        if not _effective(paragraph, "keep_with_next"):
            break
        preceding.insert(0, paragraph._p)
        document._element.body.remove(paragraph._p)
    if len(document._element.body) > 1 and document._element.body[-2].xpath('.//w:br[@w:type="page"]'):
        document._element.body.remove(document._element.body[-2])
    section = document.add_section(WD_SECTION_START.NEW_PAGE)
    section.different_first_page_header_footer = False
    width = _page_setup(section, landscape)
    for paragraph in preceding:
        document._element.body.insert(-1, paragraph)
    return width


def _block_widths(document) -> dict:
    widths, pending = {}, []
    for block in document._element.body:
        pending.append(block)
        properties = block if block.tag == qn("w:sectPr") else block.find("w:pPr/w:sectPr", block.nsmap)
        if properties is not None:
            size, margins = properties.find(qn("w:pgSz")), properties.find(qn("w:pgMar"))
            width = Twips(int(size.get(qn("w:w"))) - int(margins.get(qn("w:left"))) - int(margins.get(qn("w:right"))))
            widths.update((item, width) for item in pending)
            pending = []
    return widths


def _table_rules(markdown: str, outline: dict | None, presentation: dict | None = None) -> list[dict | None]:
    definitions = {section["title"]: section for section in (outline or {}).get("sections", [])}
    chapter, subheading, child, rules = {}, None, None, []
    for block in markdown.strip().split("\n\n"):
        heading = re.fullmatch(r"(#{1,3}) (.+)", block.strip())
        if heading and heading[1] == "#":
            chapter, subheading, child = definitions.get(heading[2].strip(), {}), None, None
        elif heading and heading[1] == "##":
            subheading, child = heading[2].strip(), None
        elif heading:
            child = heading[2].strip()
        elif markdown_table_rows(block) is not None:
            rule = next((rule for rule in chapter.get("required_tables", [])
                         if rule["subheading"] == subheading
                         and ("child_heading" not in rule or rule["child_heading"] == child)), None)
            if rule and ("font" in rule or "font_size_pt" in rule):
                raise ValueError("table fonts must be defined in presentation.table_styles")
            if rule and "style" in rule:
                style = (presentation or {}).get("table_styles", {}).get(rule["style"])
                if style is None:
                    raise ValueError("unknown table style: " + rule["style"])
                rule = {**rule, **style}
            rules.append(rule)
    return rules


def render_docx(markdown: str, template: Path, output: Path, title: str, toc_units: dict[str, int] | None = None,
                presentation: dict | None = None, toc_entries: list[tuple[int, str, int]] | None = None,
                metadata: dict | None = None, outline: dict | None = None) -> None:
    annotated = annotated_blocks(markdown, presentation)
    markdown = "\n\n".join(text for text, _ in annotated)
    if metadata is not None:
        _validate_cover(title, metadata, presentation)
    document = Document(template)
    fonts = report_fonts(presentation)
    section = document.sections[0]
    _page_setup(section)
    for name, points in STYLE_SIZES.items():
        rule = (presentation or {}).get("styles", {}).get(name)
        if rule:
            points = rule["font_size_pt"]
            report_fonts({"body_font": rule["font"], "heading_font": rule["font"],
                          "latin_font": rule["font"], "allow_font_fallback": False})
        if name not in document.styles:
            document.styles.add_style(name, WD_STYLE_TYPE.PARAGRAPH)
        style = document.styles[name]
        if name != "Normal":
            style.base_style = document.styles["Normal"]
        heading = name == "Title" or name.startswith("Heading ") or name == "TOC Heading"
        _set_fonts(style.element.get_or_add_rPr(), rule["font"] if rule else fonts["heading_font"] if heading else fonts["body_font"],
                   rule["font"] if rule else fonts["latin_font"])
        style.font.size = Pt(points)
        style.font.bold = heading or name == "Table Header"
        style.font.italic = False
        style.font.color.rgb = RGBColor(0, 0, 0)
        size_cs = style.element.rPr.find(qn("w:szCs"))
        if size_cs is None:
            size_cs = OxmlElement("w:szCs")
            style.element.rPr.append(size_cs)
        size_cs.set(qn("w:val"), str(int(points * 2)))
        fmt = style.paragraph_format
        fmt.line_spacing = 1.3
        fmt.space_before = Pt(0)
        fmt.space_after = Pt(6)
        fmt.widow_control = True
        fmt.keep_with_next = heading or name == "Caption"
        fmt.keep_together = heading or name == "Caption"
        fmt.page_break_before = False
        snap = style.element.get_or_add_pPr().find(qn("w:snapToGrid"))
        if snap is None:
            snap = OxmlElement("w:snapToGrid")
            style.element.pPr.append(snap)
        snap.set(qn("w:val"), "0")
        if heading:
            fmt.space_before, fmt.space_after = Pt(12), Pt(8)
        if name.startswith("TOC ") and name != "TOC Heading":
            fmt.line_spacing, fmt.space_after = 1.15, Pt(2)
            fmt.left_indent = Cm((int(name[-1]) - 1) * .45)
        if name.startswith("Table "):
            fmt.line_spacing, fmt.space_after = 1.15, Pt(3)
            fmt.keep_with_next = name == "Table Header"
        if name == "Cover Metadata":
            fmt.alignment, fmt.space_after = WD_ALIGN_PARAGRAPH.CENTER, Pt(10)
        if name == "Title":
            fmt.alignment = WD_ALIGN_PARAGRAPH.CENTER
            fmt.space_before, fmt.space_after = Pt(54), Pt(28)
            if (presentation or {}).get("cover"):
                fmt.left_indent = fmt.right_indent = Pt(points / 2)
        if style.element.pPr is not None:
            for border in style.element.pPr.findall(qn("w:pBdr")):
                style.element.pPr.remove(border)
    defaults = document.styles.element.find(qn("w:docDefaults"))
    if defaults is None:
        defaults = OxmlElement("w:docDefaults")
        document.styles.element.insert(0, defaults)
    run_defaults = defaults.find(qn("w:rPrDefault"))
    if run_defaults is None:
        run_defaults = OxmlElement("w:rPrDefault")
        defaults.append(run_defaults)
    properties = run_defaults.find(qn("w:rPr"))
    if properties is None:
        properties = OxmlElement("w:rPr")
        run_defaults.append(properties)
    _set_fonts(properties, fonts["body_font"], fonts["latin_font"])
    body = document._element.body
    for child in list(body):
        if child.tag != qn("w:sectPr"):
            body.remove(child)
    section.different_first_page_header_footer = True
    footer = section.footer.paragraphs[0]
    footer.clear()
    footer.style = document.styles["Footer"]
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    field = OxmlElement("w:fldSimple")
    field.set(qn("w:instr"), "PAGE")
    footer._p.append(field)
    document.core_properties.title = title
    document.add_paragraph(title, style="Title")
    for label, value in _cover_items(metadata, presentation):
        document.add_paragraph(f"{label}：{value}", style="Cover Metadata")
    document.add_page_break()
    document.add_paragraph("目录", style="TOC Heading")
    entries = toc_entries if toc_entries is not None else [(level, name, 0) for level, name in _headings(markdown)]
    width = section.page_width - section.left_margin - section.right_margin
    portrait_width = width
    for index, (level, name, page) in enumerate(entries):
        paragraph = document.add_paragraph(style=f"TOC {level}")
        paragraph.paragraph_format.tab_stops.add_tab_stop(width, WD_TAB_ALIGNMENT.RIGHT, WD_TAB_LEADER.DOTS)
        link = OxmlElement("w:hyperlink")
        link.set(qn("w:anchor"), f"report_heading_{index}")
        link.set(qn("w:history"), "1")
        for text in (name, "\t", str(page)):
            run = OxmlElement("w:r")
            item = OxmlElement("w:tab" if text == "\t" else "w:t")
            if text != "\t":
                item.text = text
            run.append(item)
            link.append(run)
        paragraph._p.append(link)
    document.add_page_break()
    first_heading, heading_index = True, 0
    landscape, following_note = False, False
    table_rules, table_index = _table_rules(markdown, outline, presentation), 0
    blocks = [block for block in markdown.strip().split("\n\n") if block.strip()]
    for block_index, block in enumerate(blocks):
        lines = block.splitlines()
        chart = re.fullmatch(r"!\[([^\]]+)\]\((assets/chart_[0-9a-f]{24}\.png)\)", block.strip())
        heading = re.fullmatch(r"(#{1,4}) (.+)", block.strip())
        if landscape:
            if block.startswith(("|", "表")):
                pass
            elif not following_note and not heading and not chart:
                following_note = True
            else:
                section = document.add_section(WD_SECTION_START.NEW_PAGE)
                section.different_first_page_header_footer = False
                width = _page_setup(section)
                landscape = False
        if chart:
            document.add_picture(str(output.parent / chart[2]), width=width)
            document.paragraphs[-1].paragraph_format.keep_with_next = True
            caption = document.add_paragraph(chart[1], style="Caption")
            paragraph = caption
            caption.paragraph_format.keep_with_next = (block_index + 1 < len(blocks)
                                                       and blocks[block_index + 1].startswith("图表数据来源"))
        elif (rows := markdown_table_rows(block)) is not None:
            rule = table_rules[table_index]
            table_index += 1
            if rule and "font" in rule:
                report_fonts({"body_font": rule["font"], "heading_font": rule["font"],
                              "latin_font": rule["font"], "allow_font_fallback": False})
            weights = [min(30, max(10, max(sum(2 if east_asian_width(c) in "WF" else 1 for c in row[col]) for row in rows)))
                       for col in range(len(rows[0]))]
            minimums = [Pt(max((len(row[col]) * 5.2 + 12 for row in rows[1:]
                                if re.fullmatch(r"[+−-]?[0-9][0-9,]*(?:\.[0-9]+)?%?", row[col])), default=24))
                        for col in range(len(rows[0]))]
            # shortcut: minimums assume 10 pt serif digits; remeasure when the table font changes.
            needs_landscape = sum(minimums) > portrait_width
            if needs_landscape != landscape:
                width = _table_section(document, needs_landscape)
                landscape = needs_landscape
            following_note = False
            if sum(minimums) > width:
                raise ValueError("financial table exceeds A4 landscape width; split the source table into appendix panels")
            table = document.add_table(rows=1, cols=len(rows[0]))
            table.style, table.autofit = "Table Grid", False
            indent = OxmlElement("w:tblInd")
            indent.set(qn("w:w"), "108")
            indent.set(qn("w:type"), "dxa")
            table._tbl.tblPr.append(indent)
            borders = OxmlElement("w:tblBorders")
            for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
                border = OxmlElement("w:" + side)
                for key, value in (("val", "single"), ("sz", "4"), ("color", "C8D0D8")):
                    border.set(qn("w:" + key), value)
                borders.append(border)
            table._tbl.tblPr.append(borders)
            widths = [int(width * weight / sum(weights)) for weight in weights]
            deficit = sum(max(0, minimum - current) for minimum, current in zip(minimums, widths))
            surplus = sum(max(0, current - minimum) for minimum, current in zip(minimums, widths))
            if deficit:
                widths = [int(max(current, minimum) - max(0, current - minimum) * deficit / surplus)
                          for current, minimum in zip(widths, minimums)]
            for column, cell_width in zip(table.columns, widths):
                column.width = cell_width
            table.rows[0]._tr.get_or_add_trPr().append(OxmlElement("w:tblHeader"))
            for index, row in enumerate(rows):
                cells = table.rows[0].cells if index == 0 else table.add_row().cells
                for cell, value, cell_width in zip(cells, row, widths):
                    cell.text, cell.width = value, cell_width
                    cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
                    paragraph = cell.paragraphs[0]
                    paragraph.style = document.styles["Table Header" if index == 0 else "Table Body"]
                    if rule and "font" in rule:
                        for run in paragraph.runs:
                            _set_fonts(run._r.get_or_add_rPr(), rule["font"], rule["font"])
                            run.font.size = Pt(rule["font_size_pt"])
                            size_cs = OxmlElement("w:szCs")
                            size_cs.set(qn("w:val"), str(int(rule["font_size_pt"] * 2)))
                            run._r.rPr.append(size_cs)
                    numeric = re.fullmatch(r"[+−-]?(?:[0-9][0-9,]*)(?:\.[0-9]+)?%?", value)
                    paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT if index and numeric else WD_ALIGN_PARAGRAPH.LEFT
                    if index == 0:
                        shade = OxmlElement("w:shd")
                        shade.set(qn("w:fill"), "E9EFF5")
                        cell._tc.get_or_add_tcPr().append(shade)
                table.rows[index]._tr.get_or_add_trPr().append(OxmlElement("w:cantSplit"))
            paragraph = next((p for row in table.rows for cell in row.cells for p in cell.paragraphs if p.text),
                             table.rows[0].cells[0].paragraphs[0])
        elif heading:
            level, name = len(heading[1]), heading[2].strip()
            paragraph = document.add_paragraph(name, style=f"Heading {level}")
            if level <= 3:
                start, end = OxmlElement("w:bookmarkStart"), OxmlElement("w:bookmarkEnd")
                start.set(qn("w:id"), str(heading_index))
                start.set(qn("w:name"), f"report_heading_{heading_index}")
                end.set(qn("w:id"), str(heading_index))
                paragraph._p.insert(1, start)
                paragraph._p.append(end)
                heading_index += 1
            if level == 1:
                paragraph.paragraph_format.page_break_before = not first_heading
                first_heading = False
        elif re.match(r"^表\s*[0-9]+[-－—][0-9]+", block):
            paragraph = document.add_paragraph(block.strip(), style="Caption")
        else:
            paragraph = document.add_paragraph(style="Normal")
            if (block.startswith("图表数据来源") or "〔来源：" in block
                    or block_index + 1 < len(blocks) and blocks[block_index + 1].startswith("# ")):
                paragraph.paragraph_format.keep_together = True
            # shortcut: inline Markdown supports simple bold spans; extend only when report prompts need more syntax.
            for part in re.split(r"(\*\*[^*\n]+\*\*)", block.strip()):
                if part:
                    bold = part.startswith("**") and part.endswith("**")
                    paragraph.add_run(part[2:-2] if bold else part).bold = bold
        for note in annotated[block_index][1]:
            anchor = next((run for run in reversed(paragraph.runs) if run.text), None)
            if anchor is None:
                raise ValueError("comment requires visible report text")
            document.add_comment(anchor, text=note, author="报告审阅", initials="")
    verify_comments(document, annotated)
    output.parent.mkdir(parents=True, exist_ok=True)
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
        if os.environ.get("FONTCONFIG_FILE"):
            ET.SubElement(config, "include").text = str(Path(os.environ["FONTCONFIG_FILE"]).resolve())
        for directory in ("/System/Library/Fonts", "/System/Library/Fonts/Supplemental", "/System/Library/AssetsV2", "/Library/Fonts",
                          "/usr/share/fonts", "/usr/local/share/fonts", str(Path.home() / "Library/Fonts"),
                          str(Path.home() / ".local/share/fonts"), str(Path.home() / ".fonts")):
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
                          metadata: dict | None = None, outline: dict | None = None) -> tuple[Path, list[tuple[int, str, int]]]:
    """Settle visible directory page numbers against the rendered final DOCX."""
    titles = _headings(markdown)
    if not titles:
        raise ValueError("report has no headings for directory")
    entries = [(level, name, 0) for level, name in titles]
    for _ in range(4):
        render_docx(markdown, template, output, title, toc_units, presentation, entries, metadata, outline)
        pdf = _convert_pdf(output)
        pdf_outline = _pdf_outline(pdf)
        cursor, measured = 0, []
        for level, name in titles:
            index = next((i for i in range(cursor, len(pdf_outline))
                          if " ".join(pdf_outline[i][1].split()) == " ".join(name.split())), None)
            if index is None:
                raise ValueError("rendered PDF directory heading missing: " + name)
            measured.append((level, name, pdf_outline[index][2]))
            cursor = index + 1
        if measured == entries:
            return pdf, entries
        entries = measured
    raise ValueError("Word directory page numbers did not converge")


def verify_docx(markdown: str, path: Path, chart_hashes: dict[str, str], *, metadata: dict | None = None,
                toc_entries: list[tuple[int, str, int]] | None = None, pdf: Path | None = None,
                outline: dict | None = None, presentation: dict | None = None) -> dict:
    """Read the delivered Word body back before the revision becomes visible."""
    document = Document(path)
    annotated = annotated_blocks(markdown, presentation)
    verify_comments(document, annotated)
    markdown = "\n\n".join(text for text, _ in annotated)
    for index, section in enumerate(document.sections):
        portrait = abs(section.page_width - Cm(21)) < Cm(.02) and abs(section.page_height - Cm(29.7)) < Cm(.02)
        landscape = abs(section.page_width - Cm(29.7)) < Cm(.02) and abs(section.page_height - Cm(21)) < Cm(.02)
        if not (portrait or index > 0 and landscape):
            raise ValueError("report page size must be A4, with a portrait cover")
        if section.orientation != (WD_ORIENT.PORTRAIT if portrait else WD_ORIENT.LANDSCAPE):
            raise ValueError("report page orientation conflicts with paper dimensions")
        if any(abs(actual - expected) > Cm(.02) for actual, expected in (
                (section.left_margin, Cm(2.3)), (section.right_margin, Cm(2.3)),
                (section.top_margin, Cm(2.15)), (section.bottom_margin, Cm(2.0)))):
            raise ValueError("report page margins differ from the report layout")
    widths = _block_widths(document)
    titles = [paragraph.text for paragraph in document.paragraphs if paragraph.style.name == "Title"]
    if titles != [document.core_properties.title]:
        raise ValueError("report cover title is missing, duplicated or inconsistent")
    headings = [block.lstrip("#").strip() for block in (item.strip() for item in markdown.strip().split("\n\n"))
                if re.match(r"^#{1,4} ", block)]
    rendered_headings = [paragraph.text for paragraph in document.paragraphs
                         if re.fullmatch(r"Heading [1-4]", paragraph.style.name)]
    if headings != rendered_headings:
        raise ValueError("rendered Word headings differ from reviewed Markdown")
    if document.core_properties.title in rendered_headings:
        raise ValueError("report body repeats the cover title")
    if document.styles["Normal"].paragraph_format.line_spacing != 1.3:
        raise ValueError("report body line spacing must be 1.3")
    heading_seen = False
    for paragraph in document.paragraphs:
        if re.fullmatch(r"Heading [1-4]", paragraph.style.name):
            if not all(_effective(paragraph, key) for key in ("keep_with_next", "keep_together", "widow_control")):
                raise ValueError("report heading pagination binding is invalid")
            if paragraph.style.name == "Heading 1":
                if heading_seen and not _effective(paragraph, "page_break_before"):
                    raise ValueError("report main chapter must begin on a new page")
                heading_seen = True
        if paragraph.style.name == "Normal" and paragraph.text:
            if _effective(paragraph, "line_spacing") != 1.3 or not _effective(paragraph, "widow_control"):
                raise ValueError("report body paragraph spacing or widow control is invalid")
    for name, points in STYLE_SIZES.items():
        rule = (presentation or {}).get("styles", {}).get(name)
        if rule:
            points = rule["font_size_pt"]
        if name not in document.styles or document.styles[name].font.size != Pt(points):
            raise ValueError("report style size is invalid: " + name)
        fonts = document.styles[name].element.rPr.rFonts
        if fonts is None or any(not fonts.get(qn("w:" + key)) for key in ("eastAsia", "ascii", "hAnsi")):
            raise ValueError("report style font is incomplete: " + name)
        if rule:
            size_cs = document.styles[name].element.rPr.find(qn("w:szCs"))
            if (any(fonts.get(qn("w:" + key)) != rule["font"] for key in ("eastAsia", "ascii", "hAnsi", "cs"))
                    or size_cs is None or size_cs.get(qn("w:val")) != str(int(points * 2))):
                raise ValueError("report style typography differs from presentation: " + name)
    for paragraph in document.paragraphs:
        rule = (presentation or {}).get("styles", {}).get(paragraph.style.name)
        if rule:
            for run in paragraph.runs:
                if not run.text:
                    continue
                properties = run._r.rPr
                fonts = properties.rFonts if properties is not None else None
                size_cs = properties.find(qn("w:szCs")) if properties is not None else None
                if ((run.font.size is not None and run.font.size != Pt(rule["font_size_pt"]))
                        or fonts is not None and any(fonts.get(qn("w:" + key)) not in (None, rule["font"])
                                                    for key in ("eastAsia", "ascii", "hAnsi", "cs"))
                        or size_cs is not None and size_cs.get(qn("w:val")) != str(int(rule["font_size_pt"] * 2))):
                    raise ValueError("paragraph typography overrides its document style")
    if metadata is not None:
        _validate_cover(document.core_properties.title, metadata, presentation)
        cover_text = [paragraph.text for paragraph in document.paragraphs if paragraph.style.name == "Cover Metadata"]
        if cover_text != [f"{key}：{value}" for key, value in _cover_items(metadata, presentation)]:
            raise ValueError("report cover differs from verified metadata")
    directory = [paragraph for paragraph in document.paragraphs if re.fullmatch(r"TOC [1-3]", paragraph.style.name)]
    if [p.text for p in document.paragraphs if p.style.name == "TOC Heading"] != ["目录"]:
        raise ValueError("report directory must have one Chinese title")
    expected = toc_entries if toc_entries is not None else [(level, name, 0) for level, name in _headings(markdown)]
    if not expected or [p.text for p in directory] != [f"{name}\t{page}" for _, name, page in expected]:
        raise ValueError("report directory differs from report headings or measured pages")
    if [(level, name) for level, name, _ in expected] != _headings(markdown):
        raise ValueError("report directory contains missing, stale or reordered headings")
    if [p.style.name for p in directory] != [f"TOC {level}" for level, _, _ in expected]:
        raise ValueError("report directory levels differ from heading styles")
    anchors = document.element.xpath('//w:hyperlink/@w:anchor')
    if anchors != [f"report_heading_{index}" for index in range(len(expected))]:
        raise ValueError("report directory links are incomplete")
    if not set(anchors) <= set(document.element.xpath('//w:bookmarkStart/@w:name')):
        raise ValueError("report directory link targets are missing")
    table_blocks = []
    for block in markdown.strip().split("\n\n"):
        if (rows := markdown_table_rows(block)) is not None:
            table_blocks.append(rows)
    rendered_tables = [[[cell.text for cell in row.cells] for row in table.rows] for table in document.tables]
    if table_blocks != rendered_tables:
        raise ValueError("rendered Word tables differ from reviewed Markdown")
    for table, rule in zip(document.tables, _table_rules(markdown, outline, presentation)):
        width = widths[table._tbl]
        if sum(column.width for column in table.columns) > width + Cm(.02):
            raise ValueError("report table exceeds page width")
        if table.rows[0]._tr.get_or_add_trPr().find(qn("w:tblHeader")) is None:
            raise ValueError("report table has no repeating header")
        for index, row in enumerate(table.rows):
            if row._tr.get_or_add_trPr().find(qn("w:cantSplit")) is None:
                raise ValueError("report table record can split across pages")
            for cell in row.cells:
                paragraph = cell.paragraphs[0]
                if paragraph.style.name != ("Table Header" if index == 0 else "Table Body"):
                    raise ValueError("report table text has no dedicated style")
                if rule and "font" in rule:
                    for run in paragraph.runs:
                        if not run.text:
                            continue
                        properties = run._r.rPr
                        fonts = properties.rFonts if properties is not None else None
                        size_cs = properties.find(qn("w:szCs")) if properties is not None else None
                        if (run.font.size != Pt(rule["font_size_pt"]) or fonts is None
                                or any(fonts.get(qn("w:" + key)) != rule["font"] for key in ("eastAsia", "ascii", "hAnsi", "cs"))
                                or size_cs is None or size_cs.get(qn("w:val")) != str(int(rule["font_size_pt"] * 2))):
                            raise ValueError("required table font or size differs from scenario configuration")
                if index and re.fullmatch(r"[+−-]?[0-9][0-9,]*(?:\.[0-9]+)?%?", cell.text) and paragraph.alignment != WD_ALIGN_PARAGRAPH.RIGHT:
                    raise ValueError("report table amount is not right aligned")
    if any(shape.width > widths[shape._inline.xpath('ancestor::w:p')[0]] for shape in document.inline_shapes):
        raise ValueError("report chart exceeds page width")
    if pdf is not None:
        outline = _pdf_outline(pdf)
        measured, cursor = [], 0
        for level, name in _headings(markdown):
            index = next((i for i in range(cursor, len(outline)) if " ".join(outline[i][1].split()) == " ".join(name.split())), None)
            if index is None:
                raise ValueError("PDF directory heading is missing: " + name)
            measured.append((level, name, outline[index][2]))
            cursor = index + 1
        if measured != expected or any(page < 3 for _, _, page in measured):
            raise ValueError("report directory page numbers differ from final PDF")
        reader = PdfReader(pdf)
        text = re.sub(r"\s+", "", reader.pages[0].extract_text() or "")
        if metadata and any(re.sub(r"\s+", "", f"{key}：{value}") not in text for key, value in _cover_items(metadata, presentation)):
            raise ValueError("report cover is incomplete or exceeds one PDF page")
        if "目录" not in re.sub(r"\s+", "", reader.pages[1].extract_text() or ""):
            raise ValueError("report directory does not begin on page two")
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
            "styles_valid": True, "cover_valid": metadata is not None, "directory_links_valid": True,
            "directory_pages_verified": pdf is not None, "table_layout_valid": True,
            "toc_mode": "static-measured", "toc_fallback_reason": "当前转换入口不提供可靠的Word目录字段更新；采用最终PDF实测页码迭代收敛及内部跳转。",
            "resolved_fonts": {"body_font": document.styles["Normal"].element.rPr.rFonts.get(qn("w:eastAsia")),
                               "heading_font": document.styles["Heading 1"].element.rPr.rFonts.get(qn("w:eastAsia")),
                               "latin_font": document.styles["Normal"].element.rPr.rFonts.get(qn("w:ascii"))},
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
