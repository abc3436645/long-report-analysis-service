"""Financial review must not amplify extraction and arithmetic errors into credit decisions."""
import unittest
from decimal import Decimal

from long_report.financials import calculate_financials, validate_financial_body, review_requirements, validate_review_coverage


class FinancialQualityTests(unittest.TestCase):
    def fact(self, metric, value, **extra):
        return {"id": metric, "metric_id": "fin." + metric, "value": value, "subject_id": "甲公司",
                "period": "2026-06-30", "period_start": "2026-01-01", "period_days": 180,
                "financial_scope": "standalone", "unit": "万元", **extra}

    def test_turnover_days_and_percent_are_calculated_with_their_real_scale(self):
        facts = [self.fact("revenue", "1480090.47"), self.fact("net_profit", "734.76"),
                 self.fact("receivables_open", "15583.64"), self.fact("receivables_close", "54713.73")]
        results = {x["metric_id"]: x for x in calculate_financials(facts, ["net_margin", "receivables_turnover", "receivables_days"])}
        self.assertAlmostEqual(float(results["net_margin"]["value"]), .04964291)
        self.assertAlmostEqual(float(results["receivables_days"]["value"]), 4.27457877)
        self.assertEqual(results["net_margin"]["annualization"], "none")
        self.assertEqual(results["net_margin"]["precision"], 34)
        self.assertEqual(len(results["receivables_days"]["input_evidence_ids"]), 3)

    def test_unknown_scope_zero_denominator_and_incomplete_average_cannot_yield_a_number(self):
        for facts, status in [([self.fact("revenue", "0"), self.fact("net_profit", "10")], "zero_denominator"),
                              ([self.fact("revenue", "100", financial_scope=None), self.fact("net_profit", "10", financial_scope=None)], "unknown_scope"),
                              ([self.fact("revenue", "100")], "missing_inputs")]:
            result = calculate_financials(facts, ["net_margin"])[0]
            self.assertEqual(result["status"], status)
            self.assertIsNone(result["value"])
        result = calculate_financials([self.fact("revenue", "100"), self.fact("receivables_close", "10")], ["receivables_turnover"])[0]
        self.assertEqual(result["status"], "missing_inputs")

    def test_units_convert_but_different_scopes_and_periods_never_mix(self):
        facts = [self.fact("revenue", "1000000", unit="元"), self.fact("net_profit", "10"),
                 self.fact("net_profit", "999", financial_scope="consolidated")]
        results = calculate_financials(facts, ["net_margin"])
        standalone = next(x for x in results if x["financial_scope"] == "standalone")
        self.assertEqual(Decimal(standalone["value"]), Decimal("10"))
        self.assertNotEqual(results[0]["id"], results[1]["id"])

    def test_unbound_table_values_and_prose_rates_are_rejected_while_dates_are_structural(self):
        section = {"required_assets": []}
        for body in ["| 指标 | 2025年 |\n| --- | --- |\n| 净利率 | 0.78% |", "周转为43天。", "金额1,000。", "### 授信利率3.5%"]:
            with self.assertRaisesRegex(ValueError, "unbound financial number"):
                validate_financial_body(body, section)
        validate_financial_body("表3-1 财务比率表\n\n| 指标 | 2025年 |\n| --- | --- |\n| 净利率 | {{calc:c1|4}}% |\n\n评价日期2026-06-30。", section)

    def test_assets_need_a_real_table_or_a_named_gap(self):
        section = {"required_assets": ["现金流量表"]}
        with self.assertRaisesRegex(ValueError, "required financial asset"):
            validate_financial_body("现金流量表尚待关注。", section)
        validate_financial_body("资料缺口：现金流量表：未提供期间流量，不能评价经营现金。", section)

    def test_review_must_cover_every_section_table_and_decision_with_real_locations(self):
        md = "# 第一章\n\n## 一、工商信息\n\n公司资料未提供。\n\n| 项目 | 内容 |\n| --- | --- |\n| 主体 | 甲公司 |\n"
        outline = {"sections": [{"id": "company", "title": "第一章", "subheadings": ["一、工商信息"]}]}
        requirements = review_requirements(md, outline)
        with self.assertRaisesRegex(ValueError, "review coverage"):
            validate_review_coverage([], requirements, md, set())
        entries = [{"id": x["id"], "locator": x["locator"], "quote": md.splitlines()[int(x["locator"].split(":")[1])-1],
                    "evidence_refs": [], "assessment": "缺资料，仅保留本节限制，没有作肯定判断。", "result": "gap"} for x in requirements]
        validate_review_coverage(entries, requirements, md, set())
        entries[0]["quote"] = "不存在的正文"
        with self.assertRaisesRegex(ValueError, "review location"):
            validate_review_coverage(entries, requirements, md, set())


class FinancialQualityCliTests(unittest.TestCase):
    def test_unread_pages_and_calculations_survive_the_full_review_gate(self):
        import json
        import subprocess
        import tempfile
        from pathlib import Path
        from pypdf import PdfReader, PdfWriter
        from credit_test_support import synthetic_credit_cli, registration_table, equity_details, synthetic_review_coverage
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cli = synthetic_credit_cli(root)
            workspace = root / "projects"
            def call(*args, request=None, fails=None):
                command = [*cli, *args, "--workspace", str(workspace)]
                if request is not None:
                    path = root / "request.json"
                    path.write_text(json.dumps(request, ensure_ascii=False))
                    command += ["--request", str(path)]
                result = subprocess.run(command, capture_output=True, text=True)
                if fails:
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(fails, result.stderr)
                    return
                self.assertEqual(result.returncode, 0, result.stderr)
                return json.loads(result.stdout)["data"]
            project = call("project", "create", request={"scenario_id": "financial_due_diligence", "scenario_version": "0.3.3",
                "credit_application_id": "SYN-MIXED", "subject_scope": {"business_unit": "甲公司"}, "evaluation_date": "2026-06-30"})
            writer = PdfWriter()
            writer.add_page(PdfReader(Path(__file__).parent / "fixtures/credit_pdf_fixture.pdf").pages[0])
            writer.add_blank_page(width=595, height=842)
            mixed = root / "mixed.pdf"
            with mixed.open("wb") as output:
                writer.write(output)
            material = call("material", "add", request={"project_id": project["id"], "input_id": "application", "path": str(mixed)})
            self.assertEqual(material["parsed"]["coverage"]["unread_pages"], [2])
            financial = root / "financial.csv"
            financial.write_text("指标,金额\nrevenue,1480090.47\nnet_profit,734.76\nreceivables_open,15583.64\nreceivables_close,54713.73\n")
            finance = call("material", "add", request={"project_id": project["id"], "input_id": "financials", "path": str(financial)})
            run = call("run", "start", request={"project_id": project["id"]})
            tasks = call("task", "list", "--project", project["id"], "--run", run["id"])
            facts = []
            for task in tasks:
                candidates = []
                if task["source_id"] == finance["id"]:
                    for i, metric in enumerate(["revenue", "net_profit", "receivables_open", "receivables_close"], 2):
                        cell = finance["parsed"]["sheets"]["CSV"]["cells"][f"B{i}"]
                        candidates.append({"subject_id": "甲公司", "metric_id": "fin." + metric, "period": "2026-06-30",
                            "period_start": "2026-01-01", "period_days": 180, "financial_scope": "standalone", "basis": "financials",
                            "unit": "万元", "source_locator": cell["locator"], "source_value": cell["value"], "value": cell["value"]})
                submitted = call("task", "submit", request={"project_id": project["id"], "run_id": run["id"], "task_id": task["id"],
                    "input_fingerprint": task["input_fingerprint"], "candidates": candidates})
                for candidate in submitted["candidates"]:
                    facts.append(call("evidence", "decide", request={"project_id": project["id"], "run_id": run["id"],
                        "candidate_id": candidate["id"], "decision": "accept"}))
            frozen = call("evidence", "freeze", request={"project_id": project["id"], "run_id": run["id"]})
            self.assertIn(material["id"], [x["material_id"] for x in frozen["material_coverage"] if x["status"] == "not_extracted"])
            calculations = call("calculate", request={"project_id": project["id"], "run_id": run["id"]})
            days = next(x for x in calculations if x["metric_id"] == "receivables_days")
            self.assertAlmostEqual(float(days["value"]), 4.27457877)
            plan_request = {"project_id": project["id"], "run_id": run["id"], "report_request": "审查合成甲公司",
                            "outline": {"sections": project["effective_config"]["outline"]["sections"]}}
            call("draft", "plan", request=plan_request, fails="material_uses")
            plan_request["material_uses"] = [{"material_id": material["id"], "use": "context", "reason": "未核页待复核，仅归档背景"},
                                             {"material_id": finance["id"], "use": "analysis", "reason": "数值复算"}]
            planned = call("draft", "plan", request=plan_request)
            sections = project["effective_config"]["outline"]["sections"]
            for section, task in zip(sections, planned):
                body = "\n\n".join("## " + heading + "\n\n本小节资料不足，仅保留可核事实。" for heading in section["subheadings"]) or "融资资料未提供。"
                if section["id"] == "company":
                    body = body.replace("## 一、工商信息\n\n", "## 一、工商信息\n\n" + registration_table(section) + "\n\n")
                    body = body.replace("## 四、股权、股东及投资情况\n\n", "## 四、股权、股东及投资情况\n\n" + equity_details(section) + "\n\n")
                body += "".join("\n\n资料缺口：" + asset + "：未提供完整表，不能评价相应能力。" for asset in section["required_assets"])
                if section["id"] == "financials":
                    body += "\n\n" + "；".join("{{fact:" + f["id"] + "}}万元" for f in facts)
                    body += "\n\n应收周转天数为{{calc:" + days["id"] + "|4}}天，依据{{ev:" + facts[0]["id"] + "}}。"
                    call("draft", "submit", request={"project_id": project["id"], "run_id": run["id"], "task_id": task["id"],
                        "author_id": "writer", "body": body + "\n\n| 指标 | 金额（万元） |\n| --- | --- |\n| 裸数 | 43 |"}, fails="unbound financial number")
                    financial_body, financial_task = body, task
                call("draft", "submit", request={"project_id": project["id"], "run_id": run["id"], "task_id": task["id"], "author_id": "writer", "body": body})
            # Facts hidden in editorial comments remain bound, but cannot satisfy business analysis coverage.
            base = {"project_id": project["id"], "run_id": run["id"]}
            parts = financial_body.split("\n\n")
            hidden = "\n\n".join("<!-- review-note:\n" + part + "\n-->" if "{{fact:" in part or "{{calc:" in part else part for part in parts)
            for test_body, expected in ((hidden, False),
                                       (hidden + "\n\n<!-- review-note:\n材料缺口：" + finance["original_name"] + "：仅验证解析，业务分析仍缺少账龄及回款资料。\n-->", True),
                                       (financial_body, True)):
                call("draft", "submit", request={**base, "task_id": financial_task["id"], "author_id": "writer", "body": test_body, "replace": True})
                call("draft", "build", request=base)
                checked = call("validate", request=base)
                self.assertTrue(checked["checks"]["financial_binding"], checked)
                self.assertEqual(checked["checks"]["analysis_material_coverage"], expected, checked)
            draft = call("draft", "build", request=base)
            self.assertIn("4.2746天", Path(draft["markdown_path"]).read_text())
            review = {"project_id": project["id"], "run_id": run["id"], "draft_sha256": draft["sha256"],
                      "reviewer_id": "reviewer", "verdict": "pass", "issues": []}
            call("review", "submit", request=review, fails="review coverage")
            review["coverage"] = synthetic_review_coverage(draft)
            call("review", "submit", request={**review, "reviewer_id": "writer"}, fails="independent")
            call("review", "submit", request={**review, "draft_sha256": "stale"}, fails="stale")
            call("review", "submit", request=review)
            validation = call("validate", request={"project_id": project["id"], "run_id": run["id"]})
            self.assertTrue(validation["hard_checks_passed"], validation)
            self.assertEqual(validation["status"], "pending_review")
            self.assertTrue(validation["gaps"]["material_gaps"])
            Path(draft["markdown_path"]).write_text(Path(draft["markdown_path"]).read_text() + "\n伪造43天。")
            validation = call("validate", request={"project_id": project["id"], "run_id": run["id"]})
            self.assertFalse(validation["checks"]["candidate_integrity"])
            call("publish", request={"project_id": project["id"], "run_id": run["id"]}, fails="publication blocked")

    def test_raw_scans_and_derived_transcripts_preserve_original_identity(self):
        import tempfile
        from pathlib import Path
        from pypdf import PdfWriter
        from long_report.application import create_project, add_material
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = create_project(root / "projects", {"scenario_id": "financial_due_diligence", "scenario_version": "0.3.3",
                "credit_application_id": "SYN-SCAN", "subject_scope": {"business_unit": "甲公司"}, "evaluation_date": "2026-06-30"})
            raw = root / "scan.pdf"
            writer = PdfWriter(); writer.add_blank_page(width=595, height=842)
            with raw.open("wb") as output:
                writer.write(output)
            source = add_material(root / "projects", {"project_id": project["id"], "input_id": "application", "path": str(raw)})
            self.assertEqual(source["parsed"]["coverage"]["unread_pages"], [1])
            text = root / "transcript.txt"; text.write_text("申请金额待核读\n")
            request = {"project_id": project["id"], "input_id": "application", "path": str(text),
                       "derivation": {"source_id": source["id"], "source_sha256": source["fingerprint"],
                                      "method": "合成转录，语义需独立核对", "locator_map": {"line:1": "page:2"}}}
            with self.assertRaisesRegex(ValueError, "original locator"):
                add_material(root / "projects", request)
            request["derivation"]["locator_map"]["line:1"] = "page:1"
            derivative = add_material(root / "projects", request)
            self.assertEqual(derivative["derivation"]["source_id"], source["id"])
            request["derivation"]["method"] = "另一套无法判断真假的关系"
            with self.assertRaisesRegex(ValueError, "different derivation"):
                add_material(root / "projects", request)

    def test_large_styled_worksheet_retains_values_without_expanding_empty_rows(self):
        from io import BytesIO
        from openpyxl import Workbook
        from openpyxl.styles import PatternFill
        from long_report.application import _parse_xlsx
        book = Workbook(); sheet = book.active
        sheet["A1"] = "金额"; sheet["B2"] = 14367.763083
        sheet["G1048451"].fill = PatternFill(fill_type="solid", fgColor="FF0000")
        data = BytesIO(); book.save(data)
        parsed = _parse_xlsx(data.getvalue())
        self.assertEqual(set(parsed["sheets"]["Sheet"]["cells"]), {"A1", "B2"})
        self.assertEqual(parsed["sheets"]["Sheet"]["cells"]["B2"]["value"], "14367.763083")


    def test_exact_source_span_preserves_trace_without_forcing_whole_ocr_lines_into_reports(self):
        import tempfile
        from pathlib import Path
        from long_report.application import create_project, add_material, start_run, list_tasks, submit_task, decide_evidence
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = create_project(root / "projects", {"scenario_id": "financial_due_diligence", "scenario_version": "0.3.3",
                "credit_application_id": "SYN-SPAN", "subject_scope": {"business_unit": "甲公司"}, "evaluation_date": "2026-06-30"})
            source = root / "source.txt"; source.write_text("法定代表人：魏斌；净利润-100.00万元；其他识别不清的长段。\n")
            material = add_material(root / "projects", {"project_id": project["id"], "input_id": "application", "path": str(source)})
            run = start_run(root / "projects", {"project_id": project["id"]})
            task = list_tasks(root / "projects", project["id"], run["id"])[0]
            text = material["parsed"]["fragments"][0]["value"]
            value = "魏斌"; first = text.index(value)
            candidate = {"subject_id": "甲公司", "metric_id": "legal_representative", "period": "2026-06-30",
                         "source_value": text, "source_locator": "line:1", "value": value, "source_span": [first, first + len(value)]}
            request = {"project_id": project["id"], "run_id": run["id"], "task_id": task["id"],
                       "input_fingerprint": task["input_fingerprint"], "candidates": [candidate]}
            for span in [[0, 2], [first, 999], [True, first + 2]]:
                request["candidates"] = [{**candidate, "source_span": span}]
                with self.assertRaisesRegex(ValueError, "source_span"):
                    submit_task(root / "projects", request)
            negative = text.index("-100.00")
            for clipped_value, span in [("100.00", [negative + 1, negative + 7]), ("-100", [negative, negative + 4])]:
                request["candidates"] = [{**candidate, "value": clipped_value, "source_span": span}]
                with self.assertRaisesRegex(ValueError, "source_span"):
                    submit_task(root / "projects", request)
            request["candidates"] = [candidate]
            submitted = submit_task(root / "projects", request)
            fact = decide_evidence(root / "projects", {"project_id": project["id"], "run_id": run["id"],
                "candidate_id": submitted["candidates"][0]["id"], "decision": "accept"})
            self.assertEqual(fact["value"], value)
            self.assertEqual(fact["source_value"], text)
            self.assertEqual(fact["source_span"], [first, first + len(value)])


    def test_content_hash_reuse_does_not_change_text_into_csv_source_locations(self):
        import tempfile
        from pathlib import Path
        from long_report.application import create_project, add_material
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = create_project(root / "projects", {"scenario_id": "financial_due_diligence", "scenario_version": "0.3.3",
                "credit_application_id": "SYN-FORMAT", "subject_scope": {"business_unit": "甲公司"}, "evaluation_date": "2026-06-30"})
            text = root / "amount.txt"; text.write_text("10\n")
            first = add_material(root / "projects", {"project_id": project["id"], "input_id": "application", "path": str(text)})
            csv = root / "contract_days.csv"; csv.write_bytes(text.read_bytes())
            with self.assertRaisesRegex(ValueError, "different material format"):
                add_material(root / "projects", {"project_id": project["id"], "input_id": "financials", "path": str(csv)})
            self.assertEqual(first["parsed"]["fragments"][0]["locator"], "line:1")

    def test_blank_lines_do_not_hide_real_word_heading_changes(self):
        import tempfile
        from pathlib import Path
        from docx import Document
        from long_report.rendering import render_docx, verify_docx
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / 'report.docx'
            template = Path(__file__).resolve().parents[1] / 'scenarios/financial_due_diligence/templates/default-v0.2.0.docx'
            markdown = '# 第一章 公司情况\n\n正文。\n\n\n# 第二章 公司运营情况\n\n\n## 一、主营业务情况\n\n持续经营。'
            render_docx(markdown, template, target, '标题回读验证')
            verify_docx(markdown, target, {})
            document = Document(target)
            heading = next(p for p in document.paragraphs if p.text == '一、主营业务情况')
            heading.text = '错误小节'
            document.save(target)
            with self.assertRaisesRegex(ValueError, 'headings differ'):
                verify_docx(markdown, target, {})
