"""Author the selected MOCK budget report through the public report CLI."""

import json
import os
import subprocess
from collections import defaultdict
from decimal import Decimal
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / "projects" / os.environ.get("BUDGET_WORK", "real_budget_acceptance_v5")
REPORT = ROOT / ".venv" / "bin" / "report"
SESSION = json.loads((WORK / "session.json").read_text(encoding="utf-8"))
PROJECT, RUN = SESSION["project_id"], SESSION["run_id"]
REQUEST = WORK / "draft_request.json"


def call(*arguments, request=None):
    command = [str(REPORT), *arguments, "--workspace", str(WORK / "projects")]
    if request is not None:
        REQUEST.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
        command += ["--request", str(REQUEST)]
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f"{' '.join(arguments)}: {result.stderr[:1000]}")
    return json.loads(result.stdout)["data"]


def ref(item, places=2):
    return "{{fact:" + item["id"] + "|" + str(places) + "}}"


def calc(item, places=2):
    return "{{calc:" + item["id"] + "|" + str(places) + "}}"


def cite(item):
    return "{{ev:" + item["id"] + "}}"


def sign(value):
    return "高于" if Decimal(value) > 0 else "低于" if Decimal(value) < 0 else "等于"


TITLES = {
    "effect": "主要单位效益构成", "tc": "铜精矿加工费", "cost": "矿山单位成本",
    "cost_inputs": "矿山成本基础量", "concentrate": "铜精矿产销与量价影响",
    "acid": "硫酸量价专项", "sulfur": "硫精矿量价专项",
    "processing": "加工产品效益", "raw_material": "原料效益",
    "equity": "持股估值收益", "price_plan": "年度产品价格计划",
}
FIELDS = {
    "month": "本月利润或价格", "previous": "上月利润或价格", "ytd": "本年累计",
    "prior": "上年同期累计", "annual": "年度计划", "time_plan": "累计序时计划",
    "sales": "本年累计销量", "sales_prior": "上年同期销量", "sales_plan": "计划销量",
    "price": "本年累计单价", "price_prior": "上年同期单价", "price_plan": "计划单价",
    "ore_cost": "吨矿成本", "ore_cost_prior": "同期吨矿成本",
    "metal_cost": "金属成本", "metal_cost_prior": "同期金属成本",
    "fee": "单位加工加价", "fee_prior": "同期单位加工加价",
    "cost": "单位加工成本", "cost_prior": "同期单位加工成本",
    "benefit": "本年累计效益", "benefit_prior": "同期效益",
    "current_tc": "本年累计加工费", "planned_tc": "计划加工费", "prior_tc": "同期加工费",
    "source_yoy": "来源表同比影响", "source_plan": "来源表对计划影响",
    "volume_effect": "来源表销量影响", "price_effect": "来源表价格影响",
    "variable": "剔除人工折旧后的吨矿成本", "variable_prior": "同期剔除人工折旧后的吨矿成本",
    "variable_metal": "剔除人工折旧后的金属成本", "variable_metal_prior": "同期剔除人工折旧后的金属成本",
    "processed": "选矿处理量", "processed_prior": "同期选矿处理量",
    "labor_depr": "人工及折旧", "labor_depr_prior": "同期人工及折旧",
    "metal": "金属量或折合量", "metal_prior": "同期金属折合量",
    "physical": "进口矿实物量", "grade": "品位", "recovery": "回收率",
    "production": "本年累计产量", "gross": "含税计划价格", "net": "不含税计划价格",
    "operating": "生产经营效益", "hedge": "期现对冲效益", "provisional": "暂定价影响",
    "operating_prior": "同期生产经营效益", "hedge_prior": "同期期现对冲效益",
    "provisional_prior": "同期暂定价影响", "plan_volume": "对计划量差影响",
    "plan_price": "对计划价差影响", "shares": "持股数", "initial": "年初股价",
    "ytd_gain": "本年公允价值收益", "month_gain": "本月公允价值收益",
    "mom_gain": "收益环比增减",
}
COMMENTS = {
    "effect": "生产经营、期现对冲和暂定价是表内构成；来源范围与利润快报须分别核对，不把构成项目再加到利润总额。",
    "tc": "加工费影响取自来源表的累计模拟拆分。需核对实物干吨、合同费率、汇率和结算期间；它不等同已实现的会计利润。",
    "cost": "单位成本的分母和费用归集须由生产、成本岗位核对；成本上升或下降本身不能确定矿源、效率或费用的具体成因。",
    "cost_inputs": "处理量、金属折合量与人工折旧是成本复核线索；金属折合量与处理量之比不能直接解释为地质品位。",
    "concentrate": "量差、价差为来源表的累计拆分；产量与销量之差仅是衔接线索，需要库存、调拨与结算台账核验。不同金属的数量单位不能相加。",
    "acid": "硫酸销量与不含税价格保留独立产品口径，量价影响不得重复加入利润；销售、生产和财务需核对发运、合同与结算。",
    "sulfur": "硫精矿销量与不含税价格保留独立产品口径，量价影响不得重复加入利润；销售、生产和财务需核对发运、合同与结算。",
    "processing": "产品加工加价、成本与效益仅用于产品自身比较，不能替代单位净利润；订单可避免成本、良率和履约条件尚待核实。",
    "raw_material": "原料效益与副产品专项可能重叠；需核对来源范围、合同结算系数及入账期间，不重复加总。",
    "equity": "表内持股量与股价均为 MOCK 测试输入；公允价值变动不能视作已实现现金收益或直接并入单位利润。",
    "price_plan": "该表是年度产品价格计划，不是同期间市场实时报价；具体税制、折算和适用品种需按预算版本确认。",
}
WINDOW = {"month": "当月", "ytd": "累计", "annual": "年度"}
BASIS = {"actuals": "实际", "budget": "预算"}


def profiles(items):
    groups = defaultdict(list)
    for item in items:
        if item["metric_id"] == "profit_total":
            continue
        profile, row, field = item["metric_id"].split(".", 2)
        groups[(profile, row, item.get("source_subject", item["subject_id"]))].append((field, item))
    return sorted(groups.items(), key=lambda pair: (list(TITLES).index(pair[0][0]), int(pair[0][1][1:])))


def profile_block(key, fields, heading_level=3):
    profile, _, source_subject = key
    ordered = dict(fields)
    body = [f"{'#' * heading_level} {TITLES[profile]}：{source_subject}"]
    if profile == "cost" and {"ore_cost", "ore_cost_prior"} <= ordered.keys():
        body.append("本年累计吨矿成本" + sign(Decimal(ordered["ore_cost"]["value"]) - Decimal(ordered["ore_cost_prior"]["value"])) + "上年同期；需结合基础量和费用归集核对。")
    if profile == "effect" and {"ytd", "prior", "operating", "operating_prior"} <= ordered.keys():
        total = sign(Decimal(ordered["ytd"]["value"]) - Decimal(ordered["prior"]["value"]))
        operating = sign(Decimal(ordered["operating"]["value"]) - Decimal(ordered["operating_prior"]["value"]))
        body.append(f"本年累计效益{total}上年同期，其中生产经营效益{operating}同期；表内构成可用于桥接差额，不能单独证明增减的经营原因。")
    if profile == "tc" and {"current_tc", "planned_tc", "prior_tc"} <= ordered.keys():
        plan = sign(Decimal(ordered["current_tc"]["value"]) - Decimal(ordered["planned_tc"]["value"]))
        prior = sign(Decimal(ordered["current_tc"]["value"]) - Decimal(ordered["prior_tc"]["value"]))
        body.append(f"本年累计加工费率{plan}计划、{prior}上年同期；应在实物量及结算汇率一致的条件下解释来源表的影响金额。")
    if profile == "concentrate" and {"production", "sales"} <= ordered.keys():
        relation = sign(Decimal(ordered["production"]["value"]) - Decimal(ordered["sales"]["value"]))
        body.append(f"来源表累计产量{relation}累计销量，差向仅提示产销衔接待核验，不能直接推断期末库存或缺货。")
    if profile == "processing" and {"fee", "cost"} <= ordered.keys() and Decimal(ordered["fee"]["value"]) < Decimal(ordered["cost"]["value"]):
        body.append("本年累计单位加工加价低于单位加工成本，表内显示负加工毛差；这是全成本口径的产品线索，不能据此认定每笔新增订单均不经济。")
    if profile == "processing" and {"benefit", "benefit_prior"} <= ordered.keys():
        direction = sign(Decimal(ordered["benefit"]["value"]) - Decimal(ordered["benefit_prior"]["value"]))
        body.append(f"本年累计产品加工费效益{direction}上年同期；须结合销量、加价及成本逐项复核，不能把产品效益变化直接解释为单位利润变化。")
    if profile == "raw_material" and {"benefit", "benefit_prior"} <= ordered.keys():
        direction = sign(Decimal(ordered["benefit"]["value"]) - Decimal(ordered["benefit_prior"]["value"]))
        body.append(f"本年累计原料效益{direction}上年同期，尚需按产品和合同结算核实构成。")
    if profile == "equity" and "month_gain" in ordered:
        body.append("本月持股估值收益为" + ("正值" if Decimal(ordered["month_gain"]["value"]) > 0 else "负值" if Decimal(ordered["month_gain"]["value"]) < 0 else "零") + "；该方向仅属于来源表模拟持仓的估值测算。")
    if profile in ("acid", "sulfur") and {"sales", "sales_prior", "price", "price_prior"} <= ordered.keys():
        sales = sign(Decimal(ordered["sales"]["value"]) - Decimal(ordered["sales_prior"]["value"]))
        price = sign(Decimal(ordered["price"]["value"]) - Decimal(ordered["price_prior"]["value"]))
        body.append(f"本年累计销量{sales}同期，不含税价格{price}同期；方向仅反映本来源的累计比较。")
    body.append(COMMENTS[profile])
    body.append("| 来源表指标 | 数值 | 单位 | 期间与身份 |\n| --- | ---: | --- | --- |\n" + "\n".join(
        f"| {FIELDS.get(field, field)} | {ref(item, 4 if field in ('grade', 'recovery') else 2)} | {item.get('unit') or '未声明'} | {item['period']}／{WINDOW.get(item['window'], item['window'])}／{BASIS.get(item['basis'], item['basis'])} |"
        for field, item in fields
    ))
    body.append("来源定位：" + "、".join(cite(item) for _, item in (fields[0], fields[-1])) + "。")
    return "\n\n".join(body)


tasks = call("draft", "plan", request={"project_id": PROJECT, "run_id": RUN})
by_section = {task["section_id"]: task for task in tasks}
assert len(tasks) == 6 + 52
revising = all(task["status"] == "submitted" for task in tasks)
project = call("project", "show", PROJECT)
units = project["subject_scope"]["units"]
special_subjects = set(project["subject_scope"]["special_subjects"])
nested_subjects = {"贵冶", "贸易事业部", "铜业铜材", "集团铜材", "江铜龙昌", "江铜台意", "华东铜材", "华东电工", "江铜嘉磁", "江铜川禾"}


def context(section_id):
    return call("draft", "context", by_section[section_id]["id"], "--project", PROJECT)


def submit(section_id, body):
    task = by_section[section_id]
    result = call("draft", "submit", request={
        "project_id": PROJECT, "run_id": RUN, "task_id": task["id"],
        "author_id": "codex-budget-writer", "body": body, "replace": revising,
    })
    assert result["status"] == "submitted", section_id


submit("scope", "本报告分析 2026 年 7 月预算经营资料，同时区分当月与本年累计、上年同期累计、年度计划及累计序时计划。11 份业务工作簿标注 MOCK，仅供技术和业务口径验证，不构成企业正式业绩。另有一份未经外部出处核验的市场 Word 已归档；其摘录记载于 2026 年 10 月中旬，晚于本报告期，不作为 7 月行情或经营原因的证据。集团合并抵销规则、组织别名及部分专项归属未获业务签认；集团行独立列示，不将单位和专项数字简单相加。本轮计划差额只用本年累计与材料的累计序时计划比较，年度目标不均摊为月度预算。")

unit_details = {}
for name in units:
    section_id = "units:" + name
    detail = context(section_id)
    profit = {item["source_locator"].split("cell:", 1)[1][0]: item for item in detail["evidence"] if item["metric_id"] == "profit_total"}
    differences = {item["metric_id"]: item for item in detail["calculations"] if item["status"] == "calculated"}
    assert set(profit) == set("DEFGHI") and set(differences) == {"budget_difference", "month_change", "ytd_change"}, name
    d, e, f, g, h, i = (profit[column] for column in "DEFGHI")
    current, previous = Decimal(d["value"]), Decimal(e["value"])
    ytd, prior, annual, plan = (Decimal(item["value"]) for item in (f, g, h, i))
    change = "由盈转亏" if previous >= 0 > current else "由亏转盈" if previous < 0 <= current else "环比改善" if current > previous else "环比回落" if current < previous else "环比持平"
    position = "高于" if ytd > plan else "低于" if ytd < plan else "等于"
    parts = [
        f"{name}本月利润为 {ref(d)} 万元，上月为 {ref(e)} 万元，表现为{change}，本月与上月差额为 {calc(differences['month_change'])} 万元。本年累计利润为 {ref(f)} 万元，{sign(ytd-prior)}上年同期 {ref(g)} 万元，累计同比差额为 {calc(differences['ytd_change'])} 万元；累计序时计划为 {ref(i)} 万元，实际{position}该计划，差额为 {calc(differences['budget_difference'])} 万元。年度计划 {ref(h)} 万元只作全年目标，不拆作七月预算。",
        "| 利润口径 | 金额（万元） |\n| --- | ---: |\n" + "\n".join(f"| {label} | {ref(profit[column])} |" for column, label in zip("DEFGHI", ("本月", "上月", "本年累计", "上年同期累计", "年度计划", "累计序时计划"))),
        f"利润来源为 {cite(d)}、{cite(f)}、{cite(i)}。当月变化与累计差额是结果，不等于已经证实的销售、成本或资金成因。",
    ]
    if annual <= 0:
        parts.append("年度计划为零或负值，不计算通常意义上的正目标完成率。")
    thematic = profiles(detail["evidence"])
    if thematic:
        parts.append("本户还有以下专项来源线索。专项本身与利润行可能范围不同，先作自身比较，再由责任岗位核对入账和组织映射。")
        parts.extend(profile_block(key, fields, 4 if name in nested_subjects else 3) for key, fields in thematic)
    else:
        parts.append("本户本轮未取得可归属的产销、成本或效益专项证据。财务岗位应补本月与上月损益桥，经营岗位补订单、产销、库存及结算，方可定位变化原因；缺口不能用其他单位数据代填。")
    parts.append("复核建议：财务岗位核实利润、预算版本与确认期间；业务岗位提供产销量、合同、库存、资金及费用明细。取得同范围凭证前，不将表内差额写成确定成因，也不据此承诺采购、停产或收益。")
    submit(section_id, "\n\n".join(parts))
    unit_details[name] = (d, e, f, i)
print("units", len(unit_details), flush=True)

special_context = context("special")
special_groups = [(key, fields) for key, fields in profiles(special_context["evidence"]) if fields[0][1]["subject_id"] in special_subjects]
assert len({item["subject_id"] for _, fields in special_groups for _, item in fields}) == len(special_subjects)
special_parts = ["本章保留无法直接归入主单位利润行的来源主体和产品口径。产品销量、加工效益、持股估值与利润总额并非同一指标；同名或相似名称未经组织代码核对也不自动归并。下列表格只重现已确认的来源值，归属、实现及重叠关系需业务和财务签认。"]
special_parts.extend(profile_block(key, fields) for key, fields in special_groups)
special_parts.append("原料效益、硫酸量价、加工产品、持股估值与利润快报之间可能存在包含或计量差异，均不追加到集团合并利润。各专项的模拟参数、真实合同与入账凭证仍需逐项核验。")
submit("special", "\n\n".join(special_parts))

group_context = context("group")
group_profit = {item["source_locator"].split("cell:", 1)[1][0]: item for item in group_context["evidence"] if item["metric_id"] == "profit_total" and item["subject_id"] == project["subject_scope"]["organization"]}
assert set(group_profit) == set("DEFGHI")
turn_loss = [(name, data) for name, data in unit_details.items() if name not in nested_subjects and Decimal(data[1]["value"]) >= 0 > Decimal(data[0]["value"])]
continuing_loss = [(name, data) for name, data in unit_details.items() if name not in nested_subjects and Decimal(data[1]["value"]) < 0 and Decimal(data[0]["value"]) < Decimal(data[1]["value"])]
g = group_profit
group_parts = [
    f"来源表的集团合并行列示本月利润 {ref(g['D'])} 万元、上月 {ref(g['E'])} 万元，本年累计 {ref(g['F'])} 万元、上年同期累计 {ref(g['G'])} 万元，累计序时计划 {ref(g['I'])} 万元。累计实际{sign(Decimal(g['F']['value'])-Decimal(g['I']['value']))}序时计划；本月{sign(Decimal(g['D']['value'])-Decimal(g['E']['value']))}上月。此为来源表独立记录 {cite(g['F'])}，项目缺合并抵销规则，不以单位求和验证或替代。",
    "| 集团利润口径 | 金额（万元） |\n| --- | ---: |\n" + "\n".join(f"| {label} | {ref(g[column])} |" for column, label in zip("DEFGHI", ("本月", "上月", "本年累计", "上年同期累计", "年度计划", "累计序时计划"))),
    "集团效益表将累计利润拆为生产经营、期现对冲及暂定价项目，表内加总在显示精度内与该表累计利润一致；该算术关系尚不能证明现金实现或可持续性。集团效益表与利润快报的范围、内部抵销仍待财务确认。",
]
group_effects = [(key, fields) for key, fields in profiles(group_context["evidence"]) if key[0] == "effect" and fields[0][1]["subject_id"] == project["subject_scope"]["organization"]]
assert len(group_effects) == 1
group_parts.extend(profile_block(key, fields) for key, fields in group_effects)
group_parts.extend([
    "### 当月转亏和持续亏损的核实",
    "按各单位自身本月与上月利润识别的转亏对象为：" + ("、".join(name for name, _ in turn_loss) or "无") + "；持续亏损且当月较上月扩大的对象为：" + ("、".join(name for name, _ in continuing_loss) or "无") + "。片区与下属单位可能包含，以下行仅供定位，不合计风险金额。",
])
selected = turn_loss[:8] + continuing_loss[:8]
if selected:
    group_parts.append("| 代表单位 | 上月利润（万元） | 本月利润（万元） |\n| --- | ---: | ---: |\n" + "\n".join(f"| {name} | {ref(data[1])} | {ref(data[0])} |" for name, data in selected))
group_parts.extend([
    "### 矿山成本及冶炼合同的共同核实",
    "矿山专项可用于比较各自吨矿成本、处理量和人工折旧，冶炼加工费专项可用于核实合同条件。不同矿山分母及费用构成不同，不能把共同方向当作共同成因；加工费模拟影响与副产品效益可能已进入利润，不能二次加总。",
    "### 加工产品毛差与订单条件",
    "加工产品表中出现单位加价低于加工成本的产品，应逐项核对订单价格、良率及全成本与可避免成本。产品负毛差是专项线索，不等于所在单位净利润，更不能直接决定停产。",
    "### 库存与采购需求的共同缺口",
    "现有材料缺期初期末可用库存、库龄、在途和已订未到、规格与交期，无法计算净采购需求或认定积压。产量和销量是期间流量，不代替期末存量；仓储、采购、销售和资金岗位需联表核对后才能评估集中协同。",
])
submit("group", "\n\n".join(group_parts))

submit("market", "### 市场材料的适用范围\n\n市场 Word 写明数据截至 2026 年 10 月中旬，且部分引用仅为编号、没有原始链接，内部还存在不同报价区间。本报告期为 2026 年 7 月，故不把该摘录中的价格当作当月市场事实，也不从较晚价格倒推利润、加工费或副产品变化原因。年度价格计划只作预算基准，不替代可核验同期报价。\n\n### 固定数量下的敏感性\n\n已归档的加工费、副产品、精矿销量等累计来源可以定义未来单因素情景的数量边界，但本项目尚未确认统一情景幅度、合同定价窗口及计算配置。当前不生成数值预测；预算、采购与销售岗位需先确认固定数量、税制、币种、合同条款及不重复计算的范围。情景假设即使补齐，也不能写成已发生损失或经营承诺。")

submit("actions", "### 需逐户落实的经营复核\n\n优先由财务岗位解释当月转亏、持续亏损扩大和累计低于序时计划单位的损益桥，逐户核对收入、成本、费用、结算调整与一次性项目；经营岗位补合同、产销、交付与回款。片区和所属明细保留包含关系，不重复汇总。\n\n### 可评估的集中协同方向\n\n加工费与副产品合同、矿山耗材和加工原料可作为联合核实议题。采购须提交规格、交付地、有效需求、在途和已订未到；仓储确认可用库存，财务核对付款和现金约束。证据齐备后再比较谈判与调拨方案，不预设采购规模或节约金额。\n\n### 需要人工确认的口径\n\n预算办确认完整组织名册、别名及七宝山等独立专项归属、年度与累计序时计划版本；财务确认集团合并抵销、利润快报与效益拆分、原料与副产品之间的包含关系；业务岗位确认产品归属、合同费率、税制和结算期间。\n\n### 需要补充的资料\n\n逐户补月度损益桥、订单、生产运行、库存、在途、采购需求和回款；市场分析另补 7 月同期间、同规格、可回溯原始出处。缺少这些证据时已核对的表内方向可保留，原因和可执行措施保持待复核。")

source_context = context("sources")
source_parts = [
    f"本轮归档 11 份业务工作簿及一份市场 Word，确认 {6 * (len(units) + 1) + 702} 条带来源定位的证据；单位利润表的 {len(units)} 个累计序时差额及本月环比、累计同比差额由注册算子按未舍入数值计算。工作簿公式先经独立重算核验，来源字段未通过核验时不会被接受；显示金额通常保留两位小数，计算使用来源未舍入值。",
    "利润字段 D、E 分别是本月和上月，F、G 为本年与上年同期累计，H 为年度计划，I 为累计序时计划。序时差额定义为 F−I；年度目标不均摊，不在零或负计划上套用正目标完成率。集团合并行独立列示，专项影响与产品效益不得再次计入利润。",
    "已保留的定义缺口为集团合并抵销规则；市场同期可靠来源、库存、订单、采购与资金约束仍需补充。报告仅为 MOCK 技术工作稿，业务成因、专项范围和措施尚待责任岗位签认。",
]
sources_by_id = {item["source_id"]: item for item in source_context["evidence"]}
assert len(sources_by_id) == 11
source_parts.append("| 证据来源 | 定位示例 |\n| --- | --- |\n" + "\n".join(f"| {index + 1} 号业务工作簿 | {cite(item)} |" for index, item in enumerate(sources_by_id.values())))
source_parts.append("第十二份市场 Word 仅用于识别材料时点及适用性；未把其报价接受为 7 月事实。")
submit("sources", "\n\n".join(source_parts))

draft = call("draft", "build", request={"project_id": PROJECT, "run_id": RUN})
(WORK / "draft.json").write_text(json.dumps(draft, ensure_ascii=False, indent=2), encoding="utf-8")
print("draft", draft["markdown_path"], draft["sha256"], flush=True)
print("special_subjects", len(special_subjects), "special_profiles", len(special_groups), flush=True)
