"""Report typography belongs to document styles, not chapter-local font settings."""

import copy
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml
from docx import Document
from docx.oxml.ns import qn
from docx.shared import Pt

from long_report.rendering import render_docx, verify_docx
from long_report.scenario import ScenarioError, load_scenario

SOURCE = Path(__file__).resolve().parents[1] / "scenarios"
STYLES = {name: dict(font="仿宋", font_size_pt=size)
          for name, size in (("Title", 26), ("Heading 1", 15), ("Heading 2", 14), ("Normal", 14))}
TABLE_STYLES = {"compact": dict(font="仿宋", font_size_pt=10.5)}
MARKDOWN = "# 第一章 公司基本情况\n\n## 一、工商信息\n\n正文内容。\n\n# 第二章 公司运营情况\n\n## 一、主营业务情况\n\n其他章节正文。"


class ScenarioTypographyTests(unittest.TestCase):
    def test_financial_report_uses_one_profile_for_all_chapters(self):
        scenario = load_scenario("financial_due_diligence")
        self.assertEqual(scenario.manifest["presentation"].get("styles"), STYLES)
        self.assertEqual(scenario.manifest["presentation"].get("table_styles"), TABLE_STYLES)
        for section in scenario.outline["sections"]:
            for table in section.get("required_tables", []):
                self.assertNotIn("font", table)
                self.assertNotIn("font_size_pt", table)
        self.assertEqual(scenario.outline["sections"][0]["required_tables"][0].get("style"), "compact")

    def test_docx_styles_and_every_chapter_use_the_requested_fonts_and_sizes(self):
        scenario = load_scenario("financial_due_diligence")
        presentation = {**scenario.manifest["presentation"], "styles": STYLES, "table_styles": TABLE_STYLES}
        template = SOURCE / "financial_due_diligence" / scenario.manifest["template"]
        with tempfile.TemporaryDirectory() as temporary, patch("long_report.rendering._installed_fonts", return_value={"仿宋"}):
            output = Path(temporary) / "typography.docx"
            render_docx(MARKDOWN, template, output, "统一样式验证", presentation=presentation)
            document = Document(output)
            for name, rule in STYLES.items():
                style = document.styles[name]
                self.assertEqual(style.font.size, Pt(rule["font_size_pt"]))
                for key in ("eastAsia", "ascii", "hAnsi", "cs"):
                    self.assertEqual(style.element.rPr.rFonts.get(qn("w:" + key)), "仿宋")
                self.assertEqual(style.element.rPr.find(qn("w:szCs")).get(qn("w:val")), str(rule["font_size_pt"] * 2))
            self.assertEqual([p.style.font.size for p in document.paragraphs if p.style.name == "Heading 1"], [Pt(15), Pt(15)])
            verify_docx(MARKDOWN, output, {}, presentation=presentation)
            heading = next(p for p in document.paragraphs if p.style.name == "Heading 1")
            heading.runs[0].font.size = Pt(16)
            document.save(output)
            with self.assertRaisesRegex(ValueError, "style|typography"):
                verify_docx(MARKDOWN, output, {}, presentation=presentation)

    def test_table_style_reference_resolves_to_the_scenario_profile(self):
        scenario = load_scenario("financial_due_diligence")
        presentation = {**scenario.manifest["presentation"], "styles": STYLES, "table_styles": TABLE_STYLES}
        template = SOURCE / "financial_due_diligence" / scenario.manifest["template"]
        table = dict(subheading="一、工商信息", columns=["项目", "内容"], required_fields=["企业名称"], style="compact")
        outline = dict(sections=[dict(title="第一章 公司基本情况", required_tables=[table])])
        markdown = "# 第一章 公司基本情况\n\n## 一、工商信息\n\n| 项目 | 内容 |\n| --- | --- |\n| 企业名称 | 未提供 |"
        with tempfile.TemporaryDirectory() as temporary, patch("long_report.rendering._installed_fonts", return_value={"仿宋"}):
            output = Path(temporary) / "table.docx"
            render_docx(markdown, template, output, "表格样式验证", presentation=presentation, outline=outline)
            self.assertEqual(Document(output).tables[0].cell(1, 0).paragraphs[0].runs[0].font.size, Pt(10.5))
            verify_docx(markdown, output, {}, presentation=presentation, outline=outline)

    def test_invalid_style_definitions_and_dangling_table_styles_are_rejected(self):
        mutations = [lambda p: p.update(styles={"Typo": dict(font="仿宋", font_size_pt=14)}),
                     lambda p: p["styles"]["Normal"].update(font_size_pt=True),
                     lambda p: p["styles"]["Normal"].update(font_size_pt=0),
                     lambda p: p["styles"]["Normal"].pop("font"),
                     lambda p: p.update(table_styles={})]
        for mutate in mutations:
            with self.subTest(mutate=mutate), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                shutil.copytree(SOURCE / "financial_due_diligence", root / "financial_due_diligence")
                path = root / "financial_due_diligence/scenario.yaml"
                data = yaml.safe_load(path.read_text(encoding="utf-8"))
                data["presentation"].update(styles=copy.deepcopy(STYLES), table_styles=copy.deepcopy(TABLE_STYLES))
                mutate(data["presentation"])
                path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
                with self.assertRaisesRegex(ScenarioError, "style"):
                    load_scenario("financial_due_diligence", root)

    def test_chapter_local_font_values_are_rejected(self):
        for location in ("chapter", "table"):
            with self.subTest(location=location), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                shutil.copytree(SOURCE / "financial_due_diligence", root / "financial_due_diligence")
                path = root / "financial_due_diligence/outline.yaml"
                data = yaml.safe_load(path.read_text(encoding="utf-8"))
                section = data["sections"][0]
                target = section if location == "chapter" else section["required_tables"][0]
                target.update(font="仿宋", font_size_pt=10.5)
                path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
                with self.assertRaisesRegex(ScenarioError, "required table|style|presentation"):
                    load_scenario("financial_due_diligence", root)


if __name__ == "__main__":
    unittest.main()
