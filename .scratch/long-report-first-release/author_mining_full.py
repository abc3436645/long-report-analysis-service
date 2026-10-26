"""One-run authoring driver for the inspected July MOCK mining materials."""

import json
import os
import sqlite3
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / "projects" / os.environ.get("MINING_WORK", "mining_board_full_delivery_2026_07")
REPORT = ROOT / ".venv/bin/report"
WORKSPACE = WORK / "projects"
session = json.loads((WORK / "session.json").read_text(encoding="utf-8"))
project_id, run_id = session["project_id"], session["run_id"]
evidence = json.loads((WORK / "evidence.json").read_text(encoding="utf-8"))
calculations = json.loads((WORK / "calculations.json").read_text(encoding="utf-8"))
mapping = json.loads((WORK / "mapping.json").read_text(encoding="utf-8"))
units = mapping["units"]
assert len(units) == 6
rows = dict(zip(units, [(4, 16, 4, 4), (5, 17, 8, 5), (6, 18, 12, 6),
                        (7, 19, 16, 7), (9, 21, None, 8), (10, 22, None, 10)]))


def cli(*args, request=None):
    command = [str(REPORT), *args, "--workspace", str(WORKSPACE)]
    if request is not None:
        path = WORK / "author_request.json"
        path.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
        command += ["--request", str(path)]
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError(f"{' '.join(args)}: {result.stderr[:3000]}")
    return json.loads(result.stdout)["data"]


def point(subject, metric, period="2026-07", window="ytd", basis="actuals", version=None):
    matches = [item for item in evidence if item["subject_id"] == subject and item["metric_id"] == metric
               and item["period"] == period and item["window"] == window and item["basis"] == basis
               and item.get("budget_version") == version]
    assert len(matches) == 1, (subject, metric, period, window, basis, version, len(matches))
    return matches[0]


def metric(subject, name):
    matches = [item for item in calculations if item["subject_id"] == subject and item["metric_id"] == name
               and item["status"] == "calculated"]
    assert len(matches) == 1, (subject, name, len(matches))
    return matches[0]


def fact(subject, name, period="2026-07", window="ytd", basis="actuals", version=None, digits=2):
    return "{{fact:" + point(subject, name, period, window, basis, version)["id"] + f"|{digits}" + "}}"


def calc(subject, name, digits=2):
    return "{{calc:" + metric(subject, name)["id"] + f"|{digits}" + "}}"


def source(subject, name, period="2026-07", window="ytd", basis="actuals", version=None):
    return "{{ev:" + point(subject, name, period, window, basis, version)["id"] + "}}"


def chart(subject, number):
    title = f"图{number} {subject}本年累计利润与上年同期、序时计划对比"
    series = [{"label": label, "evidence_id": point(subject, "profit_total", *keys)["id"]}
              for label, keys in [
                  ("本年1—7月实际", ()),
                  ("上年同期实际", ("2025-07",)),
                  ("本年1—7月序时计划", ("2026-07", "ytd", "budget", "time_plan")),
              ]]
    made = cli("chart", "create", request={"project_id": project_id, "run_id": run_id,
                                           "title": title, "series": series})
    assert made["annotations"] and Path(made["path"]).is_file()
    return "{{chart:" + made["id"] + "}}"


charts = {"矿山板块合计": chart("矿山板块合计", "3-1")}
charts.update({unit: chart(unit, f"4-{number}") for number, unit in enumerate(units, 1)})

with sqlite3.connect(WORKSPACE / project_id / "state.sqlite") as connection:
    run = json.loads(connection.execute("SELECT data FROM run WHERE id = ?", (run_id,)).fetchone()[0])
    material_lookup = {item["id"]: item for row in connection.execute("SELECT data FROM material")
                       if (item := json.loads(row[0]))}
analysis_sources = {item["source_id"] for item in evidence}
assert len(run["material_ids"]) == 13 and len(analysis_sources) == 4
reasons = {
    "年度计划主要数据": "含产品年度计划，当前缺同范围产量台账，不能与六矿销量直接计算完成率；仅用于口径提示。",
    "主要单位效益同比分析": "列示集团与其他单位效益构成，未列六矿独立主体；不并入矿山利润。",
    "TC增减利分析": "对应冶炼进口矿采购与TC，非六矿采选经营口径。",
    "母公司原料效益完成": "对应母公司冶炼原料效益，非六矿利润桥。",
    "硫酸增减利分析": "化工硫酸不同于本轮六矿硫精矿，主体与产品不能混并。",
    "铜加工板块加工费效益": "铜加工业务，不属于矿山板块六矿。",
    "江铜产融所持上市公司股权收益": "金融投资收益，不属于六矿采选经营。",
    "硬件报价明细": "仅有设备报价，未给矿山采购需求、用量和预算授权，不推造采购决策。",
    "当前国际与国内贵金属市场": "市场背景形成于报告期后，且未核实原始行情来源，仅作前瞻风险线索。",
}
material_uses = []
for material_id in run["material_ids"]:
    name = material_lookup[material_id]["original_name"]
    if material_id in analysis_sources:
        use, reason = "analysis", "与本轮矿山利润、成本、产销或硫精矿主体对应，已逐行核验并抽取。"
    else:
        matches = [reason for prefix, reason in reasons.items() if name.startswith(prefix)]
        assert len(matches) == 1, name
        use, reason = "context", matches[0]
    material_uses.append({"material_id": material_id, "use": use, "reason": reason})

section_specs = [
    ("executive", "第一章 管理层执行摘要", ["decisions"], ["actual_amount"], ["budget_difference"]),
    ("scope", "第二章 数据来源与分析范围", [], [], []),
    ("sector", "第三章 矿山板块整体经营及利润分析", ["scope"], ["actual_amount", "budget_amount"], ["ytd_change_rate", "budget_difference"]),
    ("units", "第四章 六矿逐户经营分析", ["sector"], ["actual_amount", "budget_amount"], ["month_change", "budget_difference", "cost.r4.ore_cost_yoy_rate"]),
    ("special", "第五章 专项来源与独立口径分析", ["units"], [], ["concentrate.r4.sales_yoy_rate", "sulfur.r4.sales_yoy_rate"]),
    ("common", "第六章 整体经营与共同关注事项", ["special"], [], []),
    ("market", "第七章 市场关联与情景测算边界", ["common"], [], []),
    ("decisions", "第八章 建议事项与人工确认", ["market"], [], []),
    ("methods", "第九章 来源索引与计算口径", ["scope"], [], []),
]
outline = {"unit_names": units, "unit_levels": {unit: 2 for unit in units}, "sections": [
    {"id": identifier, "title": title, "display_order": n, "repeat_for": "unit" if identifier == "units" else None,
     "depends_on": dependencies, "evidence_refs": evidence_refs, "analysis_refs": analysis_refs}
    for n, (identifier, title, dependencies, evidence_refs, analysis_refs) in enumerate(section_specs, 1)
]}
tasks = cli("draft", "plan", request={
    "project_id": project_id, "run_id": run_id,
    "report_request": "以本轮13份MOCK原始材料编制2026年1—7月预算办矿山板块月度经营分析技术工作稿。六矿依利润主表顺序各写月度、累计、序时、年度、采选成本、产销量和管理判断；有原件时纳入铜精矿及硫精矿；板块合计、七宝山专项及其他材料保持独立口径；按快报分析Prompt_v2的九章结构及逐矿双表一图交付DOCX/PDF，保留来源、计算、缺口及人工确认。",
    "outline": outline, "material_uses": material_uses})
assert len(tasks) == 14
(WORK / "report_plan.json").write_text(json.dumps({"outline": outline, "material_uses": material_uses}, ensure_ascii=False, indent=2), encoding="utf-8")


def profit_table(unit, n):
    return (f"表4-{2*n-1} {unit}利润比较情况表（万元）\n\n"
            "| 利润比较项目 | 本期实际 | 比较基准 | 差额与比率 |\n| --- | ---: | ---: | ---: |\n"
            f"| 7月较6月 | {fact(unit,'profit_total',window='month')} | {fact(unit,'profit_total','2026-06','month')} | {calc(unit,'month_change')}；环比 {calc(unit,'month_change_rate')}% |\n"
            f"| 1—7月较上年同期 | {fact(unit,'profit_total')} | {fact(unit,'profit_total','2025-07')} | {calc(unit,'ytd_change')}；同比 {calc(unit,'ytd_change_rate')}% |\n"
            f"| 1—7月较序时计划 | {fact(unit,'profit_total')} | {fact(unit,'profit_total',basis='budget',version='time_plan')} | {calc(unit,'budget_difference')}；完成率 {calc(unit,'budget_completion_rate')}% |\n"
            f"| 1—7月占年度计划 | {fact(unit,'profit_total')} | {fact(unit,'profit_total','2026','annual','budget','annual_plan')} | 年度完成率 {calc(unit,'annual_plan_completion_rate')}% |\n\n"
            f"利润实际来源：{source(unit,'profit_total')}；序时计划来源：{source(unit,'profit_total',basis='budget',version='time_plan')}。\n")


def indicator_table(unit, n):
    cost_row, input_row, copper_row, sulfur_row = rows[unit]
    pairs = [
        ("吨矿成本（元/吨）", f"cost.r{cost_row}.ore_cost"),
        ("变动吨矿成本（元/吨）", f"cost.r{cost_row}.variable"),
        ("金属成本（元/吨）", f"cost.r{cost_row}.metal_cost"),
        ("变动金属成本（元/吨）", f"cost.r{cost_row}.variable_metal"),
        ("选矿处理量（吨）", f"cost_inputs.r{input_row}.processed"),
        ("人工及折旧（万元）", f"cost_inputs.r{input_row}.labor_depr"),
        ("金属折合量（吨）", f"cost_inputs.r{input_row}.metal"),
        ("硫精矿销量（万吨）", f"sulfur.r{sulfur_row}.sales"),
        ("硫精矿均价（元/吨）", f"sulfur.r{sulfur_row}.price"),
    ]
    if copper_row:
        pairs += [("铜精矿含铜销量（吨）", f"concentrate.r{copper_row}.sales"),
                  ("铜精矿含铜均价（元/吨）", f"concentrate.r{copper_row}.price")]
    text = (f"表4-{2*n} {unit}主要生产经营指标表\n\n"
            "| 指标及原表单位 | 本年1—7月 | 上年同期 | 同比差额 | 同比率 |\n| --- | ---: | ---: | ---: | ---: |\n")
    for label, stem in pairs:
        digits = 2
        text += (f"| {label} | {fact(unit,stem,digits=digits)} | "
                 f"{fact(unit,stem+'_prior','2025-07',digits=digits)} | "
                 f"{calc(unit,stem+'_yoy_difference',digits)} | {calc(unit,stem+'_yoy_rate')}% |\n")
    text += (f"| 硫精矿单位成本（元/吨） | 未提供 | {fact(unit,f'sulfur.r{sulfur_row}.cost_prior','2025-07')} | — | — |\n")
    if copper_row:
        text += (f"| 铜精矿含铜产量（吨） | {fact(unit,f'concentrate.r{copper_row}.production')} | 未提供 | — | — |\n")
    text += (f"\n成本来源：{source(unit,f'cost.r{cost_row}.ore_cost')}；生产量来源：{source(unit,f'cost_inputs.r{input_row}.processed')}；"
             f"硫精矿来源：{source(unit,f'sulfur.r{sulfur_row}.sales')}。")
    if copper_row:
        text += f"铜精矿来源：{source(unit,f'concentrate.r{copper_row}.sales')}。"
    return text


judgments = {
    units[0]: ("德兴的核心矛盾是利润同比增长但序时计划仍有较大缺口，同时选矿处理量下降、吨矿与金属成本同升。含铜销量基本持平，价格同比上涨；这一价格信号不能单独解释利润增量，特别是矿量与成本已经给出反向压力。",
               "采选部门应逐月核对停机、入选矿品位和回收记录，财务部门按同期间重算固定费用分摊及矿石结转；销售部门核实铜精矿产销与结算时点。若三个台账不能闭合，不能把价格上涨认定为预算缺口的解决办法。"),
    units[1]: ("永平的序时差额较小，但吨矿和金属成本同比升幅显著高于处理量和金属量的增幅。当前月利润环比改善，仍需判断是否由价格、销售确认或一次性项目推动，不能据此把全年成本压力视为解除。",
               "矿山财务与生产部门先核对变动金属成本、人工折旧和处理量分母，再将含铜、金、银销量分别与销售结算台账勾稽。硫精矿销量下降而价格上升，应拆解量价与结算期，确认净效应后再修订后五个月预测。"),
    units[2]: ("武山处理量与金属量均明显增加，铜精矿含铜销量亦上升，但吨矿及金属成本仍同步上行。这种“增量未摊薄单位成本”的组合比单看利润同比增长更值得跟踪；月度改善尚不足以抹平序时缺口。",
               "生产部门核查采选计划、品位和回收率，成本部门拆开外包、能源、人工折旧与新增处理量；销售部门核对含铜销量及硫精矿结算。只有增量收入与增量成本同期间匹配后，才能判断扩量是否改善边际收益。"),
    units[3]: ("城门山处理量上升而金属折合量下降，金属成本涨幅明显高于吨矿成本；含铜销量也下降。利润虽同比增长、7月环比改善，却仍低于序时计划，产出效率与销售确认需要并行复核。",
               "先由生产部门按矿种和月份交叉核对入选品位、回收率与金属折合口径，不凭处理量与金属量两个汇总数直接推断地质变化；财务和销售部门核对库存、结算和成本分母。若金属产出缺口持续，应重排后续采选与销售计划。"),
    units[4]: ("银山是板块序时超额的主要贡献行，累计利润已高于年度计划，但处理量仅微增、金属量略降、单位成本上升，硫精矿销量下降。利润增长与生产成本信号不一致，必须查明价格、一次性收益和内部交易的作用。",
               "预算办与财务部门先形成利润桥，按经常经营、价格、暂估、套保、资产处置和抵销逐项列示，核对异常收益是否可重复；生产部门核对金属量和成本。年度计划已超额时，剩余月均差额为负值，不应当写作未来必须亏损的经营目标。"),
    units[5]: ("银珠山累计同比增幅极高，但上年同期基数很低；7月环比改善有限且序时计划仍有缺口。处理量下降、金属折合量增加、金属成本下降，说明产出与成本方向发生变化，但不能仅凭汇总数认定回收率提高。",
               "生产与财务部门核对入选矿结构、计量和成本归集，验证金属量增长及金属成本下降的可持续性；销售部门核查硫精矿销量增加的结算时点。年度利润预测应同时列示低基数效应与序时缺口，避免用同比率掩盖绝对额压力。"),
}
focus_details = {
    units[0]: (f"人工及折旧同比 {calc(units[0],'cost_inputs.r16.labor_depr_yoy_rate')}%，"
               f"而处理量同比 {calc(units[0],'cost_inputs.r16.processed_yoy_rate')}%、"
               f"变动吨矿成本同比 {calc(units[0],'cost.r4.variable_yoy_rate')}%。"
               "人工折旧增长与产量收缩叠加，可能推高总吨矿成本；生产负责人须列明停机和产能利用记录，成本负责人复核费用分摊，形成可复算的吨矿成本解释。"),
    units[1]: (f"变动吨矿成本同比 {calc(units[1],'cost.r5.variable_yoy_rate')}%，"
               f"硫精矿销量同比 {calc(units[1],'sulfur.r5.sales_yoy_rate')}%；"
               "成本部门须核实能源与材料单耗，销售部门核对硫精矿合同及库存，分别说明成本抬升和销量走弱是否发生在同一期间。"),
    units[2]: (f"处理量同比 {calc(units[2],'cost_inputs.r18.processed_yoy_rate')}%，"
               f"人工及折旧同比 {calc(units[2],'cost_inputs.r18.labor_depr_yoy_rate')}%，"
               f"变动吨矿成本同比 {calc(units[2],'cost.r6.variable_yoy_rate')}%。"
               "费用总额的增幅低于处理量增幅，但单位变动成本仍上升，说明规模扩大尚未消除能源、外包或运费压力。采选负责人应核查新增产量对应台账，财务负责人核对增量成本是否进入同期间利润。"),
    units[3]: (f"金属折合量同比 {calc(units[3],'cost_inputs.r19.metal_yoy_rate')}%，"
               f"含铜销量同比 {calc(units[3],'concentrate.r16.sales_yoy_rate')}%；"
               "生产与销售负责人须分别验证金属计量、在制品和发运结算，区分采选效率问题与销售确认跨期。"),
    units[4]: (f"变动吨矿成本同比 {calc(units[4],'cost.r9.variable_yoy_rate')}%，"
               f"总吨矿成本同比 {calc(units[4],'cost.r9.ore_cost_yoy_rate')}%，"
               f"人工及折旧同比 {calc(units[4],'cost_inputs.r21.labor_depr_yoy_rate')}%。"
               "总成本上升与变动成本平稳的背离提示固定费用或归集变化；财务负责人须说明费用及超额利润的具体项目，预算办只对可持续项目滚动预测。"),
    units[5]: (f"变动吨矿成本同比 {calc(units[5],'cost.r10.variable_yoy_rate')}%，"
               f"总吨矿成本同比 {calc(units[5],'cost.r10.ore_cost_yoy_rate')}%，"
               f"金属成本同比 {calc(units[5],'cost.r10.metal_cost_yoy_rate')}%。"
               "三者方向不同，提示矿石和金属分母及费用结构共同变化；生产与财务负责人须核查金属计量及成本分摊，并与硫精矿结算时点交叉核对。"),
}


def unit_body(unit, n):
    cost_row, input_row, copper_row, sulfur_row = rows[unit]
    insight, action = judgments[unit]
    body = (f"### 经营综述\n\n{unit}7月利润 {fact(unit,'profit_total',window='month')} 万元，"
            f"较6月增加 {calc(unit,'month_change')} 万元，环比 {calc(unit,'month_change_rate')}%；"
            "原件没有本年7月与上年7月同月的可比列，因此不报告单月同比。"
            f"本年累计利润 {fact(unit,'profit_total')} 万元，较上年同期增加 {calc(unit,'ytd_change')} 万元、"
            f"同比 {calc(unit,'ytd_change_rate')}%；较序时计划差额 {calc(unit,'budget_difference')} 万元，"
            f"完成序时计划 {calc(unit,'budget_completion_rate')}%，占年度计划 {calc(unit,'annual_plan_completion_rate')}%。")
    if unit == units[4]:
        body += "年度计划已经超额，剩余月份月均目标的负值仅表示算术差额，不是经营亏损要求。"
    else:
        body += f"按同一年度计划扣除已实现数，后五个月月均尚需 {calc(unit,'remaining_monthly_target')} 万元；这不是已获批的月度分解计划。"
    body += "\n\n" + profit_table(unit, n)
    chart_interpretation = ("同比改善仍未达到序时计划，不能用增长率代替预算达标判断。"
                            if unit != units[4] else "同比与序时均大幅上升，但产量和成本尚未验证超额利润的持续性。")
    body += (f"\n{charts[unit]}\n\n图中本年累计实际与上年同期、同期间序时计划同口径比较；"
             f"累计同比 {calc(unit,'ytd_change_rate')}%，序时差额 {calc(unit,'budget_difference')} 万元。"
             f"{chart_interpretation}图中来源和计算标注均取自本轮已核验利润表。\n\n")
    body += (f"### 经营变化分析\n\n{insight}原表显示吨矿成本同比 {calc(unit,f'cost.r{cost_row}.ore_cost_yoy_rate')}%，"
             f"金属成本同比 {calc(unit,f'cost.r{cost_row}.metal_cost_yoy_rate')}%；"
             f"选矿处理量同比 {calc(unit,f'cost_inputs.r{input_row}.processed_yoy_rate')}%，"
             f"金属折合量同比 {calc(unit,f'cost_inputs.r{input_row}.metal_yoy_rate')}%。"
             f"变动吨矿成本同比 {calc(unit,f'cost.r{cost_row}.variable_yoy_rate')}%，"
             f"人工及折旧同比 {calc(unit,f'cost_inputs.r{input_row}.labor_depr_yoy_rate')}%。"
             "人工折旧与处理量的变化方向需在费用归集及分母核对后再解释，不能把同比差额直接当作利润贡献。"
             "吨矿与金属成本的分母不同；处理量和金属量的变化方向只构成追查线索，不是品位或回收率的直接计算结果。\n\n")
    if copper_row:
        body += (f"\n\n铜精矿含铜产量 {fact(unit,f'concentrate.r{copper_row}.production')} 吨，"
                 f"销量 {fact(unit,f'concentrate.r{copper_row}.sales')} 吨；原表未提供同口径上年产量，"
                 "两数之差不能直接认定为库存变动。"
                 f"含铜销量同比 {calc(unit,f'concentrate.r{copper_row}.sales_yoy_rate')}%，"
                 f"均价同比 {calc(unit,f'concentrate.r{copper_row}.price_yoy_rate')}%；"
                 "含金与含银按公斤另列，不与含铜吨数相加。")
        for offset, product in [(1, "含金"), (2, "含银")]:
            row = copper_row + offset
            body += (f"{product}产量 {fact(unit,f'concentrate.r{row}.production')} 公斤、"
                     f"销量 {fact(unit,f'concentrate.r{row}.sales')} 公斤，"
                     f"销量同比 {calc(unit,f'concentrate.r{row}.sales_yoy_rate')}%，"
                     f"均价同比 {calc(unit,f'concentrate.r{row}.price_yoy_rate')}%；"
                     f"原表量差影响 {fact(unit,f'concentrate.r{row}.volume_effect')} 万元，"
                     f"价差影响 {fact(unit,f'concentrate.r{row}.price_effect')} 万元，"
                     "属于产品专项模拟拆分，不能独立认定为净利润变化。")
        body += f"含铜原始销量定位 {source(unit,f'concentrate.r{copper_row}.sales')}。"
    else:
        body += "\n\n四矿铜精矿专项原表未列本单位，不将其他矿山产品指标移植到本单位。"
    sales_direction = "高于" if float(point(unit,f"sulfur.r{sulfur_row}.sales")["value"]) > float(point(unit,f"sulfur.r{sulfur_row}.sales_plan",basis="budget",version="time_plan")["value"]) else "低于"
    body += (f"\n\n硫精矿销量同比 {calc(unit,f'sulfur.r{sulfur_row}.sales_yoy_rate')}%，"
             f"本期 {fact(unit,f'sulfur.r{sulfur_row}.sales')} 万吨，{sales_direction}原表计划"
             f" {fact(unit,f'sulfur.r{sulfur_row}.sales_plan',basis='budget',version='time_plan')} 万吨；"
             f"均价同比 {calc(unit,f'sulfur.r{sulfur_row}.price_yoy_rate')}%，"
             f"本期均价 {fact(unit,f'sulfur.r{sulfur_row}.price')} 元/吨，原表计划均价"
             f" {fact(unit,f'sulfur.r{sulfur_row}.price_plan',basis='budget',version='time_plan')} 元/吨。"
             f"原表 M 列 {fact(unit,f'sulfur.r{sulfur_row}.cost_prior','2025-07')} 元/吨是上年单位成本；"
             "缺本年同口径成本，不能计算本年硫精矿单位毛利或其同比。"
             "价量方向需与库存、结算和成本一起核对，不能直接换算为累计利润贡献。\n\n")
    body += indicator_table(unit, n)
    body += (f"\n\n### 管理关注\n\n{action}\n\n{focus_details[unit]}对经营影响先列明为待核事项；"
             "专项原表的量价增减利字段没有与单位利润总额逐项桥接，故不作为已确认利润归因。\n\n"
             "### 人工确认\n\n需业务签认本单位利润、序时计划和年度计划是否属于同一组织范围；"
             "补充逐月生产、成本、产品库存、销售结算和内部交易台账。"
             f"利润比较定位 {source(unit,'profit_total')}，吨矿成本定位 {source(unit,f'cost.r{cost_row}.ore_cost')}，"
             f"处理量定位 {source(unit,f'cost_inputs.r{input_row}.processed')}，硫精矿定位 {source(unit,f'sulfur.r{sulfur_row}.sales')}。")
    return body


scope = ("本报告分析对象为利润主表中的矿山板块独立合计行和六家矿山，顺序为德兴铜矿（含新技术）、永平铜矿、武山铜矿、城门山铜矿、银山矿业、银珠山矿业。统计期为本年1—7月，与上年同期、7月与6月、同期间序时计划及全年计划分别比较。七宝山只存在于硫精矿专项原表，在第五章独立展示，不并入六矿单位利润。集团合并和母公司口径未获确认，因此本稿不把矿山板块合计称为已审定集团合并利润。\n\n"
         "**数据性质：MOCK技术工作稿。** 进入本轮数值分析的四份原始工作簿均有模拟数据标识；其他背景材料分别核查用途，不推断其均为模拟材料。文件名中的10月14日是材料批次日期，不是经营统计月份。本稿的金额、成本和产销量只供验证长报告流程，不能直接用于绩效考核、预算批复或对外披露。\n\n"
         "本轮归档13份文件。利润、矿山成本、四矿铜精矿及硫精矿四份进入可追溯数值分析，其余九份逐份检查后作为背景或口径边界记录：\n\n"
         "| 原始材料 | 本轮用途 | 判断依据 |\n| --- | --- | --- |\n")
for item in material_uses:
    scope += f"| {material_lookup[item['material_id']]['original_name']} | {'分析' if item['use']=='analysis' else '背景与边界'} | {item['reason']} |\n"
scope += ("\n年度产品计划与六矿销售量不是相同指标；硬件报价没有矿山采购需求和授权；报告期后的贵金属行情未经同口径核验。这些材料不生成虚构完成率、净采购量或投资收益。材料原件哈希、来源单元格、接受的事实及计算输入均保存在本轮版本清单。")

sector = (f"矿山板块原表合计本年1—7月利润 {fact('矿山板块合计','profit_total')} 万元，"
          f"较上年同期增加 {calc('矿山板块合计','ytd_change')} 万元、同比 {calc('矿山板块合计','ytd_change_rate')}%；"
          f"较同期间序时计划高 {calc('矿山板块合计','budget_difference')} 万元，完成率 {calc('矿山板块合计','budget_completion_rate')}%。"
          f"7月利润较6月增加 {calc('矿山板块合计','month_change')} 万元。年度计划完成率"
          f" {calc('矿山板块合计','annual_plan_completion_rate')}%，后续仍须看单位结构与月度持续性。\n\n"
          "表3-1 矿山板块及六矿累计利润结构（万元）\n\n"
          "| 主体 | 本年累计 | 上年同期 | 同比率 | 序时计划 | 计划差额 |\n| --- | ---: | ---: | ---: | ---: | ---: |\n")
for unit in ["矿山板块合计", *units]:
    sector += (f"| {unit} | {fact(unit,'profit_total')} | {fact(unit,'profit_total','2025-07')} | "
               f"{calc(unit,'ytd_change_rate')}% | {fact(unit,'profit_total',basis='budget',version='time_plan')} | "
               f"{calc(unit,'budget_difference')} |\n")
sector += (f"\n板块合计的序时正差额主要来自银山矿业 {calc(units[4],'budget_difference')} 万元的超额，"
           f"德兴铜矿序时差额为 {calc(units[0],'budget_difference')} 万元；其余四矿也存在缺口。"
           "银山超过全年计划但生产与成本指标并未同步改善，意味着总量达标的质量需重点复核。"
           f"板块原表合计来源 {source('矿山板块合计','profit_total')}，"
           "本轮核对其与六矿对应行的算术关系；这不等于会计抵销和归属规则已签认。\n\n"
           f"{charts['矿山板块合计']}\n\n图示板块累计利润高于同期与序时计划，但单列合计不能遮蔽单位计划偏差。")

special = ("### 四矿铜精矿产销\n\n四矿原表分别列含铜、含金和含银。含铜销量与价格采用同一产品同一期间比较；金银以公斤单列，不能与含铜吨数合计。"
           "下面的原表增减利是专项模拟拆分，不代表已核定净利润贡献；需要产品成本、库存和内部交易抵销才能接入单位利润桥。\n\n"
           "表5-1 四矿铜精矿含铜价量变化与原表影响\n\n"
           "| 单位 | 含铜销量同比 | 含铜均价同比 | 原表量差影响（万元） | 原表价差影响（万元） |\n| --- | ---: | ---: | ---: | ---: |\n")
for unit in units[:4]:
    row = rows[unit][2]
    special += (f"| {unit} | {calc(unit,f'concentrate.r{row}.sales_yoy_rate')}% | "
                f"{calc(unit,f'concentrate.r{row}.price_yoy_rate')}% | "
                f"{fact(unit,f'concentrate.r{row}.volume_effect')} | {fact(unit,f'concentrate.r{row}.price_effect')} |\n")
special += (f"\n武山含铜销量同比变化 {calc(units[2],'concentrate.r12.sales_yoy_rate')}%，"
            f"城门山同比变化 {calc(units[3],'concentrate.r16.sales_yoy_rate')}%；"
            "原表含铜均价同向上升，但两矿销量方向相反，应分别核对生产、库存及结算，而不能给四矿统一归因。"
            f"德兴含铜原表定位 {source(units[0],'concentrate.r4.sales')}。\n\n"
            "表5-2 四矿含金与含银专项量价线索\n\n"
            "| 单位及产品 | 本年产量 | 本年销量 | 销量同比 | 原表量差影响（万元） | 原表价差影响（万元） |\n| --- | ---: | ---: | ---: | ---: | ---: |\n")
for unit in units[:4]:
    copper_row = rows[unit][2]
    for offset, product in [(1,"含金（公斤）"),(2,"含银（公斤）")]:
        row = copper_row + offset
        special += (f"| {unit}{product} | {fact(unit,f'concentrate.r{row}.production')} | "
                    f"{fact(unit,f'concentrate.r{row}.sales')} | {calc(unit,f'concentrate.r{row}.sales_yoy_rate')}% | "
                    f"{fact(unit,f'concentrate.r{row}.volume_effect')} | {fact(unit,f'concentrate.r{row}.price_effect')} |\n")
special += "\n含金、含银价量影响保留原表产品口径，不与含铜吨数相加；产销差异须以库存和结算台账验证。\n\n"
special += (
            "### 六矿硫精矿与七宝山独立专项\n\n硫精矿原表有六矿及七宝山七个主体；七宝山不在利润主表六矿单位清单中，单列而不挪入任一矿山。"
            "原表量价影响可能与铜精矿、副产品和内部交易重叠，不加总为板块利润。\n\n"
            "表5-3 硫精矿销量与均价同比变化\n\n"
            "| 原表主体 | 销量同比 | 均价同比 | 原表量差影响（万元） | 原表价差影响（万元） |\n| --- | ---: | ---: | ---: | ---: |\n")
for unit, row in [*[(u, rows[u][3]) for u in units[:5]], ("sulfur:r9:七宝山", 9), (units[5], 10)]:
    label = "七宝山（独立专项）" if row == 9 else unit
    special += (f"| {label} | {calc(unit,f'sulfur.r{row}.sales_yoy_rate')}% | "
                f"{calc(unit,f'sulfur.r{row}.price_yoy_rate')}% | "
                f"{fact(unit,f'sulfur.r{row}.volume_effect')} | {fact(unit,f'sulfur.r{row}.price_effect')} |\n")
special += (f"\n七宝山销量同比 {calc('sulfur:r9:七宝山','sulfur.r9.sales_yoy_rate')}%，"
            f"均价同比 {calc('sulfur:r9:七宝山','sulfur.r9.price_yoy_rate')}%；"
            f"来源为专项原表 {source('sulfur:r9:七宝山','sulfur.r9.sales')}。"
            "永平和银山硫精矿销量下降而价格上升，其他主体量价方向不同；须按主体分别核对期间和结算，不以原表模拟量价差直接决定利润调整。")

common = (f"**利润计划的结构性压力。** 板块合计高于序时计划 {calc('矿山板块合计','budget_difference')} 万元，"
          f"但德兴序时差额 {calc(units[0],'budget_difference')} 万元与银山超额"
          f" {calc(units[4],'budget_difference')} 万元方向相反。"
          "将两者净额视为普遍改善会低估其余矿山的计划压力；预算办应先核实银山收益是否具有持续性，再分单位更新全年预测。\n\n"
          f"**采选效率与成本。** 城门山处理量同比 {calc(units[3],'cost_inputs.r19.processed_yoy_rate')}%，"
          f"金属量同比 {calc(units[3],'cost_inputs.r19.metal_yoy_rate')}%，"
          f"金属成本同比 {calc(units[3],'cost.r7.metal_cost_yoy_rate')}%；"
          "这一组合提示金属产出和成本分母需要联查。武山处理量、金属量增长且单位成本上行，应核实扩量边际成本；银珠山金属量增加而处理量下降，需核对计量口径。不存在单一适用于六矿的降本解释。\n\n"
          "**库存、采购与财务口径。** 当前没有六矿同口径的期初库存、目标期末库存、有效合同到货、未来耗用及资金计划，不能计算净采购量或资金需求。"
          "铜精矿、硫精矿专项的量价拆分与单位利润之间尚缺结算、库存、成本和抵销桥；需要业务部门确认计划版本、单位边界和内部交易。")

market = ("当前材料包含报告期后形成的贵金属市场文字资料，但没有与本年1—7月逐月经营、实际合同、库存及矿山销售结算相匹配的可核验价格序列。"
          "因此只将贵金属价格波动作为后续预算预测需跟踪的风险线索，不将其写作已发生利润变动的原因。铜精矿含铜原表均价上升属于本轮单位产品事实，但不等同于外部市场即时铜价。\n\n"
          "若要做可复算情景，预算办需提供各产品未来可销售量、合同计价基准与价格区间、库存可售量、单位变动成本及税费。届时情景增量可以按同口径产品量乘以净价格变化，再扣除相应变动成本与结算影响；"
          "在这些输入缺失前，不填造采购数量、利润敏感性金额或投资回收期。设备硬件报价亦缺矿山需求和预算授权，只列为待论证材料。")

decisions = ("建议把复核任务与经营判断分开，先处理能改变全年预算结论的异常，再评估采选和销售措施。\n\n"
             "表8-1 管理动作、依据及通过标准\n\n"
             "| 优先级与责任 | 本轮证据与影响 | 需要执行的核验 | 通过标准 |\n| --- | --- | --- | --- |\n"
             f"| 高：预算办与银山财务 | 银山序时差额 {calc(units[4],'budget_difference')} 万元、年度完成率 {calc(units[4],'annual_plan_completion_rate')}%；决定板块超额质量 | 拆经常经营、价格、暂估、套保、一次性和抵销的利润桥 | 分项与利润总额及会计台账勾稽，明确可持续部分 |\n"
             f"| 高：德兴财务与生产 | 德兴序时差额 {calc(units[0],'budget_difference')} 万元，处理量同比 {calc(units[0],'cost_inputs.r16.processed_yoy_rate')}%；影响后续目标 | 对停机、品位、回收、成本分配和结算逐月核对 | 生产、销售、财务三表同期间闭合，原因有书面依据 |\n"
             f"| 高：城门山生产与成本部门 | 金属量同比 {calc(units[3],'cost_inputs.r19.metal_yoy_rate')}%，金属成本同比 {calc(units[3],'cost.r7.metal_cost_yoy_rate')}%；影响采选效率判断 | 按矿种复核金属折合口径及成本分母 | 计量和费用归集与财务期间一致 |\n"
             "| 中：四矿销售与六矿财务 | 铜精矿与硫精矿专项仅是模拟量价拆分；可能与利润桥重叠 | 核对生产、库存、销售合同、结算与内部交易 | 同一产品同一期间复算，重复项目剔除 |\n"
             "| 中：预算办与采购部门 | 缺同物料库存、耗用、合同与授权；无法计算采购需求 | 补齐采购计划和设备需求论证 | 再提出数量、资金或项目投资决策 |\n\n"
             "人工签认清单：六矿和七宝山的组织归属；矿山板块合计的会计抵销规则；序时及年度计划版本；销售结算与产品专项的期间；模拟材料能否替换为正式台账。"
             "未完成上述签认时，本稿只用于识别复核优先级。")

executive = (f"**结论与决策。** 原表矿山板块本年1—7月利润 {fact('矿山板块合计','profit_total')} 万元，"
             f"同比 {calc('矿山板块合计','ytd_change_rate')}%，"
             f"高于序时计划 {calc('矿山板块合计','budget_difference')} 万元。"
             "板块达标由单位间的大额相反偏差抵补，并不代表六矿普遍达标。"
             f"银山超序时 {calc(units[4],'budget_difference')} 万元且年度计划完成率"
             f" {calc(units[4],'annual_plan_completion_rate')}%，"
             f"德兴序时差额为 {calc(units[0],'budget_difference')} 万元。"
             "管理层应先要求两家提交可勾稽的利润桥，再决定是否调整全年预测。\n\n"
             "**经营变化。** 德兴矿石处理量下降而单位成本上升；武山增量伴随单位成本上行；城门山处理量增长但金属量下降；银珠山利润同比增幅受低基数影响。"
             "这些组合决定复核对象各不相同，不能用一个价格上涨解释六矿利润。铜精矿和硫精矿专项可说明价量方向，尚未与利润桥闭合。\n\n"
             "**预算、采购和风险。** 先补齐计划版本、会计抵销、库存及结算资料。现有硬件报价与矿山采购需求未关联，暂无可支持的净采购量或采购金额结论。"
             "本稿基于MOCK模拟原件，业务口径尚待签认，只能作为技术工作稿和复核清单。")

methods = ("**计算口径。** 本月环比＝7月实际减6月实际；本年累计同比＝本年1—7月减上年同期；变化率以同口径正基数为分母。"
           "序时计划差额＝累计实际减同期间序时计划，完成率＝累计实际除以序时计划；年度计划完成率＝累计实际除以全年计划，后五个月月均尚需＝全年计划减累计实际后除以五。"
           "各项差额和比率由本轮冻结证据后注册算子计算，先用未舍入值计算再显示。基数非正或缺少同口径数据时不强造增长率。\n\n"
           "**来源与可复核性。** 利润主表为《利润计划执行情况表》矿山六矿及板块合计行；成本和生产量为《矿山成本指标完成情况》各矿对应行；"
           "含铜、含金和含银来自《四矿铜精矿产销增减利情况》；硫精矿及七宝山来自《硫精矿增减利分析》。"
           "正文各矿表格和叙述保留源单元格引用；每个计算记录保留输入事实ID、源文件哈希及状态。\n\n"
           "**口径边界。** 矿山板块原表合计不等于已确认会计合并；专项量价差不是利润总额归因。"
           "年度产品产量计划没有同范围的完整产量台账，市场材料没有可核验的期间价格序列，硬件报价没有采购需求。"
           "缺口由预算、生产、销售、采购和财务部门确认后，方能把本技术稿升级为正式经营报告。")

bodies = {"executive": executive, "scope": scope, "sector": sector, "special": special,
          "common": common, "market": market, "decisions": decisions, "methods": methods}
bodies.update({"units:" + unit: unit_body(unit, n) for n, unit in enumerate(units, 1)})
assert {task["section_id"] for task in tasks} == set(bodies)

submitted = set()
while len(submitted) < len(tasks):
    next_task = next((task for task in tasks if task["section_id"] not in submitted
                      and set(task["depends_on"]) <= submitted), None)
    assert next_task is not None, "chapter dependency cycle"
    context = cli("draft", "context", next_task["id"], "--project", project_id)
    if context["task"]["status"] == "submitted":
        cli("draft", "submit", request={"project_id": project_id, "run_id": run_id,
                                        "task_id": next_task["id"], "author_id": "codex_mining_writer_20261024",
                                        "body": bodies[next_task["section_id"]], "replace": True})
        submitted.add(next_task["section_id"])
        continue
    assert context["task"]["status"] == "ready", (next_task["section_id"], context["task"]["status"])
    cli("draft", "submit", request={"project_id": project_id, "run_id": run_id,
                                    "task_id": next_task["id"], "author_id": "codex_mining_writer_20261024",
                                    "body": bodies[next_task["section_id"]]})
    submitted.add(next_task["section_id"])
    print("written", next_task["section_id"], flush=True)
draft = cli("draft", "build", request={"project_id": project_id, "run_id": run_id})
(WORK / "draft.json").write_text(json.dumps(draft, ensure_ascii=False, indent=2), encoding="utf-8")
print("draft", draft["markdown_path"], draft["sha256"], flush=True)
