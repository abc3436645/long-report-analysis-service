"""Draft the mining report from this run's frozen evidence and calculated IDs."""

import json
import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / "projects" / os.environ.get("MINING_WORK", "mining_board_2026_07_acceptance")
REPORT = ROOT / ".venv" / "bin" / "report"
REQUEST = WORK / "request.json"
session = json.loads((WORK / "session.json").read_text(encoding="utf-8"))
project_id, run_id = session["project_id"], session["run_id"]
evidence = json.loads((WORK / "evidence.json").read_text(encoding="utf-8"))
calculations = json.loads((WORK / "calculations.json").read_text(encoding="utf-8"))
units = ["德兴铜矿（含新技术）", "永平铜矿", "武山铜矿", "城门山铜矿", "银山矿业", "银珠山矿业"]
rows = dict(zip(units, [(4, 16), (5, 17), (6, 18), (7, 19), (9, 21), (10, 22)]))


def call(*args, request=None):
    command = [str(REPORT), *args, "--workspace", str(WORK / "projects")]
    if request is not None:
        REQUEST.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
        command += ["--request", str(REQUEST)]
    response = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    if response.returncode:
        raise RuntimeError(f"{' '.join(args)}: {response.stderr[:2000]}")
    return json.loads(response.stdout)["data"]


def point(subject, metric, period="2026-07", window="ytd", basis="actuals", version=None):
    found = [item for item in evidence if item["subject_id"] == subject and item["metric_id"] == metric
             and item["period"] == period and item["window"] == window and item["basis"] == basis
             and item.get("budget_version") == version]
    assert len(found) == 1, (subject, metric, period, window, basis, version, len(found))
    return found[0]


def metric(subject, name):
    found = [item for item in calculations if item["subject_id"] == subject and item["metric_id"] == name
             and item["status"] == "calculated"]
    assert len(found) == 1, (subject, name, len(found))
    return found[0]


def fact(subject, name, period="2026-07", window="ytd", basis="actuals", version=None, digits=2):
    return "{{fact:" + point(subject, name, period, window, basis, version)["id"] + f"|{digits}" + "}}"


def calc(subject, name, digits=2):
    return "{{calc:" + metric(subject, name)["id"] + f"|{digits}" + "}}"


def source(subject, name, period="2026-07", window="ytd", basis="actuals", version=None):
    return "{{ev:" + point(subject, name, period, window, basis, version)["id"] + "}}"


charts = {}
for subject in ["矿山板块合计", *units]:
    series = [
        {"label": "本年1—7月实际", "evidence_id": point(subject, "profit_total")["id"]},
        {"label": "上年同期实际", "evidence_id": point(subject, "profit_total", "2025-07")["id"]},
        {"label": "本年1—7月序时计划", "evidence_id": point(subject, "profit_total", basis="budget", version="time_plan")["id"]},
    ]
    chart = call("chart", "create", request={"project_id": project_id, "run_id": run_id,
                                               "title": f"{subject}累计利润与同期、序时计划比较", "series": series})
    assert chart["annotations"] and Path(chart["path"]).is_file()
    charts[subject] = "{{chart:" + chart["id"] + "}}"

outline = {"unit_names": units, "unit_levels": {name: 2 for name in units}, "sections": [
    {"id": "executive_summary", "title": "一、管理层摘要", "display_order": 1, "repeat_for": None,
     "depends_on": ["recommendations"], "evidence_refs": ["actual_amount", "budget_amount"],
     "analysis_refs": ["ytd_change_rate", "budget_difference"]},
    {"id": "scope", "title": "二、分析范围、材料与口径", "display_order": 2, "repeat_for": None,
     "depends_on": [], "evidence_refs": [], "analysis_refs": []},
    {"id": "sector", "title": "三、矿山板块整体表现", "display_order": 3, "repeat_for": None,
     "depends_on": ["scope"], "evidence_refs": ["actual_amount", "budget_amount"],
     "analysis_refs": ["budget_difference", "ytd_change_rate"]},
    {"id": "unit_analysis", "title": "四、六家矿山单位经营与成本分析", "display_order": 4,
     "repeat_for": "unit", "depends_on": ["sector"], "evidence_refs": ["actual_amount", "budget_amount"],
     "analysis_refs": ["budget_difference", "ytd_change_rate", "annual_plan_completion_rate"]},
    {"id": "special_analysis", "title": "五、铜精矿与硫精矿专项", "display_order": 5, "repeat_for": None,
     "depends_on": ["unit_analysis"], "evidence_refs": [],
     "analysis_refs": ["concentrate.r4.sales_yoy_rate", "sulfur.r4.price_yoy_rate"]},
    {"id": "risks", "title": "六、主要风险与待核事项", "display_order": 6, "repeat_for": None,
     "depends_on": ["special_analysis"], "evidence_refs": [], "analysis_refs": []},
    {"id": "recommendations", "title": "七、管理建议与复核清单", "display_order": 7, "repeat_for": None,
     "depends_on": ["risks"], "evidence_refs": [], "analysis_refs": []},
    {"id": "methods", "title": "八、计算方法与来源索引", "display_order": 8, "repeat_for": None,
     "depends_on": ["scope"], "evidence_refs": [], "analysis_refs": []},
]}
tasks = call("draft", "plan", request={"project_id": project_id, "run_id": run_id,
                                       "report_request": "以本轮预算办 MOCK 原始数据编写 2026 年 1—7 月矿山板块月度经营分析技术工作稿；六矿分别分析利润、计划进度、吨矿及金属成本、处理量和金属量；四矿铜精矿及硫精矿作专项；显示计算指标、来源与待核事项。",
                                       "outline": outline})
assert len(tasks) == 13

scope = """本稿围绕矿山板块及德兴铜矿（含新技术）、永平铜矿、武山铜矿、城门山铜矿、银山矿业、银珠山矿业六家单位，报告期为 2026 年 1—7 月。来源文件批次日期为 2026 年 10 月 14 日，不能据此把数据解释为 10 月经营结果。七宝山仅作为硫精矿专项原表中的独立行展示，不并入六矿单位分析。\n\n本轮仅采用利润计划执行、矿山成本指标、四矿铜精矿产销增减利、硫精矿增减利四份原始工作簿。所有工作簿标有 **MOCK**，本稿是技术工作稿，数值与结论均不代表真实经营事实。《年度计划主要数据》包含矿山产品年产量计划，但本轮没有同范围的完整产量台账与计划版本核对，因此未据此推断年度产量完成率；其他材料没有用于矿山利润归因。\n\n利润金额单位为万元；成本为元/吨；处理量、金属量、铜精矿销量按各原表单位展示。同比使用本年 1—7 月与上年同期，环比使用 7 月与 6 月；序时计划与年度计划分别比较，不能互代。板块合计使用利润原表的独立行，不把六矿结果解释为已确认的会计合并口径。集团合并规则尚未获业务确认，正式经营结论须复核。"""

sector = (
    f"矿山板块原表合计的累计利润为 {fact('矿山板块合计','profit_total')} 万元，"
    f"同比增加 {calc('矿山板块合计','ytd_change')} 万元，增幅 {calc('矿山板块合计','ytd_change_rate')}%；"
    f"较序时计划高 {calc('矿山板块合计','budget_difference')} 万元，序时计划完成率 {calc('矿山板块合计','budget_completion_rate')}%。"
    f"7 月单月较 6 月增加 {calc('矿山板块合计','month_change')} 万元。"
    "板块总量达标并不意味着单位普遍达标，结构主要由银山矿业的超计划抵补德兴铜矿等单位的缺口；不可据此直接确认利润增长的经营原因。\n\n"
    "| 利润主体 | 本年累计实际（万元） | 上年同期（万元） | 累计同比（%） | 序时计划（万元） | 计划差额（万元） |\n"
    "| --- | ---: | ---: | ---: | ---: | ---: |\n"
)
for subject in ["矿山板块合计", *units]:
    sector += (f"| {subject} | {fact(subject,'profit_total')} | {fact(subject,'profit_total','2025-07')} | "
               f"{calc(subject,'ytd_change_rate')} | {fact(subject,'profit_total',basis='budget',version='time_plan')} | "
               f"{calc(subject,'budget_difference')} |\n")
sector += ("\n差额按实际减序时计划列示；六矿中银山矿业为正，其余五家为负。板块合计来源为利润表单列行，"
           f"本次核对其单元格与六矿对应行的求和关系；来源定位：{source('矿山板块合计','profit_total')}，"
           f"序时计划 {source('矿山板块合计','profit_total',basis='budget',version='time_plan')}。\n\n"
           + charts["矿山板块合计"])

unit_notes = {
    units[0]: "累计利润同比改善，但序时计划缺口仍是六矿中最大的管理关注点。同期矿石处理量回落、吨矿及金属成本上升，说明需同步核查产量、品位、回收率和费用分摊；这些并非本稿已证实的利润因果链。铜精矿含铜销量基本持平、结算价格同比抬升，进一步说明应以单位级利润桥复核价量与成本的共同作用。",
    units[1]: "累计利润同比增长且接近序时计划，但吨矿和金属成本同比抬升幅度较大。处理量与金属量均上升，仍不能据此断定成本上涨的原因；应核对变动成本、人工折旧及采选条件。铜精矿含铜销量略减，需与售价、库存及结算节奏共同复核。",
    units[2]: "处理量、金属量和铜精矿含铜销量均同比提升，累计利润亦增长，但尚有序时计划缺口。吨矿与金属成本同时上行，应核实增产对应的边际成本和结算口径；产销价量原表的增减利拆分只可作专项线索，不能直接替代利润归因。",
    units[3]: "累计利润同比增长但未完成序时计划。处理量小幅增长而金属量同比回落、金属成本明显上升，经营质量需要重点核对；建议追查入选品位、回收率和产品结算明细，不能单凭处理量变化推断利润成因。铜精矿含铜销量同比下降，应与金属量数据对照核查。",
    units[4]: "累计利润大幅超过同期和序时计划，并已超过年度计划；这是板块合计达标的主要结构性支撑。不过金属量略降、吨矿与金属成本上行，利润跃升不能简单解释为产量或成本效率改善。应优先核对价格、存货结算、一次性收益及内部交易抵销。",
    units[5]: "累计利润同比增幅较高，但上年同期基数较低，且本年仍低于序时计划。金属量上升、金属成本下降，与处理量下降并存；应复核品位、回收率、产品组合和成本分摊后再判断改善是否可持续。",
}
followups = {
    units[0]: "管理动作应先把处理量下降和单位成本上升分开复算，再与含铜销量、售价及结算时点逐项勾稽。若原表利润桥无法闭合，先保留缺口，不用价格上涨作兜底解释。",
    units[1]: "变动成本与人工折旧应分别拆出，核对加工量增加时的单位成本变化。计划差额虽小，仍需确认本期利润是否受暂估结算或库存变化影响。",
    units[2]: "增产与成本同升并存，建议核对矿石来源、品位、回收率和新增处理量的边际收益；含铜销量显著增长也需要与产品库存及发运记录勾稽。",
    units[3]: "处理量与金属量背离是主要核查入口。先用生产台账复核品位和回收率，再对含铜销量下降与库存结转、销售确认时点建立交叉检查。",
    units[4]: "优先拆分价格和一次性项目，并核对同一期间的成本、销售与内部抵销。只有利润桥闭合后，才可把超计划结果视为可持续经营改善。",
    units[5]: "应把低基数效应与实际采选改善分开；金属量增长和金属成本下降可作为复核线索，但处理量下降及计划缺口说明改善质量仍需验证。",
}

unit_bodies = {}
for subject in units:
    cost_row, input_row = rows[subject]
    body = (f"**利润判断。** {unit_notes[subject]}本年累计利润同比变动率 {calc(subject,'ytd_change_rate')}%，"
            f"较序时计划差额 {calc(subject,'budget_difference')} 万元，"
            f"年度计划完成率 {calc(subject,'annual_plan_completion_rate')}%。\n\n"
            f"**经营交叉检查。** 吨矿成本同比 {calc(subject,f'cost.r{cost_row}.ore_cost_yoy_rate')}%，"
            f"金属成本同比 {calc(subject,f'cost.r{cost_row}.metal_cost_yoy_rate')}%；"
            f"矿石处理量同比 {calc(subject,f'cost_inputs.r{input_row}.processed_yoy_rate')}%，"
            f"金属量同比 {calc(subject,f'cost_inputs.r{input_row}.metal_yoy_rate')}%。"
            f"{followups[subject]}\n\n"
            "| 利润比较项目 | 本年实际（万元） | 比较基准（万元） | 差额或完成率 |\n"
            "| --- | ---: | ---: | ---: |\n"
            f"| 累计同比 | {fact(subject,'profit_total')} | {fact(subject,'profit_total','2025-07')} | {calc(subject,'ytd_change')} 万元 |\n"
            f"| 累计与序时计划 | {fact(subject,'profit_total')} | {fact(subject,'profit_total',basis='budget',version='time_plan')} | {calc(subject,'budget_difference')} 万元 |\n"
            f"| 累计与年度计划 | {fact(subject,'profit_total')} | {fact(subject,'profit_total','2026','annual','budget','annual_plan')} | {calc(subject,'annual_plan_completion_rate')}% |\n\n"
            "| 经营指标 | 本年1—7月 | 上年同期 | 同比差额 | 同比率 |\n"
            "| --- | ---: | ---: | ---: | ---: |\n"
            f"| 吨矿成本（元/吨） | {fact(subject,f'cost.r{cost_row}.ore_cost')} | {fact(subject,f'cost.r{cost_row}.ore_cost_prior','2025-07')} | {calc(subject,f'cost.r{cost_row}.ore_cost_yoy_difference')} | {calc(subject,f'cost.r{cost_row}.ore_cost_yoy_rate')}% |\n"
            f"| 金属成本（元/吨） | {fact(subject,f'cost.r{cost_row}.metal_cost')} | {fact(subject,f'cost.r{cost_row}.metal_cost_prior','2025-07')} | {calc(subject,f'cost.r{cost_row}.metal_cost_yoy_difference')} | {calc(subject,f'cost.r{cost_row}.metal_cost_yoy_rate')}% |\n"
            f"| 矿石处理量（吨） | {fact(subject,f'cost_inputs.r{input_row}.processed',digits=0)} | {fact(subject,f'cost_inputs.r{input_row}.processed_prior','2025-07',digits=0)} | {calc(subject,f'cost_inputs.r{input_row}.processed_yoy_difference',0)} | {calc(subject,f'cost_inputs.r{input_row}.processed_yoy_rate')}% |\n"
            f"| 金属量（吨） | {fact(subject,f'cost_inputs.r{input_row}.metal',digits=0)} | {fact(subject,f'cost_inputs.r{input_row}.metal_prior','2025-07',digits=0)} | {calc(subject,f'cost_inputs.r{input_row}.metal_yoy_difference',0)} | {calc(subject,f'cost_inputs.r{input_row}.metal_yoy_rate')}% |\n\n"
            f"来源定位：累计利润 {source(subject,'profit_total')}、序时计划 {source(subject,'profit_total',basis='budget',version='time_plan')}；"
            f"吨矿成本 {source(subject,f'cost.r{cost_row}.ore_cost')}、金属量 {source(subject,f'cost_inputs.r{input_row}.metal')}。"
            "利润、成本与产量表的单位和期间按各自原表保留；成本变化不是经验证的利润贡献额。\n\n"
            + charts[subject])
    unit_bodies[subject] = body

special = ("### 铜精矿含铜：价量变化与原表增减利线索\n\n"
           "四矿铜精矿含铜采用各单位对应产品行。售价同比上升与销量变化方向并不一致；武山销量增加，德兴、永平和城门山下降。下表中的增减利为原表模拟拆分，不等同于矿山单位累计利润的已核实归因，且不能与其他产品未经去重直接相加。\n\n"
           "| 单位 | 含铜销量同比（%） | 价格同比（%） | 原表销量增减利（万元） | 原表价格增减利（万元） |\n"
           "| --- | ---: | ---: | ---: | ---: |\n")
for subject, row in zip(units[:4], (4, 8, 12, 16)):
    special += (f"| {subject} | {calc(subject,f'concentrate.r{row}.sales_yoy_rate')} | "
                f"{calc(subject,f'concentrate.r{row}.price_yoy_rate')} | "
                f"{fact(subject,f'concentrate.r{row}.volume_effect')} | "
                f"{fact(subject,f'concentrate.r{row}.price_effect')} |\n")
special += (f"\n德兴含铜销量来源 {source(units[0],'concentrate.r4.sales')}；武山原表销量增减利来源 "
            f"{source(units[2],'concentrate.r12.volume_effect')}。四矿金、银产品亦在原表中，本稿没有将不同计量单位的销量汇总。\n\n"
            "### 硫精矿：销量分化、价格上行\n\n"
            "原表七个主体中含七宝山专项行。德兴、武山、城门山、银珠山及七宝山销量同比增加，永平和银山下降；价格同比均上行。下表分别展示单位变化率与原表模拟拆分，不能直接加总为矿山板块利润贡献。\n\n"
            "| 原表主体 | 销量同比（%） | 价格同比（%） | 原表销量增减利（万元） | 原表价格增减利（万元） |\n"
            "| --- | ---: | ---: | ---: | ---: |\n")
for subject, row in [*zip(units[:5], (4, 5, 6, 7, 8)), ("sulfur:r9:七宝山", 9), (units[5], 10)]:
    label = "七宝山（专项行）" if row == 9 else subject
    special += (f"| {label} | {calc(subject,f'sulfur.r{row}.sales_yoy_rate')} | "
                f"{calc(subject,f'sulfur.r{row}.price_yoy_rate')} | "
                f"{fact(subject,f'sulfur.r{row}.volume_effect')} | "
                f"{fact(subject,f'sulfur.r{row}.price_effect')} |\n")
special += (f"\n硫精矿销量和价格来源示例：德兴 {source(units[0],'sulfur.r4.sales')}，"
            f"七宝山 {source('sulfur:r9:七宝山','sulfur.r9.sales')}。不同材料的金额与单位可能存在结算、库存及内部交易差异，需业务部门复核。")

risks = """1. **板块达标的集中度。** 银山矿业超过序时计划，而其他五家单位仍有计划缺口；后续月份若银山收益不可持续，板块目标面临回落风险。需由预算办核对银山利润构成和是否含一次性项目。\n\n2. **产量与成本变化不能自动解释利润。** 德兴处理量下降且成本上升；城门山处理量增而金属量降；武山增产伴随成本上升。原表没有完整的品位、回收率、存货、结算及内部抵销资料，现阶段仅能识别异常组合。\n\n3. **计划和合并口径待签认。** 本稿使用利润表序时计划列作为预算比较、年度计划列作为年度完成率分母。业务部门需确认计划版本、矿山板块合计范围、六矿与七宝山的归属及内部交易抵销规则。\n\n4. **模拟数据限制。** 原始表均标有 MOCK。铜精矿和硫精矿增减利为来源表的模拟桥接字段，不能作为真实财务披露或已审定的因果归因。"""

recommendations = """| 优先级 | 管理动作 | 负责复核材料 | 通过标准 |\n| --- | --- | --- | --- |\n| 高 | 对银山超计划、德兴缺口建立单位利润桥，逐项分离价格、销量、成本、一次性及内部交易影响 | 利润明细、结算与抵销台账 | 各项贡献与单位利润差额可勾稽；异常差额有书面说明 |\n| 高 | 复核德兴、城门山、武山采选效率与单位成本，核实吨矿成本、金属成本分母与期间 | 生产日报、品位回收率、成本分配表 | 处理量、金属量及成本与财务期间一致 |\n| 中 | 对四矿铜精矿、硫精矿价量拆分进行来源核验，查明销量与生产量差异 | 产品台账、库存、销售结算单 | 同口径价量桥可复算，且未重复计入利润桥 |\n| 中 | 确认矿山板块计划版本与会计合并边界后重发正式稿 | 预算批复、组织口径、合并抵销表 | 计划分母、单位归属和合计范围获业务签认 |\n\n在复核完成前，建议把本稿用于识别核查优先级，不用于绩效考核或对外披露。"""

summary = (f"**总体判断。** 原表矿山板块本年 1—7 月累计利润 {fact('矿山板块合计','profit_total')} 万元，"
           f"同比增长 {calc('矿山板块合计','ytd_change_rate')}%，"
           f"高于序时计划 {calc('矿山板块合计','budget_difference')} 万元。"
           "达标结构集中：银山矿业大幅超计划，德兴及其余四家有不同程度缺口。\n\n"
           f"**首要偏差。** 德兴铜矿较序时计划差额 {calc(units[0],'budget_difference')} 万元，"
           f"银山矿业差额 {calc(units[4],'budget_difference')} 万元；"
           "应优先核对这两家的利润桥和一次性因素，而非只看板块合计。\n\n"
           "**经营信号。** 六矿成本及处理量走势分化；城门山金属量下降、武山增产伴随成本上升、银珠山改善受低基数影响。铜精矿与硫精矿价格走高不能直接等同于已确认利润贡献。\n\n"
           "**交付边界。** 本稿使用 MOCK 来源，计划版本、合并规则及价量成本桥仍需业务复核。建议先完成高优先级台账核对，再形成正式经营判断。")

methods = """**计算。** 同比差额＝本年 1—7 月实际－上年同期实际；同比率＝差额÷上年同期实际×100%。环比差额＝7 月实际－6 月实际。序时计划差额＝累计实际－累计序时计划，完成率＝累计实际÷累计序时计划×100%；年度计划完成率＝累计实际÷年度计划×100%。分母为零、负数或不可比时系统应显示状态，不强造增长率。报告中显示的百分比和差额均来自本轮冻结证据后的注册算子，金额按展示精度四舍五入。\n\n**来源索引。** ①《利润计划执行情况表_2026-10-14.xlsx》Sheet1，矿山单位及板块合计行；②《矿山成本指标完成情况_2026-10-14.xlsx》Sheet1，六矿成本与成本形成量行；③《四矿铜精矿产销增减利情况_2026-10-14.xlsx》Sheet1，四矿含铜产品行；④《硫精矿增减利分析_2026-10-14.xlsx》Sheet1，六矿及七宝山行。各节保留关键单元格定位；完整证据 ID、计算输入及文件哈希保存在本轮项目版本清单。\n\n**解释边界。** 板块合计、单位利润与产品增减利分属不同报表层次；未经计划版本、会计抵销与业务归因签认，不将专项拆分数求和为板块利润。"""

bodies = {"scope": scope, "sector": sector, "special_analysis": special,
          "risks": risks, "recommendations": recommendations,
          "executive_summary": summary, "methods": methods}
bodies.update({"unit_analysis:" + subject: body for subject, body in unit_bodies.items()})
assert set(bodies) == {task["section_id"] for task in tasks}
submitted = set()
while len(submitted) < len(tasks):
    next_task = next((task for task in tasks if task["section_id"] not in submitted
                      and set(task["depends_on"]) <= submitted), None)
    assert next_task is not None, "chapter dependency cycle"
    context = call("draft", "context", next_task["id"], "--project", project_id)
    assert context["task"]["status"] in ("ready", "submitted"), next_task["section_id"]
    call("draft", "submit", request={"project_id": project_id, "run_id": run_id,
                                     "task_id": next_task["id"], "author_id": "codex_writer",
                                     "body": bodies[next_task["section_id"]],
                                     "replace": context["task"]["status"] == "submitted"})
    submitted.add(next_task["section_id"])
    print("written", next_task["section_id"], flush=True)
draft = call("draft", "build", request={"project_id": project_id, "run_id": run_id})
(WORK / "draft.json").write_text(json.dumps(draft, ensure_ascii=False, indent=2), encoding="utf-8")
print("draft", draft["markdown_path"], draft["sha256"], flush=True)
