"""Write the three board drafts from confirmed CLI evidence; figures stay as source tokens."""

import json
import os
import subprocess
import sys
from collections import defaultdict
from decimal import Decimal
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / "projects" / os.environ.get("BUDGET_BOARD_WORK", "real_budget_board_acceptance")
REPORT = ROOT / ".venv/bin/report"
PROFILE = sys.argv[1]
SESSION = json.loads((WORK / f"{PROFILE}.json").read_text(encoding="utf-8"))
PROJECT, RUN = SESSION["project_id"], SESSION["run_id"]
REQUEST = WORK / f"{PROFILE}_draft_request.json"
AGGREGATE = {"mining": "矿山板块合计", "smelting": "冶炼板块合计", "processing": "加工板块"}[PROFILE]
TOPICS = {"mining": ("cost", "cost_inputs", "concentrate", "sulfur"),
          "smelting": ("tc", "acid", "raw_material", "effect"),
          "processing": ("processing", "effect")}[PROFILE]
FIELD = {"ore_cost": "吨矿成本", "ore_cost_prior": "同期吨矿成本", "labor_depr": "人工及折旧",
         "labor_depr_prior": "同期人工及折旧", "sales": "累计销量", "sales_prior": "同期销量",
         "price": "累计价格", "price_prior": "同期价格", "current_tc": "本期加工费",
         "planned_tc": "计划加工费", "prior_tc": "同期加工费", "benefit": "累计产品效益",
         "benefit_prior": "同期产品效益", "fee": "单位加工加价", "cost": "单位加工成本",
         "ytd": "累计效益", "prior": "同期效益", "operating": "生产经营效益",
         "operating_prior": "同期生产经营效益", "production": "累计产量",
         "source_yoy": "同比测算影响", "source_plan": "对计划测算影响",
         "volume_effect": "销量影响", "price_effect": "价格影响",
         "plan_volume": "对计划量差影响", "plan_price": "对计划价差影响"}
FIELDS = {"mining": {"ore_cost", "ore_cost_prior", "labor_depr", "labor_depr_prior", "production", "sales", "sales_prior", "price", "price_prior", "volume_effect", "price_effect"},
          "smelting": {"current_tc", "planned_tc", "prior_tc", "source_yoy", "source_plan", "sales", "sales_prior", "price", "price_prior", "volume_effect", "price_effect", "benefit", "benefit_prior", "operating", "operating_prior"},
          "processing": {"fee", "cost", "benefit", "benefit_prior", "operating", "operating_prior"}}[PROFILE]


def call(*arguments, request=None):
    command = [str(REPORT), *arguments, "--workspace", str(WORK / "projects")]
    if request is not None:
        REQUEST.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
        command += ["--request", str(REQUEST)]
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f"{arguments}: {result.stderr[:1000]}")
    return json.loads(result.stdout)["data"]


def fact(item):
    return "{{fact:" + item["id"] + "|2}}"


def cite(item):
    return "{{ev:" + item["id"] + "}}"


def calc(item):
    return "{{calc:" + item["id"] + "|2}}"


def direction(current, prior):
    a, b = Decimal(current["value"]), Decimal(prior["value"])
    if b < 0 <= a:
        return "由亏转盈"
    if a < 0 <= b:
        return "由盈转亏"
    if a < 0 and b < 0:
        return "亏损收窄" if a > b else "亏损扩大" if a < b else "持平"
    return "增加" if a > b else "减少" if a < b else "持平"


def profit_items(context, subject):
    rows = {item["source_locator"].rsplit("cell:", 1)[-1][:1]: item for item in context["evidence"]
            if item["subject_id"] == subject and item["metric_id"] == "profit_total"}
    if set(rows) != set("DEFGHI"):
        raise RuntimeError(f"missing profit columns for {subject}: {sorted(rows)}")
    return rows


def profit_text(context, subject):
    rows = profit_items(context, subject)
    calculated = {item["metric_id"]: item for item in context["calculations"] if item.get("subject_id") == subject and item["status"] == "calculated"}
    gap, month_change, ytd_change = (calculated.get(metric) for metric in ("budget_difference", "month_change", "ytd_change"))
    lead = (f"{subject}七月利润为 {fact(rows['D'])} 万元，上月为 {fact(rows['E'])} 万元，环比{direction(rows['D'], rows['E'])}。"
            f"一至七月累计为 {fact(rows['F'])} 万元，上年同期为 {fact(rows['G'])} 万元，同比{direction(rows['F'], rows['G'])}。"
            f"累计序时计划为 {fact(rows['I'])} 万元，")
    lead += (f"实际与计划差额为 {calc(gap)} 万元。" if gap else "集团合并抵销口径未签认，未给出自动差额。")
    if month_change and ytd_change:
        lead += f"本月与上月差额为 {calc(month_change)} 万元，累计与上年同期差额为 {calc(ytd_change)} 万元。"
    if Decimal(rows["H"]["value"]) <= 0 or Decimal(rows["I"]["value"]) <= 0:
        lead += "计划值为零或负时只列算术差额，不套用正目标完成率。"
    table = "| 利润比较项目 | 金额（万元） |\n| --- | ---: |\n" + "\n".join(
        f"| {label} | {fact(rows[column])} |" for column, label in zip("DEFGHI", ("本月", "上月", "本年累计", "上年同期累计", "年度计划", "累计序时计划")))
    return lead + "\n\n" + table + "\n\n来源定位：" + cite(rows["F"]) + "。"


def topic_rows(context, subjects=None, prefixes=None, limit=16):
    selected = [item for item in context["evidence"] if item["metric_id"] != "profit_total"
                and (subjects is None or item["subject_id"] in subjects)
                and (prefixes is None or item["metric_id"].split(".", 1)[0] in prefixes)
                and item["metric_id"].rsplit(".", 1)[-1] in FIELDS]
    selected.sort(key=lambda item: (item["metric_id"].split(".", 1)[0], item.get("source_subject", ""), item["metric_id"]))
    return selected[:limit]


def topic_table(rows):
    if not rows:
        return "本轮已采纳材料未提供该专题的可比数值，需补充同范围台账。"
    lines = ["| 主体及专项 | 指标 | 来源值 | 单位 |", "| --- | --- | ---: | --- |"]
    for item in rows:
        field = item["metric_id"].rsplit(".", 1)[-1]
        lines.append(f"| {item.get('source_subject', item['subject_id'])} | {FIELD.get(field, field)} | {fact(item)} | {item.get('unit') or '未声明'} |")
    return "\n".join(lines) + "\n\n取数示例：" + cite(rows[0]) + "。"


def unit_body(context, subject):
    heading = "####" if subject in {"贵冶", "贸易事业部", "铜业铜材", "集团铜材", "江铜龙昌", "江铜台意", "华东铜材", "华东电工", "江铜嘉磁", "江铜川禾"} else "###"
    rows = profit_items(context, subject)
    progress = "高于" if Decimal(rows["F"]["value"]) > Decimal(rows["I"]["value"]) else "低于" if Decimal(rows["F"]["value"]) < Decimal(rows["I"]["value"]) else "等于"
    parts = [profit_text(context, subject),
             f"{heading} 盈亏节奏与预算进度\n\n该单位累计利润{progress}表内序时计划；当月与上月、累计与同期分别属于不同时间窗口。"
             "利润快报未给出上年同月数，也未提供足以解释本月波动的损益桥，不能以累计同比替代单月同比。"]
    if Decimal(rows["D"]["value"]) < 0:
        parts.append("当月出现亏损，需逐项核对收入、成本、费用、结算调整及一次性项目；累计结果不能掩盖当月风险。")
    topic_filter = set() if PROFILE == "smelting" and subject == "母公司（冶炼）" else set(TOPICS)
    rows = topic_rows(context, {subject}, topic_filter, 16)
    if PROFILE == "smelting" and subject == "母公司（冶炼）":
        parts.append("主要单位效益表的“母公司”、TC及硫酸表的“股份母公司”与利润快报的母公司冶炼范围尚未核对，相关专项只在后续专题章独立讨论，不作为本户利润变动的直接原因。")
    if rows:
        parts.append(f"{heading} 经营指标与专项线索\n\n" + topic_table(rows))
        grouped = defaultdict(dict)
        for item in context["evidence"]:
            if item["subject_id"] != subject or "." not in item["metric_id"]:
                continue
            profile, row, field = item["metric_id"].split(".", 2)
            if profile in topic_filter:
                grouped[(profile, row, item.get("source_subject", subject))][field] = item
        titles = {"cost": "单位成本", "cost_inputs": "成本基础量", "concentrate": "铜精矿产销与量价", "sulfur": "硫精矿量价",
                  "tc": "加工费合同参数", "acid": "硫酸量价", "raw_material": "原料效益", "effect": "效益构成", "processing": "加工产品效益"}
        for (profile, _, source_subject), facts in sorted(grouped.items()):
            sentences = []
            pairs = {"cost": [("ore_cost", "ore_cost_prior", "吨矿成本")],
                     "cost_inputs": [("labor_depr", "labor_depr_prior", "人工及折旧")],
                     "concentrate": [("sales", "sales_prior", "累计销量"), ("price", "price_prior", "结算单价")],
                     "sulfur": [("sales", "sales_prior", "累计销量"), ("price", "price_prior", "不含税单价")],
                     "tc": [("current_tc", "prior_tc", "加工费"), ("current_tc", "planned_tc", "加工费对计划")],
                     "acid": [("sales", "sales_prior", "硫酸销量"), ("price", "price_prior", "不含税价格")],
                     "raw_material": [("benefit", "benefit_prior", "累计原料效益")],
                     "effect": [("ytd", "prior", "累计效益"), ("operating", "operating_prior", "生产经营效益")],
                     "processing": [("benefit", "benefit_prior", "累计产品效益")]}[profile]
            for current, prior, label in pairs:
                if current in facts and prior in facts:
                    a, b = facts[current], facts[prior]
                    sentences.append(f"{label}为 {fact(a)} {a.get('unit') or ''}，比较值为 {fact(b)} {b.get('unit') or ''}，方向为{direction(a, b)}。")
            if profile == "processing" and "fee" in facts and "cost" in facts and Decimal(facts["fee"]["value"]) < Decimal(facts["cost"]["value"]):
                sentences.append("表内单位加工加价低于单位加工成本，存在负加工毛差；不能由此单独认定新增订单均不经济。")
            if profile == "concentrate" and "production" in facts and "sales" in facts:
                sentences.append("产销量差额需要库存、调拨与结算台账核对，不能直接解释为期末库存。")
            if sentences:
                parts.append(f"{heading} {titles[profile]}：{source_subject}\n\n" + "".join(sentences) + "来源定位：" + cite(next(iter(facts.values()))) + "。")
        parts.append("以上专项与利润快报可能存在期间、主体或计量差异。财务和业务岗位须核对合同、结算、产销与成本归集后，再解释利润变动；来源表专项影响不重复计入单位利润。")
    else:
        parts.append("经营原因仍需月度损益桥、产销、订单及成本台账验证，不能从利润差额直接推定。")
    return "\n\n".join(parts)


def board_body(section_id, context, units):
    board = profit_text(context, AGGREGATE)
    if section_id == "scope":
        return (f"本报告仅分析{AGGREGATE}及配置列示的{len(units)}个单位分析行（含下级明细），统计期为二〇二六年一月至七月；七月与六月比较，本年累计与上年同期及表内累计序时计划比较。"
                "材料均标记为 MOCK，文件交付日期不替代经营期间。板块合计为工作簿模拟汇总，未取得真实内部抵销规则；所属明细与上级单位含有包含关系，不重复加总。"
                "市场文字材料晚于统计期间，不作为七月行情或利润成因证据。")
    if section_id == "summary":
        rows = profit_items(context, AGGREGATE)
        return ("本稿为模拟数据技术工作稿，核心结论来自已冻结的利润快报和专项表。" + board.split("\n\n", 1)[0]
                + f"板块累计与同期相比{direction(rows['F'], rows['G'])}，当月较上月{direction(rows['D'], rows['E'])}，两种时间窗口应分别评价。"
                "现有来源不能证明销售、成本或对冲的完整利润桥，也不能形成正式合并经营结论。建议先核对异常单位、专项归属和序时计划版本，再讨论措施。")
    if section_id == "group":
        return profit_text(context, "集团合并") + "\n\n集团合并行与矿山板块合计行各自列示。模拟合计未作真实内部抵销，不将所属单位和专项数重复加总。"
    if section_id == "products":
        grouped = defaultdict(list)
        for item in topic_rows(context, None, {"processing"}, 1000):
            grouped[int(item["metric_id"].split(".")[1][1:])].append(item)
        families = [("铜管", [5, 6]), ("江铜华北铜杆", [8, 9]), ("华东铜材铜杆", [10]),
                    ("铜业铜材铜杆", [11, 12, 13]), ("广州铜材铜杆", [14, 15, 16]),
                    ("集团铜材线材", [18, 19]), ("台意漆包线", [20]), ("华东电工线材", [21, 22, 23]),
                    ("广州新材料深加工线", [24]), ("标准铜箔", [26]), ("锂电铜箔", [27]),
                    ("青铜板带", [29]), ("紫铜板带", [30]), ("高铜板带", [31])]
        if set(grouped) != {row for _, group in families for row in group}:
            raise RuntimeError("processing product source rows differ from the declared families")
        parts = ["加工产品按销量、单位加价、单位成本和效益观察；产品专项不等同单位会计净利润，负毛差不能直接推断停产决策。"]
        for label, group in families:
            facts = [item for row in group for item in grouped[row]]
            parts.append(f"## {label}\n\n" + topic_table(facts))
        parts.append("产品归属、订单价格、良率及全成本与可避免成本须逐项核对；不能把产品效益重复加入板块利润。")
        return "\n\n".join(parts)
    if section_id in ("special", "tc", "acid", "quality"):
        prefixes = {"special": {"concentrate", "sulfur"}, "tc": {"tc"}, "acid": {"acid", "raw_material"},
                    "quality": {"effect", "processing"}}[section_id]
        rows = topic_rows(context, None, prefixes, 24)
        intro = {"special": "铜精矿和硫精矿的销量、价格及量价影响属于产品专项，七宝山保留独立主体。",
                 "tc": "加工费专项按来源表主体与合同参数列示，模拟影响不等同已实现利润；股份母公司与利润快报母公司冶炼的主体范围待确认。",
                 "acid": "硫酸量价与原料效益按自身产品口径呈现，须核对结算期间与重叠关系；股份母公司专项不直接归因于母公司冶炼利润。",
                 "quality": "生产经营、期现对冲、暂定价与产品效益须分别核对，专项构成不追加到利润。"}[section_id]
        return intro + "\n\n" + topic_table(rows) + "\n\n财务与业务岗位应提交同口径合同、结算和利润桥，缺口未补齐前只陈述表内方向。"
    if section_id == "common":
        losses = []
        for subject in units:
            rows = profit_items(context, subject)
            if Decimal(rows["F"]["value"]) < 0:
                losses.append(subject)
        return (board.split("\n\n", 1)[0] + "\n\n累计亏损单位为：" + ("、".join(losses) or "无")
                + "。该名单仅用于逐户复核；板块包含关系及专项影响不再次加总。共同待核事项是月度利润桥、订单及库存、合同计价窗口与成本归集。")
    if section_id == "market":
        return ("市场摘录的记载时点晚于二〇二六年七月，且部分报价缺原始出处；不用于解释本月经营结果。"
                "未来敏感性分析需先确认固定数量、产品规格、合同定价窗口、税制和币种，并核对专项范围，不能把情景金额写成已发生损失。")
    if section_id == "actions":
        return ("## 经营复核顺序\n\n财务先按单位核实当月与累计利润桥、序时计划版本和合并抵销；业务同步补合同、产销、库存、在途及订单。"
                "加工费、副产品、原料及产品加工效益先确认归属和是否已包含于利润，再讨论采购协同或经营措施。"
                "措施预期收益、责任人和时限尚无签认，维持待测算、待确认状态。")
    if section_id == "sources":
        index = {}
        for item in context["evidence"]:
            index.setdefault(item["source_id"], item)
        main = ("累计序时差额按本年累计实际减累计序时计划计算；环比差额按本月减上月计算，累计同比差额按本年累计减上年同期累计计算，底层值不预先舍入；年度计划不均摊成月度预算。"
                "负基数、跨盈亏或负计划先说明盈亏方向，不套用普通完成率。来源定位示例如下：\n\n"
                + "| 来源 | 可回查定位 |\n| --- | --- |\n"
                + "\n".join(f"| 第{number}份业务工作簿 | {cite(item)} |" for number, item in enumerate(index.values(), 1))
                + "\n\n资料标记为 MOCK；集团合并抵销、组织归属、市场同期材料和经营成因仍待业务签认。")
        appendix = ("# 附录\n\n六个矿山单位的利润、成本与产销表已在单位章节按原始单元格列示；七宝山只保留硫精矿独立口径，不并入六矿合计。"
                    "月度利润桥和期初期末库存未提供，单位图只比较累计实际与同期间序时计划。\n\n") if PROFILE == "mining" else ""
        return main + "\n\n" + appendix + "# 材料与口径追溯\n\n上述来源索引的引用可回到本轮归档原件。原件指纹、来源单元格、配置与图表哈希保存在版本快照；市场摘录不进入七月行情事实。"
    raise RuntimeError(f"unknown chapter: {section_id}")


project = call("project", "show", PROJECT)
units = project["effective_config"]["outline"]["unit_names"]
tasks = call("draft", "plan", request={"project_id": PROJECT, "run_id": RUN})
if "--charts" in sys.argv:
    for task in tasks:
        if PROFILE == "mining" and task["subject_id"] is None:
            continue
        if task["subject_id"] is None and task["section_id"] not in ("summary", "group"):
            continue
        context = call("draft", "context", task["id"], "--project", PROJECT)
        subject = task["subject_id"] or ("集团合并" if task["section_id"] == "group" else AGGREGATE)
        rows = profit_items(context, subject)
        chart = call("chart", "create", request={
            "project_id": PROJECT, "run_id": RUN, "title": f"{subject}累计利润与序时计划",
            "series": [{"label": "累计实际", "evidence_id": rows["F"]["id"]},
                       {"label": "累计序时计划", "evidence_id": rows["I"]["id"]}],
        })
        body = unit_body(context, subject) if task["subject_id"] else board_body(task["section_id"], context, units)
        call("draft", "submit", request={"project_id": PROJECT, "run_id": RUN, "task_id": task["id"],
                                         "author_id": f"{PROFILE}-board-writer", "replace": True,
                                         "body": body + f"\n\n{{{{chart:{chart['id']}}}}}"})
    tasks = call("draft", "plan", request={"project_id": PROJECT, "run_id": RUN})
if "--refresh" in sys.argv:
    for section_id in (("products", "sources") if PROFILE == "processing" else ("sources",)):
        task = next(item for item in tasks if item["section_id"] == section_id)
        context = call("draft", "context", task["id"], "--project", PROJECT)
        call("draft", "submit", request={"project_id": PROJECT, "run_id": RUN, "task_id": task["id"],
                                         "author_id": f"{PROFILE}-board-writer", "replace": True,
                                         "body": board_body(section_id, context, units)})
while any(task["status"] != "submitted" for task in tasks):
    ready = [task for task in tasks if task["status"] == "ready"]
    if not ready:
        raise RuntimeError("draft dependency deadlock")
    for task in ready:
        context = call("draft", "context", task["id"], "--project", PROJECT)
        body = unit_body(context, task["subject_id"]) if task["subject_id"] else board_body(task["section_id"], context, units)
        call("draft", "submit", request={"project_id": PROJECT, "run_id": RUN, "task_id": task["id"],
                                         "author_id": f"{PROFILE}-board-writer", "body": body})
    tasks = call("draft", "plan", request={"project_id": PROJECT, "run_id": RUN})
draft = call("draft", "build", request={"project_id": PROJECT, "run_id": RUN})
(WORK / f"{PROFILE}_draft.json").write_text(json.dumps(draft, ensure_ascii=False, indent=2), encoding="utf-8")
print("draft", PROFILE, draft["markdown_path"], draft["sha256"], flush=True)
