"""Business registration stays a complete table with its own five-size font."""

import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from docx import Document
from docx.oxml.ns import qn
from docx.shared import Pt

from long_report.rendering import render_docx, render_paginated_docx, verify_docx
from long_report.scenario import ScenarioError, load_scenario, validate_section_headings, validate_report_outline

FIELDS = ["企业名称", "统一社会信用代码", "法人代表", "成立日期", "有效期", "注册资本", "实收资本", "注册地址", "经营范围"]
RULE = dict(subheading="一、工商信息", columns=["项目", "内容"], required_fields=FIELDS,
            style="compact")


def registration_body(fields=FIELDS):
    return "## 一、工商信息\n\n| 项目 | 内容 |\n| --- | --- |\n" + "\n".join(
        "| " + field + " | 未提供（待核实） |" for field in fields)


class RegistrationTableTests(unittest.TestCase):
    def test_scenario_contains_the_nine_required_fields_and_five_size_font(self):
        section = load_scenario("financial_due_diligence").outline["sections"][0]
        self.assertEqual(section["required_tables"][0], RULE)

    def test_registration_guidance_requires_full_license_table_without_routine_prose(self):
        guidance = "\n".join(load_scenario("financial_due_diligence").analysis["writing_guidance"]["company"])
        for requirement in ("以本轮提供的营业执照为主", "经营范围按执照全文列示",
                            "实收资本无可靠依据时不照抄第三方登记快照", "表后不写文字说明",
                            "仅在内容单元格备注或紧邻表格的锚定批注提示"):
            with self.subTest(requirement=requirement):
                self.assertIn(requirement, guidance)

    def test_registration_requires_one_complete_nonempty_table_in_its_own_subsection(self):
        section = dict(subheadings=["一、工商信息", "二、背景情况"], required_tables=[RULE])
        suffix = "\n\n## 二、背景情况\n\n资料待补。"
        validate_section_headings(registration_body() + suffix, section)
        invalid = ["## 一、工商信息\n\n工商资料待补。" + suffix,
                   registration_body(FIELDS[:-1]) + suffix,
                   registration_body().replace("| 经营范围 | 未提供（待核实） |", "| 经营范围 |  |") + suffix,
                   registration_body(FIELDS + [FIELDS[0]]) + suffix,
                   "## 一、工商信息\n\n资料待补。" + suffix + "\n\n" + registration_body().split("\n\n", 1)[1]]
        for body in invalid:
            with self.subTest(body=body), self.assertRaisesRegex(ScenarioError, "required table|table field"):
                validate_section_headings(body, section)

    def test_per_run_plan_cannot_remove_or_change_the_required_table(self):
        scenario = load_scenario("financial_due_diligence")
        original = dict(sections=scenario.outline["sections"])
        for rules in ([], [{**RULE, "style": "other"}], [{**RULE, "required_fields": FIELDS[:-1]}]):
            proposed = copy.deepcopy(original)
            proposed["sections"][0]["required_tables"] = rules
            with self.subTest(rules=rules), self.assertRaisesRegex(ScenarioError, "fixed"):
                validate_report_outline(proposed, scenario.analysis, {}, fixed_outline=scenario.outline)

    def test_table_rule_survives_the_second_pagination_pass(self):
        scenario = load_scenario("financial_due_diligence")
        section = dict(title="第一章 公司基本情况", required_tables=[RULE])
        outline = dict(sections=[section])
        markdown = "# 第一章 公司基本情况\n\n" + registration_body()
        with tempfile.TemporaryDirectory() as temporary, patch("long_report.rendering._installed_fonts", return_value={"仿宋"}):
            output = Path(temporary) / "registration.docx"
            template = Path(__file__).resolve().parents[1] / "scenarios/financial_due_diligence" / scenario.manifest["template"]
            with patch("long_report.rendering._convert_pdf", return_value=output.with_suffix(".pdf")), patch(
                    "long_report.rendering._pdf_outline", return_value=[(1, section["title"], 3), (2, "一、工商信息", 3)]):
                _, entries = render_paginated_docx(markdown, template, output, "合成测试",
                    presentation=scenario.manifest["presentation"], outline=outline)
            self.assertEqual([entry[2] for entry in entries], [3, 3])
            self.assertEqual(Document(output).tables[0].cell(1, 0).paragraphs[0].runs[0].font.size, Pt(10.5))

    def test_word_cells_use_fangsong_10_5_points_without_changing_other_tables(self):
        scenario = load_scenario("financial_due_diligence")
        section = dict(id="company", title="第一章 公司基本情况", subheadings=["一、工商信息"], required_tables=[RULE])
        outline = dict(sections=[section])
        markdown = "# 第一章 公司基本情况\n\n" + registration_body() + "\n\n# 第二章 公司运营情况\n\n| 项目 | 内容 |\n| --- | --- |\n| 其他 | 待核实 |"
        with tempfile.TemporaryDirectory() as temporary, patch("long_report.rendering._installed_fonts", return_value={"仿宋"}):
            output = Path(temporary) / "registration.docx"
            template = Path(__file__).resolve().parents[1] / "scenarios/financial_due_diligence" / scenario.manifest["template"]
            render_docx(markdown, template, output, "合成测试", presentation=scenario.manifest["presentation"], outline=outline)
            document = Document(output)
            self.assertEqual(len(document.tables), 2)
            for row in document.tables[0].rows:
                for cell in row.cells:
                    for run in cell.paragraphs[0].runs:
                        self.assertEqual(run.font.size, Pt(10.5))
                        self.assertEqual(run._r.rPr.rFonts.get(qn("w:eastAsia")), "仿宋")
                        self.assertEqual(run._r.rPr.rFonts.get(qn("w:ascii")), "仿宋")
                        self.assertEqual(run._r.rPr.find(qn("w:szCs")).get(qn("w:val")), "21")
            self.assertEqual(document.tables[1].cell(1, 0).paragraphs[0].style.font.size, Pt(10))
            verify_docx(markdown, output, {}, outline=outline, presentation=scenario.manifest["presentation"])
            document.tables[0].cell(1, 0).paragraphs[0].runs[0].font.size = Pt(10)
            document.save(output)
            with self.assertRaisesRegex(ValueError, "required table.*font"):
                verify_docx(markdown, output, {}, outline=outline, presentation=scenario.manifest["presentation"])


if __name__ == "__main__":
    unittest.main()
