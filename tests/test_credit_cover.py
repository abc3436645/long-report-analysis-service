"""Only the financial due-diligence cover uses company, amount and reporting fields."""

import tempfile
import copy
import shutil
import yaml
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from docx import Document

from long_report import application
from long_report.application import _cover_metadata, create_project, start_run, get_run
from long_report.rendering import render_docx, verify_docx
from long_report.scenario import load_scenario

SOURCE = Path(__file__).resolve().parents[1] / "scenarios"


def context():
    scenario = load_scenario("financial_due_diligence")
    project = dict(scenario_id="financial_due_diligence", subject_scope=dict(business_unit="江铜华北（天津）铜业有限公司"),
                   evaluation_date="2026-07-31", effective_config=scenario.as_dict())
    run = dict(started_at="2026-10-27T16:30:00+00:00", evidence_snapshot_id="snapshot-1",
               effective_config=scenario.as_dict())
    point = dict(id="amount-1", subject_id=project["subject_scope"]["business_unit"], period="2026-07-31",
                 basis="application", metric_id="credit_amount", value="100000", unit="万元")
    return project, run, point


class CreditCoverTests(unittest.TestCase):
    def test_cover_config_is_specific_to_due_diligence(self):
        cover = load_scenario("financial_due_diligence").manifest["presentation"].get("cover")
        self.assertIsNotNone(cover)
        self.assertEqual(cover["title_template"], "关于{business_unit}{credit_amount}综合授信调查报告")
        self.assertEqual([field["label"] for field in cover["fields"]], ["呈报部门", "客户经理", "呈报时间"])
        for other in ("budget_operations", "compensation_analysis"):
            self.assertNotIn("cover", load_scenario(other).manifest["presentation"])

    def test_title_uses_frozen_amount_and_reporting_date_uses_run_in_shanghai(self):
        project, run, point = context()
        metadata = _cover_metadata(project, run, [point], [], [])
        self.assertEqual(application._report_title(project, run, metadata), "关于江铜华北（天津）铜业有限公司10亿元综合授信调查报告")
        self.assertEqual(metadata["呈报部门"], "XXXX")
        self.assertEqual(metadata["客户经理"], "XXXX")
        self.assertEqual(metadata["呈报时间"], "2026年10月28日")
        self.assertEqual(metadata["额度证据"], "amount-1")

    def test_missing_ambiguous_or_mismatched_amount_is_disclosed_instead_of_guessed(self):
        project, run, point = context()
        cases = [[], [point, {**point, "id": "other"}], [{**point, "unit": "units"}],
                 [{**point, "value": "NaN"}], [{**point, "basis": "external_credit_results"}],
                 [{**point, "subject_id": "乙公司"}], [{**point, "period": "2025-07-31"}]]
        for evidence in cases:
            with self.subTest(evidence=evidence):
                metadata = _cover_metadata(project, run, evidence, [], [])
                self.assertIn("授信额度待核实", application._report_title(project, run, metadata))
                self.assertNotIn("额度证据", metadata)

    def test_embedded_currency_unit_cannot_override_an_unknown_or_conflicting_declared_unit(self):
        project, run, point = context()
        for unit in ("美元", "units", "万元"):
            metadata = _cover_metadata(project, run, [{**point, "value": "10亿元", "unit": unit}], [], [])
            with self.subTest(unit=unit):
                self.assertIn("待核实", metadata["授信额度"])
                self.assertNotIn("额度证据", metadata)
        for unit in ("亿元", "text", None):
            metadata = _cover_metadata(project, run, [{**point, "value": "10亿元", "unit": unit}], [], [])
            with self.subTest(unit=unit):
                self.assertEqual(metadata["授信额度"], "10亿元")

    def test_invalid_cover_configuration_is_rejected_before_project_creation(self):
        original = load_scenario("financial_due_diligence").manifest["presentation"]["cover"]
        changes = [lambda c: c.update(timezone="Invalid/Zone"),
                   lambda c: c.update(amount_selector="unknown"),
                   lambda c: c.update(title_template="{business_unit.__class__}{credit_amount}"),
                   lambda c: c["fields"].append(copy.deepcopy(c["fields"][0])),
                   lambda c: c["fields"][0].update(label="数据性质"),
                   lambda c: c["fields"][2].update(default="2020年1月1日")]
        for mutate in changes:
            with self.subTest(mutate=mutate), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                shutil.copytree(SOURCE / "financial_due_diligence", root / "financial_due_diligence")
                path = root / "financial_due_diligence/scenario.yaml"
                data = yaml.safe_load(path.read_text(encoding="utf-8"))
                mutate(data["presentation"]["cover"])
                path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "cover"):
                    load_scenario("financial_due_diligence", root)

    def test_project_accepts_reporting_people_but_not_forged_dates_or_manual_title(self):
        with tempfile.TemporaryDirectory() as temporary:
            request = dict(scenario_id="financial_due_diligence", scenario_version="0.3.1",
                           credit_application_id="COVER-1", subject_scope=dict(business_unit="甲公司"),
                           evaluation_date="2026-07-31", report_metadata=dict(prepared_by="公司业务部", account_manager="甲经理"))
            project = create_project(Path(temporary), request)
            self.assertEqual(project["report_metadata"], request["report_metadata"])
            for changed in ({**request, "report_title": "随意标题"},
                            {**request, "report_metadata": {"run_date": "2020年1月1日"}}):
                with self.subTest(changed=changed), self.assertRaisesRegex(ValueError, "report_title|report_metadata"):
                    create_project(Path(temporary), changed)
            run = start_run(Path(temporary), dict(project_id=project["id"]))
            self.assertIsNotNone(datetime.fromisoformat(run["started_at"]).tzinfo)
            self.assertEqual(get_run(Path(temporary), project["id"], run["id"])["started_at"], run["started_at"])

    def test_word_cover_contains_exact_three_reporting_lines_and_keeps_audit_metadata(self):
        project, run, point = context()
        project["report_metadata"] = dict(prepared_by="公司业务部", account_manager="甲经理")
        metadata = _cover_metadata(project, run, [point], [], [])
        title = application._report_title(project, run, metadata)
        presentation = run["effective_config"]["scenario"]["presentation"]
        template = SOURCE / "financial_due_diligence" / run["effective_config"]["scenario"]["template"]
        markdown = "# 第一章 公司基本情况\n\n正文说明。"
        with tempfile.TemporaryDirectory() as temporary, patch("long_report.rendering._installed_fonts", return_value={"仿宋"}):
            output = Path(temporary) / "cover.docx"
            render_docx(markdown, template, output, title, presentation=presentation, metadata=metadata)
            document = Document(output)
            self.assertEqual([p.text for p in document.paragraphs if p.style.name == "Title"], [title])
            self.assertEqual([p.text for p in document.paragraphs if p.style.name == "Cover Metadata"],
                             ["呈报部门：公司业务部", "客户经理：甲经理", "呈报时间：2026年10月28日"])
            self.assertIn("数据版本", metadata)
            verify_docx(markdown, output, {}, metadata=metadata, presentation=presentation)
            next(p for p in document.paragraphs if p.style.name == "Cover Metadata").text = "呈报部门：错误"
            document.save(output)
            with self.assertRaisesRegex(ValueError, "cover"):
                verify_docx(markdown, output, {}, metadata=metadata, presentation=presentation)


if __name__ == "__main__":
    unittest.main()
