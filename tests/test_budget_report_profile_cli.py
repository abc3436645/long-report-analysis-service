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
            self.assertEqual(document.styles["Heading 1"].font.size.pt, 15)
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
                              if paragraph.style.name == "TOC 2"], names)


if __name__ == "__main__":
    unittest.main()
