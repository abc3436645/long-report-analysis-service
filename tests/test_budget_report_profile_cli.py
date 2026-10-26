"""Board reports use the budget scenario's own scope and chapter contract."""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
import yaml


REPORT = Path(sys.executable).with_name("report")


class BudgetReportProfileCliTests(unittest.TestCase):
    def test_layout_gate_rejects_wrong_page_and_heading_or_body_properties(self):
        from unittest.mock import patch
        from docx import Document
        from docx.shared import Cm
        from long_report.rendering import render_docx, verify_docx

        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "gate.docx"
            template = Path(__file__).resolve().parents[1] / "scenarios/budget_operations/templates/default-v0.2.0.docx"
            markdown = "# 第一章 摘要\n\n正文。"
            render_docx(markdown, template, target, "预算报告")
            mutations = (lambda d: setattr(d.sections[0], "page_width", Cm(35)),
                         lambda d: setattr(d.styles["Heading 1"].paragraph_format, "keep_with_next", False),
                         lambda d: setattr(d.styles["Normal"].paragraph_format, "line_spacing", .5))
            for mutate in mutations:
                document = Document(target)
                mutate(document)
                with patch("long_report.rendering.Document", return_value=document), self.assertRaises(ValueError):
                    verify_docx(markdown, target, {})

    def test_consecutive_wide_tables_share_local_orientation_without_empty_sections(self):
        from docx import Document
        from long_report.rendering import render_docx, verify_docx

        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "consecutive.docx"
            template = Path(__file__).resolve().parents[1] / "scenarios/budget_operations/templates/default-v0.2.0.docx"
            wide = "| " + " | ".join(["项目"] + ["金额"] * 9) + " |\n| " + " | ".join(["---"] * 10) + " |\n| 甲 | " + " | ".join(["19698.31"] * 9) + " |"
            markdown = ("# 第一章 财务\n\n表1-1 宽表\n\n" + wide + "\n\n表1-2 另一宽表\n\n" + wide
                        + "\n\n表1-3 小表\n\n| 项目 | 金额 |\n| --- | --- |\n| 甲 | 100 |")
            render_docx(markdown, template, target, "财务报告")
            document = Document(target)
            self.assertEqual([s.page_width > s.page_height for s in document.sections], [False, True, False])
            self.assertEqual(len(document.tables), 3)
            self.assertTrue(verify_docx(markdown, target, {})["table_layout_valid"])

    @unittest.skipUnless(shutil.which("soffice"), "PDF layout tools are required")
    def test_wide_table_gets_a_local_landscape_page_and_returns_to_portrait(self):
        from docx import Document
        from pypdf import PdfReader
        from long_report.rendering import render_paginated_docx, verify_docx

        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "landscape.docx"
            template = Path(__file__).resolve().parents[1] / "scenarios/budget_operations/templates/default-v0.2.0.docx"
            headers = ["指标"] + [f"金额{i}（万元）" for i in range(1, 10)]
            values = ["经营指标"] + ["19698.31"] * 9
            markdown = ("# 第一章 财务附表\n\n表1-1 宽表\n\n| " + " | ".join(headers) + " |\n| "
                        + " | ".join(["---"] * 10) + " |\n| " + " | ".join(values)
                        + " |\n\n来源：合成测试。\n\n# 第二章 后续分析\n\n后续正文。")
            pdf, entries = render_paginated_docx(markdown, template, target, "宽表报告")
            document = Document(target)
            self.assertEqual([s.page_width > s.page_height for s in document.sections], [False, True, False])
            pages = PdfReader(pdf).pages
            self.assertEqual(len(pages), 4, "local landscape must not leave an empty portrait page")
            self.assertGreater(float(pages[2].mediabox.width), float(pages[2].mediabox.height))
            self.assertIn("表1-1", (pages[2].extract_text() or "").replace(" ", ""))
            self.assertIn("来源", pages[2].extract_text())
            self.assertTrue(verify_docx(markdown, target, {}, toc_entries=entries, pdf=pdf)["table_layout_valid"])

    def test_shared_budget_numbering_is_idempotent_and_preserves_unit_identifiers(self):
        from long_report.application import _number_budget_headings

        markdown = "# 资料范围\n\n正文。\n\n# 第二章 单位分析\n\n## 甲矿\n\n### 经营综述\n\n## 02 乙矿\n\n#### 专项口径\n"
        numbered = _number_budget_headings(markdown)
        self.assertIn("# 第一章 资料范围", numbered)
        self.assertIn("## 2.1 甲矿\n\n### 2.1.1 经营综述", numbered)
        self.assertIn("## 02 乙矿", numbered)
        self.assertIn("#### 专项口径", numbered)
        self.assertEqual(_number_budget_headings(numbered), numbered)
        retained = _number_budget_headings("# 第十二章 专项\n\n## 12.7 甲矿\n\n### 成本\n\n# 附录 材料索引\n")
        self.assertIn("### 12.7.1 成本", retained)
        self.assertIn("# 附录 材料索引", retained)
        direct_topics = _number_budget_headings("# 专项\n\n### 铜精矿\n\n### 硫精矿\n")
        self.assertIn("## 1.1 铜精矿\n\n## 1.2 硫精矿", direct_topics)
        nested_unit = _number_budget_headings("# 单位\n\n### 贵冶\n", ["贵冶"])
        self.assertIn("### 1.1.1 贵冶", nested_unit)

    @unittest.skipUnless(shutil.which("soffice") and shutil.which("pdftotext"), "PDF layout tools are required")
    def test_wide_financial_table_does_not_break_a_number_between_lines(self):
        import xml.etree.ElementTree as ET
        from long_report.rendering import render_paginated_docx

        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "wide.docx"
            template = Path(__file__).resolve().parents[1] / "scenarios/budget_operations/templates/default-v0.2.0.docx"
            markdown = ("# 第一章 专项\n\n表1-1 产销比较\n\n"
                        "| 单位及产品 | 本年产量 | 本年销量 | 销量同比 | 原表量差影响（万元） | 原表价差影响（万元） |\n"
                        "| --- | ---: | ---: | ---: | ---: | ---: |\n"
                        "| 德兴铜矿（含新技术）含银（公斤） | 19698.31 | 19405.62 | 2.07% | 214.19 | 2114.85 |")
            pdf, _ = render_paginated_docx(markdown, template, target, "专项报告")
            result = subprocess.run(["pdftotext", "-bbox", str(pdf), "-"], capture_output=True, text=True, check=True)
            words = [item.text for item in ET.fromstring(result.stdout).findall(".//{*}word")]
            self.assertIn("19698.31", words, "production quantity must remain readable as one complete number")
            self.assertIn("19405.62", words)

    def test_long_chart_title_and_labels_get_space_instead_of_clipping(self):
        from PIL import Image
        from long_report.charts import draw_comparison

        with tempfile.TemporaryDirectory() as temporary:
            short, long = Path(temporary) / "short.png", Path(temporary) / "long.png"
            points = [{"label": "本年实际", "value": "100"}, {"label": "上年同期", "value": "90"}]
            draw_comparison(short, "图1-1 利润比较", points, "万元", "2026年1—7月", "合成测试", [])
            draw_comparison(long, "图1-1 " + "长中文经营分析标题" * 10,
                            [{**item, "label": "较长的中文可比期间与经营口径说明" * 2} for item in points],
                            "万元", "2026年1—7月", "合成测试", [])
            with Image.open(short) as a, Image.open(long) as b:
                self.assertEqual(a.width, b.width)
                self.assertGreater(b.height, a.height + 100)

    def test_missing_chinese_fonts_fail_or_use_verified_installed_cjk_fallback(self):
        from unittest.mock import patch
        from long_report.rendering import report_fonts

        with patch("long_report.rendering._installed_fonts", return_value={"noto serif cjk sc", "noto sans cjk sc", "liberation serif"}):
            self.assertEqual(report_fonts(), {"body_font": "Noto Serif CJK SC", "heading_font": "Noto Sans CJK SC", "latin_font": "Liberation Serif"})
        with patch("long_report.rendering._installed_fonts", return_value={"times new roman"}):
            with self.assertRaisesRegex(ValueError, "font unavailable"):
                report_fonts()

    def test_conflicting_cover_period_cannot_reach_rendering(self):
        from long_report.rendering import render_docx

        cover = {key: "已核实" for key in ("分析对象", "编制部门", "数据性质", "数据版本", "保密说明")}
        cover.update({"统计期间": "2026年7月", "报告生成日期": "2026-10-26", "报告版本": "V1.0"})
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "invalid.docx"
            with self.assertRaisesRegex(ValueError, "period conflicts"):
                render_docx("# 第一章 摘要\n\n正文。", Path("unused.docx"), target,
                            "矿山报告（2026年1—7月）", metadata=cover)
            self.assertFalse(target.exists())

    def test_cover_uses_evidence_windows_and_readable_revision_not_upload_date(self):
        from datetime import date
        from long_report.application import _cover_metadata

        project = {"scenario_id": "budget_operations", "report_period": "2026-07",
                   "subject_scope": {"organization": "江铜集团", "units": ["甲矿"]},
                   "report_metadata": {"analysis_subject": "江铜集团矿山板块", "prepared_by": "预算办"}}
        run = {"evidence_snapshot_id": "snapshot-123"}
        evidence = [{"period": "2026-07", "window": window, "basis": "actuals"} for window in ("month", "ytd")]
        materials = [{"parsed": {"note": "MOCK 模拟数据 2026-10-14"}}]
        cover = _cover_metadata(project, run, evidence, materials, [{"id": "legacy-id"}])
        self.assertEqual(cover["统计期间"], "当月：2026年7月；累计：2026年1—7月")
        self.assertEqual(cover["报告生成日期"], date.today().isoformat())
        self.assertEqual(cover["报告版本"], "V1.0")
        self.assertEqual(cover["数据版本"], "snapshot-123")
        self.assertIn("MOCK", cover["数据性质"])
        self.assertIn("未指定", cover["保密说明"])
        self.assertEqual(cover["分析对象"], "江铜集团矿山板块")
        revised = _cover_metadata(project, run, evidence, materials, [{"id": "prior", "report_version": "V1.2"}])
        self.assertEqual(revised["报告版本"], "V1.3")

    def test_report_styles_and_table_alignment_are_real_styles(self):
        from docx import Document
        from docx.shared import Pt
        from docx.oxml.ns import qn
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        from long_report.rendering import render_docx, verify_docx

        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "styles.docx"
            template = Path(__file__).resolve().parents[1] / "scenarios/budget_operations/templates/default-v0.2.0.docx"
            markdown = "# 第一章 单位\n\n表1-1 利润（万元）\n\n| 指标 | 金额 |\n| --- | ---: |\n| 利润 | -123.45 |"
            render_docx(markdown, template, target, "矿山报告")
            doc = Document(target)
            for name, size in {"Title": 22, "Heading 1": 16, "Heading 2": 14, "Heading 3": 12,
                               "Normal": 10.5, "Caption": 10.5, "Table Body": 10, "Table Header": 10,
                               "Header": 9, "Footer": 9, "TOC 1": 10.5}.items():
                self.assertEqual(doc.styles[name].font.size.pt, size, name)
                fonts = doc.styles[name].element.rPr.rFonts
                self.assertTrue(all(fonts.get(qn("w:" + key)) for key in ("eastAsia", "ascii", "hAnsi")), name)
            row = doc.tables[0].rows[1]
            self.assertEqual(row.cells[0].paragraphs[0].style.name, "Table Body")
            self.assertEqual(row.cells[1].paragraphs[0].alignment, WD_ALIGN_PARAGRAPH.RIGHT)
            self.assertEqual(row.cells[0].paragraphs[0].alignment, WD_ALIGN_PARAGRAPH.LEFT)
            doc.styles["Heading 1"].font.size = Pt(15)
            doc.save(target)
            with self.assertRaisesRegex(ValueError, "style"):
                verify_docx(markdown, target, {})

    def test_static_directory_links_distinguish_repeated_subheadings(self):
        from docx import Document
        from long_report.rendering import render_docx, verify_docx

        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "links.docx"
            template = Path(__file__).resolve().parents[1] / "scenarios/budget_operations/templates/default-v0.2.0.docx"
            markdown = "# 第一章 单位\n\n## 甲矿\n\n### 经营综述\n\n正文。\n\n## 乙矿\n\n### 经营综述\n\n正文。"
            entries = [(1, "第一章 单位", 3), (2, "甲矿", 3), (3, "经营综述", 3), (2, "乙矿", 4), (3, "经营综述", 4)]
            render_docx(markdown, template, target, "矿山报告", toc_entries=entries)
            doc = Document(target)
            anchors = doc.element.xpath('//w:hyperlink/@w:anchor')
            self.assertEqual(len(anchors), 5)
            self.assertNotEqual(anchors[2], anchors[4])
            self.assertTrue(set(anchors) <= set(doc.element.xpath('//w:bookmarkStart/@w:name')))
            with self.assertRaisesRegex(ValueError, "directory"):
                verify_docx(markdown, target, {}, toc_entries=[(1, "已经删除的章", 3)])

    def test_budget_scenario_does_not_prescribe_unit_names_or_chapters(self):
        result = subprocess.run([REPORT, "scenario", "budget_operations"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        outline = json.loads(result.stdout)["data"]["outline"]
        self.assertEqual(outline["sections"], [])
        self.assertNotIn("profiles", outline)
        self.assertNotIn("unit_names", outline)

    def test_nested_unit_detail_uses_word_heading_four(self):
        from docx import Document
        from long_report.rendering import render_docx

        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "nested.docx"
            template = Path(__file__).resolve().parents[1] / "scenarios/budget_operations/templates/default-v0.2.0.docx"
            render_docx("# 各单位经营分析\n\n### 贵冶\n\n#### 加工费口径\n\n来源待核。", template, target, "预算办月度分析")
            paragraphs = Document(target).paragraphs
            self.assertEqual([(p.text, p.style.name) for p in paragraphs if p.text in ("贵冶", "加工费口径")],
                             [("贵冶", "Heading 3"), ("加工费口径", "Heading 4")])

    def test_word_body_renders_markdown_bold_without_literal_markers(self):
        from docx import Document
        from long_report.rendering import render_docx

        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "bold.docx"
            template = Path(__file__).resolve().parents[1] / "scenarios/budget_operations/templates/default-v0.2.0.docx"
            render_docx("# 摘要\n\n**总体判断。** 矿山利润增长。", template, target, "矿山报告")
            paragraph = next(item for item in Document(target).paragraphs if "矿山利润增长" in item.text)
            self.assertEqual(paragraph.text, "总体判断。 矿山利润增长。")
            self.assertTrue(paragraph.runs[0].bold)
            self.assertFalse(paragraph.runs[-1].bold)

    def test_word_table_rows_stay_whole_across_pages(self):
        from docx import Document
        from docx.oxml.ns import qn
        from long_report.rendering import render_docx

        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "rows.docx"
            template = Path(__file__).resolve().parents[1] / "scenarios/budget_operations/templates/default-v0.2.0.docx"
            render_docx("# 单位分析\n\n表4-1 经营指标\n\n| 指标 | 本期 |\n| --- | ---: |\n| 吨矿成本（元/吨） | 111.35 |",
                        template, target, "矿山报告")
            table = Document(target).tables[0]
            self.assertTrue(all(row._tr.get_or_add_trPr().find(qn("w:cantSplit")) is not None
                                for row in table.rows))

    @unittest.skipUnless(shutil.which("soffice"), "LibreOffice is needed to measure Word pages")
    def test_word_directory_uses_rendered_page_numbers_and_reference_layout(self):
        from docx import Document
        from pypdf import PdfReader
        from long_report.rendering import render_paginated_docx

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "report.docx"
            template = Path(__file__).resolve().parents[1] / "scenarios/budget_operations/templates/default-v0.2.0.docx"
            markdown = ("# 第一章 摘要\n\n正文。\n\n# 第二章 单位\n\n## 01 德兴铜矿（含新技术）\n\n明细。"
                        "\n\n# 第三章 专项\n\n### 经营变化分析\n\n成本变化待核。")
            pdf, entries = render_paginated_docx(markdown, template, target, "矿山报告", {},
                                                 {"body_font": "宋体", "heading_font": "黑体", "latin_font": "Times New Roman"})
            document = Document(target)
            self.assertAlmostEqual(document.sections[0].page_width.inches, 8.2677, places=2)
            self.assertEqual(document.styles["Normal"].font.size.pt, 10.5)
            self.assertEqual(document.styles["Heading 1"].font.size.pt, 16)
            self.assertEqual([p.text for p in document.paragraphs if p.style.name == "TOC 1"],
                             [f"第一章 摘要\t{entries[0][2]}", f"第二章 单位\t{entries[1][2]}",
                              f"第三章 专项\t{entries[3][2]}"])
            self.assertEqual([p.text for p in document.paragraphs if p.style.name == "TOC 2"],
                             [f"01 德兴铜矿（含新技术）\t{entries[2][2]}"])
            self.assertEqual([p.text for p in document.paragraphs if p.style.name == "TOC 3"],
                             [f"经营变化分析\t{entries[4][2]}"])
            self.assertTrue(all(1 < page <= len(PdfReader(pdf).pages) for _, _, page in entries))

    def test_request_plan_can_select_six_mining_units_and_nine_chapters(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "projects"
            request_path = root / "request.json"

            def call(*args, request=None):
                command = [REPORT, *args, "--workspace", str(workspace)]
                if request is not None:
                    request_path.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
                    command += ["--request", str(request_path)]
                result = subprocess.run(command, cwd=root, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                return json.loads(result.stdout)["data"]

            names = ["德兴铜矿（含新技术）", "永平铜矿", "武山铜矿", "城门山铜矿", "银山矿业", "银珠山矿业"]
            project = call("project", "create", request={
                "scenario_id": "budget_operations", "scenario_version": "0.2.0", "report_period": "2026-07",
                "subject_scope": {"organization": "集团合并", "units": names, "special_subjects": ["七宝山专项"]},
            })
            self.assertNotIn("report_profile", project)
            source = root / "actuals.csv"
            source.write_text("单位,专项值\n德兴铜矿（含新技术）,100\n七宝山专项,20\n", encoding="utf-8")
            call("material", "add", request={"project_id": project["id"], "input_id": "actuals", "path": str(source)})
            run = call("run", "start", request={"project_id": project["id"]})
            task = call("task", "list", "--project", project["id"], "--run", run["id"])[0]
            submitted = call("task", "submit", request={"project_id": project["id"], "run_id": run["id"], "task_id": task["id"],
                                                       "input_fingerprint": task["input_fingerprint"], "candidates": [
                                                           {"subject_id": subject, "metric_id": "special.value", "period": "2026-07",
                                                            "window": "ytd", "basis": "actuals", "unit": "万元", "value": value,
                                                            "source_value": value, "source_locator": f"sheet:CSV/cell:B{row}"}
                                                           for row, subject, value in ((2, names[0], "100"), (3, "七宝山专项", "20"))]})
            evidence = [call("evidence", "decide", request={"project_id": project["id"], "run_id": run["id"],
                                                              "candidate_id": candidate["id"], "decision": "accept"})
                        for candidate in submitted["candidates"]]
            call("evidence", "freeze", request={"project_id": project["id"], "run_id": run["id"]})
            call("calculate", request={"project_id": project["id"], "run_id": run["id"]})
            reference = yaml.safe_load((Path(__file__).parent / "fixtures/budget_reference_outline.yaml").read_text(encoding="utf-8"))["profiles"]["mining"]
            request_path.write_text(json.dumps({"project_id": project["id"], "run_id": run["id"],
                                                "report_request": "只分析矿山板块及六户单位", "outline": reference,
                                                "material_uses": [{"material_id": run["material_ids"][0], "use": "context", "reason": "暂作背景"}]},
                                               ensure_ascii=False), encoding="utf-8")
            mislabeled = subprocess.run([REPORT, "draft", "plan", "--workspace", str(workspace), "--request", str(request_path)],
                                        capture_output=True, text=True)
            self.assertNotEqual(mislabeled.returncode, 0)
            self.assertIn("accepted evidence must be analysis", mislabeled.stderr)
            sections = call("draft", "plan", request={"project_id": project["id"], "run_id": run["id"],
                                                     "report_request": "只分析矿山板块及六户单位",
                                                     "material_uses": [{"material_id": run["material_ids"][0], "use": "analysis", "reason": "已确认单位和独立专项数据"}],
                                                     "outline": reference})
            self.assertEqual([task["subject_id"] for task in sections if task["subject_id"]], names)
            planned_run = call("run", "show", run["id"], "--project", project["id"])
            self.assertEqual([section["title"] for section in planned_run["effective_config"]["outline"]["sections"]], [
                "第一章 管理层执行摘要", "第二章 数据来源与分析范围", "第三章 集团整体经营及利润分析",
                "第四章 产业板块与二级单位经营分析", "第五章 专项来源与独立口径分析",
                "第六章 整体经营与共同关注事项", "第七章 市场关联与情景测算",
                "第八章 建议事项与人工确认", "第九章 来源索引与计算口径",
            ])
            while any(task["status"] != "submitted" for task in sections):
                for ready in (task for task in sections if task["status"] == "ready"):
                    call("draft", "submit", request={"project_id": project["id"], "run_id": run["id"],
                                                    "task_id": ready["id"], "author_id": "writer", "body": "材料与经营判断待核实。"})
                sections = call("draft", "plan", request={"project_id": project["id"], "run_id": run["id"]})
            call("draft", "build", request={"project_id": project["id"], "run_id": run["id"]})
            coverage = call("validate", request={"project_id": project["id"], "run_id": run["id"]})
            self.assertFalse(coverage["checks"]["analysis_material_coverage"])
            self.assertFalse(coverage["checks"]["unit_evidence_coverage"])
            self.assertFalse(coverage["checks"]["special_subject_coverage"])
            for section_id, item in ((f"units:{names[0]}", evidence[0]), ("special", evidence[1])):
                task = next(task for task in sections if task["section_id"] == section_id)
                call("draft", "submit", request={"project_id": project["id"], "run_id": run["id"],
                                                "task_id": task["id"], "author_id": "writer", "replace": True,
                                                "body": "独立来源数值 {{fact:" + item["id"] + "}}；位置 {{ev:" + item["id"] + "}}。"})
            draft = call("draft", "build", request={"project_id": project["id"], "run_id": run["id"]})
            coverage = call("validate", request={"project_id": project["id"], "run_id": run["id"]})
            self.assertTrue(coverage["checks"]["analysis_material_coverage"])
            self.assertTrue(coverage["checks"]["unit_evidence_coverage"])
            self.assertTrue(coverage["checks"]["special_subject_coverage"])
            call("review", "submit", request={"project_id": project["id"], "run_id": run["id"],
                                              "draft_sha256": draft["sha256"], "reviewer_id": "render-qa",
                                              "verdict": "pass", "issues": []})
            revision = call("publish", request={"project_id": project["id"], "run_id": run["id"]})
            manifest = json.loads((Path(revision["docx_path"]).parents[1] / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["material_uses"], [{"material_id": run["material_ids"][0], "use": "analysis",
                                                         "reason": "已确认单位和独立专项数据"}])
            self.assertEqual(manifest["scope_exclusions"], [])
            from docx import Document
            delivered = Document(revision["docx_path"])
            self.assertEqual([paragraph.text.split("\t")[0] for paragraph in delivered.paragraphs
                              if paragraph.style.name == "TOC 2"], [f"4.{i} {name}" for i, name in enumerate(names, 1)])


if __name__ == "__main__":
    unittest.main()
