import json
import os
import subprocess
import sys
import tempfile
import unittest
from decimal import Decimal
from contextlib import nullcontext
from pathlib import Path
from zipfile import ZipFile
import yaml


REPORT = Path(sys.executable).with_name("report")


class BudgetCalculationCliTests(unittest.TestCase):
    def test_one_mixed_workbook_uses_fact_basis_instead_of_file_role_for_comparison(self):
        acceptance = os.environ.get("LONG_REPORT_ACCEPTANCE_ROOT")
        directory = Path(acceptance) / self._testMethodName if acceptance else None
        if directory:
            directory.mkdir(parents=True)
        with nullcontext(directory) if directory else tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "projects"
            request_file = root / "request.json"

            def call(*args, request=None):
                command = [REPORT, *args, "--workspace", str(workspace)]
                if request is not None:
                    request_file.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
                    command += ["--request", str(request_file)]
                result = subprocess.run(command, cwd=root, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                return json.loads(result.stdout)["data"]

            project = call("project", "create", request={
                "scenario_id": "budget_operations", "scenario_version": "0.2.0",
                "subject_scope": {"organization": "合成集团", "units": ["甲单位"]}, "report_period": "2026-07",
                "overrides": {"business_definitions.measurement_unit": "万元", "business_definitions.budget_version_rule": "v1"},
            })
            source = root / "mixed.csv"
            source.write_text("单位,本月实际,本月预算,产量\n甲单位,120.50,100.00,12\n", encoding="utf-8")
            for role in ("actuals", "budget"):
                call("material", "add", request={"project_id": project["id"], "input_id": role, "path": str(source)})
            run = call("run", "start", request={"project_id": project["id"]})
            tasks = call("task", "list", "--project", project["id"], "--run", run["id"])
            self.assertEqual(len(tasks), 1)
            task = tasks[0]
            submitted = call("task", "submit", request={
                "project_id": project["id"], "run_id": run["id"], "task_id": task["id"], "input_fingerprint": task["input_fingerprint"],
                "candidates": [{
                    "subject_id": "甲单位", "metric_id": "profit_total", "period": "2026-07", "window": "month", "unit": "万元",
                    "basis": role, "budget_version": "v1" if role == "budget" else None,
                    "value": value, "source_value": value, "source_locator": f"sheet:CSV/cell:{cell}",
                } for role, value, cell in (("actuals", "120.50", "B2"), ("budget", "100.00", "C2"))] + [{
                    "subject_id": "甲单位", "metric_id": "production_volume", "period": "2026-07", "window": "month", "unit": "吨",
                    "basis": "actuals", "value": "12", "source_value": "12", "source_locator": "sheet:CSV/cell:D2",
                }],
            })
            for candidate in submitted["candidates"]:
                call("evidence", "decide", request={"project_id": project["id"], "run_id": run["id"], "candidate_id": candidate["id"], "decision": "accept"})
            snapshot = call("evidence", "freeze", request={"project_id": project["id"], "run_id": run["id"]})
            self.assertEqual(snapshot["missing_inputs"], [])
            results = call("calculate", request={"project_id": project["id"], "run_id": run["id"]})
            self.assertEqual({item["metric_id"]: item["value"] for item in results if item.get("status") == "calculated"},
                             {"budget_difference": "20.50", "budget_completion_rate": "120.500"})

    def test_confirmed_actual_and_matching_budget_produce_traced_difference(self):
        acceptance = os.environ.get("LONG_REPORT_ACCEPTANCE_ROOT")
        directory = Path(acceptance) / self._testMethodName if acceptance else None
        if directory:
            directory.mkdir(parents=True)
        with nullcontext(directory) if directory else tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "projects"
            request_file = root / "request.json"

            def call(*args, request=None):
                command = [REPORT, *args, "--workspace", str(workspace)]
                if request is not None:
                    request_file.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
                    command += ["--request", str(request_file)]
                result = subprocess.run(command, cwd=root, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                return json.loads(result.stdout)["data"]

            project = call("project", "create", request={
                "scenario_id": "budget_operations", "scenario_version": "0.2.0",
                "subject_scope": {"organization": "合成集团", "units": ["甲单位"]},
                "report_period": "2026-07",
                "report_title": "预算办月度经营分析报告（模拟验收）",
                "overrides": {
                    "business_definitions.measurement_unit": "万元",
                    "business_definitions.budget_version_rule": "v1",
                },
            })
            material_ids_by_input = {}
            for input_id, amount in (("actuals", "120.50"), ("budget", "100.00")):
                source = root / f"{input_id}.csv"
                source.write_text(f"单位,利润总额\n甲单位,{amount}\n", encoding="utf-8")
                material_ids_by_input[input_id] = call("material", "add", request={"project_id": project["id"], "input_id": input_id, "path": str(source)})["id"]
            run = call("run", "start", request={"project_id": project["id"]})
            tasks = call("task", "list", "--project", project["id"], "--run", run["id"])
            evidence_ids = []
            evidence_by_input = {}
            for task in tasks:
                context = call("task", "context", task["id"], "--project", project["id"])
                material = context["material"]
                cell = material["parsed"]["sheets"]["CSV"]["cells"]["B2"]
                candidate = call("task", "submit", request={
                    "project_id": project["id"], "run_id": run["id"], "task_id": task["id"],
                    "input_fingerprint": task["input_fingerprint"],
                    "candidates": [{
                        "subject_id": "甲单位", "metric_id": "profit_total", "period": "2026-07",
                        "window": "month", "unit": "万元", "budget_version": "v1" if material["input_id"] == "budget" else None,
                        "value": cell["value"], "source_value": cell["value"], "source_locator": cell["locator"],
                    }],
                })["candidates"][0]
                evidence = call("evidence", "decide", request={
                    "project_id": project["id"], "run_id": run["id"],
                    "candidate_id": candidate["id"], "decision": "accept",
                })
                evidence_ids.append(evidence["id"])
                evidence_by_input[material["input_id"]] = evidence["id"]
            call("evidence", "freeze", request={"project_id": project["id"], "run_id": run["id"]})
            results = call("calculate", request={"project_id": project["id"], "run_id": run["id"]})
            difference = next(item for item in results if item["metric_id"] == "budget_difference")
            self.assertEqual(difference["value"], "20.50")
            self.assertEqual(set(difference["input_evidence_ids"]), set(evidence_ids))
            self.assertEqual(difference["operator"], "difference")
            self.assertEqual((difference["unit"], difference["window"], difference["budget_version"]), ("万元", "month", "v1"))
            chart = call("chart", "create", request={
                "project_id": project["id"], "run_id": run["id"], "title": "甲单位本月利润与预算",
                "series": [{"label": "实际", "evidence_id": evidence_by_input["actuals"]},
                           {"label": "预算", "evidence_id": evidence_by_input["budget"]}],
            })
            self.assertEqual(chart["source_evidence_ids"], [evidence_by_input["actuals"], evidence_by_input["budget"]])
            self.assertIn("actuals.csv", chart["source_caption"])
            self.assertIn("budget.csv", chart["source_caption"])
            self.assertEqual({item["metric_id"] for item in chart["annotations"]}, {"budget_difference", "budget_completion_rate"})

            reference = yaml.safe_load((Path(__file__).parent / "fixtures/budget_reference_outline.yaml").read_text(encoding="utf-8"))
            sections = call("draft", "plan", request={"project_id": project["id"], "run_id": run["id"],
                                                     "report_request": "分析甲单位本月经营与预算执行",
                                                     "material_uses": [{"material_id": identifier, "use": "analysis", "reason": "已确认实际和预算利润"} for identifier in run["material_ids"]],
                                                     "outline": {"sections": reference["sections"], "unit_names": ["甲单位"]}})
            self.assertEqual([item["section_id"] for item in sections], [
                "scope", "units:甲单位", "special", "group", "market", "actions", "sources",
            ])
            self.assertEqual(sections[0]["status"], "ready")
            self.assertEqual(sections[1]["status"], "blocked")
            self.assertEqual(sections[1]["subject_id"], "甲单位")
            unit_context = call("draft", "context", sections[1]["id"], "--project", project["id"])
            self.assertEqual(unit_context["task"]["section_id"], "units:甲单位")
            self.assertEqual({item["metric_id"] for item in unit_context["calculations"]}, {"budget_difference", "budget_completion_rate"})
            self.assertEqual({item["id"] for item in unit_context["evidence"]}, set(evidence_ids))

            request_file.write_text(json.dumps({
                "project_id": project["id"], "run_id": run["id"], "task_id": sections[1]["id"],
                "author_id": "writer-agent",
                "body": f"甲单位本月利润差额为 {{{{calc:{difference['id']}}}}} 万元。",
            }, ensure_ascii=False), encoding="utf-8")
            premature = subprocess.run([
                REPORT, "draft", "submit", "--workspace", str(workspace), "--request", str(request_file)
            ], cwd=root, capture_output=True, text=True)
            self.assertNotEqual(premature.returncode, 0)
            self.assertIn("depends", premature.stderr)

            call("draft", "submit", request={
                "project_id": project["id"], "run_id": run["id"], "task_id": sections[0]["id"],
                "author_id": "writer-agent",
                "body": "本报告依据已登记的实际和预算资料，尚未确认集团合并规则。",
            })
            request_file.write_text(json.dumps({
                "project_id": project["id"], "run_id": run["id"], "task_id": sections[1]["id"],
                "author_id": "writer-agent", "body": "甲单位利润差额为 999 万元。",
            }, ensure_ascii=False), encoding="utf-8")
            invented_amount = subprocess.run([REPORT, "draft", "submit", "--workspace", str(workspace), "--request", str(request_file)], cwd=root, capture_output=True, text=True)
            self.assertNotEqual(invented_amount.returncode, 0)
            rate = next(item for item in results if item["metric_id"] == "budget_completion_rate")
            actual_ref = "{{fact:" + evidence_by_input["actuals"] + "}}"
            actual_ref_one = "{{fact:" + evidence_by_input["actuals"] + "|1}}"
            actual_source = "{{ev:" + evidence_by_input["actuals"] + "}}"
            budget_ref = "{{fact:" + evidence_by_input["budget"] + "}}"
            difference_ref = "{{calc:" + difference["id"] + "}}"
            rate_ref = "{{calc:" + rate["id"] + "|1}}"
            chart_ref = "{{chart:" + chart["id"] + "}}"
            incomplete_body = f"甲单位利润差额为 {difference_ref} 万元。\n\n| 指标 | 实际 |\n| --- | ---: |\n| 利润 | {actual_ref} |\n\n{chart_ref}"
            request_file.write_text(json.dumps({"project_id": project["id"], "run_id": run["id"], "task_id": sections[1]["id"],
                                                "author_id": "writer-agent", "body": incomplete_body}, ensure_ascii=False), encoding="utf-8")
            incomplete = subprocess.run([REPORT, "draft", "submit", "--workspace", str(workspace), "--request", str(request_file)],
                                        cwd=root, capture_output=True, text=True)
            self.assertNotEqual(incomplete.returncode, 0)
            self.assertIn("operating indicator or data gap table", incomplete.stderr)
            unit_body = (f"甲单位本月实际利润为 {actual_ref} 万元，展示一位小数为 {actual_ref_one} 万元，"
                         f"差额为 {difference_ref} 万元，预算完成率为 {rate_ref}%，依据 {actual_source}。\n\n"
                         "| 指标 | 实际 | 预算 | 差额 | 完成率 |\n| --- | ---: | ---: | ---: | ---: |\n"
                         f"| 利润总额（万元） | {actual_ref} | {budget_ref} | {difference_ref} | {rate_ref}% |\n\n{chart_ref}\n\n"
                         "| 经营指标或数据缺口 | 状态 |\n| --- | --- |\n| 产销量、成本 | 未提供同口径来源，待补充核对 |")
            unit_request = {
                "project_id": project["id"], "run_id": run["id"], "task_id": sections[1]["id"],
                "author_id": "writer-agent",
                "body": unit_body,
            }
            unit = call("draft", "submit", request=unit_request)
            self.assertEqual(unit["status"], "submitted")
            self.assertEqual(call("draft", "submit", request=unit_request)["id"], unit["id"])

            for section_id in ("special", "market", "group", "actions", "sources"):
                task = next(item for item in call("draft", "plan", request={"project_id": project["id"], "run_id": run["id"]}) if item["section_id"] == section_id)
                self.assertEqual(task["status"], "ready")
                call("draft", "submit", request={
                    "project_id": project["id"], "run_id": run["id"], "task_id": task["id"],
                    "author_id": "writer-agent",
                    "body": "### 专项核验\n\n本节仅列示已取得的材料；缺少的专项或市场资料需补充核验。" if section_id == "special" else "本节仅列示已取得的材料；缺少的专项或市场资料需补充核验。",
                })
            special_task = next(item for item in sections if item["section_id"] == "special")
            call("draft", "submit", request={
                "project_id": project["id"], "run_id": run["id"], "task_id": special_task["id"],
                "author_id": "writer-agent", "replace": True,
                "body": "### 专项核验\n\n专项材料仍待核实归属。",
            })
            candidate_report = call("draft", "build", request={"project_id": project["id"], "run_id": run["id"]})
            content = Path(candidate_report["markdown_path"]).read_text(encoding="utf-8")
            self.assertIn("专项材料仍待核实归属", content)
            self.assertEqual(content.count("## 2.1 甲单位"), 1)
            self.assertIn("甲单位本月实际利润为 120.50 万元", content)
            self.assertIn("差额为 20.50 万元", content)
            self.assertIn("展示一位小数为 120.5 万元", content)
            self.assertIn("sheet:CSV/cell:B2", content)
            self.assertIn("图表数据来源：", content)
            self.assertEqual([line[2:] for line in content.splitlines() if line.startswith("# ")], [
                "第一章 报告口径与资料范围", "第二章 各单位经营分析", "第三章 专项来源的独立口径",
                "第四章 整体经营与共同关注事项", "第五章 市场关联及情景测算", "第六章 建议事项与人工确认", "第七章 来源索引与计算口径",
            ])

            request_file.write_text(json.dumps({"project_id": project["id"], "run_id": run["id"]}), encoding="utf-8")
            before_review = subprocess.run([REPORT, "publish", "--workspace", str(workspace), "--request", str(request_file)], cwd=root, capture_output=True, text=True)
            self.assertNotEqual(before_review.returncode, 0)

            first_review_request = {
                "project_id": project["id"], "run_id": run["id"], "draft_sha256": candidate_report["sha256"],
                "reviewer_id": "independent-reviewer", "verdict": "pass", "issues": [],
            }
            first_review = call("review", "submit", request=first_review_request)
            self.assertEqual(call("review", "submit", request=first_review_request)["id"], first_review["id"])
            validation = call("validate", request={"project_id": project["id"], "run_id": run["id"]})
            self.assertEqual(validation["status"], "pending_review")
            self.assertTrue(validation["hard_checks_passed"])
            revision = call("publish", request={"project_id": project["id"], "run_id": run["id"]})
            self.assertEqual(revision["status"], "pending_review")
            self.assertEqual(call("publish", request={"project_id": project["id"], "run_id": run["id"]})["id"], revision["id"])
            self.assertEqual(Path(revision["markdown_path"]).read_text(encoding="utf-8"), content)
            with ZipFile(revision["docx_path"]) as word:
                document_xml = word.read("word/document.xml").decode("utf-8")
            from docx import Document
            from docx.oxml.ns import qn
            from long_report.rendering import report_fonts
            delivered = Document(revision["docx_path"])
            self.assertEqual(delivered.styles["Normal"].element.rPr.rFonts.get(qn("w:eastAsia")), report_fonts()["body_font"])
            self.assertEqual(delivered.styles["Heading 1"].element.rPr.rFonts.get(qn("w:eastAsia")), report_fonts()["heading_font"])
            self.assertEqual(delivered.paragraphs[0].text, "预算办月度经营分析报告（模拟验收）")
            self.assertEqual([paragraph.text for paragraph in delivered.paragraphs if paragraph.style.name == "TOC Heading"], ["目录"])
            self.assertEqual([paragraph.text for paragraph in delivered.paragraphs if paragraph.text.startswith("数据性质：")],
                             ["数据性质：未明确标识（待核实）"])
            self.assertEqual(revision["report_version"], "V1.0")
            self.assertEqual(len(delivered.inline_shapes), 1)
            self.assertEqual([paragraph.text.split("\t")[0] for paragraph in delivered.paragraphs if paragraph.style.name == "TOC 1"], [
                "第一章 报告口径与资料范围", "第二章 各单位经营分析", "第三章 专项来源的独立口径",
                "第四章 整体经营与共同关注事项", "第五章 市场关联及情景测算", "第六章 建议事项与人工确认", "第七章 来源索引与计算口径",
            ])
            self.assertEqual([paragraph.text.split("\t")[0] for paragraph in delivered.paragraphs if paragraph.style.name == "TOC 2"],
                             ["2.1 甲单位", "3.1 专项核验"])
            self.assertIn("甲单位", document_xml)
            self.assertIn("20.50", document_xml)
            self.assertIn("<w:tbl>", document_xml)
            self.assertIn("<w:tblHeader", document_xml)
            self.assertIn("<w:tblBorders>", document_xml)
            self.assertIn('<w:pStyle w:val="Heading2"/>', document_xml)
            latest = call("revision", "latest", "--project", project["id"])
            self.assertEqual(latest["id"], revision["id"])
            self.assertEqual(latest["file_hashes"], revision["file_hashes"])

            supplement = root / "supplement.csv"
            supplement.write_text("单位,补充说明\n甲单位,已核实差异原因\n", encoding="utf-8")
            new_material = call("material", "add", request={"project_id": project["id"], "input_id": "actuals", "path": str(supplement)})
            next_run = call("run", "start", request={"project_id": project["id"], "base_revision_id": revision["id"]})
            self.assertEqual(next_run["base_revision_id"], revision["id"])
            self.assertIn(new_material["id"], next_run["material_ids"])
            next_tasks = call("task", "list", "--project", project["id"], "--run", next_run["id"])
            self.assertEqual([task["source_id"] for task in next_tasks], [new_material["id"]])
            supplement_cell = call("task", "context", next_tasks[0]["id"], "--project", project["id"])["material"]["parsed"]["sheets"]["CSV"]["cells"]["B2"]
            explanation = call("task", "submit", request={
                "project_id": project["id"], "run_id": next_run["id"], "task_id": next_tasks[0]["id"],
                "input_fingerprint": next_tasks[0]["input_fingerprint"], "candidates": [{
                    "subject_id": "甲单位", "metric_id": "reason_note", "period": "2026-07", "window": "month", "unit": "text", "basis": "actuals",
                    "value": supplement_cell["value"], "source_value": supplement_cell["value"], "source_locator": supplement_cell["locator"],
                }],
            })["candidates"][0]
            new_evidence = call("evidence", "decide", request={
                "project_id": project["id"], "run_id": next_run["id"], "candidate_id": explanation["id"], "decision": "accept",
            })
            carried = call("evidence", "freeze", request={"project_id": project["id"], "run_id": next_run["id"]})
            self.assertEqual(set(carried["evidence_ids"]), set(evidence_ids) | {new_evidence["id"]})
            recalculated = call("calculate", request={"project_id": project["id"], "run_id": next_run["id"]})
            self.assertEqual({item["metric_id"]: item["value"] for item in recalculated if item.get("status") == "calculated"},
                             {"budget_difference": "20.50", "budget_completion_rate": "120.500"})
            next_sections = call("draft", "plan", request={"project_id": project["id"], "run_id": next_run["id"],
                                                          "report_request": "分析甲单位本月经营与预算执行，纳入补充说明",
                                                          "outline": {"sections": reference["sections"], "unit_names": ["甲单位"]},
                                                          "material_uses": [{"material_id": identifier, "use": "analysis", "reason": "已确认利润或补充说明"}
                                                                            for identifier in next_run["material_ids"]]})
            next_by_id = {item["section_id"]: item for item in next_sections}
            self.assertEqual(next_by_id["special"]["status"], "submitted")
            self.assertEqual(next_by_id["market"]["status"], "submitted")
            self.assertNotEqual(next_by_id["units:甲单位"]["status"], "submitted")
            resumed = call("run", "show", next_run["id"], "--project", project["id"])
            self.assertEqual(resumed["id"], next_run["id"])
            def submit_next(section_id, body):
                return call("draft", "submit", request={
                    "project_id": project["id"], "run_id": next_run["id"], "task_id": next_by_id[section_id]["id"],
                    "author_id": "writer-agent", "body": body,
                })
            submit_next("scope", "本轮补充了原因说明，合并规则仍待确认。")
            next_difference = next(item for item in recalculated if item["metric_id"] == "budget_difference")
            next_rate = next(item for item in recalculated if item["metric_id"] == "budget_completion_rate")
            next_body = unit_body.replace(difference_ref, "{{calc:" + next_difference["id"] + "}}")
            next_body = next_body.replace(rate_ref, "{{calc:" + next_rate["id"] + "|1}}")
            next_body += f"\n\n补件记录为 {{{{fact:{new_evidence['id']}}}}}，来源 {{{{ev:{new_evidence['id']}}}}}。"
            submit_next("units:甲单位", next_body)
            submit_next("group", "集团合并规则仍缺，单位变化不直接加总。")
            submit_next("actions", "请财务核对补件与利润桥，形成后续经营措施。")
            submit_next("sources", f"补件来源为 {{{{ev:{new_evidence['id']}}}}}；其余来源沿用上一版本。")
            second_draft = call("draft", "build", request={"project_id": project["id"], "run_id": next_run["id"]})
            second_content = Path(second_draft["markdown_path"]).read_text(encoding="utf-8")
            def section(text, title):
                heading = next(line for line in text.splitlines() if line.startswith("# ") and line.endswith(" " + title))
                return text.split(heading + "\n", 1)[1].split("\n# ", 1)[0]
            self.assertEqual(section(second_content, "专项来源的独立口径"), section(content, "专项来源的独立口径"))
            self.assertEqual(section(second_content, "市场关联及情景测算"), section(content, "市场关联及情景测算"))
            call("review", "submit", request={
                "project_id": project["id"], "run_id": next_run["id"], "draft_sha256": second_draft["sha256"],
                "reviewer_id": "reviewer-2", "verdict": "pass", "issues": [],
            })
            from unittest.mock import patch
            from long_report.application import publish_run, get_latest_revision
            with patch("long_report.application.verify_docx", side_effect=ValueError("report style size is invalid")):
                with self.assertRaisesRegex(ValueError, "style size"):
                    publish_run(workspace, {"project_id": project["id"], "run_id": next_run["id"]})
            self.assertEqual(get_latest_revision(workspace, project["id"])["id"], revision["id"])
            self.assertFalse(list((workspace / project["id"] / "revisions").glob(".staging_*")))
            second_revision = call("publish", request={"project_id": project["id"], "run_id": next_run["id"]})
            self.assertEqual(second_revision["report_version"], "V1.1")
            self.assertIn("supplement.csv", Path(second_revision["markdown_path"]).read_text(encoding="utf-8"))
            self.assertIn("supplement.csv", (Path(second_revision["markdown_path"]).parent / "changes.md").read_text(encoding="utf-8"))
            self.assertEqual(call("revision", "latest", "--project", project["id"])["id"], second_revision["id"])
            self.assertEqual(Path(revision["markdown_path"]).read_text(encoding="utf-8"), content)

            canceled_run = call("run", "start", request={"project_id": project["id"], "base_revision_id": second_revision["id"]})
            self.assertEqual(call("task", "list", "--project", project["id"], "--run", canceled_run["id"]), [])
            call("evidence", "freeze", request={"project_id": project["id"], "run_id": canceled_run["id"]})
            call("calculate", request={"project_id": project["id"], "run_id": canceled_run["id"]})
            wording_sections = call("draft", "plan", request={"project_id": project["id"], "run_id": canceled_run["id"]})
            self.assertTrue(all(item["status"] == "submitted" for item in wording_sections))
            group_task = next(item for item in wording_sections if item["section_id"] == "group")
            edited = call("draft", "submit", request={
                "project_id": project["id"], "run_id": canceled_run["id"], "task_id": group_task["id"],
                "author_id": "writer-agent", "replace": True,
                "body": "集团合并规则仍缺；请复核利润桥。",
            })
            self.assertNotIn("reused_from_task_id", edited)
            wording_draft = call("draft", "build", request={"project_id": project["id"], "run_id": canceled_run["id"]})
            wording_content = Path(wording_draft["markdown_path"]).read_text(encoding="utf-8")
            self.assertEqual(section(wording_content, "专项来源的独立口径"), section(second_content, "专项来源的独立口径"))
            self.assertEqual(section(wording_content, "市场关联及情景测算"), section(second_content, "市场关联及情景测算"))
            self.assertNotEqual(section(wording_content, "整体经营与共同关注事项"), section(second_content, "整体经营与共同关注事项"))
            call("review", "submit", request={
                "project_id": project["id"], "run_id": canceled_run["id"], "draft_sha256": wording_draft["sha256"],
                "reviewer_id": "reviewer-3", "verdict": "pass", "issues": [],
            })
            wording_revision = call("publish", request={"project_id": project["id"], "run_id": canceled_run["id"]})
            changes = (Path(wording_revision["markdown_path"]).parent / "changes.md").read_text(encoding="utf-8")
            self.assertIn("更新章节：group", changes)
            self.assertIn("新增材料：无", changes)
            abandoned = call("run", "start", request={"project_id": project["id"], "base_revision_id": wording_revision["id"]})
            canceled = call("run", "cancel", request={"project_id": project["id"], "run_id": abandoned["id"]})
            self.assertEqual(canceled["status"], "canceled")
            self.assertEqual(call("revision", "latest", "--project", project["id"])["id"], wording_revision["id"])

            correction = root / "correction.csv"
            correction.write_text("单位,利润总额\n甲单位,130.00\n", encoding="utf-8")
            corrected_source = call("material", "add", request={"project_id": project["id"], "input_id": "actuals", "path": str(correction)})
            corrected_run = call("run", "start", request={"project_id": project["id"], "base_revision_id": wording_revision["id"]})
            corrected_tasks = call("task", "list", "--project", project["id"], "--run", corrected_run["id"])
            self.assertEqual({task["source_id"] for task in corrected_tasks}, {corrected_source["id"]})
            for task in corrected_tasks:
                material = call("task", "context", task["id"], "--project", project["id"])["material"]
                candidates = []
                if material["id"] == corrected_source["id"]:
                    cell = material["parsed"]["sheets"]["CSV"]["cells"]["B2"]
                    candidates = [{
                        "subject_id": "甲单位", "metric_id": "profit_total", "period": "2026-07", "window": "month",
                        "unit": "万元", "basis": "actuals", "value": cell["value"], "source_value": cell["value"], "source_locator": cell["locator"],
                    }]
                submitted = call("task", "submit", request={
                    "project_id": project["id"], "run_id": corrected_run["id"], "task_id": task["id"],
                    "input_fingerprint": task["input_fingerprint"], "candidates": candidates,
                })
                if candidates:
                    corrected_candidate = submitted["candidates"][0]
            conflict = call("evidence", "decide", request={
                "project_id": project["id"], "run_id": corrected_run["id"],
                "candidate_id": corrected_candidate["id"], "decision": "accept",
            })
            self.assertEqual(conflict["status"], "conflict")
            self.assertEqual(conflict["conflicts_with"], [evidence_by_input["actuals"]])
            replacement = call("evidence", "decide", request={
                "project_id": project["id"], "run_id": corrected_run["id"],
                "candidate_id": corrected_candidate["id"], "decision": "replace",
                "supersedes_evidence_id": evidence_by_input["actuals"], "reason": "利润快报勘误",
            })
            corrected_snapshot = call("evidence", "freeze", request={"project_id": project["id"], "run_id": corrected_run["id"]})
            self.assertEqual(set(corrected_snapshot["evidence_ids"]), {evidence_by_input["budget"], new_evidence["id"], replacement["id"]})
            recalculated = call("calculate", request={"project_id": project["id"], "run_id": corrected_run["id"]})
            self.assertEqual({item["metric_id"]: Decimal(item["value"]) for item in recalculated if item.get("status") == "calculated"},
                             {"budget_difference": Decimal("30"), "budget_completion_rate": Decimal("130")})
            corrected_sections = call("draft", "plan", request={"project_id": project["id"], "run_id": corrected_run["id"],
                                                               "report_request": "分析甲单位本月经营与预算执行，按勘误更正利润",
                                                               "outline": {"sections": reference["sections"], "unit_names": ["甲单位"]},
                                                               "material_uses": [{"material_id": identifier,
                                                                                  "use": "context" if identifier == material_ids_by_input["actuals"] else "analysis",
                                                                                  "reason": "旧利润表已由勘误替代" if identifier == material_ids_by_input["actuals"] else "本轮有效利润或说明"}
                                                                                 for identifier in corrected_run["material_ids"]]})
            corrected_by_id = {item["section_id"]: item for item in corrected_sections}
            self.assertEqual(corrected_by_id["special"]["status"], "submitted")
            self.assertEqual(corrected_by_id["market"]["status"], "submitted")
            self.assertNotEqual(corrected_by_id["units:甲单位"]["status"], "submitted")
            def submit_corrected(section_id, body):
                call("draft", "submit", request={
                    "project_id": project["id"], "run_id": corrected_run["id"], "task_id": corrected_by_id[section_id]["id"],
                    "author_id": "writer-agent", "body": body,
                })
            submit_corrected("scope", "本轮更正了甲单位利润值，集团合并规则仍缺。")
            corrected_difference = next(item for item in recalculated if item["metric_id"] == "budget_difference")
            corrected_rate = next(item for item in recalculated if item["metric_id"] == "budget_completion_rate")
            corrected_chart = call("chart", "create", request={
                "project_id": project["id"], "run_id": corrected_run["id"], "title": "甲单位更正后利润与预算",
                "series": [{"label": "更正实际", "evidence_id": replacement["id"]},
                           {"label": "预算", "evidence_id": evidence_by_input["budget"]}],
            })
            corrected_body = (f"甲单位更正后实际利润为 {{{{fact:{replacement['id']}|2}}}} 万元，"
                              f"计划差额为 {{{{calc:{corrected_difference['id']}|2}}}} 万元，"
                              f"预算完成率为 {{{{calc:{corrected_rate['id']}|1}}}}%，更正依据 {{{{ev:{replacement['id']}}}}}。\n\n"
                              "| 利润比较项目 | 实际 | 预算 | 差额 | 完成率 |\n| --- | ---: | ---: | ---: | ---: |\n"
                              f"| 利润（万元） | {{{{fact:{replacement['id']}|2}}}} | {budget_ref} | {{{{calc:{corrected_difference['id']}|2}}}} | {{{{calc:{corrected_rate['id']}|1}}}}% |\n\n"
                              f"{{{{chart:{corrected_chart['id']}}}}}\n\n| 数据缺口 | 状态 |\n| --- | --- |\n| 产销量、成本 | 待补充 |")
            corrected_body += f"\n\n沿用已核实的差异说明 {{{{fact:{new_evidence['id']}}}}}，来源 {{{{ev:{new_evidence['id']}}}}}。"
            submit_corrected("units:甲单位", corrected_body)
            submit_corrected("group", "更正影响甲单位利润观察，集团合并规则仍待确认。")
            submit_corrected("actions", "请财务核对更正记录及对应利润桥。")
            submit_corrected("sources", f"更正来源为 {{{{ev:{replacement['id']}}}}}，旧版证据仍留存在历史版本。")
            corrected_draft = call("draft", "build", request={"project_id": project["id"], "run_id": corrected_run["id"]})
            call("review", "submit", request={
                "project_id": project["id"], "run_id": corrected_run["id"], "draft_sha256": corrected_draft["sha256"],
                "reviewer_id": "reviewer-4", "verdict": "pass", "issues": [],
            })
            corrected_revision = call("publish", request={"project_id": project["id"], "run_id": corrected_run["id"]})
            corrected_content = Path(corrected_revision["markdown_path"]).read_text(encoding="utf-8")
            self.assertIn("更正后实际利润为 130.00 万元，计划差额为 30.00 万元", corrected_content)
            self.assertEqual(section(corrected_content, "专项来源的独立口径"), section(wording_content, "专项来源的独立口径"))
            self.assertEqual(call("revision", "latest", "--project", project["id"])["id"], corrected_revision["id"])
            self.assertIn("correction.csv", (Path(corrected_revision["markdown_path"]).parent / "changes.md").read_text(encoding="utf-8"))
            self.assertEqual(Path(revision["markdown_path"]).read_text(encoding="utf-8"), content)

            next_correction = root / "next_correction.csv"
            next_correction.write_text("单位,利润总额\n甲单位,140.00\n", encoding="utf-8")
            call("material", "add", request={"project_id": project["id"], "input_id": "actuals", "path": str(next_correction)})
            locked_run = call("run", "start", request={
                "project_id": project["id"], "base_revision_id": corrected_revision["id"],
                "locked_sections": ["units:甲单位"],
            })
            locked_task = call("task", "list", "--project", project["id"], "--run", locked_run["id"])[0]
            locked_cell = call("task", "context", locked_task["id"], "--project", project["id"])["material"]["parsed"]["sheets"]["CSV"]["cells"]["B2"]
            locked_candidate = call("task", "submit", request={
                "project_id": project["id"], "run_id": locked_run["id"], "task_id": locked_task["id"],
                "input_fingerprint": locked_task["input_fingerprint"], "candidates": [{
                    "subject_id": "甲单位", "metric_id": "profit_total", "period": "2026-07", "window": "month",
                    "unit": "万元", "basis": "actuals", "value": locked_cell["value"], "source_value": locked_cell["value"], "source_locator": locked_cell["locator"],
                }],
            })["candidates"][0]
            call("evidence", "decide", request={"project_id": project["id"], "run_id": locked_run["id"], "candidate_id": locked_candidate["id"], "decision": "accept"})
            call("evidence", "decide", request={
                "project_id": project["id"], "run_id": locked_run["id"], "candidate_id": locked_candidate["id"],
                "decision": "replace", "supersedes_evidence_id": replacement["id"], "reason": "再次勘误",
            })
            call("evidence", "freeze", request={"project_id": project["id"], "run_id": locked_run["id"]})
            call("calculate", request={"project_id": project["id"], "run_id": locked_run["id"]})
            request_file.write_text(json.dumps({"project_id": project["id"], "run_id": locked_run["id"],
                                                "report_request": "分析甲单位本月经营与预算执行，纳入再次勘误",
                                                "outline": {"sections": reference["sections"], "unit_names": ["甲单位"]},
                                                "material_uses": [{"material_id": identifier,
                                                                   "use": "context" if identifier in (material_ids_by_input["actuals"], corrected_source["id"]) else "analysis",
                                                                   "reason": "已被新勘误替代" if identifier in (material_ids_by_input["actuals"], corrected_source["id"]) else "本轮有效依据"}
                                                                  for identifier in locked_run["material_ids"]]}, ensure_ascii=False), encoding="utf-8")
            locked_plan = subprocess.run([REPORT, "draft", "plan", "--workspace", str(workspace), "--request", str(request_file)], cwd=root, capture_output=True, text=True)
            self.assertNotEqual(locked_plan.returncode, 0)
            self.assertIn("locked section conflict", locked_plan.stderr)
            self.assertEqual(call("revision", "latest", "--project", project["id"])["id"], corrected_revision["id"])


if __name__ == "__main__":
    unittest.main()
