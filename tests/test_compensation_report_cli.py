import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
import yaml


REPORT = Path(sys.executable).with_name("report")


class CompensationReportCliTests(unittest.TestCase):
    def test_accrual_groups_and_small_sample_suppression_reach_the_full_report(self):
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
                "scenario_id": "compensation_analysis", "scenario_version": "0.2.0",
                "subject_scope": {"organization": "合成企业", "groups": ["研发", "管理"]},
                "report_period": "2026-07",
                "overrides": {
                    "business_definitions.pay_components": "base,bonus",
                    "business_definitions.accounting_basis": "accrual",
                    "business_definitions.headcount_or_fte_rule": "distinct_people_at_period_end",
                    "business_definitions.minimum_group_size": 3,
                },
            })
            payroll = root / "payroll.csv"
            payroll.write_text(
                "person_id,component,accrual_period,payment_period,amount\n"
                "P1,base,2026-07,2026-07,100\nP1,bonus,2026-07,2026-07,20\n"
                "P2,base,2026-07,2026-07,120\nP3,base,2026-07,2026-07,110\n"
                "P4,base,2026-07,2026-07,200\nP1,bonus,2026-06,2026-07,50\n",
                encoding="utf-8",
            )
            roster = root / "roster.csv"
            roster.write_text(
                "person_id,group,effective_period\nP1,研发,2026-01\nP2,研发,2026-01\n"
                "P3,研发,2026-01\nP4,管理,2026-01\n",
                encoding="utf-8",
            )
            originals = {}
            for input_id, source in (("payroll", payroll), ("roster", roster)):
                originals[input_id] = call("material", "add", request={"project_id": project["id"], "input_id": input_id, "path": str(source)})
            run = call("run", "start", request={"project_id": project["id"]})
            for task in call("task", "list", "--project", project["id"], "--run", run["id"]):
                call("task", "submit", request={
                    "project_id": project["id"], "run_id": run["id"], "task_id": task["id"],
                    "input_fingerprint": task["input_fingerprint"], "candidates": [],
                })
            call("evidence", "freeze", request={"project_id": project["id"], "run_id": run["id"]})
            calculations = call("calculate", request={"project_id": project["id"], "run_id": run["id"]})
            safe = next(item for item in calculations if item["subject_id"] == "研发")
            small = next(item for item in calculations if item["subject_id"] == "管理")
            overall = next(item for item in calculations if item["subject_id"] == "合成企业")
            self.assertEqual((safe["status"], safe["value"], safe["sample_size"]), ("calculated", "350", 3))
            self.assertEqual((small["status"], small["value"]), ("suppressed", None))
            self.assertEqual((overall["status"], overall["value"]), ("suppressed", None))
            sections = call("draft", "plan", request={"project_id": project["id"], "run_id": run["id"],
                                                     "report_request": "分析研发与管理群体薪酬结构和展示限制",
                                                     "outline": yaml.safe_load((Path(__file__).parent / "fixtures/compensation_reference_outline.yaml").read_text(encoding="utf-8"))})
            by_id = {item["section_id"]: item for item in sections}
            request_file.write_text(json.dumps({
                "project_id": project["id"], "run_id": run["id"], "task_id": by_id["population"]["id"],
                "author_id": "pay-writer", "body": "P4 的个人薪酬应单列。",
            }, ensure_ascii=False), encoding="utf-8")
            unsafe = subprocess.run([REPORT, "draft", "submit", "--workspace", str(workspace), "--request", str(request_file)], cwd=root, capture_output=True, text=True)
            self.assertNotEqual(unsafe.returncode, 0)
            bodies = {
                "population": "本期按有效名册将人员分为研发与管理两组。管理组样本未达展示下限，不能展示个人或该组薪酬。",
                "pay_structure": "研发组本期应计薪酬为 {{calc:" + safe["id"] + "}} 元。支付于本期但归属于上期的奖金不计入本期。\n\n| 群体 | 应计薪酬（元） |\n| --- | ---: |\n| 研发 | {{calc:" + safe["id"] + "}} |",
                "group_differences": "管理组及可反推该组的总体合计均已抑制；现阶段不比较两组薪酬差异。",
                "budget_productivity": "未提供预算及可比的人效分子，且人效公式未定义，不计算人效。",
                "recommendations": "先确认薪酬组成、人员调整与预算口径，再讨论结构优化；小样本保持抑制。",
                "appendix": "本报告采用合成示例：应计期间、distinct_people_at_period_end 人数口径及最小展示样本三人。小样本和总体均不展示。",
                "summary": "本期仅展示达到样本下限的研发组应计薪酬；管理组及总体合计已抑制，人效待定义和补件。",
            }
            for section_id in ("population", "pay_structure", "group_differences", "budget_productivity", "recommendations", "appendix", "summary"):
                call("draft", "submit", request={
                    "project_id": project["id"], "run_id": run["id"], "task_id": by_id[section_id]["id"],
                    "author_id": "pay-writer", "body": bodies[section_id],
                })
            draft = call("draft", "build", request={"project_id": project["id"], "run_id": run["id"]})
            report = Path(draft["markdown_path"]).read_text(encoding="utf-8")
            self.assertIn("350 元", report)
            self.assertNotIn("P4", report)
            self.assertNotIn("200 元", report)
            Path(draft["markdown_path"]).write_text(report + "\nP4\n", encoding="utf-8")
            privacy = call("validate", request={"project_id": project["id"], "run_id": run["id"]})
            self.assertFalse(privacy["checks"]["personal_pay_hidden"])
            Path(draft["markdown_path"]).write_text(report, encoding="utf-8")
            call("review", "submit", request={
                "project_id": project["id"], "run_id": run["id"], "draft_sha256": draft["sha256"],
                "reviewer_id": "pay-reviewer", "verdict": "pass", "issues": [],
            })
            revision = call("publish", request={"project_id": project["id"], "run_id": run["id"]})
            self.assertEqual(revision["status"], "pending_review")
            self.assertTrue(Path(revision["docx_path"]).is_file())
            corrected = root / "payroll_corrected.csv"
            corrected.write_text(payroll.read_text(encoding="utf-8").replace("P2,base,2026-07,2026-07,120", "P2,base,2026-07,2026-07,130"), encoding="utf-8")
            replacement = call("material", "add", request={
                "project_id": project["id"], "input_id": "payroll", "path": str(corrected),
                "replaces_material_id": originals["payroll"]["id"],
            })
            self.assertEqual(replacement["replaces_material_id"], originals["payroll"]["id"])
            second = call("run", "start", request={"project_id": project["id"], "base_revision_id": revision["id"]})
            self.assertNotIn(originals["payroll"]["id"], second["material_ids"])
            for task in call("task", "list", "--project", project["id"], "--run", second["id"]):
                call("task", "submit", request={"project_id": project["id"], "run_id": second["id"],
                    "task_id": task["id"], "input_fingerprint": task["input_fingerprint"], "candidates": []})
            call("evidence", "freeze", request={"project_id": project["id"], "run_id": second["id"]})
            recalculated = call("calculate", request={"project_id": project["id"], "run_id": second["id"]})
            self.assertEqual(next(item["value"] for item in recalculated if item["subject_id"] == "研发"), "360")
            changed_safe = next(item for item in recalculated if item["subject_id"] == "研发")
            second_plan = call("draft", "plan", request={"project_id": project["id"], "run_id": second["id"]})
            self.assertEqual(next(item for item in second_plan if item["section_id"] == "population")["status"], "submitted")
            self.assertEqual(next(item for item in second_plan if item["section_id"] == "pay_structure")["status"], "ready")
            revised_bodies = {key: value.replace(safe["id"], changed_safe["id"]) for key, value in bodies.items()}
            for section_id in ("pay_structure", "group_differences", "budget_productivity", "recommendations", "appendix", "summary"):
                task = next(item for item in call("draft", "plan", request={"project_id": project["id"], "run_id": second["id"]})
                            if item["section_id"] == section_id)
                if task["status"] != "submitted":
                    call("draft", "submit", request={"project_id": project["id"], "run_id": second["id"],
                        "task_id": task["id"], "author_id": "pay-writer", "body": revised_bodies[section_id]})
            second_draft = call("draft", "build", request={"project_id": project["id"], "run_id": second["id"]})
            self.assertIn("360 元", Path(second_draft["markdown_path"]).read_text(encoding="utf-8"))
            call("review", "submit", request={"project_id": project["id"], "run_id": second["id"],
                "draft_sha256": second_draft["sha256"], "reviewer_id": "pay-reviewer", "verdict": "pass", "issues": []})
            second_revision = call("publish", request={"project_id": project["id"], "run_id": second["id"]})
            self.assertNotEqual(second_revision["id"], revision["id"])
            productivity = root / "output.csv"
            productivity.write_text("group,period,output\n研发,2026-07,1000\n", encoding="utf-8")
            call("material", "add", request={"project_id": project["id"], "input_id": "productivity_sources", "path": str(productivity)})
            third = call("run", "start", request={"project_id": project["id"], "base_revision_id": second_revision["id"]})
            for task in call("task", "list", "--project", project["id"], "--run", third["id"]):
                call("task", "submit", request={"project_id": project["id"], "run_id": third["id"],
                    "task_id": task["id"], "input_fingerprint": task["input_fingerprint"], "candidates": []})
            call("evidence", "freeze", request={"project_id": project["id"], "run_id": third["id"]})
            call("calculate", request={"project_id": project["id"], "run_id": third["id"]})
            third_plan = call("draft", "plan", request={"project_id": project["id"], "run_id": third["id"]})
            self.assertEqual(next(item for item in third_plan if item["section_id"] == "pay_structure")["status"], "submitted")
            self.assertEqual(next(item for item in third_plan if item["section_id"] == "budget_productivity")["status"], "ready")
            for section_id in ("budget_productivity", "group_differences", "recommendations", "appendix", "summary"):
                task = next(item for item in call("draft", "plan", request={"project_id": project["id"], "run_id": third["id"]})
                            if item["section_id"] == section_id)
                if task["status"] != "submitted":
                    body = revised_bodies[section_id]
                    if section_id == "budget_productivity":
                        body = "已补群体产出来源，但人效公式尚未定义，不能把产出值直接当做人效结果。"
                    call("draft", "submit", request={"project_id": project["id"], "run_id": third["id"],
                        "task_id": task["id"], "author_id": "pay-writer", "body": body})
            third_draft = call("draft", "build", request={"project_id": project["id"], "run_id": third["id"]})
            call("review", "submit", request={"project_id": project["id"], "run_id": third["id"],
                "draft_sha256": third_draft["sha256"], "reviewer_id": "pay-reviewer", "verdict": "pass", "issues": []})
            third_revision = call("publish", request={"project_id": project["id"], "run_id": third["id"]})
            fourth = call("run", "start", request={"project_id": project["id"], "base_revision_id": third_revision["id"]})
            self.assertEqual(call("task", "list", "--project", project["id"], "--run", fourth["id"]), [])
            call("evidence", "freeze", request={"project_id": project["id"], "run_id": fourth["id"]})
            call("calculate", request={"project_id": project["id"], "run_id": fourth["id"]})
            fourth_plan = call("draft", "plan", request={"project_id": project["id"], "run_id": fourth["id"]})
            self.assertTrue(all(item["status"] == "submitted" for item in fourth_plan))
            summary_task = next(item for item in fourth_plan if item["section_id"] == "summary")
            call("draft", "submit", request={"project_id": project["id"], "run_id": fourth["id"],
                "task_id": summary_task["id"], "author_id": "pay-writer", "replace": True,
                "body": revised_bodies["summary"] + " 新增材料仅用于提示进一步核对人效口径。"})
            fourth_draft = call("draft", "build", request={"project_id": project["id"], "run_id": fourth["id"]})
            call("review", "submit", request={"project_id": project["id"], "run_id": fourth["id"],
                "draft_sha256": fourth_draft["sha256"], "reviewer_id": "pay-reviewer", "verdict": "pass", "issues": []})
            final_revision = call("publish", request={"project_id": project["id"], "run_id": fourth["id"]})
            self.assertNotEqual(final_revision["id"], third_revision["id"])
            self.assertEqual(Path(final_revision["markdown_path"]).read_text(encoding="utf-8").count("360 元"), 1)


if __name__ == "__main__":
    unittest.main()
