"""JSON CLI; all scenario interpretation stays in the core."""

import argparse
import json
import sys

from long_report.application import get_scenario, list_scenarios
from long_report.scenario import ScenarioError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="report", description="Long report scenario contract CLI")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("scenarios", help="validate and list installed scenarios")
    detail = commands.add_parser("scenario", help="validate and show one scenario")
    detail.add_argument("id")
    detail.add_argument("--version")
    args = parser.parse_args(argv)
    try:
        result = list_scenarios() if args.command == "scenarios" else get_scenario(args.id, args.version)
    except (ScenarioError, ValueError, OSError) as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps({"ok": True, "capability": "scenario_contract_only", "data": result}, ensure_ascii=False))
    return 0
