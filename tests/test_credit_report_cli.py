import json
import os
import shutil
import subprocess
import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path

from credit_test_support import synthetic_credit_cli, registration_table, equity_details, synthetic_review_coverage

PDF = Path(__file__).parent / "fixtures" / "credit_pdf_fixture.pdf"
PROFESSIONAL = Path(__file__).parent / "fixtures" / "credit_professional_records.docx"


class CreditReportCliTests(unittest.TestCase):
    def test_application_financials_and_professional_records_yield_a_reviewable_full_report(self):
        acceptance = os.environ.get("LONG_REPORT_ACCEPTANCE_ROOT")
        directory = Path(acceptance) / self._testMethodName if acceptance else None
        if directory:
            directory.mkdir(parents=True)
        with nullcontext(directory) if directory else tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "projects"
            request_file = root / "request.json"
            cli = synthetic_credit_cli(root)

            def call(*args, request=None):
                command = [*cli, *args, "--workspace", str(workspace)]
                if request is not None:
                    request_file.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
                    command += ["--request", str(request_file)]
                result = subprocess.run(command, cwd=root, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                return json.loads(result.stdout)["data"]

            project = call("project", "create", request={
                "scenario_id": "financial_due_diligence", "scenario_version": "0.3.3", "credit_application_id": "SYN-001",
                "subject_scope": {"business_unit": "甲公司"}, "evaluation_date": "2026-07-31",
            })
            financial = root / "financial.csv"
            financial.write_text('指标,金额（万元）\n营业收入,800\n有息负债,300\n备注,"记录\n\n# 额外章节\n\n## 额外小节\n\n资料。"\n', encoding="utf-8")
            records = root / "professional.docx"
            shutil.copyfile(PROFESSIONAL, records)
            for input_id, source in (("application", PDF), ("financials", financial), ("professional_records", records)):
                call("material", "add", request={"project_id": project["id"], "input_id": input_id, "path": str(source)})
            run = call("run", "start", request={"project_id": project["id"]})
            tasks = call("task", "list", "--project", project["id"], "--run", run["id"])
            initial_tasks = list(tasks)
            facts = {}
            for task in tasks:
                source = call("task", "context", task["id"], "--project", project["id"])["material"]
                if source["input_id"] == "application":
                    fragments = [item for item in source["parsed"]["fragments"] if "Requested amount" in item["value"]]
                    records_to_submit = [("application_amount_text", fragments[0])]
                elif source["input_id"] == "financials":
                    cells = source["parsed"]["sheets"]["CSV"]["cells"]
                    records_to_submit = [("revenue", cells["B2"]), ("debt", cells["B3"]), ("note", cells["B4"])]
                else:
                    records_to_submit = [(metric, item) for metric, item in zip(("construction", "guarantee", "lawsuit"), source["parsed"]["fragments"])]
                submitted = call("task", "submit", request={
                    "project_id": project["id"], "run_id": run["id"], "task_id": task["id"],
                    "input_fingerprint": task["input_fingerprint"],
                    "candidates": [{
                        "subject_id": "甲公司", "metric_id": metric, "period": "2026-07-31",
                        "value": item["value"], "source_value": item["value"], "source_locator": item["locator"],
                        "basis": source["input_id"], "unit": "万元" if metric in ("revenue", "debt") else "text",
                    } for metric, item in records_to_submit],
                })
                for (metric, _), candidate in zip(records_to_submit, submitted["candidates"]):
                    facts[metric] = call("evidence", "decide", request={
                        "project_id": project["id"], "run_id": run["id"], "candidate_id": candidate["id"], "decision": "accept",
                    })
            frozen = call("evidence", "freeze", request={"project_id": project["id"], "run_id": run["id"]})
            self.assertEqual(len(frozen["evidence_ids"]), 7)
            self.assertEqual(call("calculate", request={"project_id": project["id"], "run_id": run["id"]}), [])
            standard_outline = {"sections": project["effective_config"]["outline"]["sections"]}
            invalid_outline = json.loads(json.dumps(standard_outline))
            invalid_outline["sections"][0]["title"] = "任意替换章节"
            request_file.write_text(json.dumps({"project_id": project["id"], "run_id": run["id"],
                "report_request": "审查甲公司", "outline": invalid_outline}, ensure_ascii=False), encoding="utf-8")
            rejected = subprocess.run([*cli, "draft", "plan", "--workspace", str(workspace),
                                       "--request", str(request_file)], capture_output=True, text=True)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("fixed chapter titles", rejected.stderr)
            sections = call("draft", "plan", request={"project_id": project["id"], "run_id": run["id"],
                                                     "report_request": "审查甲公司授信风险与策略",
                                                     "outline": standard_outline, "material_uses": [
                            {"material_id": task["source_id"], "use": "analysis", "reason": "用于合成流程事实与缺口检查"} for task in tasks]})
            by_id = {item["section_id"]: item for item in sections}
            self.assertEqual(set(by_id), {"company", "operations", "financials", "financing", "industry", "risks", "credit", "terms", "conclusion"})

            def fact(metric):
                return "{{fact:" + facts[metric]["id"] + "}}"

            def cite(metric):
                return "{{ev:" + facts[metric]["id"] + "}}"

            outline = standard_outline
            self.assertEqual(call("draft", "context", by_id["credit"]["id"], "--project", project["id"])["section"]["subheadings"],
                             ["一、信用评级", "二、征信情况", "三、涉诉情况"])
            for section_id in by_id:
                context = call("draft", "context", by_id[section_id]["id"], "--project", project["id"])
                self.assertEqual(context["section"]["required_assets"],
                                 next(item["required_assets"] for item in standard_outline["sections"] if item["id"] == section_id))
                self.assertEqual(context["section"]["questions"],
                                 next(item["questions"] for item in standard_outline["sections"] if item["id"] == section_id))
                self.assertEqual(context["writing_guidance"], project["effective_config"]["analysis"]["writing_guidance"])
                self.assertTrue(context["writing_guidance"]["review_checklist"])
                for requirement in ("management_profiles", "table_interpretation", "counterparty_assessment", "operating_stability",
                                    "business_adaptation", "report_expression", "cross_chapter_consistency", "comprehensive_assessment", "credit_policy_application",
                                    "credit_scoring_review", "working_capital_review", "credit_terms_tables", "conclusion_traceability"):
                    self.assertTrue(context["writing_guidance"][requirement],
                                    "Detailed management and business interpretation requirements must reach the writer")

            def chapter(section_id, text):
                headings = next(item["subheadings"] for item in outline["sections"] if item["id"] == section_id)
                return "\n\n".join("## " + title + "\n\n" + (text if i == 0 else "本小节资料未提供，相关判断待核实。")
                                      for i, title in enumerate(headings)) if headings else text

            bodies = {
                "company": chapter("company", "评审对象为甲公司，评价基准为2026-07-31。申请记载：" + fact("application_amount_text") + "，来源 " + cite("application_amount_text") + "。units币种与计量待核，不转换为万元。"),
                "operations": chapter("operations", "在建项目记录：" + fact("construction") + "，来源 " + cite("construction") + "。项目进度和资金安排还需底稿。"),
                "financials": chapter("financials", "财务表营业收入为 " + fact("revenue") + " 万元，有息负债为 " + fact("debt") + " 万元。\n\n| 财务指标 | 金额（万元） |\n| --- | ---: |\n| 营业收入 | " + fact("revenue") + " |\n| 有息负债 | " + fact("debt") + " |"),
                "financing": "机构授信与用信、到期结构资料未提供，不能推断无债务违约。",
                "industry": chapter("industry", "行业政策和竞争地位仍待补充证据。"),
                "risks": chapter("risks", "担保记录：" + fact("guarantee") + "；诉讼记录：" + fact("lawsuit") + "。是不同事项，偿债、关联交易和控制措施仍缺支持。建议核实担保合同、诉讼状态及在建项目资金安排。"),
                "credit": chapter("credit", "未提供正式评级、征信及完整涉诉记录，不推定评级与无诉讼。"),
                "terms": chapter("terms", "本批未提供可核对的外部授信额度、等级和期限结果；不从申请金额自行推定。"),
                "conclusion": chapter("conclusion", "已核对申请、财务和专业记录，担保、诉讼及在建项目均需进一步核验。外部结果和内部政策缺失，本稿待复核，不作批准决定。"),
            }
            bodies["company"] = bodies["company"].replace("## 一、工商信息\n\n",
                "## 一、工商信息\n\n" + registration_table(outline["sections"][0]) + "\n\n", 1)
            bodies["company"] = bodies["company"].replace("## 四、股权、股东及投资情况\n\n",
                "## 四、股权、股东及投资情况\n\n" + equity_details(outline["sections"][0]) + "\n\n", 1)
            for section in outline["sections"]:
                bodies[section["id"]] += "".join("\n\n资料缺口：" + asset + "：合成用例未提供完整业务表，相关能力待核实。" for asset in section["required_assets"])
            order = ("company", "operations", "financials", "financing", "industry", "risks", "credit", "terms", "conclusion")
            for section_id in order:
                call("draft", "submit", request={
                    "project_id": project["id"], "run_id": run["id"], "task_id": by_id[section_id]["id"],
                    "author_id": "credit-writer", "body": bodies[section_id],
                })
            call("draft", "submit", request={"project_id": project["id"], "run_id": run["id"],
                "task_id": by_id["conclusion"]["id"], "author_id": "credit-writer", "replace": True,
                "body": bodies["conclusion"] + "\n\n" + fact("note")})
            request_file.write_text(json.dumps({"project_id": project["id"], "run_id": run["id"]}), encoding="utf-8")
            expanded = subprocess.run([*cli, "draft", "build", "--workspace", str(workspace),
                                       "--request", str(request_file)], capture_output=True, text=True)
            self.assertNotEqual(expanded.returncode, 0)
            self.assertIn("fixed second-level headings", expanded.stderr)
            call("draft", "submit", request={"project_id": project["id"], "run_id": run["id"],
                "task_id": by_id["conclusion"]["id"], "author_id": "credit-writer", "replace": True,
                "body": bodies["conclusion"]})
            draft = call("draft", "build", request={"project_id": project["id"], "run_id": run["id"]})
            content = Path(draft["markdown_path"]).read_text(encoding="utf-8")
            self.assertEqual(content.count("\n# "), 8)
            self.assertIn("Requested amount 100 units", content)
            self.assertIn("案件A已受理", content)
            self.assertIn("未提供可核对的外部授信额度", content)
            call("review", "submit", request={
                "project_id": project["id"], "run_id": run["id"], "draft_sha256": draft["sha256"],
                "reviewer_id": "credit-reviewer", "verdict": "pass", "issues": [], "coverage": synthetic_review_coverage(draft),
            })
            released = call("publish", request={"project_id": project["id"], "run_id": run["id"]})
            self.assertEqual(released["status"], "pending_review")
            self.assertTrue(Path(released["docx_path"]).is_file())

            def next_external_report(value, prior_revision, replaces=None):
                record = root / f"external_{value}.txt"
                record.write_text(f"授信模型结果：额度 {value} 万元；等级由专门流程确认，期限需依等级核对。\n", encoding="utf-8")
                request = {"project_id": project["id"], "input_id": "external_credit_results", "path": str(record)}
                if replaces:
                    request["replaces_material_id"] = replaces
                material = call("material", "add", request=request)
                update = call("run", "start", request={"project_id": project["id"], "base_revision_id": prior_revision["id"]})
                tasks = call("task", "list", "--project", project["id"], "--run", update["id"])
                self.assertEqual(len(tasks), 1)
                source = call("task", "context", tasks[0]["id"], "--project", project["id"])["material"]
                fragment = source["parsed"]["fragments"][0]
                submitted = call("task", "submit", request={"project_id": project["id"], "run_id": update["id"],
                    "task_id": tasks[0]["id"], "input_fingerprint": tasks[0]["input_fingerprint"],
                    "candidates": [{"subject_id": "甲公司", "metric_id": "external_result", "period": "2026-07-31",
                        "value": fragment["value"], "source_value": fragment["value"], "source_locator": fragment["locator"],
                        "basis": "external_credit_results"}]})
                accepted = call("evidence", "decide", request={"project_id": project["id"], "run_id": update["id"],
                    "candidate_id": submitted["candidates"][0]["id"], "decision": "accept"})
                call("evidence", "freeze", request={"project_id": project["id"], "run_id": update["id"]})
                call("calculate", request={"project_id": project["id"], "run_id": update["id"]})
                updated_uses = [item for item in run["report_plan"]["material_uses"] if item["material_id"] != replaces] if "report_plan" in run else [
                    {"material_id": task["source_id"], "use": "analysis", "reason": "用于合成流程事实与缺口检查"} for task in initial_tasks]
                updated_uses = [item for item in updated_uses if item["material_id"] in update["material_ids"]]
                updated_uses.append({"material_id": material["id"], "use": "analysis", "reason": "新增外部结果核对"})
                plan = call("draft", "plan", request={"project_id": project["id"], "run_id": update["id"],
                    "report_request": "补充外部结果后审查", "outline": standard_outline, "material_uses": updated_uses})
                initial_tasks.append({"source_id": material["id"]})
                self.assertNotEqual(next(item for item in plan if item["section_id"] == "terms")["status"], "submitted")
                revised = dict(bodies)
                revised["terms"] = chapter("terms", "已收到外部结果：{{fact:" + accepted["id"] + "}}，来源 {{ev:" + accepted["id"] + "}}。仍须核对模型版本、等级流程和期限规则。")
                revised["terms"] += "".join("\n\n资料缺口：" + asset + "：合成补件只有结果，未提供完整测算和要素依据。"
                                              for asset in next(item for item in outline["sections"] if item["id"] == "terms")["required_assets"])
                revised["conclusion"] = chapter("conclusion", "已核对申请、财务、专业记录和本次外部结果；等级及期限仍按独立流程确认，本稿待复核。")
                for section_id in order:
                    task = next(item for item in call("draft", "plan", request={"project_id": project["id"], "run_id": update["id"]})
                                if item["section_id"] == section_id)
                    if task["status"] != "submitted":
                        call("draft", "submit", request={"project_id": project["id"], "run_id": update["id"],
                            "task_id": task["id"], "author_id": "credit-writer", "body": revised[section_id]})
                complete = call("draft", "build", request={"project_id": project["id"], "run_id": update["id"]})
                self.assertIn(f"额度 {value} 万元", Path(complete["markdown_path"]).read_text(encoding="utf-8"))
                call("review", "submit", request={"project_id": project["id"], "run_id": update["id"],
                    "draft_sha256": complete["sha256"], "reviewer_id": "credit-reviewer", "verdict": "pass", "issues": [], "coverage": synthetic_review_coverage(complete)})
                revision = call("publish", request={"project_id": project["id"], "run_id": update["id"]})
                return material, revision

            supplement, second_revision = next_external_report(50, released)
            correction, third_revision = next_external_report(55, second_revision, supplement["id"])
            self.assertNotEqual(second_revision["id"], third_revision["id"])
            self.assertNotIn("额度 50 万元", Path(third_revision["markdown_path"]).read_text(encoding="utf-8"))
            self.assertEqual(correction["replaces_material_id"], supplement["id"])
            wording = call("run", "start", request={"project_id": project["id"], "base_revision_id": third_revision["id"]})
            self.assertEqual(call("task", "list", "--project", project["id"], "--run", wording["id"]), [])
            call("evidence", "freeze", request={"project_id": project["id"], "run_id": wording["id"]})
            call("calculate", request={"project_id": project["id"], "run_id": wording["id"]})
            wording_plan = call("draft", "plan", request={"project_id": project["id"], "run_id": wording["id"]})
            self.assertTrue(all(item["status"] == "submitted" for item in wording_plan))
            strategy_task = next(item for item in wording_plan if item["section_id"] == "risks")
            call("draft", "submit", request={"project_id": project["id"], "run_id": wording["id"],
                "task_id": strategy_task["id"], "author_id": "credit-writer", "replace": True,
                "body": bodies["risks"] + " 补充核验后再提交有条件建议。"})
            final_draft = call("draft", "build", request={"project_id": project["id"], "run_id": wording["id"]})
            call("review", "submit", request={"project_id": project["id"], "run_id": wording["id"],
                "draft_sha256": final_draft["sha256"], "reviewer_id": "credit-reviewer", "verdict": "pass", "issues": [], "coverage": synthetic_review_coverage(final_draft)})
            final_revision = call("publish", request={"project_id": project["id"], "run_id": wording["id"]})
            self.assertIn("补充核验后再提交", Path(final_revision["markdown_path"]).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
