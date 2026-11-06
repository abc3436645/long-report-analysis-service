"""An enterprise's fixed report structure must survive planning and chapter submission."""

import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from docx import Document
from docx.oxml.ns import qn

from long_report.application import submit_draft
from long_report.financials import review_requirements, validate_financial_body
from long_report.rendering import report_fonts, render_docx, verify_docx
from long_report.scenario import ScenarioError, load_scenario, validate_report_outline, validate_section_headings


class FixedReportContractTests(unittest.TestCase):
    def test_risk_headings_follow_current_findings_and_each_reaches_review(self):
        scenario = load_scenario("financial_due_diligence")
        section = next(item for item in scenario.outline["sections"] if item["id"] == "risks")
        self.assertNotIn("subheadings", section)
        self.assertTrue(section["dynamic_subheadings"])
        validate_report_outline({"sections": scenario.outline["sections"]}, scenario.analysis, {},
                                fixed_outline=scenario.outline)
        for headings in (["一、回款与短债到期错配", "二、关键合同续签不确定性"],
                         ["一、关联资金占用影响偿付"]):
            body = "\n\n".join("## " + title + "\n\n已核发现及判断限制。" for title in headings)
            validate_section_headings(body, section)
            requirements = review_requirements("# " + section["title"] + "\n\n" + body, scenario.outline)
            self.assertEqual([item["id"] for item in requirements if item["kind"] == "section"],
                             ["risks:body", *("risks:" + title for title in headings)])
            frozen_old_section = {key: value for key, value in section.items() if key != "dynamic_subheadings"}
            frozen_old_section["subheadings"] = ["一、行业竞争、加工费下行风险"]
            with self.assertRaises(ScenarioError):
                validate_section_headings(body, frozen_old_section)
        for body in ("# 错误章级标题\n\n正文。", "## 同名风险\n\n正文。\n\n## 同名风险\n\n正文。",
                     "## 空小节", "## 风险标题\n没有分块的正文"):
            with self.subTest(body=body), self.assertRaises(ScenarioError):
                validate_section_headings(body, section)
        validate_section_headings("资料范围不足，尚不能形成具体风险判断。", section)

    def test_dynamic_risk_mode_is_explicit_and_cannot_weaken_fixed_chapters(self):
        scenario = load_scenario("financial_due_diligence")
        for value in (False, "true", 1):
            proposed = copy.deepcopy(scenario.outline)
            proposed["sections"][5]["dynamic_subheadings"] = value
            with self.subTest(value=value), self.assertRaisesRegex(ScenarioError, "dynamic_subheadings"):
                validate_report_outline({"sections": proposed["sections"]}, scenario.analysis, {})
        proposed = copy.deepcopy(scenario.outline)
        proposed["sections"][5]["subheadings"] = []
        with self.assertRaisesRegex(ScenarioError, "coexist"):
            validate_report_outline({"sections": proposed["sections"]}, scenario.analysis, {})
        proposed = copy.deepcopy(scenario.outline)
        proposed["sections"][4].pop("subheadings")
        proposed["sections"][4]["dynamic_subheadings"] = True
        with self.assertRaisesRegex(ScenarioError, "preserve fixed"):
            validate_report_outline({"sections": proposed["sections"]}, scenario.analysis, {}, fixed_outline=scenario.outline)

    def test_financial_ratio_table_keeps_four_groups_and_sixteen_sourced_indicators(self):
        scenario = load_scenario("financial_due_diligence")
        guidance = scenario.analysis["writing_guidance"]
        groups = [line.split("：", 1)[1].rstrip("。").split("、") for line in guidance["financial_ratio_rows"]]
        self.assertEqual(groups, [
            ["净资产收益率", "总资产报酬率", "营业收入利润率", "盈余现金保障倍数", "营业现金比率"],
            ["总资产周转率", "应收账款周转率", "流动资产周转率", "两金占流动资产比重", "存货周转率"],
            ["资产负债率", "速动比率", "带息负债比率", "现金流动负债比率"],
            ["营业总收入增长率", "利润总额增长率"],
        ])
        tables = "\n".join(guidance["financials_tables"])
        review = "\n".join(guidance["review_checklist"])
        self.assertIn("缺定义、缺输入、不适用或不可比时在该单元格具名标状态和原因", tables)
        self.assertIn("四组分别紧接财务比率表作专属分析", tables)
        self.assertIn("四组16项", review)

    def test_cash_flow_guidance_requires_complete_statement_and_evidence_based_direction(self):
        scenario = load_scenario("financial_due_diligence")
        section = scenario.outline["sections"][2]
        question = next(item for item in section["questions"] if item.startswith("现金流量表："))
        guidance = scenario.analysis["writing_guidance"]
        tables = "\n".join(guidance["financials_tables"])
        review = "\n".join(guidance["review_checklist"])
        self.assertIn("现金流量表", section["required_assets"])
        self.assertIn("近几年完整年度及最新期间", question)
        for expected in ("逐行完整列示原报表中经营、投资、筹资活动的各项流入流出、小计与净额", "不以三类净额摘要代替主表", "累计数须有可靠相邻累计数才可还原单期", "以本轮原表为准", "建议围绕已证实的主要现金约束或改善机会选一条主方向"):
            self.assertIn(expected, tables)
        for expected in ("仅列三类净额", "正向与负向经营信号", "不把待核原因或建议写成事实"):
            self.assertIn(expected, review)

    def test_profit_statement_guidance_requires_complete_periods_and_sourced_reconciliation(self):
        scenario = load_scenario("financial_due_diligence")
        section = scenario.outline["sections"][2]
        guidance = scenario.analysis["writing_guidance"]
        tables = "\n".join(guidance["financials_tables"])
        review = "\n".join(guidance["review_checklist"])
        self.assertIn("利润表", section["required_assets"])
        for expected in ("逐行完整列示原报表所有收入、成本、费用、损益、所得税科目与各级小计合计", "累计数须有可核期差才可还原单期", "不能机械要求利息费用减利息收入等于财务费用", "无法量化时写明原因，不编造调整数字"):
            self.assertIn(expected, tables)
        for expected in ("只摘录主要损益", "无法调平的差额列疑点", "影响意见的实质限制进入正文"):
            self.assertIn(expected, review)

    def test_balance_sheet_guidance_keeps_full_multi_year_statement_and_evidence_based_drilldown(self):
        scenario = load_scenario("financial_due_diligence")
        section = scenario.outline["sections"][2]
        question = next(item for item in section["questions"] if item.startswith("资产负债表："))
        guidance = scenario.analysis["writing_guidance"]
        tables = "\n".join(guidance["financials_tables"])
        financials = "\n".join(guidance["financials"])
        review = "\n".join(guidance["review_checklist"])
        self.assertIn("资产负债表", section["required_assets"])
        for expected in ("近几年年末及最新时点", "资产、负债和所有者权益各科目及合计", "货币资金", "应收账款", "其他应收款", "其他应付款", "存货", "长期股权投资", "证据链"):
            self.assertIn(expected, question)
        for expected in ("逐行完整列示原报表中资产、负债、所有者权益各科目与小计合计", "不只截取重点科目", "完整资产负债表后先比较资产、负债和权益总量", "余额下降、稳定大额和科目重分类"):
            self.assertIn(expected, tables)
        for expected in ("已有数据时全部输出并逐表深度解读", "重点筛选只决定分析重心", "不利数据", "正向反映公司经营运行", "也按科目、期间或对象整理成表并紧接解读", "事实、企业解释、审查推断和结论强度分开", "不得只用批注隐去实质异常"):
            self.assertIn(expected, tables)
        for expected in ("先写具体时点余额、占比及分母", "企业解释、已核事实和审查推断分别表述", "最新中期或评价基准时点与上年末比较须标明时间跨度", "下降不能直接写成回款或风险消除"):
            self.assertIn(expected, financials)
        self.assertIn("以文字摘要代替完整主表", review)
        self.assertIn("相关表格均须输出并逐表深入解读", review)
        self.assertIn("可核实的正向经营数据也须成表", review)
        self.assertIn("异常及重大变化的已证事实和实质影响须在正文说明", review)

    def test_supplier_and_customer_tables_have_distinct_validated_headers_or_named_gaps(self):
        section = load_scenario("financial_due_diligence").outline["sections"][1]
        self.assertEqual([(rule["asset"], rule["columns"]) for rule in section["required_tables"]], [
            ("主要供应商表", ["供应商名称", "产品", "采购金额（万元）", "占比", "结算方式", "账期"]),
            ("主要客户表", ["客户名称", "产品", "销售金额（万元）", "占比", "结算方式", "账期"]),
        ])
        prefix = ("## 一、主营业务情况\n\n主营业务资料待核实。\n\n"
                  "## 二、主营产销情况\n\n产销资料待核实。\n\n"
                  "## 三、原料采购、产品销售情况\n\n")
        supplier = ("表2-1 主要供应商表\n\n"
                    "| 供应商名称 | 产品 | 采购金额（万元） | 占比 | 结算方式 | 账期 |\n"
                    "| --- | --- | --- | --- | --- | --- |\n"
                    "| 甲供方 | 产品甲 | 待核实 | 待核实 | 电汇 | 月结 |")
        customer = ("表2-2 主要客户表\n\n"
                    "| 客户名称 | 产品 | 销售金额（万元） | 占比 | 结算方式 | 账期 |\n"
                    "| --- | --- | --- | --- | --- | --- |\n"
                    "| 乙客户 | 产品甲 | 待核实 | 待核实 | 电汇 | 月结 |")
        other_gaps = ("\n\n资料缺口：主营产能产销表：合成材料未提供。"
                      "\n\n资料缺口：主营收入成本表：合成材料未提供。")
        body = prefix + supplier + "\n\n供应商交易情况待核实。\n\n" + customer + "\n\n客户交易情况待核实。" + other_gaps
        validate_section_headings(body, section)
        validate_financial_body(body, section)
        for invalid in (body.replace("| 供应商名称 | 产品 | 采购金额", "| 客户名称 | 产品 | 采购金额", 1),
                        body.replace("| 客户名称 | 产品 | 销售金额", "| 供应商名称 | 产品 | 销售金额", 1),
                        body.replace("| 客户名称 | 产品 | 销售金额", "| 客户名称 | 产品 | 采购金额", 1),
                        body + "\n\n" + supplier):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(ScenarioError, "required table"):
                validate_section_headings(invalid, section)
        misplaced = ("## 一、主营业务情况\n\n" + supplier + "\n\n"
                     "## 二、主营产销情况\n\n产销资料待核实。\n\n"
                     "## 三、原料采购、产品销售情况\n\n" + customer + other_gaps)
        with self.assertRaisesRegex(ScenarioError, "wrong subheading"):
            validate_section_headings(misplaced, section)
        gaps_only = (prefix + "资料缺口：主要供应商表：合成材料未提供。\n\n"
                     "资料缺口：主要客户表：合成材料未提供。" + other_gaps)
        validate_section_headings(gaps_only, section)
        validate_financial_body(gaps_only, section)
        supplier_only = prefix + supplier + "\n\n资料缺口：主要客户表：合成材料未提供。" + other_gaps
        validate_section_headings(supplier_only, section)
        validate_financial_body(supplier_only, section)
        with self.assertRaisesRegex(ScenarioError, "required table or named gap"):
            validate_section_headings(prefix + other_gaps, section)
        comparison = ("表2-3 主要供应商表与主要客户表对照\n\n"
                      "| 关系 | 说明 |\n| --- | --- |\n| 重叠 | 待核实 |")
        validate_section_headings(body + "\n\n" + comparison, section)

    def test_supplier_customer_guidance_uses_fixed_supplier_columns_and_sourced_relationships(self):
        scenario = load_scenario("financial_due_diligence")
        section = scenario.outline["sections"][1]
        question = next(item for item in section["questions"] if item.startswith("三、原料采购、产品销售情况："))
        tables = "\n".join(scenario.analysis["writing_guidance"]["operations_tables"])
        guidance = "\n".join(scenario.analysis["writing_guidance"]["operations"])
        counterparties = "\n".join(scenario.analysis["writing_guidance"]["counterparty_assessment"])
        review = "\n".join(scenario.analysis["writing_guidance"]["review_checklist"])
        self.assertIn("供应商名称｜产品｜采购金额（万元）｜占比｜结算方式｜账期", tables)
        self.assertIn("缺整表资料时各按required_assets具名披露对应缺口", tables)
        for expected in ("前五大供应商", "前五大客户", "少于五户时只按已知户数列示", "合同有效期", "实际履约", "控制权变更"):
            self.assertIn(expected, tables + question + guidance)
        self.assertIn("不能仅因新增或入股就认定异常交易", counterparties)
        self.assertIn("没有合同条款或控制权变更证据时不推测合同终止", counterparties)
        self.assertIn("无资料时罗列推测性风险", review)

    def test_production_and_sales_guidance_requires_comparable_periods_and_evidence_chain(self):
        scenario = load_scenario("financial_due_diligence")
        section = scenario.outline["sections"][1]
        question = next(item for item in section["questions"] if item.startswith("二、主营产销情况："))
        guidance = "\n".join(scenario.analysis["writing_guidance"]["operations"])
        tables = "\n".join(scenario.analysis["writing_guidance"]["operations_tables"])
        review = "\n".join(scenario.analysis["writing_guidance"]["review_checklist"])
        for expected in ("近几年及当年", "同比", "环比", "异常升降", "完整证据链"):
            self.assertIn(expected, question)
        for expected in ("主营产销量", "主营收支", "近几年完整年度", "当年截至评价基准", "原因链不完整时仅陈述已证变化", "优势须以资源或措施、实际执行、可核经营效果及持续条件形成链条"):
            self.assertIn(expected, guidance)
        for expected in ("同比只用上年同期间同范围数据", "环比只用相邻月度或季度等同频数据", "无对应期间或不可比时不编造百分比"):
            self.assertIn(expected, tables)
        self.assertIn("跨不可比期间计算比率", review)

    def test_main_business_guidance_requires_evidence_for_business_model_and_capabilities(self):
        scenario = load_scenario("financial_due_diligence")
        section = scenario.outline["sections"][1]
        question = next(item for item in section["questions"] if item.startswith("一、主营业务情况："))
        guidance = "\n".join(scenario.analysis["writing_guidance"]["operations"])
        review = "\n".join(scenario.analysis["writing_guidance"]["review_checklist"])
        for expected in ("已提供材料", "业务线收入结构", "客户与收费方式", "市场规模", "研发技术知识产权", "在建项目资金使用", "仅在有对应资料时展开"):
            self.assertIn(expected, question)
        for expected in ("占比分母", "实际适用方式", "同口径分子和分母", "非制造业务不套用产能", "技术来源", "商业转化", "资金使用去向", "没有资料的主题连同其三级标题或段落省略", "整类研发与技术资料均未提供时不设置该部分标题或正文"):
            self.assertIn(expected, guidance)
        self.assertIn("用行业常识、样本、资质或计划代替本公司事实", review)
        self.assertIn("不将其逐项出现当作完整性条件", review)

    def test_management_section_contains_separate_resumes_without_extra_commentary(self):
        scenario = load_scenario("financial_due_diligence")
        section = scenario.outline["sections"][0]
        question = next(item for item in section["questions"] if item.startswith("六、法人代表及主要管理人情况："))
        guidance = "\n".join(scenario.analysis["writing_guidance"]["management_profiles"])
        review = "\n".join(scenario.analysis["writing_guidance"]["review_checklist"])
        self.assertIn("按人分段", question)
        self.assertIn("一人一段", guidance)
        self.assertIn("正文只写有依据的任职和经历事实", guidance)
        self.assertIn("不追加经历如何支持管理能力", guidance)
        self.assertIn("整份履历未提供时不编造人员或设置空白履历段", guidance)
        self.assertIn("锚定批注", guidance)
        self.assertIn("在履历之间加入评价、核查说明和总结时", review)

    def test_organization_section_only_describes_departments_and_does_not_require_a_chart(self):
        scenario = load_scenario("financial_due_diligence")
        section = scenario.outline["sections"][0]
        self.assertNotIn("三、基本组织机构情况", section["required_subsections"])
        self.assertEqual(section["required_assets"], [])
        self.assertIn("主要部门及可核的隶属关系", "\n".join(section["questions"]))
        guidance = "\n".join(scenario.analysis["writing_guidance"]["company"])
        self.assertIn("只简要说明本轮材料可确认的主要部门名称", guidance)
        self.assertIn("不扩写部门职责、人数、授权制衡或内控有效性评价", guidance)
        self.assertIn("当前不是必需图表", guidance)

    def test_approved_secondary_font_preserves_priority_and_is_written_to_styles(self):
        profile = copy.deepcopy(load_scenario("financial_due_diligence").manifest["presentation"])
        self.assertEqual(profile["font_alternatives"], {"仿宋": ["仿宋-简"]})
        with patch("long_report.rendering._installed_fonts", return_value={"仿宋", "仿宋-简"}):
            self.assertEqual(set(report_fonts(profile).values()), {"仿宋"})
        with patch("long_report.rendering._installed_fonts", return_value={"stfangsong"}):
            with self.assertRaisesRegex(ValueError, "required report font unavailable"):
                report_fonts(profile)
        with patch("long_report.rendering._installed_fonts", return_value={"仿宋-简"}), tempfile.TemporaryDirectory() as tmp:
            template, output = Path(tmp)/"template.docx", Path(tmp)/"report.docx"
            Document().save(template)
            md = "# 公司\n\n公司经营情况。\n\n| 项目 | 内容 |\n| --- | --- |\n| 主体 | 本公司 |"
            render_docx(md, template, output, "报告", presentation=profile)
            checked = verify_docx(md, output, {}, presentation=profile)
            self.assertEqual(set(checked["resolved_fonts"].values()), {"仿宋-简"})
            document = Document(output)
            for name in ("Title", "Heading 1", "Heading 2", "Normal", "Table Body"):
                self.assertEqual(document.styles[name].element.rPr.rFonts.get(qn("w:eastAsia")), "仿宋-简")
            document.tables[0].cell(1, 1).paragraphs[0].runs[0]._r.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), "宋体")
            document.save(output)
            with self.assertRaisesRegex(ValueError, "table typography overrides"):
                verify_docx(md, output, {}, presentation=profile)
            render_docx(md, template, output, "报告", presentation=profile)
            document = Document(output)
            document.styles["Table Body"].element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
            document.save(output)
            with self.assertRaisesRegex(ValueError, "typography differs.*Table Body"):
                verify_docx(md, output, {}, presentation=profile)
        self.assertEqual(profile["styles"]["Normal"]["font"], "仿宋")

    def test_financial_scenario_declares_standard_chapters_and_fangsong(self):
        scenario = load_scenario("financial_due_diligence")
        self.assertTrue(scenario.outline.get("fixed"))
        self.assertEqual(len(scenario.outline["sections"]), 9)
        self.assertEqual(sum(len(s.get("subheadings", [])) for s in scenario.outline["sections"]), 27)
        self.assertEqual(scenario.outline["sections"][2]["subheadings"],
                         ["资产负债表", "利润表：", "现金流量表：", "财务比率及分析"])
        self.assertEqual(scenario.outline["sections"][3]["subheadings"], [])
        self.assertEqual({key: scenario.manifest["presentation"][key] for key in ("body_font", "heading_font", "latin_font", "allow_font_fallback")},
                         dict(body_font="仿宋", heading_font="仿宋", latin_font="仿宋", allow_font_fallback=False))

    def test_per_run_plan_cannot_replace_a_fixed_heading_or_omit_a_chapter(self):
        scenario = load_scenario("financial_due_diligence")
        original = {"sections": [dict(id="credit", title="信用能力评估", display_order=1, repeat_for=None,
                                      subheadings=["一、信用评级", "二、征信情况"], evidence_refs=[], analysis_refs=[], depends_on=[])]}
        fixed = {**original, "fixed": True}
        for mutation in ("title", "subheading", "omit", "reorder", "repeat", "empty"):
            proposed = copy.deepcopy(original)
            if mutation == "empty":
                proposed["sections"] = []
            elif mutation == "omit":
                proposed["sections"].pop()
            elif mutation == "reorder":
                proposed["sections"][0]["display_order"] = 10
            elif mutation == "repeat":
                proposed["sections"][0]["repeat_for"] = "unit"
            elif mutation == "subheading":
                proposed["sections"][0]["subheadings"] = ["自定标题"]
            else:
                proposed["sections"][0]["title"] = "自定章节"
            with self.subTest(mutation=mutation), self.assertRaisesRegex(ScenarioError, "fixed|requires sections"):
                validate_report_outline(proposed, scenario.analysis, {"units": ["甲公司"]},
                                        fixed_outline=fixed)
        accepted = validate_report_outline(original, scenario.analysis, {}, fixed_outline=fixed)
        self.assertEqual(accepted["sections"], original["sections"])

    def test_every_fixed_subheading_has_a_business_question_and_chapter_guidance(self):
        scenario = load_scenario("financial_due_diligence")
        guidance = scenario.analysis["writing_guidance"]
        for shared in ("business_adaptation", "report_expression", "cross_chapter_consistency", "comprehensive_assessment"):
            self.assertTrue(guidance[shared], "Company-specific reports need reusable evidence and expression requirements")
        for section in scenario.outline["sections"]:
            with self.subTest(section=section["id"]):
                self.assertIn(section["id"], guidance)
                self.assertTrue(section["questions"])
                self.assertNotIn(section["goal"], section["questions"])
                self.assertIn("report_expression", "\n".join(guidance[section["id"]]),
                              "The expression requirements must apply to all nine chapters")
                self.assertIn("comprehensive_assessment", "\n".join(guidance[section["id"]]),
                              "Identifying strengths and warning signs is a whole-report objective, not a risk-only appendix")
                for heading in section.get("subheadings", []):
                    self.assertTrue(any(question.startswith(heading.rstrip("：") + "：") for question in section["questions"]),
                                    "Each retained heading must answer its own review question: " + heading)
        self.assertTrue(guidance["review_checklist"])
        self.assertTrue(guidance["management_profiles"], "Known career histories must not collapse into a shared manager summary")
        self.assertIn("management_profiles", "\n".join(guidance["company"]))

    def test_reference_company_facts_do_not_become_reusable_scenario_requirements(self):
        scenario = load_scenario("financial_due_diligence")
        requirements = repr((scenario.analysis, scenario.outline))
        for value in ("江铜华北", "天津大无缝", "魏斌", "周泓睿", "左带发", "SCR4500", "T1R",
                      "64020.41", "100138.66", "91.59%", "92.88%"):
            with self.subTest(value=value):
                self.assertNotIn(value, requirements, "A reference fact must be supplied by each project's own evidence")

    def test_chapters_two_to_five_declare_tables_with_matching_writing_instructions(self):
        scenario = load_scenario("financial_due_diligence")
        guidance = scenario.analysis["writing_guidance"]
        for name in ("table_interpretation", "counterparty_assessment", "operating_stability"):
            self.assertTrue(guidance[name], "Table presence alone does not establish business capability or risk")
        for section in scenario.outline["sections"][1:5]:
            with self.subTest(section=section["id"]):
                self.assertTrue(section["required_assets"], "Table requirements must reach each chapter plan")
                table_guidance = "\n".join(guidance[section["id"] + "_tables"])
                for name in section["required_assets"]:
                    self.assertIn(name, table_guidance, "A named table needs field and analysis instructions")
                self.assertIn("table_interpretation", "\n".join(guidance[section["id"]]),
                              "Every table-bearing chapter must use the per-table interpretation requirements")
                self.assertTrue(any("每张" in question and "表" in question for question in section["questions"]),
                                "Each chapter plan must ask for interpretation of every actual table")
        self.assertIn("其他应付款", "\n".join(guidance["current_accounts_focus"]))
        self.assertIn("长期股权投资", "\n".join(guidance["equity_investment_focus"]))
        self.assertTrue(guidance["materiality_selection"])

    def test_missing_or_reordered_subheadings_are_rejected_before_storage(self):
        context = {"task": {}, "section": {"subheadings": ["一、信用评级", "二、征信情况"]}}
        bodies = (" ## 一、信用评级\n\n缺资料。\n\n ## 二、征信情况\n\n缺资料。", "## 一、信用评级\n缺资料。\n\n## 二、征信情况\n缺资料。", "评级资料缺失。", "## 二、征信情况\n缺资料。\n## 一、信用评级\n缺资料。",
                  "## 一、信用评级\n## 二、征信情况\n缺资料。",
                  "# 额外一级标题\n## 一、信用评级\n缺资料。\n## 二、征信情况\n缺资料。")
        with patch("long_report.application.get_draft_context", return_value=context):
            for body in bodies:
                with self.subTest(body=body), self.assertRaisesRegex(ValueError, "fixed.*heading|empty.*subheading"):
                    submit_draft(None, dict(project_id="p", task_id="t", body=body))

    def test_fixed_font_is_never_silently_substituted(self):
        presentation = dict(body_font="仿宋", heading_font="仿宋", latin_font="仿宋", allow_font_fallback=False)
        with patch("long_report.rendering._installed_fonts", return_value={"songti sc", "heiti sc", "times new roman"}):
            with self.assertRaisesRegex(ValueError, "required report font unavailable.*仿宋"):
                report_fonts(presentation)
        with patch("long_report.rendering._installed_fonts", return_value={"仿宋"}):
            self.assertEqual(set(report_fonts(presentation).values()), {"仿宋"})


if __name__ == "__main__":
    unittest.main()
