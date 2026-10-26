"""Check, publish, and package this mining report CLI run."""

import json
import os
import re
import shutil
import subprocess
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

from docx import Document


ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / "projects" / os.environ.get("MINING_WORK", "mining_board_2026_07_acceptance")
DEST = ROOT / "results" / "budget_operations" / "矿山板块_当前版本验收_20261023"
REPORT = ROOT / ".venv" / "bin" / "report"
REQUEST = WORK / "request.json"
session = json.loads((WORK / "session.json").read_text(encoding="utf-8"))
project_id, run_id = session["project_id"], session["run_id"]
draft = json.loads((WORK / "draft.json").read_text(encoding="utf-8"))
evidence = json.loads((WORK / "evidence.json").read_text(encoding="utf-8"))
calculations = json.loads((WORK / "calculations.json").read_text(encoding="utf-8"))
content = Path(draft["markdown_path"]).read_text(encoding="utf-8")
units = ["德兴铜矿（含新技术）", "永平铜矿", "武山铜矿", "城门山铜矿", "银山矿业", "银珠山矿业"]


def call(*args, request):
    REQUEST.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
    response = subprocess.run([str(REPORT), *args, "--workspace", str(WORK / "projects"),
                               "--request", str(REQUEST)], cwd=ROOT, capture_output=True, text=True)
    if response.returncode:
        raise RuntimeError(f"{' '.join(args)}: {response.stderr[:2000]}")
    return json.loads(response.stdout)["data"]


assert sha256(content.encode()).hexdigest() == draft["sha256"]
assert len(re.findall(r"(?m)^## (?:" + "|".join(map(re.escape, units)) + r")$", content)) == 6
assert len(re.findall(r"(?m)^\| 利润比较项目 ", content)) == 6
assert len(re.findall(r"(?m)^\| 经营指标 ", content)) == 6
assert len(re.findall(r"(?m)^\| ---", content)) == 16
assert len(re.findall(r"!\[[^]]+\]\(assets/chart_[a-f0-9]{24}\.png\)", content)) == 7
assert "{{" not in content and "MOCK" in content and "七宝山（专项行）" in content
for period, window, basis, version in [
    ("2026-07", "month", "actuals", None), ("2026-06", "month", "actuals", None),
    ("2026-07", "ytd", "actuals", None), ("2025-07", "ytd", "actuals", None),
    ("2026", "annual", "budget", "annual_plan"), ("2026-07", "ytd", "budget", "time_plan"),
]:
    def value(subject):
        found = [item for item in evidence if item["subject_id"] == subject and item["metric_id"] == "profit_total"
                 and (item["period"], item["window"], item["basis"], item["budget_version"]) == (period, window, basis, version)]
        assert len(found) == 1
        return Decimal(found[0]["value"])
    assert abs(value("矿山板块合计") - sum((value(subject) for subject in units), Decimal())) < Decimal("0.000001")
assert sum(item["status"] == "calculated" for item in calculations) == 209

review = call("review", "submit", request={"project_id": project_id, "run_id": run_id,
                                            "draft_sha256": draft["sha256"],
                                            "reviewer_id": "rule_based_qa", "verdict": "pass", "issues": []})
validation = call("validate", request={"project_id": project_id, "run_id": run_id})
assert validation["hard_checks_passed"] and validation["status"] == "pending_review", validation
assert validation["gaps"]["definition_missing"] == ["consolidation_rule"], validation
revision = call("publish", request={"project_id": project_id, "run_id": run_id})
assert revision["status"] == "pending_review", revision
document = Document(revision["docx_path"])
assert len(document.tables) == 16 and len(document.inline_shapes) == 7
paragraphs = "\n".join(paragraph.text for paragraph in document.paragraphs)
assert all(subject in paragraphs for subject in units)
assert "MOCK" in paragraphs and "679883.74" in paragraphs
revision_dir = Path(revision["docx_path"]).parents[1]
render_qa = json.loads((revision_dir / "qa" / "render_qa.json").read_text(encoding="utf-8"))
assert render_qa["headings_match"] and render_qa["tables_match"]
assert render_qa["embedded_chart_count"] == 7 and render_qa["charts_nonblank"]
DEST.mkdir(parents=True, exist_ok=True)
for source, name in [(Path(revision["markdown_path"]), "矿山板块月度经营分析报告.md"),
                     (Path(revision["docx_path"]), "矿山板块月度经营分析报告.docx"),
                     (revision_dir / "manifest.json", "manifest.json"),
                     (revision_dir / "qa" / "content_qa.json", "content_qa.json"),
                     (revision_dir / "qa" / "render_qa.json", "render_qa.json"),
                     (WORK / "mapping.json", "本轮来源映射.json"),
                     (WORK / "evidence.json", "本轮冻结事实.json"),
                     (WORK / "calculations.json", "本轮计算结果.json")]:
    assert source.is_file(), source
    shutil.copy2(source, DEST / name)
shutil.copytree(Path(revision["markdown_path"]).parent / "assets", DEST / "assets", dirs_exist_ok=True)
assert all((DEST / image).is_file() for image in re.findall(r"!\[[^]]+\]\((assets/[^)]+)\)", content))
note = f"""# 矿山板块当前版本全流程验收记录

- 场景：`budget_operations` v0.2.0；项目 `{project_id}`；运行 `{run_id}`；版本 `{revision['id']}`。
- 本轮需求：2026 年 1—7 月矿山板块及六矿月度经营分析。章节按本轮需求与四份当前原始工作簿规划。
- 来源：本轮行列核验后提交映射；4 份原表、287 条冻结事实、209 条可用计算结果。另有 42 条非适用的通用预算比较状态，未进入正文。
- 结构：8 个顶层章节、6 家单位独立分析、16 张表、7 张图；Markdown 与 DOCX 均已读回检查，图像文件哈希和嵌入数量通过渲染 QA。
- 数值核对：利润表六矿之和与板块合计在月度、累计、同期、年度计划、序时计划六种口径相符。
- CLI 校验：`{validation['status']}`，硬检查全通过；业务定义缺口：`consolidation_rule`。全部源文件均标注 MOCK。
- 审阅说明：`rule_based_qa` 是独立于章节编写命令的确定性校验脚本，检查结构、数字、来源与交付文件；本轮未取得独立业务专家的语义审阅或签认，因此交付仅为技术工作稿。
- PDF：当前首期 CLI 的正式交付为 Markdown、DOCX；本轮未生成 PDF。

源数据与运行状态保留在 `projects/{WORK.name}/`。此目录是可查看的交付副本，不应代替工作区中的原始材料和冻结证据。
"""
(DEST / "验收记录.md").write_text(note, encoding="utf-8")
print(json.dumps({"destination": str(DEST), "revision": revision["id"], "status": revision["status"],
                  "tables": len(document.tables), "charts": len(document.inline_shapes),
                  "review": review["reviewer_id"]}, ensure_ascii=False, indent=2))
