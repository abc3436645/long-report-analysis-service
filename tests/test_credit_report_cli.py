import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
import yaml

REPORT = Path(sys.executable).with_name("report")
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

            def call(*args, request=None):
                command = [REPORT, *args, "--workspace", str(workspace)]
                if request is not None:
                    request_file.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
                    command += ["--request", str(request_file)]
                result = subprocess.run(command, cwd=root, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                return json.loads(result.stdout)["data"]

            project = call("project", "create", request={
                "scenario_id": "credit_review", "scenario_version": "0.2.0", "credit_application_id": "SYN-001",
                "subject_scope": {"business_unit": "甲公司"}, "evaluation_date": "2026-07-31",
            })
            financial = root / "financial.csv"
            financial.write_text("指标,金额（万元）\n营业收入,800\n有息负债,300\n", encoding="utf-8")
            records = root / "professional.docx"
            shutil.copyfile(PROFESSIONAL, records)
            for input_id, source in (("application", PDF), ("financials", financial), ("professional_records", records)):
                call("material", "add", request={"project_id": project["id"], "input_id": input_id, "path": str(source)})
            run = call("run", "start", request={"project_id": project["id"]})
            tasks = call("task", "list", "--project", project["id"], "--run", run["id"])
            facts = {}
            for task in tasks:
                source = call("task", "context", task["id"], "--project", project["id"])["material"]
                if source["input_id"] == "application":
                    fragments = [item for item in source["parsed"]["fragments"] if "Requested amount" in item["value"]]
                    records_to_submit = [("application_amount_text", fragments[0])]
                elif source["input_id"] == "financials":
                    cells = source["parsed"]["sheets"]["CSV"]["cells"]
                    records_to_submit = [("revenue", cells["B2"]), ("debt", cells["B3"])]
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
            self.assertEqual(len(frozen["evidence_ids"]), 6)
            self.assertEqual(call("calculate", request={"project_id": project["id"], "run_id": run["id"]}), [])
            sections = call("draft", "plan", request={"project_id": project["id"], "run_id": run["id"],
                                                     "report_request": "审查甲公司授信风险与策略",
                                                     "outline": yaml.safe_load((Path(__file__).parent / "fixtures/credit_reference_outline.yaml").read_text(encoding="utf-8"))})
            by_id = {item["section_id"]: item for item in sections}
            self.assertEqual(set(by_id), {"summary", "scope", "overview", "financial_risks", "external_results", "strategy", "appendix"})

            def fact(metric):
                return "{{fact:" + facts[metric]["id"] + "}}"

            def cite(metric):
                return "{{ev:" + facts[metric]["id"] + "}}"

            bodies = {
                "scope": "评审对象为甲公司，评价基准为 2026-07-31。申请材料记载：" + fact("application_amount_text") + "，来源 " + cite("application_amount_text") + "。其中 units 的计量与币种尚未核实，不转换为万元。",
                "overview": "在建项目记录：" + fact("construction") + "，来源 " + cite("construction") + "。项目进度和资金安排还需底稿。",
                "financial_risks": "财务表营业收入为 " + fact("revenue") + " 万元，有息负债为 " + fact("debt") + " 万元。担保记录：" + fact("guarantee") + "；诉讼记录：" + fact("lawsuit") + "。担保、诉讼是不同事项，不按材料出现次数重复累计；偿债、关联交易和控制措施仍缺支持。\n\n| 财务指标 | 金额（万元） |\n| --- | ---: |\n| 营业收入 | " + fact("revenue") + " |\n| 有息负债 | " + fact("debt") + " |",
                "external_results": "本批未提供可核对的外部授信额度、等级和期限结果；不从申请金额自行推定。",
                "strategy": "建议先核实有息负债的到期结构、担保合同、诉讼状态及在建项目资金安排，再按已确认制度提出条件性授信策略。本报告不作批准决定。",
                "appendix": "申请来源 " + cite("application_amount_text") + "；担保来源 " + cite("guarantee") + "；诉讼来源 " + cite("lawsuit") + "。需补外部结果、偿债计划及关联交易记录。",
                "summary": "已核对申请、财务和专业记录，担保、诉讼及在建项目均需进一步核验。外部结果和内部政策缺失，本稿为待复核评审材料，不给出授信等级或期限。",
            }
            for section_id in ("scope", "overview", "financial_risks", "external_results", "strategy", "appendix", "summary"):
                call("draft", "submit", request={
                    "project_id": project["id"], "run_id": run["id"], "task_id": by_id[section_id]["id"],
                    "author_id": "credit-writer", "body": bodies[section_id],
                })
            draft = call("draft", "build", request={"project_id": project["id"], "run_id": run["id"]})
            content = Path(draft["markdown_path"]).read_text(encoding="utf-8")
            self.assertEqual(content.count("\n# "), 6)
            self.assertIn("Requested amount 100 units", content)
            self.assertIn("案件A已受理", content)
            self.assertIn("未提供可核对的外部授信额度", content)
            call("review", "submit", request={
                "project_id": project["id"], "run_id": run["id"], "draft_sha256": draft["sha256"],
                "reviewer_id": "credit-reviewer", "verdict": "pass", "issues": [],
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
                plan = call("draft", "plan", request={"project_id": project["id"], "run_id": update["id"]})
                self.assertNotEqual(next(item for item in plan if item["section_id"] == "external_results")["status"], "submitted")
                revised = dict(bodies)
                revised["external_results"] = "已收到外部结果：{{fact:" + accepted["id"] + "}}，来源 {{ev:" + accepted["id"] + "}}。仍须核对模型版本、等级流程和期限规则。"
                revised["appendix"] = bodies["appendix"] + " 外部结果来源 {{ev:" + accepted["id"] + "}}。"
                revised["summary"] = "已核对申请、财务、专业记录和本次外部结果；等级及期限仍按独立流程确认，本稿待复核。"
                for section_id in ("scope", "overview", "financial_risks", "external_results", "strategy", "appendix", "summary"):
                    task = next(item for item in call("draft", "plan", request={"project_id": project["id"], "run_id": update["id"]})
                                if item["section_id"] == section_id)
                    if task["status"] != "submitted":
                        call("draft", "submit", request={"project_id": project["id"], "run_id": update["id"],
                            "task_id": task["id"], "author_id": "credit-writer", "body": revised[section_id]})
                complete = call("draft", "build", request={"project_id": project["id"], "run_id": update["id"]})
                self.assertIn(f"额度 {value} 万元", Path(complete["markdown_path"]).read_text(encoding="utf-8"))
                call("review", "submit", request={"project_id": project["id"], "run_id": update["id"],
                    "draft_sha256": complete["sha256"], "reviewer_id": "credit-reviewer", "verdict": "pass", "issues": []})
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
            strategy_task = next(item for item in wording_plan if item["section_id"] == "strategy")
            call("draft", "submit", request={"project_id": project["id"], "run_id": wording["id"],
                "task_id": strategy_task["id"], "author_id": "credit-writer", "replace": True,
                "body": bodies["strategy"] + " 补充核验后再提交有条件建议。"})
            final_draft = call("draft", "build", request={"project_id": project["id"], "run_id": wording["id"]})
            call("review", "submit", request={"project_id": project["id"], "run_id": wording["id"],
                "draft_sha256": final_draft["sha256"], "reviewer_id": "credit-reviewer", "verdict": "pass", "issues": []})
            final_revision = call("publish", request={"project_id": project["id"], "run_id": wording["id"]})
            self.assertIn("补充核验后再提交", Path(final_revision["markdown_path"]).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
