"""Use installed fonts for synthetic lifecycle QA, independently of exact 仿宋 checks."""

import shutil
import sys
from pathlib import Path

import yaml

from long_report.rendering import report_fonts

SOURCE = Path(__file__).resolve().parents[1] / "scenarios"


def synthetic_credit_cli(root):
    scenario_root = root / "scenarios"
    shutil.copytree(SOURCE / "financial_due_diligence", scenario_root / "financial_due_diligence")
    path = scenario_root / "financial_due_diligence/scenario.yaml"
    manifest = yaml.safe_load(path.read_text(encoding="utf-8"))
    manifest["presentation"] = {**manifest["presentation"], **report_fonts(), "allow_font_fallback": False}
    for group in ("styles", "table_styles"):
        for style in manifest["presentation"].get(group, {}).values():
            style["font"] = manifest["presentation"]["body_font"]
    path.write_text(yaml.safe_dump(manifest, allow_unicode=True), encoding="utf-8")
    driver = root / "report_cli.py"
    driver.write_text("from pathlib import Path\nimport long_report.scenario as scenario\n"
                      "scenario._root = lambda: Path(" + repr(str(scenario_root)) + ")\n"
                      "from long_report.adapters.cli import main\nraise SystemExit(main())\n", encoding="utf-8")
    return [sys.executable, str(driver)]


def registration_table(section):
    rule = section["required_tables"][0]
    return "| " + " | ".join(rule["columns"]) + " |\n| --- | --- |\n" + "\n".join(
        "| " + field + " | 未提供（待核实） |" for field in rule["required_fields"])


def equity_details(section):
    rule = next(item for item in section["required_tables"] if "total_row" in item)
    total = ["" if column in rule["total_row"]["blank_columns"] else
             rule["total_row"]["label"] if column == rule["total_row"]["label_column"] else "未提供（待核实）"
             for column in rule["columns"]]
    table = "| " + " | ".join(rule["columns"]) + " |\n| " + " | ".join("---" for _ in rule["columns"]) + " |\n"
    table += "| " + " | ".join("未提供（待核实）" for _ in rule["columns"]) + " |\n| " + " | ".join(total) + " |"
    children = [item["title"] for item in section["required_subsections"][rule["subheading"]]]
    return "### " + children[0] + "\n\n" + table + "\n\n### " + children[1] + "\n\n股东名单及持股、控制关系和简介资料待补，不推定股东人数或实际控制人。"
