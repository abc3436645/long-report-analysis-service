"""JSON CLI; all scenario interpretation stays in the core."""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from long_report.application import add_material, auto_submit_task, build_draft, calculate_run, cancel_run, create_chart, create_project, decide_evidence, execute_retrieval, freeze_evidence, get_draft_context, get_latest_revision, get_material, get_project, get_run, get_scenario, get_task_context, list_scenarios, list_tasks, plan_draft, publish_run, start_run, submit_draft, submit_review, submit_task, validate_run
from long_report.scenario import ScenarioError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="report", description="Long report scenario contract CLI")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("scenarios", help="validate and list installed scenarios")
    detail = commands.add_parser("scenario", help="validate and show one scenario")
    detail.add_argument("id")
    detail.add_argument("--version")
    project = commands.add_parser("project", help="create or show a report project")
    project_commands = project.add_subparsers(dest="project_command", required=True)
    create = project_commands.add_parser("create")
    create.add_argument("--workspace", type=Path, required=True)
    create.add_argument("--request", type=Path, required=True)
    show = project_commands.add_parser("show")
    show.add_argument("id")
    show.add_argument("--workspace", type=Path, required=True)
    material = commands.add_parser("material", help="register or inspect source material")
    material_commands = material.add_subparsers(dest="material_command", required=True)
    add = material_commands.add_parser("add")
    add.add_argument("--workspace", type=Path, required=True)
    add.add_argument("--request", type=Path, required=True)
    material_show = material_commands.add_parser("show")
    material_show.add_argument("id")
    material_show.add_argument("--project", required=True)
    material_show.add_argument("--workspace", type=Path, required=True)
    run = commands.add_parser("run", help="start an analysis run")
    run_commands = run.add_subparsers(dest="run_command", required=True)
    start = run_commands.add_parser("start")
    start.add_argument("--workspace", type=Path, required=True)
    start.add_argument("--request", type=Path, required=True)
    run_show = run_commands.add_parser("show")
    run_show.add_argument("id")
    run_show.add_argument("--workspace", type=Path, required=True)
    run_show.add_argument("--project", required=True)
    run_cancel = run_commands.add_parser("cancel")
    run_cancel.add_argument("--workspace", type=Path, required=True)
    run_cancel.add_argument("--request", type=Path, required=True)
    task = commands.add_parser("task", help="inspect analysis tasks")
    task_commands = task.add_subparsers(dest="task_command", required=True)
    task_list = task_commands.add_parser("list")
    task_list.add_argument("--workspace", type=Path, required=True)
    task_list.add_argument("--project", required=True)
    task_list.add_argument("--run", required=True)
    task_context = task_commands.add_parser("context")
    task_context.add_argument("id")
    task_context.add_argument("--workspace", type=Path, required=True)
    task_context.add_argument("--project", required=True)
    task_submit = task_commands.add_parser("submit")
    task_submit.add_argument("--workspace", type=Path, required=True)
    task_submit.add_argument("--request", type=Path, required=True)
    task_auto = task_commands.add_parser("auto-submit")
    task_auto.add_argument("--workspace", type=Path, required=True)
    task_auto.add_argument("--request", type=Path, required=True)
    retrieval = commands.add_parser("retrieval", help="execute an enabled professional-source task")
    retrieval_commands = retrieval.add_subparsers(dest="retrieval_command", required=True)
    retrieval_execute = retrieval_commands.add_parser("execute")
    retrieval_execute.add_argument("--workspace", type=Path, required=True)
    retrieval_execute.add_argument("--request", type=Path, required=True)
    evidence = commands.add_parser("evidence", help="decide and freeze evidence")
    evidence_commands = evidence.add_subparsers(dest="evidence_command", required=True)
    decide = evidence_commands.add_parser("decide")
    decide.add_argument("--workspace", type=Path, required=True)
    decide.add_argument("--request", type=Path, required=True)
    freeze = evidence_commands.add_parser("freeze")
    freeze.add_argument("--workspace", type=Path, required=True)
    freeze.add_argument("--request", type=Path, required=True)
    calculate = commands.add_parser("calculate", help="calculate registered metrics from frozen evidence")
    calculate.add_argument("--workspace", type=Path, required=True)
    calculate.add_argument("--request", type=Path, required=True)
    chart = commands.add_parser("chart", help="create a comparison chart from frozen evidence")
    chart_commands = chart.add_subparsers(dest="chart_command", required=True)
    chart_create = chart_commands.add_parser("create")
    chart_create.add_argument("--workspace", type=Path, required=True)
    chart_create.add_argument("--request", type=Path, required=True)
    draft = commands.add_parser("draft", help="plan and submit report sections")
    draft_commands = draft.add_subparsers(dest="draft_command", required=True)
    draft_plan = draft_commands.add_parser("plan")
    draft_plan.add_argument("--workspace", type=Path, required=True)
    draft_plan.add_argument("--request", type=Path, required=True)
    draft_context = draft_commands.add_parser("context")
    draft_context.add_argument("id")
    draft_context.add_argument("--workspace", type=Path, required=True)
    draft_context.add_argument("--project", required=True)
    draft_submit = draft_commands.add_parser("submit")
    draft_submit.add_argument("--workspace", type=Path, required=True)
    draft_submit.add_argument("--request", type=Path, required=True)
    draft_build = draft_commands.add_parser("build")
    draft_build.add_argument("--workspace", type=Path, required=True)
    draft_build.add_argument("--request", type=Path, required=True)
    review = commands.add_parser("review", help="submit independent semantic review")
    review_commands = review.add_subparsers(dest="review_command", required=True)
    review_submit = review_commands.add_parser("submit")
    review_submit.add_argument("--workspace", type=Path, required=True)
    review_submit.add_argument("--request", type=Path, required=True)
    validate = commands.add_parser("validate", help="check candidate report gates")
    validate.add_argument("--workspace", type=Path, required=True)
    validate.add_argument("--request", type=Path, required=True)
    publish = commands.add_parser("publish", help="publish a reviewed complete revision")
    publish.add_argument("--workspace", type=Path, required=True)
    publish.add_argument("--request", type=Path, required=True)
    revision = commands.add_parser("revision", help="inspect delivered report revisions")
    revision_commands = revision.add_subparsers(dest="revision_command", required=True)
    latest = revision_commands.add_parser("latest")
    latest.add_argument("--workspace", type=Path, required=True)
    latest.add_argument("--project", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "scenarios":
            result = list_scenarios()
        elif args.command == "scenario":
            result = get_scenario(args.id, args.version)
        elif args.command == "project" and args.project_command == "create":
            result = create_project(args.workspace, json.loads(args.request.read_text(encoding="utf-8")))
        elif args.command == "project":
            result = get_project(args.workspace, args.id)
        elif args.command == "material" and args.material_command == "add":
            result = add_material(args.workspace, json.loads(args.request.read_text(encoding="utf-8")))
        elif args.command == "material":
            result = get_material(args.workspace, args.project, args.id)
        elif args.command == "run" and args.run_command == "start":
            result = start_run(args.workspace, json.loads(args.request.read_text(encoding="utf-8")))
        elif args.command == "run" and args.run_command == "show":
            result = get_run(args.workspace, args.project, args.id)
        elif args.command == "run":
            result = cancel_run(args.workspace, json.loads(args.request.read_text(encoding="utf-8")))
        elif args.command == "task" and args.task_command == "list":
            result = list_tasks(args.workspace, args.project, args.run)
        elif args.command == "task" and args.task_command == "context":
            result = get_task_context(args.workspace, args.project, args.id)
        elif args.command == "task" and args.task_command == "auto-submit":
            result = auto_submit_task(args.workspace, json.loads(args.request.read_text(encoding="utf-8")))
        elif args.command == "task":
            result = submit_task(args.workspace, json.loads(args.request.read_text(encoding="utf-8")))
        elif args.command == "retrieval":
            result = execute_retrieval(args.workspace, json.loads(args.request.read_text(encoding="utf-8")))
        elif args.command == "evidence" and args.evidence_command == "decide":
            result = decide_evidence(args.workspace, json.loads(args.request.read_text(encoding="utf-8")))
        elif args.command == "evidence":
            result = freeze_evidence(args.workspace, json.loads(args.request.read_text(encoding="utf-8")))
        elif args.command == "calculate":
            result = calculate_run(args.workspace, json.loads(args.request.read_text(encoding="utf-8")))
        elif args.command == "chart":
            result = create_chart(args.workspace, json.loads(args.request.read_text(encoding="utf-8")))
        elif args.command == "draft" and args.draft_command == "plan":
            result = plan_draft(args.workspace, json.loads(args.request.read_text(encoding="utf-8")))
        elif args.command == "draft" and args.draft_command == "context":
            result = get_draft_context(args.workspace, args.project, args.id)
        elif args.command == "draft" and args.draft_command == "submit":
            result = submit_draft(args.workspace, json.loads(args.request.read_text(encoding="utf-8")))
        elif args.command == "draft":
            result = build_draft(args.workspace, json.loads(args.request.read_text(encoding="utf-8")))
        elif args.command == "review":
            result = submit_review(args.workspace, json.loads(args.request.read_text(encoding="utf-8")))
        elif args.command == "validate":
            result = validate_run(args.workspace, json.loads(args.request.read_text(encoding="utf-8")))
        elif args.command == "publish":
            result = publish_run(args.workspace, json.loads(args.request.read_text(encoding="utf-8")))
        else:
            result = get_latest_revision(args.workspace, args.project)
    except (ScenarioError, ValueError, KeyError, TypeError, OSError, sqlite3.Error) as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1
    capability = "scenario_contract_only" if args.command in ("scenario", "scenarios") else "project_state" if args.command == "project" else "material_state" if args.command == "material" else "run_state" if args.command in ("run", "task") else "retrieval_state" if args.command == "retrieval" else "evidence_state" if args.command == "evidence" else "calculation_state" if args.command == "calculate" else "chart_state" if args.command == "chart" else "draft_state" if args.command == "draft" else "review_state" if args.command == "review" else "validation_state" if args.command == "validate" else "revision_state"
    print(json.dumps({"ok": True, "capability": capability, "data": result}, ensure_ascii=False))
    return 0
