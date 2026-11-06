"""Equity ownership is a scoped shareholder table, followed by sourced biographies."""

import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from docx import Document
from docx.shared import Pt

from long_report.rendering import render_docx, verify_docx
from long_report.scenario import ScenarioError, load_scenario, validate_section_headings, validate_report_outline, markdown_table_rows

PARENT = "四、股权、股东及投资情况"
CHILDREN = ["（一）股权架构", "（二）股东简介、持股情况"]
SUBSECTIONS = [dict(title=CHILDREN[0], content="table"), dict(title=CHILDREN[1], content="narrative")]
COLUMNS = ["排名", "股东名称", "认缴资本（万元）", "持股比例（%）"]
RULE = dict(subheading=PARENT, child_heading=CHILDREN[0], columns=COLUMNS,
            total_row=dict(label_column="股东名称", label="合计", blank_columns=["排名"],
                           sum_columns=["认缴资本（万元）", "持股比例（%）"]))
TABLE = "| 排名 | 股东名称 | 认缴资本（万元） | 持股比例（%） |\n| --- | --- | ---: | ---: |\n| 1 | 甲股东 | 32,650.41 | 51.00 |\n| 2 | 乙股东 | 31,370.00 | 49.00 |\n|  | 合    计 | 64,020.41 | 100.00 |"


def equity_body(table=TABLE):
    return ("## " + PARENT + "\n\n### " + CHILDREN[0] + "\n\n" + table
            + "\n\n### " + CHILDREN[1] + "\n\n1、甲股东的身份、持股及简介以本轮材料为准。\n\n2、乙股东的身份、持股及简介以本轮材料为准。")


def equity_section():
    return dict(title="第一章 公司基本情况", subheadings=[PARENT],
                required_subsections={PARENT: SUBSECTIONS}, required_tables=[RULE])


class EquityTableTests(unittest.TestCase):
    def test_numeric_reference_precision_does_not_create_extra_table_columns(self):
        source = TABLE.replace("32,650.41", "{{fact:capital_a|2}}")
        source = source.replace("31,370.00", "{{fact:capital_b|2}}")
        source = source.replace("64,020.41", "{{calc:capital_total|2}}")
        validate_section_headings(equity_body(source), equity_section())
        rows = markdown_table_rows(source)
        self.assertEqual(rows[1][2], "{{fact:capital_a|2}}")
        self.assertEqual(rows[-1], ["", "合    计", "{{calc:capital_total|2}}", "100.00"])
        ordinary = "| 项目 | 内容 |\n| --- | --- |\n| 1 | 2}} |"
        self.assertEqual(markdown_table_rows(ordinary)[1], ["1", "2}}"])

    def test_config_declares_scoped_four_columns_total_and_biographies_without_prefilling_facts(self):
        section = load_scenario("financial_due_diligence").outline["sections"][0]
        self.assertEqual(section.get("required_subsections", {}).get(PARENT), SUBSECTIONS)
        self.assertIn(RULE, section["required_tables"])
        self.assertNotIn("江西铜业股份有限公司", str(section))

    def test_shareholder_guidance_keeps_the_table_only_and_requires_sourced_biographies(self):
        guidance = "\n".join(load_scenario("financial_due_diligence").analysis["writing_guidance"]["company"])
        for requirement in ("股权架构只输出排名、股东名称、认缴资本（万元）、持股比例（%）四列表格",
                            "不在表后添加正文", "识别控股股东", "不把控股股东自动写成实际控制人",
                            "公司全称、简称、成立时间、主营产品及可核实的行业地位",
                            "不移植参考样例中的公司事实或评价"):
            with self.subTest(requirement=requirement):
                self.assertIn(requirement, guidance)

    def test_table_must_be_in_equity_child_section_and_have_a_final_total_row(self):
        section = equity_section()
        validate_section_headings(equity_body(), section)
        invalid = [equity_body() + "\n### 额外三级标题\n额外文字。",
                   equity_body().split("### " + CHILDREN[1], 1)[0] + "### " + CHILDREN[1] + "\n\n" + TABLE,
                   equity_body().replace("### " + CHILDREN[0], "### 其他"),
                   equity_body().replace("### " + CHILDREN[1], "### 其他"),
                   equity_body().replace(TABLE, "股权资料待补。") + "\n\n" + TABLE,
                   equity_body("\n".join(TABLE.splitlines()[:-1])),
                   equity_body(TABLE + "\n| 3 | 丙股东 | 1.00 | 1.00 |"),
                   equity_body(TABLE.replace("| 2 | 乙股东 |", "| 2 | 甲股东 |")),
                   equity_body(TABLE.replace("| 2 | 乙股东 |", "| 2 |  |"))]
        for body in invalid:
            with self.subTest(body=body), self.assertRaisesRegex(ScenarioError, "subsection|required table|table field|total row"):
                validate_section_headings(body, section)

    def test_numeric_totals_are_checked_and_missing_values_are_not_invented(self):
        section = equity_section()
        for table in (TABLE.replace("64,020.41", "64,020.42"), TABLE.replace("100.00", "99.00"),
                      TABLE.replace("32,650.41", "未提供").replace("31,370.00", "NaN")):
            with self.subTest(table=table), self.assertRaisesRegex(ScenarioError, "table total"):
                validate_section_headings(equity_body(table), section)
        unknown = "| " + " | ".join(COLUMNS) + " |\n| --- | --- | --- | --- |\n| 待核实 | 未提供 | 未提供 | 未提供 |\n|  | 合计 | 未提供 | 未提供 |"
        validate_section_headings(equity_body(unknown), section)

    def test_per_run_plan_cannot_remove_biography_heading_or_total_requirement(self):
        scenario = load_scenario("financial_due_diligence")
        original = dict(sections=scenario.outline["sections"])
        for field in ("required_tables", "required_subsections"):
            proposed = copy.deepcopy(original)
            proposed["sections"][0].pop(field, None)
            with self.subTest(field=field), self.assertRaisesRegex(ScenarioError, "fixed|invalid required"):
                validate_report_outline(proposed, scenario.analysis, {}, fixed_outline=scenario.outline)

    def test_word_preserves_the_four_columns_total_and_third_level_headings(self):
        scenario = load_scenario("financial_due_diligence")
        markdown = "# 第一章 公司基本情况\n\n" + equity_body()
        outline = dict(sections=[equity_section()])
        with tempfile.TemporaryDirectory() as temporary, patch("long_report.rendering._installed_fonts", return_value={"仿宋"}):
            output = Path(temporary) / "equity.docx"
            template = Path(__file__).resolve().parents[1] / "scenarios/financial_due_diligence" / scenario.manifest["template"]
            render_docx(markdown, template, output, "合成测试", presentation=scenario.manifest["presentation"], outline=outline)
            document = Document(output)
            self.assertEqual([cell.text for cell in document.tables[0].rows[0].cells], COLUMNS)
            self.assertEqual([cell.text for cell in document.tables[0].rows[-1].cells], ["", "合    计", "64,020.41", "100.00"])
            self.assertEqual([p.text for p in document.paragraphs if p.style.name == "Heading 3"], CHILDREN)
            self.assertEqual(document.tables[0].cell(1, 0).paragraphs[0].style.font.size, Pt(10))
            verify_docx(markdown, output, {}, outline=outline, presentation=scenario.manifest["presentation"])


if __name__ == "__main__":
    unittest.main()
