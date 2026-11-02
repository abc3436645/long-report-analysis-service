"""The current public application operations."""

import csv
import calendar
import json
import re
import shutil
import sqlite3
from datetime import datetime, timedelta, timezone
from io import BytesIO, StringIO
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
from hashlib import sha256
from pathlib import Path
from uuid import uuid4
from zipfile import BadZipFile, ZipFile
from zoneinfo import ZoneInfo

from long_report.scenario import load_scenario, scenario_ids, scenario_template, validate_report_outline, validate_section_headings, validate_source_mapping, markdown_table_rows
from long_report.amounts import UNITS, display_amount, convert_chart_point
from long_report.financials import calculate_financials, material_coverage, validate_financial_body, review_requirements, validate_review_coverage
from long_report.operators import OPERATORS
from long_report.rendering import render_paginated_docx, verify_docx, verify_pdf_charts
from long_report.formula_verification import recalculate
from long_report.compensation import calculate_groups, private_terms
from long_report.retrieval import fetch
from long_report.charts import CHART_RENDERER_VERSION, draw_comparison


SUBJECT_MODELS = {
    "organization_and_units": {"organization": "text", "units": "names"},
    "credit_application_and_business_unit": {"business_unit": "text"},
    "workforce_groups": {"organization": "text", "groups": "names"},
}
REFERENCE = r"\{\{(calc|ev|fact):([^}|]+)(?:\|([0-6]))?\}\}"
CHART_REFERENCE = r"\{\{chart:(chart_[0-9a-f]{24})\}\}"


def _retrieval_query(project: dict, definition: dict) -> dict:
    scope = project["subject_scope"]
    period = project.get("evaluation_date", project.get("report_period"))
    if len(period) == 7:
        year, month = map(int, period.split("-"))
        period += f"-{calendar.monthrange(year, month)[1]:02d}"
    return {"subject_id": scope.get("business_unit", scope.get("organization")),
            "as_of": period, "need": definition["need"]}


def _check_scope(model: str, scope: object) -> None:
    if not isinstance(scope, dict) or model not in SUBJECT_MODELS:
        raise ValueError("invalid subject_scope")
    for field, kind in SUBJECT_MODELS[model].items():
        value = scope.get(field)
        if kind == "text" and (not isinstance(value, str) or not value.strip()):
            raise ValueError(f"subject_scope.{field} is required")
        if kind == "names" and (not isinstance(value, list) or not value or any(not isinstance(name, str) or not name.strip() for name in value) or len(value) != len(set(value))):
            raise ValueError(f"subject_scope.{field} must name distinct subjects")
    special = scope.get("special_subjects", [])
    if not isinstance(special, list) or any(not isinstance(name, str) or not name.strip() for name in special) or len(special) != len(set(special)):
        raise ValueError("subject_scope.special_subjects must name distinct subjects")


def list_scenarios() -> list[dict]:
    return [load_scenario(scenario_id).summary() for scenario_id in scenario_ids()]


def get_scenario(scenario_id: str, version: str | None = None) -> dict:
    scenario = load_scenario(scenario_id)
    if version is not None and scenario.version != version:
        raise ValueError(f"{scenario_id}: requested version {version}, installed {scenario.version}")
    return scenario.as_dict()


def create_project(workspace: Path, request: dict) -> dict:
    scenario = get_scenario(request["scenario_id"], request["scenario_version"])
    overrides = request.get("overrides", {})
    if not isinstance(overrides, dict):
        raise ValueError("overrides must be an object")
    manifest = scenario["scenario"]
    allowed = manifest.get("overridable_fields", {})
    for path, value in overrides.items():
        rule = allowed.get(path)
        if not rule or not (rule.get("type") == "string" and isinstance(value, str) and len(value) >= rule.get("min_length", 0) or rule.get("type") == "integer" and type(value) is int and value >= rule.get("minimum", 0) or rule.get("type") == "boolean" and type(value) is bool):
            raise ValueError(f"invalid override: {path}")
    for path, value in overrides.items():
        if path.startswith("business_definitions."):
            manifest["business_definitions"][path.removeprefix("business_definitions.")] = value
        elif path == "retrieval.enabled":
            manifest["retrieval"]["enabled"] = value
    manifest["definition_missing"] = [key for key, value in manifest["business_definitions"].items() if value is None]
    scope = request.get("subject_scope")
    _check_scope(manifest["subject_model"], scope)
    report_profile = request.get("report_profile")
    if report_profile is not None:
        raise ValueError("report_profile is no longer configured; submit a per-run report outline")
    effective_config = {key: scenario[key] for key in ("scenario", "outline", "analysis", "quality")}
    fingerprint_options = overrides
    fingerprint = sha256((scenario["fingerprint"] + json.dumps(fingerprint_options, ensure_ascii=False, sort_keys=True)).encode()).hexdigest() if fingerprint_options else scenario["fingerprint"]
    report_title = request.get("report_title")
    if report_title is not None and (not isinstance(report_title, str) or not report_title.strip() or len(report_title) > 120 or "\n" in report_title or "\r" in report_title):
        raise ValueError("report_title must be a single line of at most 120 characters")
    cover_profile = manifest["presentation"].get("cover")
    if cover_profile and report_title is not None:
        raise ValueError("report_title is generated by the scenario cover")
    metadata_fields = {"analysis_subject", "prepared_by", "confidentiality"}
    if cover_profile:
        metadata_fields.update(field["source"] for field in cover_profile["fields"] if field["source"] != "run_date")
    report_metadata = request.get("report_metadata", {})
    if (not isinstance(report_metadata, dict)
            or set(report_metadata) - metadata_fields
            or any(not isinstance(value, str) or not value.strip() or len(value) > 120 or "\n" in value or "\r" in value
                   for value in report_metadata.values())):
        raise ValueError("invalid report_metadata: unsupported field or invalid single-line text")
    time_field = "evaluation_date" if scenario["scenario"]["time_model"] == "evaluation_date" else "report_period"
    period = request.get(time_field)
    if not isinstance(period, str) or not period:
        raise ValueError(f"{time_field} is required")
    try:
        if time_field == "report_period":
            if len(period) != 7:
                raise ValueError(period)
            date.fromisoformat(period + "-01")
        else:
            date.fromisoformat(period)
    except ValueError as error:
        raise ValueError(f"invalid {time_field}: {period}") from error
    if time_field == "evaluation_date" and (not isinstance(request.get("credit_application_id"), str) or not request["credit_application_id"]):
        raise ValueError("credit_application_id is required")
    related = request.get("related_project_id")
    if related is not None:
        get_project(workspace, related)
    project = {
        "id": uuid4().hex,
        "scenario_id": scenario["id"],
        "scenario_version": scenario["version"],
        "scenario_fingerprint": scenario["fingerprint"],
        "effective_config_fingerprint": fingerprint,
        "effective_config": effective_config,
        "overrides": overrides,
        "subject_scope": scope,
        time_field: period,
        "definition_missing": manifest["definition_missing"],
    }
    if time_field == "evaluation_date":
        project["credit_application_id"] = request["credit_application_id"]
    if report_title is not None:
        project["report_title"] = report_title.strip()
    if report_metadata:
        project["report_metadata"] = {key: value.strip() for key, value in report_metadata.items()}
    if related is not None:
        project["related_project_id"] = related
    directory = workspace / project["id"]
    directory.mkdir(parents=True)
    with sqlite3.connect(directory / "state.sqlite") as connection:
        connection.execute("CREATE TABLE project (id TEXT PRIMARY KEY, data TEXT NOT NULL)")
        connection.execute("INSERT INTO project VALUES (?, ?)", (project["id"], json.dumps(project, ensure_ascii=False)))
    return project


def get_project(workspace: Path, project_id: str) -> dict:
    if len(project_id) != 32 or any(char not in "0123456789abcdef" for char in project_id):
        raise ValueError("invalid project id")
    database = workspace / project_id / "state.sqlite"
    if not database.is_file():
        raise ValueError(f"unknown project: {project_id}")
    with sqlite3.connect(database) as connection:
        row = connection.execute("SELECT data FROM project WHERE id = ?", (project_id,)).fetchone()
    if row is None:
        raise ValueError(f"unknown project: {project_id}")
    return json.loads(row[0])


def add_material(workspace: Path, request: dict) -> dict:
    project = get_project(workspace, request["project_id"])
    input_id = request["input_id"]
    source = Path(request["path"])
    inputs = {item["id"]: item for item in project["effective_config"]["scenario"]["inputs"]}
    if input_id not in inputs or source.suffix.lower().lstrip(".") not in inputs[input_id]["kinds"]:
        raise ValueError(f"unsupported material input or format: {input_id}")
    data = source.read_bytes()
    fingerprint = sha256(data).hexdigest()
    material_id = "src_" + fingerprint[:24]
    replaced_id = request.get("replaces_material_id")
    project_dir = workspace / project["id"]
    with sqlite3.connect(project_dir / "state.sqlite") as connection:
        connection.execute("CREATE TABLE IF NOT EXISTS material (id TEXT PRIMARY KEY, data TEXT NOT NULL)")
        if replaced_id is not None:
            prior_row = connection.execute("SELECT data FROM material WHERE id = ?", (replaced_id,)).fetchone()
            if prior_row is None or replaced_id == material_id or input_id not in json.loads(prior_row[0])["input_ids"]:
                raise ValueError("replacement must name a different archived material with the same input role")
            replacements = [json.loads(row[0]) for row in connection.execute("SELECT data FROM material") if json.loads(row[0]).get("replaces_material_id") == replaced_id]
            if replacements and any(item["id"] != material_id for item in replacements):
                raise ValueError("material already has a different replacement")
        old = connection.execute("SELECT data FROM material WHERE id = ?", (material_id,)).fetchone()
        if old:
            material = _checked_material(json.loads(old[0]))
            if Path(material["original_name"]).suffix.lower() != source.suffix.lower():
                raise ValueError("same bytes are already archived in a different material format")
            if request.get("derivation") is not None and material.get("derivation") != request["derivation"]:
                raise ValueError("archived material has a different derivation; preserve its source relationship")
            if replaced_id is not None and material.get("replaces_material_id") not in (None, replaced_id):
                raise ValueError("archived material belongs to a different replacement chain")
            if replaced_id is not None and material.get("replaces_material_id") is None:
                material["replaces_material_id"] = replaced_id
            if input_id not in material["input_ids"]:
                material["input_ids"].append(input_id)
            connection.execute("UPDATE material SET data = ? WHERE id = ?", (json.dumps(material, ensure_ascii=False), material_id))
            return material
        kind = source.suffix.lower()
        parsers = {".csv": _parse_csv, ".xlsx": _parse_xlsx, ".txt": _parse_text, ".md": _parse_text, ".docx": _parse_docx, ".pdf": _parse_pdf}
        if project["scenario_id"] == "financial_due_diligence" and kind in (".jpg", ".jpeg", ".png"):
            parsers[kind] = _parse_image
        if kind not in parsers:
            raise ValueError(f"no parser for material format: {kind}")
        if kind == ".pdf" and project["scenario_id"] == "financial_due_diligence":
            parsed = _parse_pdf(data, allow_empty=True)
        else:
            parsed = parsers[kind](data)
        derivation = request.get("derivation")
        if derivation is not None:
            if not isinstance(derivation, dict) or not isinstance(derivation.get("method"), str) or not derivation["method"].strip():
                raise ValueError("derivation requires source_id, source_sha256, method and locator_map")
            original = get_material(workspace, project["id"], derivation.get("source_id"))
            mapping = derivation.get("locator_map")
            locators = {f["locator"] for f in parsed.get("fragments", [])}
            locators.update(c["locator"] for sh in parsed.get("sheets", {}).values() for c in sh["cells"].values())
            if (derivation.get("source_sha256") != original["fingerprint"] or original["fingerprint"] == fingerprint
                    or not isinstance(mapping, dict) or set(mapping) != locators):
                raise ValueError("derivation must bind every fragment to the archived original hash and locator")
            pages = original["parsed"].get("coverage", {}).get("page_count", 0)
            original_locators = {f["locator"] for f in original["parsed"].get("fragments", [])}
            original_locators.update(c["locator"] for sh in original["parsed"].get("sheets", {}).values() for c in sh["cells"].values())
            for locator in mapping.values():
                page = re.fullmatch(r"page:([1-9][0-9]*)", str(locator))
                if locator not in original_locators and not (page and int(page[1]) <= pages):
                    raise ValueError("derivation original locator does not exist")
        archive = project_dir / "sources" / material_id
        archive.mkdir(parents=True)
        destination = archive / source.name
        with destination.open("xb") as output:
            output.write(data)
        material = {
            "id": material_id, "input_id": input_id, "input_ids": [input_id], "original_name": source.name,
            "fingerprint": fingerprint, "status": "parsed", "archived_path": str(destination),
            "parsed": parsed,
        }
        if replaced_id is not None:
            material["replaces_material_id"] = replaced_id
        if derivation is not None:
            material["derivation"] = derivation
        connection.execute("INSERT INTO material VALUES (?, ?)", (material_id, json.dumps(material, ensure_ascii=False)))
    return material


def get_material(workspace: Path, project_id: str, material_id: str) -> dict:
    project = get_project(workspace, project_id)
    with sqlite3.connect(workspace / project["id"] / "state.sqlite") as connection:
        row = connection.execute("SELECT data FROM material WHERE id = ?", (material_id,)).fetchone()
    if row is None:
        raise ValueError(f"unknown material: {material_id}")
    return _checked_material(json.loads(row[0]))


def start_run(workspace: Path, request: dict) -> dict:
    project = get_project(workspace, request["project_id"])
    database = workspace / project["id"] / "state.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE IF NOT EXISTS material (id TEXT PRIMARY KEY, data TEXT NOT NULL)")
        connection.execute("CREATE TABLE IF NOT EXISTS run (id TEXT PRIMARY KEY, data TEXT NOT NULL)")
        connection.execute("CREATE TABLE IF NOT EXISTS task (id TEXT PRIMARY KEY, run_id TEXT NOT NULL, data TEXT NOT NULL)")
        active = connection.execute("SELECT data FROM run").fetchall()
        if any(json.loads(row[0])["status"] == "active" for row in active):
            raise ValueError("project already has an active run")
        latest_id = None
        if connection.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'latest'").fetchone():
            latest_row = connection.execute("SELECT revision_id FROM latest WHERE slot = 1").fetchone()
            latest_id = latest_row[0] if latest_row else None
        if request.get("base_revision_id") is not None and request["base_revision_id"] != latest_id:
            raise ValueError("stale base revision")
        archived = [_checked_material(json.loads(row[0])) for row in connection.execute("SELECT data FROM material ORDER BY id")]
        superseded = {material["replaces_material_id"] for material in archived if material.get("replaces_material_id")}
        materials = [material for material in archived if material["id"] not in superseded]
        base_run = None
        if latest_id is not None:
            revision = json.loads(connection.execute("SELECT data FROM revision WHERE id = ?", (latest_id,)).fetchone()[0])
            base_run = json.loads(connection.execute("SELECT data FROM run WHERE id = ?", (revision["run_id"],)).fetchone()[0])
        unchanged = [material["id"] for material in materials if base_run and base_run["material_fingerprints"].get(material["id"]) == material["fingerprint"] and base_run["material_input_ids"].get(material["id"]) == material["input_ids"]]
        locked = request.get("locked_sections", [])
        base_outline = base_run["effective_config"]["outline"] if base_run else project["effective_config"]["outline"]
        valid_sections = {section["id"] + ":" + subject for section in base_outline["sections"] if section["repeat_for"] == "unit" for subject in base_outline.get("unit_names", project["subject_scope"].get("units", []))}
        valid_sections |= {section["id"] for section in base_outline["sections"] if section["repeat_for"] != "unit"}
        if not isinstance(locked, list) or any(not isinstance(item, str) or item not in valid_sections for item in locked) or len(locked) != len(set(locked)) or locked and latest_id is None:
            raise ValueError("locked_sections must name existing sections of a delivered revision")
        run = {
            "id": uuid4().hex, "project_id": project["id"], "status": "active",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "base_revision_id": latest_id,
            "effective_config_fingerprint": base_run["effective_config_fingerprint"] if base_run and base_run.get("report_plan") else project["effective_config_fingerprint"],
            "effective_config": base_run["effective_config"] if base_run and base_run.get("report_plan") else project["effective_config"],
            "material_ids": [material["id"] for material in materials],
            "material_fingerprints": {material["id"]: material["fingerprint"] for material in materials},
            "material_input_ids": {material["id"]: material["input_ids"] for material in materials},
            "unchanged_material_ids": unchanged,
            "locked_sections": locked,
        }
        if base_run and base_run.get("report_plan"):
            run["report_plan"] = base_run["report_plan"]
            run["report_request"] = base_run["report_request"]
        connection.execute("INSERT INTO run VALUES (?, ?)", (run["id"], json.dumps(run, ensure_ascii=False)))
        for material in materials:
            if material["id"] in unchanged:
                continue
            task = {
                "id": uuid4().hex, "run_id": run["id"], "kind": "extract_candidate_facts",
                "source_id": material["id"], "input_fingerprint": material["fingerprint"], "status": "ready",
            }
            connection.execute("INSERT INTO task VALUES (?, ?, ?)", (task["id"], run["id"], json.dumps(task, ensure_ascii=False)))
        if run["effective_config"]["scenario"]["retrieval"]["enabled"]:
            provider_id = request.get("retrieval_provider_id")
            if not isinstance(provider_id, str) or not provider_id.strip() or type(request.get("refresh_retrieval", False)) is not bool:
                raise ValueError("enabled retrieval requires provider id and boolean refresh_retrieval")
            for task_ref in run["effective_config"]["scenario"]["retrieval"]["task_refs"]:
                definition = next(item for item in run["effective_config"]["analysis"]["retrieval_tasks"] if item["id"] == task_ref)
                query_hash = sha256(json.dumps(_retrieval_query(project, definition), ensure_ascii=False, sort_keys=True).encode()).hexdigest()
                task = {"id": uuid4().hex, "run_id": run["id"], "kind": "retrieve", "task_ref": task_ref,
                        "provider_id": provider_id, "query_sha256": query_hash, "status": "ready"}
                if not request.get("refresh_retrieval"):
                    for previous_row in connection.execute("SELECT data FROM task ORDER BY rowid DESC"):
                        previous = json.loads(previous_row[0])
                        if previous.get("kind") != "retrieve" or previous.get("task_ref") != task_ref or previous.get("provider_id") != provider_id or previous.get("query_sha256") != query_hash or previous.get("result_status") != "success":
                            continue
                        fetched_at = datetime.fromisoformat(previous["retrieved_at"])
                        raw_path = Path(previous["raw_path"])
                        if previous["material_id"] in run["material_ids"] and datetime.now(timezone.utc) - fetched_at <= timedelta(days=definition["ttl_days"]) and raw_path.is_file() and sha256(raw_path.read_bytes()).hexdigest() == previous["raw_sha256"] and get_material(workspace, project["id"], previous["material_id"]):
                            task.update(status="submitted", result_status="success", reused_from_task_id=previous["id"],
                                        retrieved_at=previous["retrieved_at"], raw_path=previous["raw_path"],
                                        raw_sha256=previous["raw_sha256"], material_id=previous["material_id"])
                        break
                connection.execute("INSERT INTO task VALUES (?, ?, ?)", (task["id"], run["id"], json.dumps(task, ensure_ascii=False)))
    return run


def get_run(workspace: Path, project_id: str, run_id: str) -> dict:
    project = get_project(workspace, project_id)
    with sqlite3.connect(workspace / project["id"] / "state.sqlite") as connection:
        row = connection.execute("SELECT data FROM run WHERE id = ?", (run_id,)).fetchone()
    if row is None:
        raise ValueError(f"unknown run: {run_id}")
    return json.loads(row[0])


def cancel_run(workspace: Path, request: dict) -> dict:
    run = get_run(workspace, request["project_id"], request["run_id"])
    if run["status"] != "active":
        raise ValueError("only an active run can be canceled")
    with sqlite3.connect(workspace / request["project_id"] / "state.sqlite") as connection:
        run["status"] = "canceled"
        connection.execute("UPDATE run SET data = ? WHERE id = ?", (json.dumps(run, ensure_ascii=False), run["id"]))
    return run


def list_tasks(workspace: Path, project_id: str, run_id: str) -> list[dict]:
    project = get_project(workspace, project_id)
    with sqlite3.connect(workspace / project["id"] / "state.sqlite") as connection:
        run = connection.execute("SELECT data FROM run WHERE id = ?", (run_id,)).fetchone()
        if run is None:
            raise ValueError(f"unknown run: {run_id}")
        rows = connection.execute("SELECT data FROM task WHERE run_id = ? ORDER BY id", (run_id,))
        return [json.loads(row[0]) for row in rows]


def get_task_context(workspace: Path, project_id: str, task_id: str) -> dict:
    project = get_project(workspace, project_id)
    with sqlite3.connect(workspace / project["id"] / "state.sqlite") as connection:
        task_row = connection.execute("SELECT data FROM task WHERE id = ?", (task_id,)).fetchone()
        if task_row is None:
            raise ValueError(f"unknown task: {task_id}")
        task = json.loads(task_row[0])
        run_row = connection.execute("SELECT data FROM run WHERE id = ?", (task["run_id"],)).fetchone()
    run = json.loads(run_row[0])
    if task["kind"] == "retrieve":
        definition = next(item for item in run["effective_config"]["analysis"]["retrieval_tasks"] if item["id"] == task["task_ref"])
        return {"task": task, "run": run, "query": _retrieval_query(project, definition), "effective_config": run["effective_config"]}
    material = get_material(workspace, project_id, task["source_id"])
    material["input_ids"] = run["material_input_ids"][material["id"]]
    return {"task": task, "run": run, "material": material, "effective_config": run["effective_config"]}


def execute_retrieval(workspace: Path, request: dict) -> dict:
    context = get_task_context(workspace, request["project_id"], request["task_id"])
    task, run = context["task"], context["run"]
    if task["kind"] != "retrieve" or task["run_id"] != request["run_id"] or run["status"] != "active" or run.get("evidence_snapshot_id") or task["status"] != "ready":
        raise ValueError("retrieval task is not eligible")
    provider = request["provider"]
    if not isinstance(provider, dict) or provider.get("id") != task["provider_id"]:
        raise ValueError("provider id does not match planned retrieval task")
    raw, result = fetch(provider, context["query"])
    status = result["status"]
    records = result.get("records", [])
    if status in ("success", "partial"):
        valid_metadata = (result.get("subject_id") == context["query"]["subject_id"]
                          and isinstance(result.get("source_ref"), str) and bool(result["source_ref"].strip())
                          and isinstance(result.get("as_of"), str))
        try:
            valid_date = valid_metadata and date.fromisoformat(result["as_of"]) <= date.fromisoformat(context["query"]["as_of"])
        except ValueError:
            valid_date = False
        if not valid_date:
            status = "mismatch"
        elif not isinstance(records, list) or any(not isinstance(item, str) or not item.strip() or "\n" in item or "\r" in item for item in records):
            status = "failed"
        elif not records:
            status = "empty"
    project_dir = workspace / request["project_id"]
    retrieval_dir = project_dir / "runs" / run["id"] / "retrieval"
    retrieval_dir.mkdir(parents=True, exist_ok=True)
    attempt_id = uuid4().hex
    raw_path = retrieval_dir / (attempt_id + ".raw.json")
    with raw_path.open("xb") as output:
        output.write(raw)
    material = None
    if status in ("success", "partial"):
        definition = next(item for item in run["effective_config"]["analysis"]["retrieval_tasks"] if item["id"] == task["task_ref"])
        source_path = retrieval_dir / (attempt_id + ".txt")
        source_path.write_text("\n".join([f"raw_sha256: {sha256(raw).hexdigest()}", f"source_ref: {result['source_ref']}", f"subject_id: {result['subject_id']}", f"as_of: {result['as_of']}", *records]) + "\n", encoding="utf-8")
        material = add_material(workspace, {"project_id": request["project_id"], "input_id": definition["input"], "path": str(source_path)})
    database = project_dir / "state.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute("BEGIN IMMEDIATE")
        current = json.loads(connection.execute("SELECT data FROM task WHERE id = ?", (task["id"],)).fetchone()[0])
        current_run = json.loads(connection.execute("SELECT data FROM run WHERE id = ?", (run["id"],)).fetchone()[0])
        if current["status"] != "ready" or current_run.get("evidence_snapshot_id") or current_run["status"] != "active":
            raise ValueError("retrieval task changed before archive commit")
        task.update(status="submitted", result_status=status, raw_path=str(raw_path), raw_sha256=sha256(raw).hexdigest(),
                    retrieved_at=datetime.now(timezone.utc).isoformat(), limitations=result.get("limitations", []))
        if material:
            task["material_id"] = material["id"]
            provenance = {"source_ref": result["source_ref"],
                          "subject_id": result["subject_id"], "as_of": result["as_of"], "raw_sha256": task["raw_sha256"]}
            material["retrieval_provenance"] = provenance
            connection.execute("UPDATE material SET data = ? WHERE id = ?", (json.dumps(material, ensure_ascii=False), material["id"]))
            if material["id"] not in current_run["material_ids"]:
                current_run["material_ids"].append(material["id"])
                current_run["material_fingerprints"][material["id"]] = material["fingerprint"]
                current_run["material_input_ids"][material["id"]] = material["input_ids"]
                extraction = {"id": uuid4().hex, "run_id": run["id"], "kind": "extract_candidate_facts", "source_id": material["id"],
                              "input_fingerprint": material["fingerprint"], "status": "ready"}
                connection.execute("INSERT INTO task VALUES (?, ?, ?)", (extraction["id"], run["id"], json.dumps(extraction, ensure_ascii=False)))
            connection.execute("UPDATE run SET data = ? WHERE id = ?", (json.dumps(current_run, ensure_ascii=False), run["id"]))
        connection.execute("UPDATE task SET data = ? WHERE id = ?", (json.dumps(task, ensure_ascii=False), task["id"]))
    return task


def submit_task(workspace: Path, request: dict) -> dict:
    context = get_task_context(workspace, request["project_id"], request["task_id"])
    task, run, material = context["task"], context["run"], context["material"]
    fingerprint = sha256(json.dumps(request, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    if task["run_id"] != request["run_id"] or run["status"] != "active" or run.get("evidence_snapshot_id"):
        raise ValueError("task is not eligible for submission")
    if task["status"] == "submitted" and task.get("submission_fingerprint") == fingerprint:
        with sqlite3.connect(workspace / request["project_id"] / "state.sqlite") as connection:
            candidates = [json.loads(row[0]) for row in connection.execute("SELECT data FROM candidate WHERE run_id = ?", (run["id"],))]
        return {"task": task, "candidates": [item for item in candidates if item["task_id"] == task["id"]]}
    if task["status"] != "ready":
        raise ValueError("task already submitted with different results")
    if task["input_fingerprint"] != request["input_fingerprint"] or run["material_fingerprints"][material["id"]] != material["fingerprint"]:
        raise ValueError("stale task input")
    submitted = request["candidates"]
    if not isinstance(submitted, list):
        raise ValueError("candidates must be a list")
    parsed = material["parsed"]
    fragments = parsed.get("fragments", [])
    fragments += [cell for sheet in parsed.get("sheets", {}).values() for cell in sheet["cells"].values()]
    cells = {fragment["locator"]: fragment for fragment in fragments}
    candidates = []
    for item in submitted:
        if not isinstance(item, dict) or any(not isinstance(item.get(key), str) or not item[key].strip() for key in ("subject_id", "metric_id", "period", "value", "source_locator", "source_value")):
            raise ValueError("candidate requires subject, metric, period, value and source")
        cell = cells.get(item["source_locator"])
        if cell is None or cell["value"] != item["source_value"]:
            raise ValueError("candidate source locator or value does not match archived material")
        span = item.get("source_span")
        if span is None:
            matches = item["value"] == item["source_value"]
        else:
            matches = (isinstance(span, list) and len(span) == 2 and all(type(index) is int for index in span)
                       and 0 <= span[0] < span[1] <= len(item["source_value"])
                       and item["source_value"][span[0]:span[1]] == item["value"])
            if matches and item["value"][0].isdigit() and span[0] and item["source_value"][span[0] - 1] in "0123456789.,+-−":
                matches = False
            if matches and item["value"][-1].isdigit() and span[1] < len(item["source_value"]) and item["source_value"][span[1]] in "0123456789.,":
                matches = False
        if not matches:
            raise ValueError("candidate source locator or value does not match archived material; invalid source_span")
        candidates.append({"id": uuid4().hex, **item, "source_id": material["id"], "task_id": task["id"], "run_id": run["id"], "status": "candidate"})
    database = workspace / request["project_id"] / "state.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE IF NOT EXISTS candidate (id TEXT PRIMARY KEY, run_id TEXT NOT NULL, data TEXT NOT NULL)")
        current = json.loads(connection.execute("SELECT data FROM task WHERE id = ?", (task["id"],)).fetchone()[0])
        if current["status"] != "ready":
            raise ValueError("task already submitted")
        for candidate in candidates:
            connection.execute("INSERT INTO candidate VALUES (?, ?, ?)", (candidate["id"], run["id"], json.dumps(candidate, ensure_ascii=False)))
        task["status"] = "submitted"
        task["submission_fingerprint"] = fingerprint
        connection.execute("UPDATE task SET data = ? WHERE id = ?", (json.dumps(task, ensure_ascii=False), task["id"]))
    return {"task": task, "candidates": candidates}


def auto_submit_task(workspace: Path, request: dict) -> dict:
    context = get_task_context(workspace, request["project_id"], request["task_id"])
    task, run, material = context["task"], context["run"], context["material"]
    if task["kind"] != "extract_candidate_facts" or task["run_id"] != request["run_id"]:
        raise ValueError("auto-submit requires an extraction task from this run")
    profile = validate_source_mapping(request.get("mapping"), {item["id"] for item in run["effective_config"]["scenario"]["inputs"]})
    project = get_project(workspace, request["project_id"])
    if project.get("report_period") != profile["report_period"] or project["subject_scope"].get("organization") != profile["organization"]:
        raise ValueError("source mapping scope or period does not match this project")
    tables = [item for item in profile["tables"] if item["filename"] == material["original_name"]]
    if not tables:
        raise ValueError("material has no table in source profile")
    allowed_subjects = {project["subject_scope"]["organization"], *project["subject_scope"]["units"], *project["subject_scope"].get("special_subjects", [])}
    candidates = []
    excluded_rows = []
    for table in tables:
        if not set(table["input_ids"]) <= set(material["input_ids"]):
            raise ValueError(f"source profile {table['id']} requires material roles {table['input_ids']}")
        cells = material["parsed"].get("sheets", {}).get(table["sheet"], {}).get("cells")
        if cells is None:
            raise ValueError(f"source profile {table['id']} sheet is missing")
        for row in table["rows"]:
            subject_cell = cells.get(f"{table['subject_column']}{row['row']}")
            if subject_cell is None or subject_cell["value"] != row["source_subject"]:
                raise ValueError(f"source profile {table['id']} row {row['row']} subject changed")
            if not set(row["targets"]) <= allowed_subjects:
                excluded_rows.append({"table_id": table["id"], "row": row["row"], "targets": row["targets"]})
                continue
            for field in table["fields"]:
                cell = cells.get(f"{field['column']}{row['row']}")
                if cell is None or cell.get("state") in ("pending_verify", "cached_unverified", "cache_mismatch"):
                    raise ValueError(f"source profile {table['id']} {field['column']}{row['row']} missing or unverified")
                try:
                    Decimal(cell["value"])
                except (InvalidOperation, TypeError):
                    raise ValueError(f"source profile {table['id']} {field['column']}{row['row']} is not numeric") from None
                for target in row["targets"]:
                    candidates.append({"subject_id": target, "source_subject": row["source_subject"].strip(),
                                       "metric_id": "profit_total" if table["id"] == "profit" else f"{table['id']}.r{row['row']}.{field['id']}",
                                       "period": field["period"], "window": field["window"], "unit": field.get("units_by_row", {}).get(str(row["row"]), field["unit"]),
                                       "basis": field["basis"], "budget_version": field["budget_version"],
                                       "value": cell["value"], "source_value": cell["value"], "source_locator": cell["locator"],
                                       "mapping_basis": f"{profile['id']}:{table['id']}:r{row['row']}"})
    reason = request.get("scope_exclusion_reason")
    if excluded_rows and (not isinstance(reason, str) or not reason.strip()):
        raise ValueError("scope_exclusion_reason is required for source rows outside the project scope")
    result = submit_task(workspace, {"project_id": request["project_id"], "run_id": request["run_id"],
                                     "task_id": task["id"], "input_fingerprint": task["input_fingerprint"], "candidates": candidates})
    with sqlite3.connect(workspace / project["id"] / "state.sqlite") as connection:
        stored = json.loads(connection.execute("SELECT data FROM task WHERE id = ?", (task["id"],)).fetchone()[0])
        stored["source_mapping"] = profile
        stored["scope_exclusions"] = [{**item, "reason": reason.strip()} for item in excluded_rows]
        connection.execute("UPDATE task SET data = ? WHERE id = ?", (json.dumps(stored, ensure_ascii=False), task["id"]))
    return {**result, "excluded_rows": excluded_rows}


def _carried_evidence(connection: sqlite3.Connection, run: dict) -> list[dict]:
    if not run["base_revision_id"]:
        return []
    revision = json.loads(connection.execute("SELECT data FROM revision WHERE id = ?", (run["base_revision_id"],)).fetchone()[0])
    base_run = json.loads(connection.execute("SELECT data FROM run WHERE id = ?", (revision["run_id"],)).fetchone()[0])
    snapshot = json.loads(connection.execute("SELECT data FROM evidence_snapshot WHERE id = ?", (base_run["evidence_snapshot_id"],)).fetchone()[0])
    allowed = set(snapshot["evidence_ids"])
    unchanged = set(run["unchanged_material_ids"])
    excluded = set(run.get("excluded_evidence_ids", []))
    return [item for row in connection.execute("SELECT data FROM evidence") if (item := json.loads(row[0]))["id"] in allowed - excluded and item["source_id"] in unchanged]


def decide_evidence(workspace: Path, request: dict) -> dict:
    project = get_project(workspace, request["project_id"])
    decision = request["decision"]
    if decision not in ("accept", "reject", "replace"):
        raise ValueError("unsupported evidence decision")
    database = workspace / project["id"] / "state.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute("BEGIN IMMEDIATE")
        run_row = connection.execute("SELECT data FROM run WHERE id = ?", (request["run_id"],)).fetchone()
        if run_row is None or json.loads(run_row[0])["status"] != "active" or json.loads(run_row[0]).get("evidence_snapshot_id"):
            raise ValueError("run is not active")
        run = json.loads(run_row[0])
        candidate_row = connection.execute("SELECT data FROM candidate WHERE id = ? AND run_id = ?", (request["candidate_id"], request["run_id"])).fetchone()
        if candidate_row is None:
            raise ValueError("unknown candidate for run")
        candidate = json.loads(candidate_row[0])
        if candidate["status"] not in ("candidate", "conflict"):
            raise ValueError("candidate already decided")
        if project["scenario_id"] == "compensation_analysis" and any(role in ("payroll", "roster") for role in run["material_input_ids"][candidate["source_id"]]):
            raise ValueError("personal payroll and roster rows must use registered group calculation")
        if decision == "reject":
            if not isinstance(request.get("reason"), str) or not request["reason"].strip():
                raise ValueError("rejection reason is required")
            candidate.update(status="rejected", decision_reason=request["reason"])
            connection.execute("UPDATE candidate SET data = ? WHERE id = ?", (json.dumps(candidate, ensure_ascii=False), candidate["id"]))
            return candidate
        if candidate.get("basis") is not None and candidate["basis"] not in run["material_input_ids"][candidate["source_id"]]:
            raise ValueError("candidate basis is not declared for frozen source")
        scope = project["subject_scope"]
        allowed_subjects = [scope[key] for key in ("organization", "business_unit") if key in scope]
        allowed_subjects += scope.get("units", []) + scope.get("groups", []) + scope.get("special_subjects", [])
        if candidate["subject_id"] not in allowed_subjects:
            raise ValueError("candidate subject is outside project scope")
        material = get_material(workspace, project["id"], candidate["source_id"])
        source_cells = [cell for sheet in material["parsed"].get("sheets", {}).values() for cell in sheet["cells"].values()]
        source_cells += material["parsed"].get("fragments", [])
        source_cell = next((cell for cell in source_cells if cell["locator"] == candidate["source_locator"]), None)
        if source_cell is None or source_cell.get("state") in ("pending_verify", "cached_unverified", "cache_mismatch"):
            raise ValueError("candidate source is unverified")
        connection.execute("CREATE TABLE IF NOT EXISTS evidence (id TEXT PRIMARY KEY, run_id TEXT NOT NULL, candidate_id TEXT UNIQUE NOT NULL, data TEXT NOT NULL)")
        if connection.execute("SELECT id FROM evidence WHERE candidate_id = ?", (candidate["id"],)).fetchone():
            raise ValueError("candidate already decided")
        existing = [json.loads(row[0]) for row in connection.execute("SELECT data FROM evidence WHERE run_id = ?", (run["id"],))] + _carried_evidence(connection, run)
        identity = ("subject_id", "metric_id", "period", "window", "unit", "budget_version", "financial_scope", "financial_version", "period_start", "period_days")
        def basis(item):
            roles = run["material_input_ids"][item["source_id"]]
            return item.get("basis") or (roles[0] if len(roles) == 1 else None)
        conflicts = [item for item in existing if item["status"] == "usable" and basis(item) == basis(candidate) and all(item.get(key) == candidate.get(key) for key in identity)]
        if decision == "accept" and conflicts:
            candidate.update(status="conflict", conflicts_with=[item["id"] for item in conflicts])
            connection.execute("UPDATE candidate SET data = ? WHERE id = ?", (json.dumps(candidate, ensure_ascii=False), candidate["id"]))
            return candidate
        if decision == "replace":
            prior_id = request.get("supersedes_evidence_id")
            if candidate["status"] != "conflict" or len(conflicts) != 1 or prior_id != conflicts[0]["id"] or not isinstance(request.get("reason"), str) or not request["reason"].strip():
                raise ValueError("replacement needs one conflicting usable evidence and a reason")
            previous = conflicts[0]
            if previous["run_id"] == run["id"]:
                previous["status"] = "superseded"
                previous["superseded_by_candidate_id"] = candidate["id"]
                connection.execute("UPDATE evidence SET data = ? WHERE id = ?", (json.dumps(previous, ensure_ascii=False), previous["id"]))
            else:
                run.setdefault("excluded_evidence_ids", []).append(previous["id"])
                connection.execute("UPDATE run SET data = ? WHERE id = ?", (json.dumps(run, ensure_ascii=False), run["id"]))
        evidence = {**candidate, "id": "ev_" + uuid4().hex, "candidate_id": candidate["id"], "status": "usable"}
        if decision == "replace":
            evidence["supersedes_evidence_id"] = prior_id
            evidence["decision_reason"] = request["reason"]
        connection.execute("INSERT INTO evidence VALUES (?, ?, ?, ?)", (evidence["id"], request["run_id"], candidate["id"], json.dumps(evidence, ensure_ascii=False)))
        candidate["status"] = "accepted"
        connection.execute("UPDATE candidate SET data = ? WHERE id = ?", (json.dumps(candidate, ensure_ascii=False), candidate["id"]))
    return evidence


def freeze_evidence(workspace: Path, request: dict) -> dict:
    project = get_project(workspace, request["project_id"])
    database = workspace / project["id"] / "state.sqlite"
    with sqlite3.connect(database) as connection:
        row = connection.execute("SELECT data FROM run WHERE id = ?", (request["run_id"],)).fetchone()
        if row is None:
            raise ValueError("unknown run")
        run = json.loads(row[0])
        if run["status"] != "active" or run.get("evidence_snapshot_id"):
            raise ValueError("run cannot freeze evidence")
        tasks = [json.loads(item[0]) for item in connection.execute("SELECT data FROM task WHERE run_id = ?", (run["id"],))]
        if any(task["status"] != "submitted" for task in tasks):
            raise ValueError("extraction tasks remain open")
        if any(task["kind"] == "retrieve" and (not Path(task["raw_path"]).is_file() or sha256(Path(task["raw_path"]).read_bytes()).hexdigest() != task["raw_sha256"]) for task in tasks):
            raise ValueError("retrieval raw response checksum mismatch")
        connection.execute("CREATE TABLE IF NOT EXISTS candidate (id TEXT PRIMARY KEY, run_id TEXT NOT NULL, data TEXT NOT NULL)")
        unresolved = [json.loads(row[0])["id"] for row in connection.execute("SELECT data FROM candidate WHERE run_id = ?", (run["id"],)) if json.loads(row[0])["status"] == "conflict"]
        if unresolved:
            raise ValueError("unresolved source conflict: " + ", ".join(unresolved))
        connection.execute("CREATE TABLE IF NOT EXISTS evidence (id TEXT PRIMARY KEY, run_id TEXT NOT NULL, candidate_id TEXT UNIQUE NOT NULL, data TEXT NOT NULL)")
        evidence = [item for row in connection.execute("SELECT data FROM evidence WHERE run_id = ? ORDER BY id", (run["id"],)) if (item := json.loads(row[0]))["status"] == "usable"]
        evidence = _carried_evidence(connection, run) + evidence
        inputs = {item["id"] for item in run["effective_config"]["scenario"]["inputs"] if item["required"]}
        present = {input_id for roles in run["material_input_ids"].values() for input_id in roles}
        snapshot = {
            "id": uuid4().hex, "run_id": run["id"], "evidence_ids": [item["id"] for item in evidence],
            "missing_inputs": sorted(inputs - present),
            "definition_missing": run["effective_config"]["scenario"]["definition_missing"],
            "retrieval_gaps": [f"{task['task_ref']}:{task['result_status']}" for task in tasks if task["kind"] == "retrieve" and task.get("result_status") != "success"],
        }
        if project["scenario_id"] == "financial_due_diligence":
            current_materials = [json.loads(row[0]) for row in connection.execute("SELECT data FROM material")
                                 if json.loads(row[0])["id"] in run["material_ids"]]
            snapshot["material_coverage"] = material_coverage(current_materials, evidence)
        connection.execute("CREATE TABLE IF NOT EXISTS evidence_snapshot (id TEXT PRIMARY KEY, run_id TEXT NOT NULL, data TEXT NOT NULL)")
        connection.execute("INSERT INTO evidence_snapshot VALUES (?, ?, ?)", (snapshot["id"], run["id"], json.dumps(snapshot, ensure_ascii=False)))
        run["evidence_snapshot_id"] = snapshot["id"]
        connection.execute("UPDATE run SET data = ? WHERE id = ?", (json.dumps(run, ensure_ascii=False), run["id"]))
    return snapshot


def calculate_run(workspace: Path, request: dict) -> list[dict]:
    project = get_project(workspace, request["project_id"])
    with sqlite3.connect(workspace / project["id"] / "state.sqlite") as connection:
        run_row = connection.execute("SELECT data FROM run WHERE id = ?", (request["run_id"],)).fetchone()
        if run_row is None:
            raise ValueError("unknown run")
        run = json.loads(run_row[0])
        if not run.get("evidence_snapshot_id"):
            raise ValueError("evidence must be frozen before calculation")
        snapshot = json.loads(connection.execute("SELECT data FROM evidence_snapshot WHERE id = ?", (run["evidence_snapshot_id"],)).fetchone()[0])
        evidence = [json.loads(row[0]) for row in connection.execute("SELECT data FROM evidence")]
        evidence = [item for item in evidence if item["id"] in snapshot["evidence_ids"]]
        material_inputs = {json.loads(row[0])["id"]: json.loads(row[0])["input_id"] for row in connection.execute("SELECT data FROM material")}
        config = run["effective_config"]
        if project["scenario_id"] == "compensation_analysis":
            materials = [json.loads(row[0]) for row in connection.execute("SELECT data FROM material")]
            results = calculate_groups(project, run, materials)
            connection.execute("CREATE TABLE IF NOT EXISTS calculation (id TEXT PRIMARY KEY, run_id TEXT NOT NULL, data TEXT NOT NULL)")
            for item in results:
                if item.get("id"):
                    connection.execute("INSERT OR REPLACE INTO calculation VALUES (?, ?, ?)", (item["id"], run["id"], json.dumps(item, ensure_ascii=False)))
            return results
        if project["scenario_id"] == "financial_due_diligence" and config["analysis"].get("financial_metrics"):
            results = calculate_financials(evidence, config["analysis"]["financial_metrics"])
            connection.execute("CREATE TABLE IF NOT EXISTS calculation (id TEXT PRIMARY KEY, run_id TEXT NOT NULL, data TEXT NOT NULL)")
            for item in results:
                item["run_id"] = run["id"]
                item["id"] = "calc_" + sha256((run["id"] + item["id"]).encode()).hexdigest()[:24]
                connection.execute("INSERT OR REPLACE INTO calculation VALUES (?, ?, ?)", (item["id"], run["id"], json.dumps(item, ensure_ascii=False)))
            return results
        selectors = {item["id"]: item for item in config["analysis"]["evidence_selectors"]}
        results = []
        for metric in config["analysis"]["metrics"]:
            selected = []
            for selector_id in metric["inputs"]:
                input_id = selectors[selector_id]["input"]
                selected.append([item for item in evidence if item.get("basis", material_inputs[item["source_id"]]) == input_id and (not metric.get("applies_to") or item["metric_id"] in metric["applies_to"])])
            for actual in selected[0]:
                if any(key not in actual for key in ("window", "unit")):
                    raise ValueError("evidence is missing comparison dimensions")
                if actual["unit"] != config["scenario"]["business_definitions"].get("measurement_unit"):
                    raise ValueError("evidence unit does not match project definition")
                if actual["subject_id"] == project["subject_scope"].get("organization") and not config["scenario"]["business_definitions"].get("consolidation_rule"):
                    continue
                matches = [item for item in selected[1] if all(item.get(key) == actual.get(key) for key in ("subject_id", "metric_id", "period", "window", "unit"))]
                if config["scenario"]["id"] == "budget_operations":
                    version = config["scenario"]["business_definitions"].get("budget_version_rule")
                    matches = [item for item in matches if version is not None and item.get("budget_version") == version]
                else:
                    version = None
                if not matches:
                    results.append({"metric_id": metric["id"], "subject_id": actual["subject_id"], "period": actual["period"], "window": actual["window"], "status": "missing_comparable_baseline", "value": None})
                    continue
                if len(matches) != 1:
                    raise ValueError("ambiguous comparison baseline")
                baseline = matches[0]
                try:
                    values = (Decimal(actual["value"]), Decimal(baseline["value"]))
                except (InvalidOperation, TypeError) as error:
                    raise ValueError("non-numeric comparison evidence") from error
                if metric["operator"].startswith("positive_base_") and (values[1] <= 0 or values[0] < 0):
                    results.append({"metric_id": metric["id"], "subject_id": actual["subject_id"], "period": actual["period"],
                                    "window": actual["window"], "status": "non_comparable_rate", "value": None,
                                    "reason": "non_positive_baseline" if values[1] <= 0 else "negative_actual",
                                    "input_evidence_ids": [actual["id"], baseline["id"]]})
                    continue
                value = OPERATORS[metric["operator"]](*values)
                results.append({
                    "id": "calc_" + sha256((run["id"] + actual["id"] + baseline["id"] + metric["id"]).encode()).hexdigest()[:24],
                    "metric_id": metric["id"], "subject_id": actual["subject_id"], "period": actual["period"],
                    "window": actual["window"], "unit": "%" if metric["operator"].startswith("positive_base_") else actual["unit"], "budget_version": version,
                    "operator": metric["operator"], "value": str(value), "status": "calculated",
                    "input_evidence_ids": [actual["id"], baseline["id"]], "evidence_snapshot_id": snapshot["id"],
                })
        if config["analysis"].get("period_comparisons"):
            current_period = project["report_period"]
            year, month = map(int, current_period.split("-"))
            baseline_periods = {"previous_month": (date(year, month, 1) - timedelta(days=1)).strftime("%Y-%m"),
                                "previous_year_same_month": f"{year - 1:04d}-{month:02d}", "annual_plan": str(year)}
            for comparison in config["analysis"]["period_comparisons"]:
                basis = comparison["basis"]
                def matches_basis(item):
                    return item.get("basis", material_inputs[item["source_id"]]) == basis
                current_items = [item for item in evidence if matches_basis(item) and item["period"] == current_period
                                 and item.get("window") == comparison["window"] and item["metric_id"] in comparison["applies_to"]]
                for actual in current_items:
                    annual = comparison["baseline"] == "annual_plan"
                    baselines = [item for item in evidence if item.get("basis", material_inputs[item["source_id"]]) == comparison.get("baseline_basis", basis)
                                 and item["period"] == baseline_periods[comparison["baseline"]]
                                 and item.get("window") == ("annual" if annual else comparison["window"])
                                 and (not annual or item.get("budget_version") == "annual_plan")
                                 and all(item.get(key) == actual.get(key) for key in ("subject_id", "metric_id", "unit"))]
                    if not baselines:
                        results.append({"metric_id": comparison["id"], "subject_id": actual["subject_id"], "period": current_period,
                                        "window": comparison["window"], "status": "missing_comparable_baseline", "value": None})
                        continue
                    if len(baselines) != 1:
                        raise ValueError("ambiguous period comparison baseline")
                    baseline = baselines[0]
                    try:
                        values = (Decimal(actual["value"]), Decimal(baseline["value"]))
                    except (InvalidOperation, TypeError) as error:
                        raise ValueError("non-numeric period comparison evidence") from error
                    if not all(value.is_finite() for value in values):
                        raise ValueError("period comparison evidence is not finite")
                    if comparison["operator"].startswith("positive_base_") and (values[1] <= 0 or values[0] < 0):
                        results.append({"metric_id": comparison["id"], "subject_id": actual["subject_id"], "period": current_period,
                                        "window": comparison["window"], "status": "non_comparable_rate", "value": None,
                                        "reason": "non_positive_baseline" if values[1] <= 0 else "negative_actual",
                                        "input_evidence_ids": [actual["id"], baseline["id"]]})
                        continue
                    if comparison["operator"] == "remaining_monthly_target" and month == 12:
                        results.append({"metric_id": comparison["id"], "subject_id": actual["subject_id"], "period": current_period,
                                        "window": comparison["window"], "status": "no_remaining_months", "value": None,
                                        "input_evidence_ids": [actual["id"], baseline["id"]]})
                        continue
                    operands = (*values, 12 - month) if comparison["operator"] == "remaining_monthly_target" else values
                    results.append({"id": "calc_" + sha256((run["id"] + actual["id"] + baseline["id"] + comparison["id"]).encode()).hexdigest()[:24],
                                    "metric_id": comparison["id"], "subject_id": actual["subject_id"], "period": current_period,
                                    "window": comparison["window"], "unit": "%" if comparison["operator"].startswith("positive_base_") else actual["unit"], "operator": comparison["operator"],
                                    "value": str(OPERATORS[comparison["operator"]](*operands)), "status": "calculated",
                                    "input_evidence_ids": [actual["id"], baseline["id"]], "evidence_snapshot_id": snapshot["id"]})
        paired = config["analysis"].get("paired_indicators", {})
        if paired:
            prior_period = str(int(project["report_period"][:4]) - 1) + project["report_period"][4:]
            for actual in evidence:
                prefix, separator, field = actual["metric_id"].rpartition(".")
                if not separator or field not in paired or actual["period"] != project["report_period"] or actual.get("window") != "ytd":
                    continue
                baseline_metric = prefix + "." + paired[field]["prior"]
                baselines = [item for item in evidence if item["metric_id"] == baseline_metric and item["subject_id"] == actual["subject_id"]
                             and item["period"] == prior_period and item.get("window") == "ytd" and item.get("unit") == actual.get("unit")
                             and item.get("basis", material_inputs[item["source_id"]]) == actual.get("basis", material_inputs[actual["source_id"]])]
                if not baselines:
                    continue
                if len(baselines) != 1:
                    raise ValueError("ambiguous operating indicator baseline")
                baseline = baselines[0]
                values = (Decimal(actual["value"]), Decimal(baseline["value"]))
                if not all(value.is_finite() for value in values):
                    raise ValueError("operating indicator is not finite")
                for suffix, operator in (("difference", "difference"), ("rate", "positive_base_change_rate")):
                    metric_id = prefix + "." + field + "_yoy_" + suffix
                    result = {"metric_id": metric_id, "label": paired[field]["label"] + ("同比差额" if suffix == "difference" else "同比变化率"),
                              "subject_id": actual["subject_id"], "period": actual["period"], "window": actual["window"],
                              "unit": actual["unit"] if suffix == "difference" else "%", "operator": operator,
                              "input_evidence_ids": [actual["id"], baseline["id"]], "evidence_snapshot_id": snapshot["id"]}
                    if suffix == "rate" and (values[1] <= 0 or values[0] < 0):
                        result.update(status="non_comparable_rate", value=None,
                                      reason="non_positive_baseline" if values[1] <= 0 else "negative_actual")
                    else:
                        result.update(id="calc_" + sha256((run["id"] + actual["id"] + baseline["id"] + metric_id).encode()).hexdigest()[:24],
                                      status="calculated", value=str(OPERATORS[operator](*values)))
                    results.append(result)
        connection.execute("CREATE TABLE IF NOT EXISTS calculation (id TEXT PRIMARY KEY, run_id TEXT NOT NULL, data TEXT NOT NULL)")
        for result in results:
            if "id" in result:
                connection.execute("INSERT OR REPLACE INTO calculation VALUES (?, ?, ?)", (result["id"], run["id"], json.dumps(result, ensure_ascii=False)))
    return results


def _chart_records(connection: sqlite3.Connection) -> dict[str, dict]:
    if not connection.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'chart'").fetchone():
        return {}
    return {item["id"]: item for row in connection.execute("SELECT data FROM chart") if (item := json.loads(row[0]))}


def create_chart(workspace: Path, request: dict) -> dict:
    project = get_project(workspace, request["project_id"])
    run = get_run(workspace, project["id"], request["run_id"])
    title, series = request.get("title"), request.get("series")
    if run["status"] != "active" or not run.get("evidence_snapshot_id"):
        raise ValueError("chart requires an active run with frozen evidence")
    if not isinstance(title, str) or not title.strip() or len(title) > 100 or "\n" in title or "\r" in title:
        raise ValueError("chart title must be a short single line")
    if not isinstance(series, list) or not 2 <= len(series) <= 12 or any(not isinstance(item, dict) or not isinstance(item.get("label"), str) or not item["label"].strip() or len(item["label"]) > 40 or not isinstance(item.get("evidence_id"), str) for item in series):
        raise ValueError("chart requires 2 to 12 labeled evidence points")
    ids = [item["evidence_id"] for item in series]
    if len(ids) != len(set(ids)):
        raise ValueError("chart evidence points must be distinct")
    project_dir = workspace / project["id"]
    with sqlite3.connect(project_dir / "state.sqlite") as connection:
        snapshot = json.loads(connection.execute("SELECT data FROM evidence_snapshot WHERE id = ?", (run["evidence_snapshot_id"],)).fetchone()[0])
        evidence = {item["id"]: item for row in connection.execute("SELECT data FROM evidence") if (item := json.loads(row[0])) and item["id"] in ids}
        if not set(ids) <= set(snapshot["evidence_ids"]) or len(evidence) != len(ids):
            raise ValueError("chart references unconfirmed evidence")
        dimensions = {(item["subject_id"], item["metric_id"], item.get("window"), item.get("unit")) for item in evidence.values()}
        if len(dimensions) != 1:
            raise ValueError("chart evidence has incompatible subject, metric, window or unit")
        calculations = ([json.loads(row[0]) for row in connection.execute("SELECT data FROM calculation WHERE run_id = ?", (run["id"],))]
                        if connection.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'calculation'").fetchone() else [])
        if len({item["period"] for item in evidence.values()}) > 1 and any(
            not any(item.get("status") == "calculated" and ids[0] in item.get("input_evidence_ids", [])
                    and identifier in item.get("input_evidence_ids", []) for item in calculations) for identifier in ids[1:]
        ):
            raise ValueError("chart periods need registered comparable calculations")
        points = []
        for entry in series:
            item = evidence[entry["evidence_id"]]
            try:
                value = Decimal(item["value"])
            except (InvalidOperation, TypeError) as error:
                raise ValueError("chart evidence is not numeric") from error
            if not value.is_finite():
                raise ValueError("chart evidence is not finite")
            points.append({"label": entry["label"].strip(), "value": str(value)})
        materials = {item["id"]: item for row in connection.execute("SELECT data FROM material") if (item := json.loads(row[0]))}
        source_names = list(dict.fromkeys(materials[evidence[identifier]["source_id"]]["original_name"] for identifier in ids))
        labels = {item["id"]: item.get("label", item["id"]) for item in
                  run["effective_config"]["analysis"]["metrics"] + run["effective_config"]["analysis"].get("period_comparisons", [])}
        annotations = [{"id": item["id"], "metric_id": item["metric_id"], "label": item.get("label", labels.get(item["metric_id"], item["metric_id"])),
                        "value": item["value"], "unit": item["unit"]}
                       for item in calculations if item.get("status") == "calculated" and item.get("subject_id") == next(iter(dimensions))[0]
                       and set(item.get("input_evidence_ids", [])) <= set(ids) and item.get("input_evidence_ids")][:4]
        amount_display = run["effective_config"]["scenario"]["presentation"].get("amount_display")
        chart_unit = next(iter(dimensions))[3]
        if amount_display and chart_unit in UNITS:
            points = [convert_chart_point({**point, "unit": chart_unit}, amount_display["chart_unit"]) for point in points]
            chart_unit = amount_display["chart_unit"]
        if amount_display:
            annotations = [convert_chart_point(item, amount_display["chart_unit"]) for item in annotations]
        source_locations = {}
        for identifier in ids:
            item = evidence[identifier]
            name = materials[item["source_id"]]["original_name"]
            locator = re.sub(r"^sheet:([^/]+)/cell:", r"\1!", item["source_locator"])
            source_locations.setdefault(name, []).append(locator)
        source_caption = "图表数据来源：" + "；".join(
            name + "（" + "、".join(locators) + "）" for name, locators in source_locations.items()) + "。"
        spec = {"title": title.strip(), "renderer_version": CHART_RENDERER_VERSION,
                "series": [{"label": item["label"].strip(), "evidence_id": item["evidence_id"]} for item in series],
                "annotation_ids": [item["id"] for item in annotations]}
        if amount_display:
            spec["amount_display"] = amount_display
        chart_id = "chart_" + sha256((project["id"] + json.dumps(spec, ensure_ascii=False, sort_keys=True)).encode()).hexdigest()[:24]
        existing = _chart_records(connection).get(chart_id)
        if existing:
            if sha256(Path(existing["path"]).read_bytes()).hexdigest() != existing["sha256"]:
                raise ValueError("chart asset checksum mismatch")
            return existing
        assets = project_dir / "assets"
        assets.mkdir(exist_ok=True)
        path = assets / (chart_id + ".png")
        if path.exists():
            raise ValueError("chart asset already exists without a registered record")
        dimensions_value = next(iter(dimensions))
        draw_comparison(path, title.strip(), points, chart_unit or "",
                        dimensions_value[0] + " · " + evidence[ids[0]]["period"], "、".join(source_names), annotations)
        chart = {"id": chart_id, "project_id": project["id"], "created_run_id": run["id"], "title": title.strip(),
                 "series": spec["series"], "renderer_version": CHART_RENDERER_VERSION,
                 "source_evidence_ids": ids, "subject_id": next(iter(dimensions))[0], "metric_id": next(iter(dimensions))[1],
                 "period": evidence[ids[0]]["period"], "unit": chart_unit,
                 "display_series": points,
                 "source_caption": source_caption, "annotations": annotations,
                 "path": str(path), "sha256": sha256(path.read_bytes()).hexdigest()}
        connection.execute("CREATE TABLE IF NOT EXISTS chart (id TEXT PRIMARY KEY, data TEXT NOT NULL)")
        connection.execute("INSERT INTO chart VALUES (?, ?)", (chart_id, json.dumps(chart, ensure_ascii=False)))
    return chart


def _budget_material_uses(uses: object, material_ids: list[str], used_sources: set[str]) -> list[dict]:
    if not isinstance(uses, list) or len(uses) != len(material_ids):
        raise ValueError("material_uses must decide every current source")
    ids = []
    for item in uses:
        if (not isinstance(item, dict) or set(item) != {"material_id", "use", "reason"}
                or not isinstance(item["material_id"], str) or item["use"] not in ("analysis", "context", "excluded")
                or not isinstance(item["reason"], str) or not item["reason"].strip()):
            raise ValueError("material_uses needs material_id, use and reason for every source")
        ids.append(item["material_id"])
        if item["material_id"] in used_sources and item["use"] != "analysis":
            raise ValueError("material_uses source with accepted evidence must be analysis: " + item["material_id"])
    if set(ids) != set(material_ids) or len(ids) != len(set(ids)):
        raise ValueError("material_uses must decide every current source exactly once")
    return uses


def plan_draft(workspace: Path, request: dict) -> list[dict]:
    project = get_project(workspace, request["project_id"])
    with sqlite3.connect(workspace / project["id"] / "state.sqlite") as connection:
        row = connection.execute("SELECT data FROM run WHERE id = ?", (request["run_id"],)).fetchone()
        if row is None:
            raise ValueError("unknown run")
        run = json.loads(row[0])
        if run["status"] != "active" or not run.get("evidence_snapshot_id"):
            raise ValueError("draft requires an active run with frozen evidence")
        if not run.get("report_plan") and ("outline" not in request or "report_request" not in request):
            raise ValueError("report_request and outline are required for the first draft plan")
        if (project["scenario_id"] == "budget_operations" or run["effective_config"]["quality"].get("financial_quality")) and run.get("report_plan") and "outline" not in request and "report_request" not in request:
            uses = run["report_plan"].get("material_uses")
            if not isinstance(uses, list) or any(not isinstance(item, dict) for item in uses) or {item.get("material_id") for item in uses} != set(run["material_ids"]):
                raise ValueError("material_uses changed; submit a new report plan")
        if "outline" in request or "report_request" in request:
            if not isinstance(request.get("report_request"), str) or not request["report_request"].strip():
                raise ValueError("report_request is required with a report outline")
            calculated_metric_ids = ({item["metric_id"] for row in connection.execute("SELECT data FROM calculation WHERE run_id = ?", (run["id"],))
                                      if (item := json.loads(row[0]))["status"] == "calculated"}
                                     if connection.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'calculation'").fetchone() else set())
            outline = validate_report_outline(request.get("outline"), run["effective_config"]["analysis"],
                                              project["subject_scope"], calculated_metric_ids,
                                              fixed_outline=project["effective_config"]["outline"])
            proposed = {"request": request["report_request"].strip(), "outline": outline}
            if project["scenario_id"] == "budget_operations":
                units = project["subject_scope"]["units"]
                if run["effective_config"]["quality"]["require_full_unit_scope"] and (
                    outline["unit_names"] != units or units and not any(section["repeat_for"] == "unit" for section in outline["sections"])
                ):
                    raise ValueError("report outline must cover all project units with a repeated unit section")
                snapshot = json.loads(connection.execute("SELECT data FROM evidence_snapshot WHERE id = ?", (run["evidence_snapshot_id"],)).fetchone()[0])
                used_sources = {json.loads(row[0])["source_id"] for row in connection.execute("SELECT data FROM evidence")
                                if json.loads(row[0])["id"] in snapshot["evidence_ids"]}
                proposed["material_uses"] = _budget_material_uses(request.get("material_uses"), run["material_ids"], used_sources)
            if project["scenario_id"] == "financial_due_diligence" and run["effective_config"]["quality"].get("financial_quality"):
                snapshot = json.loads(connection.execute("SELECT data FROM evidence_snapshot WHERE id = ?", (run["evidence_snapshot_id"],)).fetchone()[0])
                used_sources = {json.loads(row[0])["source_id"] for row in connection.execute("SELECT data FROM evidence")
                                if json.loads(row[0])["id"] in snapshot["evidence_ids"]}
                proposed["material_uses"] = _budget_material_uses(request.get("material_uses"), run["material_ids"], used_sources)
            if run.get("report_plan") != proposed:
                planned_tasks = (connection.execute("SELECT 1 FROM section_task WHERE run_id = ? LIMIT 1", (run["id"],)).fetchone()
                                 if connection.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'section_task'").fetchone() else None)
                if planned_tasks or run.get("report_plan") and not run.get("base_revision_id"):
                    raise ValueError("report plan is frozen after chapter tasks are created; start a revision to add requirements")
                run["report_plan"] = proposed
                run["report_request"] = proposed["request"]
                run["effective_config"]["outline"] = outline
                run["effective_config"]["quality"]["required_sections"] = [section["id"] for section in outline["sections"]]
                run["effective_config_fingerprint"] = sha256((project["effective_config_fingerprint"] + json.dumps(proposed, ensure_ascii=False, sort_keys=True)).encode()).hexdigest()
                connection.execute("UPDATE run SET data = ? WHERE id = ?", (json.dumps(run, ensure_ascii=False), run["id"]))
        connection.execute("CREATE TABLE IF NOT EXISTS section_task (id TEXT PRIMARY KEY, run_id TEXT NOT NULL, data TEXT NOT NULL)")
        existing = [json.loads(item[0]) for item in connection.execute("SELECT data FROM section_task WHERE run_id = ?", (run["id"],))]
        if existing:
            return sorted(existing, key=lambda item: item["display_order"])
        outline = run["effective_config"]["outline"]["sections"]
        expanded = {}
        for section in outline:
            subjects = run["effective_config"]["outline"].get("unit_names", project["subject_scope"]["units"]) if section["repeat_for"] == "unit" else [None]
            expanded[section["id"]] = [section["id"] + ":" + subject if subject else section["id"] for subject in subjects]
        tasks = []
        for section in outline:
            for index, section_id in enumerate(expanded[section["id"]]):
                subject = section_id.split(":", 1)[1] if section["repeat_for"] == "unit" else None
                dependencies = [item for dependency in section["depends_on"] for item in expanded[dependency]]
                task = {
                    "id": uuid4().hex, "run_id": run["id"], "section_id": section_id,
                    "title": section["title"] if subject is None else subject,
                    "subject_id": subject, "depends_on": dependencies,
                    "display_order": [section["display_order"], index],
                    "status": "blocked" if dependencies else "ready",
                    "evidence_snapshot_id": run["evidence_snapshot_id"],
                }
                tasks.append(task)
        reused_bodies = {}
        if run["base_revision_id"]:
            revision = json.loads(connection.execute("SELECT data FROM revision WHERE id = ?", (run["base_revision_id"],)).fetchone()[0])
            base_run = json.loads(connection.execute("SELECT data FROM run WHERE id = ?", (revision["run_id"],)).fetchone()[0])
            base_tasks = {item["section_id"]: item for row in connection.execute("SELECT data FROM section_task WHERE run_id = ?", (base_run["id"],)) if (item := json.loads(row[0]))}
            bodies = {row[0]: row[1] for row in connection.execute("SELECT task_id, body FROM section_body")}
            old_snapshot = json.loads(connection.execute("SELECT data FROM evidence_snapshot WHERE id = ?", (base_run["evidence_snapshot_id"],)).fetchone()[0])
            new_snapshot = json.loads(connection.execute("SELECT data FROM evidence_snapshot WHERE id = ?", (run["evidence_snapshot_id"],)).fetchone()[0])
            old_ids, new_ids = set(old_snapshot["evidence_ids"]), set(new_snapshot["evidence_ids"])
            charts = _chart_records(connection)
            changed_ids = old_ids ^ new_ids
            changed_evidence = [item for row in connection.execute("SELECT data FROM evidence") if (item := json.loads(row[0]))["id"] in changed_ids]
            changed_subjects = {item["subject_id"] for item in changed_evidence}
            old_calculations = {item["id"]: item for row in connection.execute("SELECT data FROM calculation WHERE run_id = ?", (base_run["id"],)) if (item := json.loads(row[0]))}
            new_calculations = [json.loads(row[0]) for row in connection.execute("SELECT data FROM calculation WHERE run_id = ?", (run["id"],))]
            def calculation_key(item):
                return item["metric_id"], item["subject_id"], item["period"], item.get("window"), tuple(item.get("input_evidence_ids", item.get("source_ids", []))), item["value"], item.get("financial_scope"), item.get("financial_version"), item.get("period_start"), item.get("period_days"), item.get("formula_version"), item.get("unit")
            new_calculation_ids = {calculation_key(item): item["id"] for item in new_calculations if item.get("status") == "calculated"}
            changed_material_ids = set(run["material_ids"]) ^ set(base_run["material_ids"])
            changed_roles = {role for material_id in changed_material_ids for role in run["material_input_ids"].get(material_id, base_run["material_input_ids"].get(material_id, []))}
            selectors = {item["id"]: item["input"] for item in run["effective_config"]["analysis"]["evidence_selectors"]}
            definitions = {item["id"]: item for item in outline}
            previous_definitions = {item["id"]: item for item in base_run["effective_config"]["outline"]["sections"]}
            dirty = set()
            for task in tasks:
                section_id = task["section_id"].split(":", 1)[0]
                prior = base_tasks.get(task["section_id"])
                body = bodies.get(prior["id"]) if prior else None
                if body is None or definitions[section_id] != previous_definitions.get(section_id) or any(identifier not in new_ids for identifier in re.findall(r"\{\{(?:fact|ev):([^}|]+)", body)) or any(identifier not in charts or not set(charts[identifier]["source_evidence_ids"]) <= new_ids for identifier in re.findall(CHART_REFERENCE, body)):
                    dirty.add(task["section_id"])
                    continue
                calc_refs = re.findall(r"\{\{calc:([^}|]+)", body)
                if any(identifier not in old_calculations or calculation_key(old_calculations[identifier]) not in new_calculation_ids for identifier in calc_refs):
                    dirty.add(task["section_id"])
                    continue
                if task["subject_id"] in changed_subjects or section_id == "special" and changed_subjects.intersection(project["subject_scope"].get("special_subjects", [])) or section_id == "group" and project["subject_scope"].get("organization") in changed_subjects:
                    dirty.add(task["section_id"])
                elif not project["subject_scope"].get("units") and any(selectors[reference] in changed_roles for reference in definitions[section_id]["evidence_refs"]):
                    dirty.add(task["section_id"])
                reused_bodies[task["section_id"]] = re.sub(r"\{\{calc:([^}|]+)(\|[0-6])?\}\}", lambda match: "{{calc:" + new_calculation_ids[calculation_key(old_calculations[match[1]])] + (match[2] or "") + "}}", body)
            affected = set(dirty)
            while True:
                expanded_affected = affected | {task["section_id"] for task in tasks if set(task["depends_on"]) & affected}
                if expanded_affected == affected:
                    break
                affected = expanded_affected
            if set(run["material_ids"]) != set(base_run["material_ids"]):
                affected.update(task["section_id"] for task in tasks if task["section_id"] in ("scope", "sources", "appendix"))
            locked_conflicts = affected.intersection(run.get("locked_sections", []))
            if locked_conflicts:
                raise ValueError("locked section conflict: " + ", ".join(sorted(locked_conflicts)))
            for task in tasks:
                if task["section_id"] not in affected:
                    task.update(status="submitted", author_id=base_tasks[task["section_id"]]["author_id"], reused_from_task_id=base_tasks[task["section_id"]]["id"])
        connection.execute("CREATE TABLE IF NOT EXISTS section_body (task_id TEXT PRIMARY KEY, body TEXT NOT NULL)")
        submitted = {task["section_id"] for task in tasks if task["status"] == "submitted"}
        for task in tasks:
            if task["status"] == "blocked" and set(task["depends_on"]) <= submitted:
                task["status"] = "ready"
            connection.execute("INSERT INTO section_task VALUES (?, ?, ?)", (task["id"], run["id"], json.dumps(task, ensure_ascii=False)))
            if task["status"] == "submitted":
                connection.execute("INSERT INTO section_body VALUES (?, ?)", (task["id"], reused_bodies[task["section_id"]]))
    return tasks


def get_draft_context(workspace: Path, project_id: str, task_id: str) -> dict:
    project = get_project(workspace, project_id)
    with sqlite3.connect(workspace / project["id"] / "state.sqlite") as connection:
        row = connection.execute("SELECT data FROM section_task WHERE id = ?", (task_id,)).fetchone()
        if row is None:
            raise ValueError("unknown section task")
        task = json.loads(row[0])
        run = json.loads(connection.execute("SELECT data FROM run WHERE id = ?", (task["run_id"],)).fetchone()[0])
        snapshot = json.loads(connection.execute("SELECT data FROM evidence_snapshot WHERE id = ?", (task["evidence_snapshot_id"],)).fetchone()[0])
        evidence = [json.loads(item[0]) for item in connection.execute("SELECT data FROM evidence")]
        calculations = [json.loads(item[0]) for item in connection.execute("SELECT data FROM calculation WHERE run_id = ?", (run["id"],))]
        materials = {item["id"]: item["original_name"] for row in connection.execute("SELECT data FROM material") if (item := json.loads(row[0]))}
        scope_exclusions = [{**entry, "source_id": item["source_id"]}
                            for row in connection.execute("SELECT data FROM task WHERE run_id = ?", (run["id"],))
                            if (item := json.loads(row[0])).get("kind") == "extract_candidate_facts"
                            for entry in item.get("scope_exclusions", [])]
    evidence = [item for item in evidence if item["id"] in snapshot["evidence_ids"] and (task["subject_id"] is None or item["subject_id"] == task["subject_id"])]
    calculations = [item for item in calculations if task["subject_id"] is None or item["subject_id"] == task["subject_id"]]
    section_id = task["section_id"].split(":", 1)[0]
    section = next(item for item in run["effective_config"]["outline"]["sections"] if item["id"] == section_id)
    return {"task": task, "section": section, "run_id": run["id"], "evidence": evidence, "calculations": calculations, "gaps": snapshot,
            "material_uses": [{**item, "original_name": materials[item["material_id"]]} for item in run.get("report_plan", {}).get("material_uses", [])],
            "scope_exclusions": scope_exclusions,
            "writing_guidance": run["effective_config"]["analysis"].get("writing_guidance", {}),
            "amount_display": run["effective_config"]["scenario"]["presentation"].get("amount_display"),
            "quality_rules": run["effective_config"]["quality"]}


def submit_draft(workspace: Path, request: dict) -> dict:
    context = get_draft_context(workspace, request["project_id"], request["task_id"])
    task = context["task"]
    replacing = request.get("replace") is True
    body = request["body"]
    if not isinstance(body, str) or not body.strip():
        raise ValueError("section body is required")
    validate_section_headings(body, context["section"])
    if context["quality_rules"].get("financial_quality"):
        validate_financial_body(body, context["section"])
    if re.search(r"!\[[^\]]*\]\([^)]+\)", body):
        raise ValueError("report images must use a registered chart reference")
    if re.search(r"(?<![\w.])\d+(?:\.\d+)?\s*(?:万|亿)?元", body):
        raise ValueError("monetary number must use an evidence or calculation reference")
    project = get_project(workspace, request["project_id"])
    if project["scenario_id"] == "compensation_analysis":
        with sqlite3.connect(workspace / project["id"] / "state.sqlite") as connection:
            run = json.loads(connection.execute("SELECT data FROM run WHERE id = ?", (request["run_id"],)).fetchone()[0])
            materials = [json.loads(row[0]) for row in connection.execute("SELECT data FROM material")]
        if any(re.search(r"(?<![A-Za-z0-9])" + re.escape(term) + r"(?![A-Za-z0-9])", body) for term in private_terms(run, materials)):
            raise ValueError("section exposes a payroll person identifier")
    if not isinstance(request.get("author_id"), str) or not request["author_id"].strip():
        raise ValueError("section author_id is required")
    if task["run_id"] == request["run_id"] and task["status"] == "submitted" and not replacing:
        with sqlite3.connect(workspace / request["project_id"] / "state.sqlite") as connection:
            existing = connection.execute("SELECT body FROM section_body WHERE task_id = ?", (task["id"],)).fetchone()
        if existing and existing[0] == body and task.get("author_id") == request["author_id"]:
            return task
    if task["run_id"] != request["run_id"] or task["status"] != ("submitted" if replacing else "ready"):
        raise ValueError("section depends on unfinished work or is already submitted")
    references = re.findall(REFERENCE, body)
    permitted = {"calc": {item["id"] for item in context["calculations"] if item["status"] == "calculated"}, "ev": {item["id"] for item in context["evidence"]}, "fact": {item["id"] for item in context["evidence"]}}
    chart_ids = re.findall(CHART_REFERENCE, body)
    with sqlite3.connect(workspace / project["id"] / "state.sqlite") as connection:
        charts = _chart_records(connection)
        run = json.loads(connection.execute("SELECT data FROM run WHERE id = ?", (task["run_id"],)).fetchone()[0])
        snapshot = json.loads(connection.execute("SELECT data FROM evidence_snapshot WHERE id = ?", (run["evidence_snapshot_id"],)).fetchone()[0])
    if any(identifier not in charts or not set(charts[identifier]["source_evidence_ids"]) <= set(snapshot["evidence_ids"]) or sha256(Path(charts[identifier]["path"]).read_bytes()).hexdigest() != charts[identifier]["sha256"] for identifier in chart_ids):
        raise ValueError("section has stale or unregistered chart reference")
    if project["scenario_id"] == "budget_operations" and task["subject_id"] and any(item["metric_id"] == "profit_total" for item in context["evidence"]):
        tables = re.findall(r"(?m)^\|[^\n]+\|\n\|[ :|\-]+\|(?:\n\|[^\n]+\|)*", body)
        if not tables or "利润" not in tables[0]:
            raise ValueError("budget unit requires its own profit comparison table")
        if len(tables) < 2 or not any(term in table for table in tables[1:] for term in ("经营指标", "数据缺口", "产量", "销量", "成本")):
            raise ValueError("budget unit requires an operating indicator or data gap table")
        comparable = any(item["metric_id"] in ("budget_difference", "month_change", "ytd_change") and item["status"] == "calculated" for item in context["calculations"])
        unit_charts = [charts[identifier] for identifier in chart_ids if charts[identifier].get("subject_id") == task["subject_id"]]
        if comparable and not unit_charts:
            raise ValueError("budget unit requires its own comparable chart")
        if comparable and not any(chart.get("annotations") for chart in unit_charts):
            raise ValueError("budget unit chart requires registered calculation annotations")
        rates = [item for item in context["calculations"] if item["status"] == "calculated" and item["metric_id"] in
                 ("budget_completion_rate", "month_change_rate", "ytd_change_rate", "annual_plan_completion_rate")]
        if rates and not any(item["id"] in [value for kind, value, _ in references if kind == "calc"] for item in rates):
            raise ValueError("budget unit requires a calculated rate in the analysis")
        rules = context["quality_rules"]
        profit_calculations = [item for item in context["calculations"] if item["status"] == "calculated"
                               and item["metric_id"] in rules["unit_required_calculations"]]
        if any("{{calc:" + item["id"] not in tables[0] for item in profit_calculations):
            raise ValueError("budget unit profit table omits an available monthly, ytd or plan comparison")
        operating = [item for item in context["calculations"] if item["status"] == "calculated" and "." in item["metric_id"]]
        detailed = bool(operating)
        required_operating = min(len(operating), rules["unit_min_operating_calculations"])
        if detailed and len({item["id"] for item in operating if any("{{calc:" + item["id"] in table for table in tables[1:])}) < required_operating:
            raise ValueError("budget unit operating table omits calculated source indicators")
        narrative = body
        for table in tables:
            narrative = narrative.replace(table, "")
        if detailed:
            for label in rules["unit_required_blocks"]:
                if label not in body:
                    raise ValueError("budget unit analysis block missing: " + label)
            if len({item["id"] for item in operating if "{{calc:" + item["id"] in narrative}) < min(len(operating), rules["unit_min_operating_narrative_calculations"]):
                raise ValueError("budget unit operating analysis needs calculated evidence")
        for family in rules["unit_evidence_families"]:
            family_evidence = [item for item in context["evidence"] if item["metric_id"].startswith(tuple(family["prefixes"]))]
            if not family_evidence:
                continue
            family_calculations = [item for item in operating if item["metric_id"].startswith(tuple(family["prefixes"]))]
            kind, identifiers = ("calc", [item["id"] for item in family_calculations]) if family_calculations else ("fact", [item["id"] for item in family_evidence])
            if not any("{{" + kind + ":" + identifier in table for identifier in identifiers for table in tables[1:]) or not any(
                "{{" + kind + ":" + identifier in narrative for identifier in identifiers
            ) or not any("{{ev:" + item["id"] in body for item in family_evidence):
                raise ValueError("budget unit omits available evidence family: " + family["id"])
        if detailed and rules["unit_requires_source_citations"]:
            citations = {value for kind, value, _ in references if kind == "ev"}
            profit_sources = {item["id"] for item in context["evidence"] if item["metric_id"] == "profit_total"}
            operating_sources = {item["id"] for item in context["evidence"] if item["metric_id"] != "profit_total"}
            if not citations & profit_sources or operating_sources and not citations & operating_sources:
                raise ValueError("budget unit needs profit and operating source locations")
        if detailed and rules["unit_requires_numbered_tables_and_chart"]:
            first, second = body.find(tables[0]), body.find(tables[1])
            if not re.search(r"(?m)^表\d+-\d+[^\n]*利润", body[:first]) or not re.search(r"(?m)^表\d+-\d+[^\n]*(经营|成本|指标|缺口)", body[:second]):
                raise ValueError("budget unit tables need numbered captions")
            if comparable and not any(re.match(r"^图\d+-\d+", chart["title"]) and first < body.find("{{chart:" + chart["id"] + "}}") < second for chart in unit_charts):
                raise ValueError("budget unit needs a numbered chart between its profit and operating tables")
    if any(value not in permitted[kind] or kind == "ev" and precision for kind, value, precision in references) or "{{" in re.sub(CHART_REFERENCE, "", re.sub(REFERENCE, "", body)):
        raise ValueError("section has unknown or malformed evidence/calculation reference")
    database = workspace / request["project_id"] / "state.sqlite"
    with sqlite3.connect(database) as connection:
        run = json.loads(connection.execute("SELECT data FROM run WHERE id = ?", (task["run_id"],)).fetchone()[0])
        if run["status"] != "active" or run["evidence_snapshot_id"] != task["evidence_snapshot_id"]:
            raise ValueError("stale section task")
        current = json.loads(connection.execute("SELECT data FROM section_task WHERE id = ?", (task["id"],)).fetchone()[0])
        if current["status"] != ("submitted" if replacing else "ready"):
            raise ValueError("section task already changed")
        if replacing:
            connection.execute("CREATE TABLE IF NOT EXISTS review (run_id TEXT PRIMARY KEY, data TEXT NOT NULL)")
            if current.get("author_id") != request["author_id"] or connection.execute("SELECT 1 FROM review WHERE run_id = ?", (run["id"],)).fetchone():
                raise ValueError("reviewed section or different author cannot replace draft")
        connection.execute("CREATE TABLE IF NOT EXISTS section_body (task_id TEXT PRIMARY KEY, body TEXT NOT NULL)")
        if replacing:
            connection.execute("UPDATE section_body SET body = ? WHERE task_id = ?", (body, task["id"]))
            if task.get("reused_from_task_id"):
                task["edited_from_task_id"] = task.pop("reused_from_task_id")
        else:
            connection.execute("INSERT INTO section_body VALUES (?, ?)", (task["id"], body))
        task["status"] = "submitted"
        task["author_id"] = request["author_id"]
        connection.execute("UPDATE section_task SET data = ? WHERE id = ?", (json.dumps(task, ensure_ascii=False), task["id"]))
        tasks = [json.loads(row[0]) for row in connection.execute("SELECT data FROM section_task WHERE run_id = ?", (run["id"],))]
        submitted_ids = {item["section_id"] for item in tasks if item["status"] == "submitted"}
        for item in tasks:
            if item["status"] == "blocked" and set(item["depends_on"]) <= submitted_ids:
                item["status"] = "ready"
                connection.execute("UPDATE section_task SET data = ? WHERE id = ?", (json.dumps(item, ensure_ascii=False), item["id"]))
    return task


def _number_budget_headings(markdown: str, unit_names: list[str] | None = None) -> str:
    counters, lines = [0, 0, 0], []
    digits = "零一二三四五六七八九"
    units, has_second_level = set(unit_names or []), False
    for line in markdown.splitlines():
        match = re.fullmatch(r"(#{1,3}) (.+)", line)
        if match:
            level, title = len(match[1]), match[2]
            if level == 1:
                has_second_level = False
            elif level == 2:
                has_second_level = True
            elif (not has_second_level and title not in units
                  and not re.match(r"^[0-9]+(?:\.[0-9]+)*[ .、．]", title)):
                level, line = 2, "## " + title
            for parent in range(level - 1):
                if not counters[parent]:
                    counters[parent] = 1
            counters[level - 1] += 1
            counters[level:] = [0] * (3 - level)
            chapter = re.match(r"^第([零〇一二三四五六七八九十百千万0-9]+)章", title)
            path = re.match(r"^([0-9]+(?:\.[0-9]+)*)(?:[ .、．]|$)", title)
            if level == 1 and chapter:
                label = chapter[1].replace("〇", "零")
                if label.isascii() and label.isdigit():
                    counters[0] = int(label)
                elif not any(character in "十百千万" for character in label):
                    counters[0] = int("".join(str(digits.index(character)) for character in label))
                else:
                    total, value = 0, 0
                    for character in label:
                        if character in digits:
                            value = digits.index(character)
                        elif character == "万":
                            total, value = (total + value) * 10000, 0
                        else:
                            total, value = total + (value or 1) * {"十": 10, "百": 100, "千": 1000}[character], 0
                    counters[0] = total + value
            elif path and len(path[1].split(".")) == level:
                counters[:level] = map(int, path[1].split("."))
            if not (chapter or path or title.startswith("附录")):
                if level == 1:
                    number = counters[0]
                    ordinal = (digits[number] if number < 10 else
                               ("十" if number // 10 == 1 else digits[number // 10] + "十") + (digits[number % 10] if number % 10 else "")
                               if number < 100 else str(number))
                    prefix = f"第{ordinal}章"
                else:
                    prefix = ".".join(map(str, counters[:level]))
                line = f"{'#' * level} {prefix} {title}"
        lines.append(line)
    return "\n".join(lines) + ("\n" if markdown.endswith("\n") else "")


def build_draft(workspace: Path, request: dict) -> dict:
    project = get_project(workspace, request["project_id"])
    project_dir = workspace / project["id"]
    with sqlite3.connect(project_dir / "state.sqlite") as connection:
        row = connection.execute("SELECT data FROM run WHERE id = ?", (request["run_id"],)).fetchone()
        if row is None:
            raise ValueError("unknown run")
        run = json.loads(row[0])
        if run["status"] != "active" or not run.get("evidence_snapshot_id"):
            raise ValueError("run cannot build a draft")
        tasks = [json.loads(item[0]) for item in connection.execute("SELECT data FROM section_task WHERE run_id = ?", (run["id"],))]
        if not tasks or any(task["status"] != "submitted" for task in tasks):
            raise ValueError("required sections remain unfinished")
        bodies = {row[0]: row[1] for row in connection.execute("SELECT task_id, body FROM section_body")}
        calculations = {item["id"]: item for row in connection.execute("SELECT data FROM calculation WHERE run_id = ?", (run["id"],)) if (item := json.loads(row[0]))}
        evidence = {item["id"]: item for row in connection.execute("SELECT data FROM evidence") if (item := json.loads(row[0]))}
        materials = {item["id"]: item for row in connection.execute("SELECT data FROM material") if (item := json.loads(row[0]))}
        charts = _chart_records(connection)
    parts = []
    amount_display = run["effective_config"]["scenario"]["presentation"].get("amount_display")
    section_defs = {item["id"]: item for item in run["effective_config"]["outline"]["sections"]}
    for task in sorted(tasks, key=lambda item: item["display_order"]):
        section_id = task["section_id"].split(":", 1)[0]
        section = section_defs[section_id]
        if task["subject_id"] is None:
            parts.append(f"# {section['title']}")
        else:
            if not parts or parts[-1] != f"# {section['title']}":
                if not any(part == f"# {section['title']}" for part in parts):
                    parts.append(f"# {section['title']}")
            level = run["effective_config"]["outline"].get("unit_levels", {}).get(task["subject_id"], 2)
            parts.append(f"{'#' * level} {task['subject_id']}")

        def replace(match):
            kind, identifier, precision = match.group(1, 2, 3)
            suffix = (match[4] or "") if amount_display else ""
            if kind in ("calc", "fact") and identifier in (calculations if kind == "calc" else evidence):
                item = (calculations if kind == "calc" else evidence)[identifier]
                if amount_display and (shown := display_amount(item, amount_display, medium, precision or None)):
                    return shown[0] + ("" if medium == "table" and table_has_unit else shown[1])
                value = item["value"]
                return (format(Decimal(value).quantize(Decimal(1).scaleb(-int(precision)), rounding=ROUND_HALF_UP), "f") if precision else value) + suffix
            if kind == "ev" and identifier in evidence:
                item = evidence[identifier]
                return f"〔来源：{materials[item['source_id']]['original_name']}，{item['source_locator']}〕" + suffix
            raise ValueError(f"missing report reference: {identifier}")

        if run["effective_config"]["quality"].get("financial_quality"):
            validate_financial_body(bodies[task["id"]], section)
        if amount_display:
            blocks = []
            raw_blocks = bodies[task["id"]].split("\n\n")
            for index, block in enumerate(raw_blocks):
                medium = "table" if markdown_table_rows(block) is not None else "text"
                table_has_unit = medium == "table" and bool(re.search(r"[（(](?:亿元|万元|元)[）)]|单位[：:]\s*(?:亿元|万元|元)", block.splitlines()[0]))
                if medium == "table":
                    header, rest = block.split("\n", 1)
                    header = re.sub(r"([（(])(?:亿元|万元|元)([）)])", lambda m: m[1] + amount_display["table_unit"] + m[2], header)
                    header = re.sub(r"(单位[：:]\s*)(?:亿元|万元|元)", lambda m: m[1] + amount_display["table_unit"], header)
                    block = header + "\n" + rest
                elif index + 1 < len(raw_blocks) and markdown_table_rows(raw_blocks[index + 1]) is not None:
                    block = re.sub(r"(单位[：:]\s*)(?:亿元|万元|元)(?![/／])", lambda m: m[1] + amount_display["table_unit"], block)
                blocks.append(re.sub(REFERENCE + r"([ \t]*(?:亿元|万元|元)(?![/／]))?", replace, block))
            rendered = "\n\n".join(blocks)
        else:
            rendered = re.sub(REFERENCE, replace, bodies[task["id"]])
        def replace_chart(match):
            chart = charts[match[1]]
            point = evidence[chart["source_evidence_ids"][0]]
            year, month = chart["period"].split("-")[:2]
            period = (chart["period"] if len(chart["period"]) == 10 else
                      f"{year}年1—{int(month)}月" if point.get("window") == "ytd" else f"{year}年{int(month)}月")
            source_text = json.dumps([materials[evidence[identifier]["source_id"]]["parsed"]
                                      for identifier in chart["source_evidence_ids"]], ensure_ascii=False)
            nature = "含MOCK模拟数据" if re.search(r"(?i)\bMOCK\b|模拟数据|模拟报表", source_text) else "数据性质以原件标识为准"
            caption = f"{chart['title']}（统计期间：{period}；单位：{chart['unit']}；{nature}）"
            return f"![{caption}](assets/{chart['id']}.png)\n\n{chart.get('source_caption', '')}"
        rendered = re.sub(CHART_REFERENCE, replace_chart, rendered)
        validate_section_headings(rendered, section)
        parts.append(rendered)
    content = "\n\n".join(parts) + "\n"
    if project["scenario_id"] == "budget_operations":
        content = _number_budget_headings(content, project["subject_scope"]["units"])
    output = project_dir / "runs" / run["id"] / "draft" / "full_report.md"
    output.parent.mkdir(parents=True, exist_ok=True)
    for identifier in set(re.findall(r"!\[[^\]]*\]\(assets/(chart_[0-9a-f]{24})\.png\)", content)):
        chart = charts[identifier]
        source = Path(chart["path"])
        if sha256(source.read_bytes()).hexdigest() != chart["sha256"]:
            raise ValueError("chart asset checksum mismatch")
        (output.parent / "assets").mkdir(exist_ok=True)
        shutil.copyfile(source, output.parent / "assets" / (identifier + ".png"))
    temporary = output.with_suffix(".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(output)
    result = {"run_id": run["id"], "status": "candidate", "markdown_path": str(output), "sha256": sha256(content.encode()).hexdigest()}
    if run["effective_config"]["quality"].get("financial_quality"):
        result["review_requirements"] = review_requirements(content, run["effective_config"]["outline"])
        with sqlite3.connect(project_dir / "state.sqlite") as connection:
            run["draft_sha256"] = result["sha256"]
            run["section_body_sha256"] = {task["id"]: sha256(bodies[task["id"]].encode()).hexdigest() for task in tasks}
            connection.execute("UPDATE run SET data = ? WHERE id = ?", (json.dumps(run, ensure_ascii=False), run["id"]))
    return result


def submit_review(workspace: Path, request: dict) -> dict:
    project = get_project(workspace, request["project_id"])
    reviewer = request.get("reviewer_id")
    if not isinstance(reviewer, str) or not reviewer.strip() or request.get("verdict") not in ("pass", "fail") or not isinstance(request.get("issues"), list):
        raise ValueError("review requires reviewer, verdict and issues")
    draft = workspace / project["id"] / "runs" / request["run_id"] / "draft" / "full_report.md"
    if not draft.is_file() or sha256(draft.read_bytes()).hexdigest() != request["draft_sha256"]:
        raise ValueError("review references a stale or missing draft")
    with sqlite3.connect(workspace / project["id"] / "state.sqlite") as connection:
        row = connection.execute("SELECT data FROM run WHERE id = ?", (request["run_id"],)).fetchone()
        if row is None or json.loads(row[0])["status"] != "active":
            raise ValueError("run is not active")
        tasks = [json.loads(item[0]) for item in connection.execute("SELECT data FROM section_task WHERE run_id = ?", (request["run_id"],))]
        if not tasks or any(task["status"] != "submitted" for task in tasks) or reviewer in {task.get("author_id") for task in tasks}:
            raise ValueError("review must be independent of completed section authors")
        run = json.loads(row[0])
        if run["effective_config"]["quality"].get("financial_quality"):
            snapshot = json.loads(connection.execute("SELECT data FROM evidence_snapshot WHERE id = ?", (run["evidence_snapshot_id"],)).fetchone()[0])
            permitted = set(snapshot["evidence_ids"])
            permitted.update(json.loads(row[0])["id"] for row in connection.execute("SELECT data FROM calculation WHERE run_id = ?", (run["id"],))
                             if json.loads(row[0])["status"] == "calculated")
            content = draft.read_text(encoding="utf-8")
            validate_review_coverage(request.get("coverage"), review_requirements(content, run["effective_config"]["outline"]), content, permitted)
            if request["verdict"] == "pass" and any(item["result"] == "needs_changes" for item in request["coverage"]):
                raise ValueError("passing review cannot have unresolved coverage findings")
        if request["verdict"] == "pass" and request["issues"]:
            raise ValueError("passing review cannot have open issues")
        connection.execute("CREATE TABLE IF NOT EXISTS review (run_id TEXT PRIMARY KEY, data TEXT NOT NULL)")
        previous = connection.execute("SELECT data FROM review WHERE run_id = ?", (request["run_id"],)).fetchone()
        if previous:
            saved = json.loads(previous[0])
            if all(saved[key] == request[key] for key in ("draft_sha256", "reviewer_id", "verdict", "issues")) and saved.get("coverage") == request.get("coverage"):
                return saved
            raise ValueError("review already submitted with different content")
        review = {"id": uuid4().hex, "run_id": request["run_id"], "draft_sha256": request["draft_sha256"],
                  "reviewer_id": reviewer, "verdict": request["verdict"], "issues": request["issues"]}
        if "coverage" in request:
            review["coverage"] = request["coverage"]
        connection.execute("INSERT INTO review VALUES (?, ?)", (review["run_id"], json.dumps(review, ensure_ascii=False)))
    return review


def validate_run(workspace: Path, request: dict) -> dict:
    project = get_project(workspace, request["project_id"])
    project_dir = workspace / project["id"]
    with sqlite3.connect(project_dir / "state.sqlite") as connection:
        row = connection.execute("SELECT data FROM run WHERE id = ?", (request["run_id"],)).fetchone()
        if row is None:
            raise ValueError("unknown run")
        run = json.loads(row[0])
        connection.execute("CREATE TABLE IF NOT EXISTS review (run_id TEXT PRIMARY KEY, data TEXT NOT NULL)")
        review_row = connection.execute("SELECT data FROM review WHERE run_id = ?", (run["id"],)).fetchone()
        review = json.loads(review_row[0]) if review_row else None
        tasks = [json.loads(item[0]) for item in connection.execute("SELECT data FROM section_task WHERE run_id = ?", (run["id"],))]
        run_tasks = [json.loads(row[0]) for row in connection.execute("SELECT data FROM task WHERE run_id = ?", (run["id"],))]
        retrieval_tasks = [item for item in run_tasks if item["kind"] == "retrieve"]
        scope_exclusions = [{**entry, "source_id": item["source_id"]} for item in run_tasks
                            if item["kind"] == "extract_candidate_facts" for entry in item.get("scope_exclusions", [])]
        snapshot = None
        if run.get("evidence_snapshot_id"):
            snapshot = json.loads(connection.execute("SELECT data FROM evidence_snapshot WHERE id = ?", (run["evidence_snapshot_id"],)).fetchone()[0])
        materials = [json.loads(row[0]) for row in connection.execute("SELECT data FROM material")]
        charts = _chart_records(connection)
        if project["scenario_id"] == "budget_operations":
            evidence = {item["id"]: item for row in connection.execute("SELECT data FROM evidence")
                        if (item := json.loads(row[0]))["id"] in (snapshot["evidence_ids"] if snapshot else [])}
            calculations = ({item["id"]: item for row in connection.execute("SELECT data FROM calculation WHERE run_id = ?", (run["id"],))
                             if (item := json.loads(row[0])).get("id")}
                            if connection.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'calculation'").fetchone() else {})
            bodies = {item["section_id"]: connection.execute("SELECT body FROM section_body WHERE task_id = ?", (item["id"],)).fetchone()
                      for item in tasks if item["status"] == "submitted"}
    draft = project_dir / "runs" / run["id"] / "draft" / "full_report.md"
    draft_hash = sha256(draft.read_bytes()).hexdigest() if draft.is_file() else None
    images = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", draft.read_text(encoding="utf-8")) if draft_hash is not None else []
    required = set(run["effective_config"]["quality"]["required_sections"])
    present = {task["section_id"].split(":", 1)[0] for task in tasks if task["status"] == "submitted"}
    checks = {
        "evidence_frozen": snapshot is not None,
        "required_sections": required <= present and bool(tasks) and all(task["status"] == "submitted" for task in tasks),
        "draft_exists": draft_hash is not None,
        "independent_review": review is not None and review["verdict"] == "pass" and review["draft_sha256"] == draft_hash,
        "source_integrity": all(_material_intact(workspace, project["id"], material_id) for material_id in run["material_ids"]),
        "retrieval_integrity": all(task.get("raw_path") and Path(task["raw_path"]).is_file() and sha256(Path(task["raw_path"]).read_bytes()).hexdigest() == task["raw_sha256"] for task in retrieval_tasks),
        "chart_integrity": draft_hash is not None and all(
            (match := re.fullmatch(r"assets/(chart_[0-9a-f]{24})\.png", image)) is not None
            and (chart := charts.get(match[1])) is not None
            and snapshot is not None and set(chart["source_evidence_ids"]) <= set(snapshot["evidence_ids"])
            and Path(chart["path"]).is_file() and sha256(Path(chart["path"]).read_bytes()).hexdigest() == chart["sha256"]
            and (asset := draft.parent / image).is_file() and sha256(asset.read_bytes()).hexdigest() == chart["sha256"]
            for image in images),
    }
    if project["scenario_id"] == "budget_operations":
        uses = run.get("report_plan", {}).get("material_uses")
        try:
            _budget_material_uses(uses, run["material_ids"], {item["source_id"] for item in evidence.values()})
            checks["material_disposition"] = True
        except ValueError:
            checks["material_disposition"] = False
        def used_facts(section_bodies):
            result = set()
            for body in section_bodies:
                for kind, identifier, _ in re.findall(REFERENCE, body):
                    if kind == "fact":
                        result.add(identifier)
                    elif kind == "calc" and identifier in calculations:
                        result.update(calculations[identifier].get("input_evidence_ids", []))
            return result
        all_bodies = [row[0] for row in bodies.values() if row]
        used = used_facts(all_bodies)
        used_sources = {evidence[identifier]["source_id"] for identifier in used if identifier in evidence}
        checks["analysis_material_coverage"] = checks["material_disposition"] and all(
            item["material_id"] in used_sources for item in uses if item["use"] == "analysis")
        general_used = used_facts(row[0] for section_id, row in bodies.items() if row and ":" not in section_id)
        checks["unit_evidence_coverage"] = all(
            any(item["id"] in used_facts(row[0] for section_id, row in bodies.items()
                                          if row and section_id.endswith(":" + unit))
                for item in evidence.values() if item["subject_id"] == unit)
            for unit in project["subject_scope"]["units"]
            if any(item["subject_id"] == unit for item in evidence.values()))
        checks["special_subject_coverage"] = all(
            any(item["id"] in general_used for item in evidence.values() if item["subject_id"] == subject)
            for subject in project["subject_scope"].get("special_subjects", [])
            if any(item["subject_id"] == subject for item in evidence.values()))
        planned_units = {task["subject_id"] for task in tasks if task["subject_id"]}
        checks["unit_scope_coverage"] = planned_units == set(project["subject_scope"]["units"])
    if project["scenario_id"] == "compensation_analysis":
        content = draft.read_text(encoding="utf-8") if draft_hash is not None else ""
        checks["personal_pay_hidden"] = draft_hash is not None and not any(re.search(r"(?<![A-Za-z0-9])" + re.escape(term) + r"(?![A-Za-z0-9])", content) for term in private_terms(run, materials))
    if run["effective_config"]["quality"].get("financial_quality"):
        checks.update(_financial_validation(project_dir=project_dir, run=run, tasks=tasks,
                                             snapshot=snapshot, review=review, draft=draft))
    hard_passed = all(checks.values())
    gaps = {"missing_inputs": snapshot["missing_inputs"] if snapshot else [], "definition_missing": snapshot["definition_missing"] if snapshot else [],
            "retrieval_gaps": snapshot.get("retrieval_gaps", []) if snapshot else []}
    if run["effective_config"]["quality"].get("financial_quality"):
        gaps["material_gaps"] = [item for item in (snapshot or {}).get("material_coverage", [])
                                  if item["status"] in ("partial", "not_extracted")]
        gaps["review_gaps"] = [item["id"] for item in (review or {}).get("coverage", []) if item["result"] == "gap"]
        with sqlite3.connect(project_dir / "state.sqlite") as connection:
            gaps["calculation_gaps"] = ([{"metric_id": item["metric_id"], "subject_id": item["subject_id"], "period": item["period"], "status": item["status"]}
                                        for row in connection.execute("SELECT data FROM calculation WHERE run_id = ?", (run["id"],))
                                        if (item := json.loads(row[0]))["status"] != "calculated"]
                                       if connection.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'calculation'").fetchone() else [])
    status = "blocked" if not hard_passed else "pending_review" if any(gaps.values()) else "formal"
    return {"run_id": run["id"], "status": status, "hard_checks_passed": hard_passed, "checks": checks, "gaps": gaps,
            "scope_exclusions": scope_exclusions, "draft_sha256": draft_hash}


def _financial_validation(project_dir: Path, run: dict, tasks: list[dict], snapshot: dict | None,
                          review: dict | None, draft: Path) -> dict:
    checks = {"material_disposition": False, "analysis_material_coverage": False,
              "financial_binding": False, "financial_review_coverage": False, "candidate_integrity": False}
    with sqlite3.connect(project_dir / "state.sqlite") as connection:
        if not snapshot or not tasks or not draft.is_file():
            return checks
        evidence = {item["id"]: item for row in connection.execute("SELECT data FROM evidence")
                    if (item := json.loads(row[0]))["id"] in snapshot["evidence_ids"]}
        calculations = ({item["id"]: item for row in connection.execute("SELECT data FROM calculation WHERE run_id = ?", (run["id"],))
                         if (item := json.loads(row[0])).get("status") == "calculated"}
                        if connection.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'calculation'").fetchone() else {})
        bodies = {row[0]: row[1] for row in connection.execute("SELECT task_id, body FROM section_body")}
        materials = {item["id"]: item for row in connection.execute("SELECT data FROM material") if (item := json.loads(row[0]))}
    content = draft.read_text(encoding="utf-8")
    checks["candidate_integrity"] = (sha256(draft.read_bytes()).hexdigest() == run.get("draft_sha256") and
        all(task["id"] in bodies and sha256(bodies[task["id"]].encode()).hexdigest() == run.get("section_body_sha256", {}).get(task["id"]) for task in tasks))
    try:
        uses = _budget_material_uses(run.get("report_plan", {}).get("material_uses"), run["material_ids"], {item["source_id"] for item in evidence.values()})
        checks["material_disposition"] = True
        referenced = set()
        definitions = {item["id"]: item for item in run["effective_config"]["outline"]["sections"]}
        for task in tasks:
            body = bodies[task["id"]]
            validate_section_headings(body, definitions[task["section_id"]])
            validate_financial_body(body, definitions[task["section_id"]])
            for kind, identifier, precision in re.findall(REFERENCE, body):
                if kind == "calc":
                    if identifier not in calculations:
                        raise ValueError("stale calculation")
                    referenced.update(calculations[identifier]["input_evidence_ids"])
                else:
                    if identifier not in evidence:
                        raise ValueError("stale evidence")
                    if kind == "fact":
                        referenced.add(identifier)
        checks["financial_binding"] = True
        used_sources = {evidence[identifier]["source_id"] for identifier in referenced if identifier in evidence}
        # A derived fact explains the original's use; it never asserts a full-page OCR verification.
        used_originals = {materials[identifier]["derivation"]["source_id"] for identifier in used_sources if materials[identifier].get("derivation")}
        checks["analysis_material_coverage"] = all(
            item["material_id"] in used_sources | used_originals or
            re.search(r"(?m)^材料缺口：" + re.escape(materials[item["material_id"]]["original_name"]) + r"：\S.+$", content)
            for item in uses if item["use"] == "analysis")
        if review:
            validate_review_coverage(review.get("coverage"), review_requirements(content, run["effective_config"]["outline"]), content, set(evidence) | set(calculations))
            checks["financial_review_coverage"] = review["verdict"] == "pass" and not any(item["result"] == "needs_changes" for item in review["coverage"])
    except (ValueError, KeyError, TypeError):
        pass  # Each failed gate remains explicitly false in the returned checks.
    return checks


def _material_intact(workspace: Path, project_id: str, material_id: str) -> bool:
    try:
        material = get_material(workspace, project_id, material_id)
        if material.get("derivation"):
            original = get_material(workspace, project_id, material["derivation"]["source_id"])
            if original["fingerprint"] != material["derivation"]["source_sha256"]:
                return False
    except (ValueError, sqlite3.Error):
        return False
    return True


def _cover_metadata(project: dict, run: dict, evidence: list[dict], materials: list[dict], revisions: list[dict]) -> dict:
    period = project.get("report_period", project.get("evaluation_date"))
    year, month, *day = period.split("-")
    label = f"{year}年{int(month)}月" + (f"{int(day[0])}日" if day else "")
    windows = {item.get("window") for item in evidence if item.get("period") == period and item.get("basis") == "actuals"}
    if "ytd" in windows:
        label = ("当月：" if "month" in windows else "报告期：") + label + f"；累计：{year}年1—{int(month)}月"
    elif project["scenario_id"] == "budget_operations" and not windows:
        label += "（项目报告期，源数据期间待核实）"
    raw = json.dumps([item["parsed"] for item in materials], ensure_ascii=False)
    nature = ("含模拟数据（MOCK，技术工作稿）" if re.search(r"(?i)\bMOCK\b|模拟数据|模拟报表", raw)
              else "实际数据（来源明确标识）" if re.search(r"(?:数据性质|数据标识)[：:]\s*(?:实际数据|真实数据)", raw) else "未明确标识（待核实）")
    versions = [tuple(map(int, match.groups())) for revision in revisions
                if (match := re.fullmatch(r"V([1-9][0-9]*)\.([0-9]+)", revision.get("report_version", "")))]
    major, minor = max(versions) if versions else (1, -1)
    scope, specified = project["subject_scope"], project.get("report_metadata", {})
    subject = scope.get("business_unit", scope.get("organization"))
    if scope.get("units"):
        subject += f"；纳入{len(scope['units'])}家单位，详见分析范围"
    metadata = {"统计期间": label, "报告生成日期": date.today().isoformat(),
            "分析对象": specified.get("analysis_subject", subject),
            "编制部门": specified.get("prepared_by", "预算办" if project["scenario_id"] == "budget_operations" else "未指定（待确认）"),
            "数据性质": nature, "报告版本": f"V{major}.{minor + 1}",
            "数据版本": run["evidence_snapshot_id"],
            "保密说明": specified.get("confidentiality", "保密要求及等级未指定（待确认）")}

    profile = run.get("effective_config", {}).get("scenario", {}).get("presentation", {}).get("cover")
    if profile:
        started = datetime.fromisoformat(run["started_at"])
        if started.tzinfo is None:
            raise ValueError("cover requires a timezone-aware run start")
        local_day = started.astimezone(ZoneInfo(profile["timezone"])).date()
        for field in profile["fields"]:
            metadata[field["label"]] = (f"{local_day.year}年{local_day.month}月{local_day.day}日" if field["source"] == "run_date"
                                        else specified.get(field["source"], field["default"]))
        selector = next(item for item in run["effective_config"]["analysis"]["evidence_selectors"]
                        if item["id"] == profile["amount_selector"])
        points = [item for item in evidence if item.get("subject_id") == scope["business_unit"]
                  and item.get("period") == period and item.get("basis") == selector["input"]
                  and item.get("metric_id") == selector["field"]]
        metadata["授信额度"] = profile["missing_amount"]
        if len(points) == 1:
            point = points[0]
            raw = str(point.get("value", "")).strip()
            match = re.fullmatch(r"((?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)(?:\.[0-9]+)?)(亿元|万元|元)?", raw) if len(raw) <= 80 else None
            units = {"元": 1, "万元": 10000, "亿元": 100000000}
            unit = (match[2] or point.get("unit")) if match else None
            if (match and isinstance(unit, str) and unit in units
                    and (not match[2] or point.get("unit") in (None, "", "text", match[2]))):
                with localcontext() as arithmetic:
                    arithmetic.prec = 120
                    value = Decimal(match[1].replace(",", "")) * units[unit] / units[profile["amount_unit"]]
                    text = format(value, "f")
                metadata["授信额度"] = (text.rstrip("0").rstrip(".") if "." in text else text) + profile["amount_unit"]
                amount_display = run["effective_config"]["scenario"]["presentation"].get("amount_display")
                if amount_display:
                    shown, shown_unit = display_amount({"value": match[1], "unit": unit}, amount_display, "text")
                    metadata["授信额度"] = (shown.rstrip("0").rstrip(".") if "." in shown else shown) + shown_unit
                metadata["额度证据"] = point["id"]
    return metadata


def _report_title(project: dict, run: dict, metadata: dict) -> str:
    profile = run["effective_config"]["scenario"]["presentation"].get("cover")
    if profile:
        title = profile["title_template"].format(business_unit=project["subject_scope"]["business_unit"], credit_amount=metadata["授信额度"])
        if not title.strip() or len(title) > 120 or "\n" in title or "\r" in title:
            raise ValueError("generated report title must be a single line of at most 120 characters")
        return title
    year, month, *day = project.get("report_period", project.get("evaluation_date", "")).split("-")
    period_label = f"{year}年{int(month)}月" + (f"{int(day[0])}日" if day else "")
    subject = project["subject_scope"].get("organization", project["subject_scope"].get("business_unit"))
    return project.get("report_title", f"{subject}{run['effective_config']['scenario']['title']}报告（{period_label}）")


def publish_run(workspace: Path, request: dict) -> dict:
    project = get_project(workspace, request["project_id"])
    project_dir = workspace / project["id"]
    with sqlite3.connect(project_dir / "state.sqlite") as connection:
        row = connection.execute("SELECT data FROM run WHERE id = ?", (request["run_id"],)).fetchone()
        if row is None:
            raise ValueError("unknown run")
        run = json.loads(row[0])
        if run["status"] == "published":
            revisions = [item for row in connection.execute("SELECT data FROM revision") if (item := json.loads(row[0]))["run_id"] == run["id"]]
            if len(revisions) != 1:
                raise ValueError("published run has no unique revision")
            revision = revisions[0]
            for kind, path_key in (("markdown", "markdown_path"), ("docx", "docx_path"), ("pdf", "pdf_path")):
                if kind == "pdf" and path_key not in revision:
                    continue
                if sha256(Path(revision[path_key]).read_bytes()).hexdigest() != revision["file_hashes"][kind]:
                    raise ValueError(f"delivered {kind} checksum mismatch")
            return revision
    validation = validate_run(workspace, request)
    if not validation["hard_checks_passed"]:
        raise ValueError("publication blocked: " + ", ".join(key for key, passed in validation["checks"].items() if not passed))
    if run["status"] != "active":
        raise ValueError("run is not eligible for publication")
    if load_scenario(project["scenario_id"]).fingerprint != project["scenario_fingerprint"]:
        raise ValueError("installed scenario changed since project creation")
    revision_id = uuid4().hex
    revisions = project_dir / "revisions"
    stage = revisions / (".staging_" + revision_id)
    final = revisions / revision_id
    try:
        dist = stage / "dist"
        snapshot_dir = stage / "snapshot"
        qa_dir = stage / "qa"
        for directory in (dist, snapshot_dir, qa_dir):
            directory.mkdir(parents=True)
        source_markdown = project_dir / "runs" / run["id"] / "draft" / "full_report.md"
        markdown = dist / "full_report.md"
        shutil.copyfile(source_markdown, markdown)
        with sqlite3.connect(project_dir / "state.sqlite") as connection:
            charts = _chart_records(connection)
            source_materials = [item for row in connection.execute("SELECT data FROM material")
                                if (item := json.loads(row[0]))["id"] in run["material_ids"]]
            evidence = [json.loads(row[0]) for row in connection.execute("SELECT data FROM evidence")]
            snapshot = json.loads(connection.execute("SELECT data FROM evidence_snapshot WHERE id = ?", (run["evidence_snapshot_id"],)).fetchone()[0])
            evidence = [item for item in evidence if item["id"] in snapshot["evidence_ids"]]
            previous = ([json.loads(row[0]) for row in connection.execute("SELECT data FROM revision")]
                        if connection.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'revision'").fetchone() else [])
        cover = _cover_metadata(project, run, evidence, source_materials, previous)
        metadata_gaps = [f"{key}：{value}" for key, value in cover.items() if "待核实" in value or "待确认" in value]
        if "MOCK" in cover["数据性质"]:
            metadata_gaps.append("来源包含模拟数据，只能作为技术工作稿。")
        if metadata_gaps:
            validation["gaps"]["report_metadata"] = metadata_gaps
            validation["status"] = "pending_review"
        chart_hashes = {}
        for identifier in set(re.findall(r"!\[[^\]]*\]\(assets/(chart_[0-9a-f]{24})\.png\)", markdown.read_text(encoding="utf-8"))):
            asset = source_markdown.parent / "assets" / (identifier + ".png")
            if identifier not in charts or sha256(asset.read_bytes()).hexdigest() != charts[identifier]["sha256"]:
                raise ValueError("chart asset changed after review")
            (dist / "assets").mkdir(exist_ok=True)
            shutil.copyfile(asset, dist / "assets" / (identifier + ".png"))
            chart_hashes[identifier] = charts[identifier]["sha256"]
        template = scenario_template(project["scenario_id"], run["effective_config"]["scenario"]["template"])
        shutil.copyfile(template, snapshot_dir / "template.docx")
        (snapshot_dir / "effective_config.json").write_text(json.dumps(run["effective_config"], ensure_ascii=False, indent=2), encoding="utf-8")
        word = dist / "full_report.docx"
        title = _report_title(project, run, cover)
        outline = run["effective_config"]["outline"]
        toc_units = {name: outline.get("unit_levels", {}).get(name, 2) for name in outline.get("unit_names", project["subject_scope"].get("units", []))}
        pdf, toc_entries = render_paginated_docx(
            markdown.read_text(encoding="utf-8"), snapshot_dir / "template.docx", word, title, toc_units,
            run["effective_config"]["scenario"]["presentation"], cover, outline)
        with ZipFile(word) as archive:
            if archive.testzip() is not None or "word/document.xml" not in archive.namelist():
                raise ValueError("rendered Word file is damaged")
        render_checks = verify_docx(markdown.read_text(encoding="utf-8"), word, chart_hashes,
                                    metadata=cover, toc_entries=toc_entries, pdf=pdf, outline=outline,
                                    presentation=run["effective_config"]["scenario"]["presentation"])
        render_checks.update(verify_pdf_charts(pdf, chart_hashes))
        hashes = {name: sha256(path.read_bytes()).hexdigest() for name, path in (("markdown", markdown), ("docx", word), ("pdf", pdf))}
        manifest = {
            "id": revision_id, "run_id": run["id"], "project_id": project["id"], "status": validation["status"],
            "scenario_id": project["scenario_id"], "scenario_version": project["scenario_version"],
            "effective_config_fingerprint": run["effective_config_fingerprint"],
            "evidence_snapshot_id": run["evidence_snapshot_id"], "material_fingerprints": run["material_fingerprints"],
            "material_uses": run.get("report_plan", {}).get("material_uses", []),
            "scope_exclusions": validation["scope_exclusions"],
            "file_hashes": hashes,
            "chart_hashes": chart_hashes,
            "report_version": cover["报告版本"], "report_metadata": cover,
        }
        (stage / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        (qa_dir / "content_qa.json").write_text(json.dumps(validation, ensure_ascii=False, indent=2), encoding="utf-8")
        (qa_dir / "render_qa.json").write_text(json.dumps({**render_checks, "sha256": hashes["docx"],
                                                              "toc_entries": toc_entries, "pdf_sha256": hashes["pdf"]}, ensure_ascii=False, indent=2), encoding="utf-8")
        issues = validation["gaps"]
        (dist / "open_issues.md").write_text("# 待确认事项\n\n" + "\n".join(f"- {kind}: {value}" for kind, values in issues.items() for value in values) + "\n", encoding="utf-8")
        changes = "# 本版本变化\n\n首次交付。\n"
        if run["base_revision_id"]:
            with sqlite3.connect(project_dir / "state.sqlite") as connection:
                base = json.loads(connection.execute("SELECT data FROM revision WHERE id = ?", (run["base_revision_id"],)).fetchone()[0])
                base_run = json.loads(connection.execute("SELECT data FROM run WHERE id = ?", (base["run_id"],)).fetchone()[0])
                section_tasks = [json.loads(row[0]) for row in connection.execute("SELECT data FROM section_task WHERE run_id = ?", (run["id"],))]
                material_names = {item["id"]: item["original_name"] for row in connection.execute("SELECT data FROM material") if (item := json.loads(row[0]))}
            added = [material_names[identifier] for identifier in run["material_ids"] if identifier not in base_run["material_ids"]]
            updated = [item["section_id"] for item in section_tasks if not item.get("reused_from_task_id")]
            changes = "# 本版本变化\n\n基础版本：" + run["base_revision_id"] + "\n\n新增材料：" + ("、".join(added) if added else "无") + "\n\n更新章节：" + ("、".join(updated) if updated else "无") + "\n\n沿用章节：" + str(len(section_tasks) - len(updated)) + "。\n"
            if not base.get("report_version"):
                changes += "\n历史版本只有内部修订ID；本次首次建立可读报告版本，不回写旧文件版本号。\n"
        changes += "\n报告版本：" + cover["报告版本"] + "\n"
        (dist / "changes.md").write_text(changes, encoding="utf-8")
        stage.rename(final)
        revision = {**manifest, "markdown_path": str(final / "dist" / "full_report.md"), "docx_path": str(final / "dist" / "full_report.docx"),
                    "pdf_path": str(final / "dist" / "full_report.pdf")}
        with sqlite3.connect(project_dir / "state.sqlite") as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS revision (id TEXT PRIMARY KEY, data TEXT NOT NULL)")
            connection.execute("CREATE TABLE IF NOT EXISTS latest (slot INTEGER PRIMARY KEY CHECK (slot = 1), revision_id TEXT NOT NULL)")
            connection.execute("INSERT INTO revision VALUES (?, ?)", (revision_id, json.dumps(revision, ensure_ascii=False)))
            connection.execute("INSERT OR REPLACE INTO latest VALUES (1, ?)", (revision_id,))
            run["status"] = "published"
            connection.execute("UPDATE run SET data = ? WHERE id = ?", (json.dumps(run, ensure_ascii=False), run["id"]))
        return revision
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def get_latest_revision(workspace: Path, project_id: str) -> dict:
    project = get_project(workspace, project_id)
    with sqlite3.connect(workspace / project["id"] / "state.sqlite") as connection:
        if not connection.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'latest'").fetchone():
            raise ValueError("project has no delivered revision")
        row = connection.execute("SELECT revision.data FROM latest JOIN revision ON revision.id = latest.revision_id WHERE latest.slot = 1").fetchone()
    if row is None:
        raise ValueError("project has no delivered revision")
    revision = json.loads(row[0])
    for kind, path_key in (("markdown", "markdown_path"), ("docx", "docx_path"), ("pdf", "pdf_path")):
        if kind == "pdf" and path_key not in revision:
            continue
        if sha256(Path(revision[path_key]).read_bytes()).hexdigest() != revision["file_hashes"][kind]:
            raise ValueError(f"delivered {kind} checksum mismatch")
    return revision


def _checked_material(material: dict) -> dict:
    try:
        data = Path(material["archived_path"]).read_bytes()
    except OSError as error:
        raise ValueError("material archive is missing") from error
    if sha256(data).hexdigest() != material["fingerprint"]:
        raise ValueError("material archive checksum mismatch")
    return material


def _parse_csv(data: bytes) -> dict:
    cells = {}
    for row_number, row in enumerate(csv.reader(StringIO(data.decode("utf-8-sig"))), 1):
        for column_number, value in enumerate(row, 1):
            number = column_number
            letters = ""
            while number:
                number, remainder = divmod(number - 1, 26)
                letters = chr(65 + remainder) + letters
            coordinate = f"{letters}{row_number}"
            cells[coordinate] = {"value": value, "locator": f"sheet:CSV/cell:{coordinate}"}
    return {"sheets": {"CSV": {"cells": cells}}}


def _parse_xlsx(data: bytes) -> dict:
    from openpyxl import load_workbook

    try:
        book = load_workbook(BytesIO(data), data_only=False)
        cached = load_workbook(BytesIO(data), data_only=True)
        try:
            sheets = {}
            for sheet in book.worksheets:
                cells = {}
                # Loaded worksheets are sparse; .rows would allocate millions of styled blank cells.
                for cell in sorted(list(sheet._cells.values()), key=lambda item: (item.row, item.column)):
                    if cell.value is None:
                        continue
                    locator = f"sheet:{sheet.title}/cell:{cell.coordinate}"
                    if cell.data_type == "f":
                        result = cached[sheet.title][cell.coordinate].value
                        state = "pending_verify" if result is None else "cached_unverified"
                        if result is not None:
                            try:
                                recomputed = recalculate(sheet, cell.coordinate)
                                state = "verified" if abs(recomputed - Decimal(str(result))) <= Decimal("0.000001") else "cache_mismatch"
                            except (ValueError, SyntaxError, TypeError, InvalidOperation, ZeroDivisionError):
                                pass
                        cells[cell.coordinate] = {"value": str(result) if state in ("verified", "cached_unverified") else None,
                                                   "formula": cell.value, "state": state, "locator": locator}
                    else:
                        cells[cell.coordinate] = {"value": str(cell.value), "locator": locator}
                sheets[sheet.title] = {"cells": cells}
            return {"sheets": sheets}
        finally:
            book.close()
            cached.close()
    except BadZipFile as error:
        raise ValueError("invalid xlsx archive") from error


def _parse_text(data: bytes) -> dict:
    try:
        lines = data.decode("utf-8-sig").splitlines()
    except UnicodeDecodeError as error:
        raise ValueError("text material must be UTF-8") from error
    return {"fragments": [{"value": line, "locator": f"line:{index}"} for index, line in enumerate(lines, 1) if line.strip()]}


def _parse_docx(data: bytes) -> dict:
    from docx import Document

    try:
        document = Document(BytesIO(data))
    except (BadZipFile, KeyError, ValueError) as error:
        raise ValueError("invalid Word material") from error
    fragments = []
    for index, paragraph in enumerate(document.paragraphs, 1):
        if paragraph.text.strip():
            fragments.append({"value": paragraph.text, "locator": f"paragraph:{index}", "style": paragraph.style.name})
    for table_number, table in enumerate(document.tables, 1):
        for row_number, row in enumerate(table.rows, 1):
            for column_number, cell in enumerate(row.cells, 1):
                if cell.text.strip():
                    fragments.append({"value": cell.text, "locator": f"table:{table_number}/row:{row_number}/cell:{column_number}"})
    return {"fragments": fragments}


def _parse_pdf(data: bytes, allow_empty: bool = False) -> dict:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    if not data.startswith(b"%PDF-"):
        raise ValueError("invalid PDF material")
    try:
        reader = PdfReader(BytesIO(data), strict=False)
        fragments, pages = [], []
        for page_number, page in enumerate(reader.pages, 1):
            text = page.extract_text() or ""
            pages.append({"page": page_number, "text_chars": len(text.strip()),
                          "status": "text_extracted" if text.strip() else "unread"})
            fragments.extend({"value": line, "locator": f"page:{page_number}/line:{line_number}"}
                             for line_number, line in enumerate(text.splitlines(), 1) if line.strip())
    except (PdfReadError, ValueError, OSError) as error:
        raise ValueError("invalid PDF material") from error
    if not fragments and not allow_empty:
        raise ValueError("PDF has no extractable text")
    return {"fragments": fragments, "coverage": {"page_count": len(pages), "pages": pages,
            "unread_pages": [page["page"] for page in pages if page["status"] == "unread"]}}


def _parse_image(data: bytes) -> dict:
    from PIL import Image
    try:
        with Image.open(BytesIO(data)) as image:
            image.verify()
    except (OSError, ValueError) as error:
        raise ValueError("invalid image material") from error
    return {"fragments": [], "coverage": {"page_count": 1, "pages": [{"page": 1, "text_chars": 0, "status": "unread"}], "unread_pages": [1]}}
