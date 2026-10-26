"""Build a traceable 42-unit budget draft from the CLI acceptance run."""

import json
import subprocess
from decimal import Decimal
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / "projects" / "real_budget_acceptance"
REPORT = ROOT / ".venv" / "bin" / "report"
REQUEST = WORK / "draft_request.json"
SESSION = json.loads((WORK / "session.json").read_text(encoding="utf-8"))
PROJECT = SESSION["project_id"]
RUN = SESSION["run_id"]


def call(*arguments, request=None):
    command = [str(REPORT), *arguments, "--workspace", str(WORK / "projects")]
    if request is not None:
        REQUEST.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
        command += ["--request", str(REQUEST)]
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f"{' '.join(arguments)}: {result.stderr[:1000]}")
    return json.loads(result.stdout)["data"]


tasks = call("draft", "plan", request={"project_id": PROJECT, "run_id": RUN})
by_section = {task["section_id"]: task for task in tasks}
assert len(tasks) == 48


def submit(section_id, body):
    task = by_section[section_id]
    result = call("draft", "submit", request={
        "project_id": PROJECT, "run_id": RUN, "task_id": task["id"],
        "author_id": "codex-budget-draft", "body": body,
    })
    if result["status"] != "submitted":
        raise RuntimeError(section_id)


submit("scope", "本稿分析 2026 年 7 月预算经营材料。当前材料为 MOCK 模拟输入，不能解释为真实企业经营业绩。利润快报提供当月、上月、当年累计、上年同期累计、年度计划和累计序时计划；本轮单位差额仅按本年累计减累计序时计划计算。集团合并抵销规则尚未确认，单位数字不加总为集团合并结果。另有十份专题工作簿已归档，但本轮尚未完成逐项事实核对，相关经营原因和专项结论保留待核实。")

for section_id, task in by_section.items():
    if not section_id.startswith("units:"):
        continue
    context = call("draft", "context", task["id"], "--project", PROJECT)
    subject = task["subject_id"]
    facts = {item["source_locator"].split("cell:", 1)[1][0]: item for item in context["evidence"]}
    calculated = [item for item in context["calculations"] if item["status"] == "calculated"]
    if set(facts) != set("DEFGHI") or len(calculated) != 1:
        raise RuntimeError(f"incomplete unit context: {subject}")
    value = lambda column: "{{fact:" + facts[column]["id"] + "}}"
    citation = lambda column: "{{ev:" + facts[column]["id"] + "}}"
    difference = "{{calc:" + calculated[0]["id"] + "}}"
    sign = "亏损" if Decimal(facts["D"]["value"]) < 0 else "盈利"
    body = (
        f"{subject}本月利润为 {value('D')} 万元，表现为{sign}；上月为 {value('E')} 万元。"
        f"本年累计利润为 {value('F')} 万元，上年同期累计为 {value('G')} 万元。"
        f"本年累计较序时计划差额为 {difference} 万元。上述数字分别回到来源单元格核对，不能仅凭差额判断原因。\n\n"
        "| 口径 | 金额（万元） |\n| --- | ---: |\n"
        f"| 本月利润 | {value('D')} |\n| 上月利润 | {value('E')} |\n"
        f"| 本年累计利润 | {value('F')} |\n| 上年同期累计利润 | {value('G')} |\n"
        f"| 年度计划利润 | {value('H')} |\n| 累计序时计划利润 | {value('I')} |\n\n"
        f"利润数字来源：{citation('D')}、{citation('F')}、{citation('I')}。"
        "生产、成本、订单或资金等原因仍需结合专项资料和单位说明核验；在核验前不归因，也不把年度计划均摊成月度预算。"
    )
    submit(section_id, body)
print("unit sections", 42, flush=True)

submit("special", "十份专题工作簿已按原件版本归档，并完成表格及公式解析；本轮尚未将其项目、单位和期间逐项映射为已确认事实。七宝山、母公司专项、产融收益及加工产品等不能直接并入各单位利润表口径。相关专题数值、归属与增减利原因在后续核验前均列为待确认。")
submit("market", "本轮材料不足以形成市场价格与经营结果之间的可靠归因，也未声明敏感性测算所需的数量、价格和适用期间。市场关联和情景结果暂不计算；不得将情景假设写为已发生事实。")
group_task = by_section["group"]
group_context = call("draft", "context", group_task["id"], "--project", PROJECT)
group_facts = {item["source_locator"].split("cell:", 1)[1][0]: item for item in group_context["evidence"] if item["subject_id"] == "集团合并"}
assert set(group_facts) == set("DEFGHI")
group_fact = lambda column: "{{fact:" + group_facts[column]["id"] + "}}"
group_citation = "{{ev:" + group_facts["F"]["id"] + "}}"
submit("group", f"利润快报的集团合并行列示本月利润 {group_fact('D')} 万元、本年累计利润 {group_fact('F')} 万元、累计序时计划利润 {group_fact('I')} 万元。该行是来源表内独立记录，来源为 {group_citation}；本项目尚未取得合并抵销规则，不能把 42 户单位简单加总来验证或替代该行。共同关注事项集中在亏损或下滑单位的原因核验、专项来源归属、成本和产销资料的同口径对应。")
submit("actions", "请逐户核实利润变化对应的产销量、成本、合同、库存与资金资料，并由业务部门确认口径和原因。预算办需确认年度计划与累计序时计划的版本及局部调整范围；财务部门需确认集团合并抵销规则。专项工作簿核对完成前，采购、销售与生产协同措施只作为待评估方向，不能据此形成确定收益承诺。")
submit("sources", "本轮归档 11 份业务工作簿，利润快报共确认 258 条数值证据，覆盖 42 个主要单位及集团合并行的六个利润字段。关键值在正文以来源单元格定位，差额由 Python 注册算子按未舍入值计算。其他专题表尚未完成业务口径映射；材料齐备不等于分析结论已成立。集团合并规则仍缺，所有专题归因和管理建议需复核。")
draft = call("draft", "build", request={"project_id": PROJECT, "run_id": RUN})
print("draft", draft["markdown_path"], draft["sha256"], flush=True)
(WORK / "draft.json").write_text(json.dumps(draft, ensure_ascii=False, indent=2), encoding="utf-8")
