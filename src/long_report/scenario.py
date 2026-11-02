"""Read and validate immutable, installed four-file scenario definitions."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from importlib import resources
from inspect import signature
from pathlib import Path
from typing import Any
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

from long_report.operators import OPERATORS
from long_report.amounts import validate_amount_display


class ScenarioError(ValueError):
    pass


FILES = ("scenario.yaml", "outline.yaml", "analysis.yaml", "quality.yaml")
REQUIRED_CHECKS = {"evidence_location", "numeric_binding", "independent_review", "md_docx_openable"}


def _root():
    packaged = resources.files("long_report").joinpath("scenarios")
    return packaged if packaged.is_dir() else Path(__file__).resolve().parents[2] / "scenarios"


def scenario_ids(root=None) -> list[str]:
    root = root or _root()
    return sorted(item.name for item in root.iterdir() if item.is_dir())


def scenario_template(scenario_id: str, relative_path: str) -> Path:
    if not relative_path.startswith("templates/") or ".." in Path(relative_path).parts:
        raise ScenarioError("unsafe scenario template path")
    path = _root() / scenario_id / relative_path
    if not path.is_file():
        raise ScenarioError(f"missing scenario template: {relative_path}")
    return path


def _records(value: Any, label: str) -> dict[str, dict]:
    if not isinstance(value, list):
        raise ScenarioError(f"{label}: expected a list")
    result = {}
    for item in value:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"]:
            raise ScenarioError(f"{label}: each item needs a nonempty id")
        if item["id"] in result:
            raise ScenarioError(f"{label}: duplicate id {item['id']}")
        result[item["id"]] = item
    return result


def _references(values: Any, ids: dict, label: str) -> None:
    if not isinstance(values, list):
        raise ScenarioError(f"{label}: expected a list")
    for value in values:
        if not isinstance(value, str) or value not in ids:
            raise ScenarioError(f"{label}: unknown id {value}")


def _check_dag(sections: dict[str, dict]) -> None:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(section_id: str, path: list[str]) -> None:
        if section_id in visiting:
            raise ScenarioError("outline.sections: cycle " + " -> ".join(path + [section_id]))
        if section_id in visited:
            return
        visiting.add(section_id)
        section = sections[section_id]
        _references(section.get("depends_on"), sections, f"outline.sections.{section_id}.depends_on")
        for dependency in section["depends_on"]:
            visit(dependency, path + [section_id])
        visiting.remove(section_id)
        visited.add(section_id)

    for section_id in sections:
        visit(section_id, [])


def _valid_table_labels(value: object) -> bool:
    return (isinstance(value, list) and all(isinstance(item, str) and item.strip() and "\n" not in item
                                          and len(item) <= 120 for item in value)
            and len(value) == len(set(value)))


def markdown_table_rows(block: str) -> list[list[str]] | None:
    lines = block.splitlines()
    if not (len(lines) >= 3 and all(line.startswith("|") and line.endswith("|") for line in lines)
            and all(set(cell.strip()) <= {"-", ":"} for cell in lines[1].strip("|").split("|"))):
        return None
    rows = []
    for line in (lines[0], *lines[2:]):
        cells, start = [], 1
        for match in re.finditer(r"\{\{(?:fact|calc):[^}|]+\|[0-6]\}\}|\|", line):
            if match[0] == "|" and match.start() > 0:
                cells.append(line[start:match.start()].strip())
                start = match.end()
        rows.append(cells)
    if any(len(row) != len(rows[0]) for row in rows):
        raise ScenarioError("Markdown table has inconsistent columns")
    return rows


def validate_section_headings(body: str, section: dict) -> None:
    """Check fixed headings and required tables before submission and after evidence expansion."""
    if "subheadings" in section:
        headings = list(re.finditer(r"(?m)^ *(#{1,2}) +(.+?)\s*$", body))
        if (any(match[0].startswith(" ") or match[1] != "##" for match in headings)
                or [match[2].strip() for match in headings] != section["subheadings"]):
            raise ScenarioError("section must preserve fixed second-level headings and order")
        rendered_headings = [match[2].strip() for block in body.strip().split("\n\n")
                             if (match := re.fullmatch(r"(#{1,2}) (.+)", block.strip()))]
        if rendered_headings != section["subheadings"]:
            raise ScenarioError("fixed headings must be standalone Markdown blocks separated by blank lines")
        for index, heading in enumerate(headings):
            end = headings[index + 1].start() if index + 1 < len(headings) else len(body)
            if not re.sub(r"(?m)^ *#{3,6} +.*$", "", body[heading.end():end]).strip():
                raise ScenarioError("empty fixed subheading requires analysis or an explicit gap")
    raw_children, active = {}, None
    for heading in re.finditer(r"(?m)^([ \t]*)(#{1,3}) +(.+?) *$", body):
        if len(heading[2]) <= 2:
            active = heading[3].strip() if heading[2] == "##" else None
        elif active in section.get("required_subsections", {}):
            if heading[1]:
                raise ScenarioError("required subsection heading must not be indented")
            raw_children.setdefault(active, []).append(heading[3].strip())
    child_scopes, active, child = {}, None, None
    for block in body.strip().split("\n\n"):
        heading = re.fullmatch(r"(#{1,3}) (.+)", block.strip())
        if heading and len(heading[1]) <= 2:
            active, child = heading[2].strip() if heading[1] == "##" else None, None
        elif heading and active in section.get("required_subsections", {}):
            if re.search(r"(?m)^[ \t]+### ", block):
                raise ScenarioError("required subsection heading must not be indented")
            child = heading[2].strip()
            child_scopes.setdefault(active, []).append((child, []))
        elif active in section.get("required_subsections", {}) and child is not None:
            child_scopes[active][-1][1].append(block)
    for parent, required in section.get("required_subsections", {}).items():
        scopes = child_scopes.get(parent, [])
        titles = [item["title"] for item in required]
        if (raw_children.get(parent, []) != titles or [name for name, _ in scopes] != titles
                or any(not re.sub(r"(?m)^#{4,6} +.*$", "", "\n\n".join(blocks)).strip() for _, blocks in scopes)):
            raise ScenarioError("required subsection missing, empty or out of order: " + parent)
        for (_, blocks), definition in zip(scopes, required):
            if definition["content"] == "narrative" and not any(
                    markdown_table_rows(block) is None and block.strip()
                    and not re.fullmatch(r"#{4,6} +.+", block.strip()) for block in blocks):
                raise ScenarioError("required subsection needs narrative or an explicit gap: " + definition["title"])
    for rule in section.get("required_tables", []):
        active, child, tables = None, None, []
        for block in body.strip().split("\n\n"):
            heading = re.fullmatch(r"(#{1,3}) (.+)", block.strip())
            if heading and len(heading[1]) <= 2:
                active, child = heading[2].strip() if heading[1] == "##" else None, None
            elif heading:
                child = heading[2].strip()
            elif (active == rule["subheading"] and ("child_heading" not in rule or child == rule["child_heading"])
                  and (rows := markdown_table_rows(block)) is not None):
                tables.append(rows)
        if len(tables) != 1 or tables[0][0] != rule["columns"]:
            raise ScenarioError("required table missing or has incorrect columns: " + rule["subheading"])
        records = tables[0][1:]
        if "required_fields" in rule:
            fields = [row[0] for row in records]
            if (not set(rule["required_fields"]) <= set(fields) or len(fields) != len(set(fields))
                    or any(not cell for row in records for cell in row)):
                raise ScenarioError("required table field missing, duplicated or empty: " + rule["subheading"])
        else:
            total = rule["total_row"]
            key = rule["columns"].index(total["label_column"])
            if (len(records) < 2 or "".join(records[-1][key].split()) != "".join(total["label"].split())
                    or any("".join(row[key].split()) == "".join(total["label"].split()) for row in records[:-1])):
                raise ScenarioError("required table total row must appear once at the end")
            labels = [row[key] for row in records[:-1]]
            if (len(labels) != len(set(labels)) or any(not cell for row in records[:-1] for cell in row)
                    or any(records[-1][i] for i, column in enumerate(rule["columns"]) if column in total["blank_columns"])
                    or any(not records[-1][i] for i, column in enumerate(rule["columns"]) if column not in total["blank_columns"])):
                raise ScenarioError("required table field missing, duplicated or invalid in total row")
            for column in total["sum_columns"]:
                index, numbers = rule["columns"].index(column), []
                for row in records:
                    value = row[index]
                    if re.fullmatch(r"\{\{(?:fact|calc):[^}]+\}\}", value) or re.search(r"未提供|缺|待核实|不适用", value):
                        numbers.append(None)
                        continue
                    try:
                        number = Decimal(value.replace(",", "").removesuffix("%"))
                    except InvalidOperation as error:
                        raise ScenarioError("table total requires numeric values or an explicit gap") from error
                    if not number.is_finite():
                        raise ScenarioError("table total requires finite numeric values")
                    numbers.append(number)
                if None not in numbers:
                    if sum(numbers[:-1], Decimal(0)) != numbers[-1]:
                        raise ScenarioError("table total differs from shareholder rows: " + column)


def validate_report_outline(outline: object, analysis: dict, scope: dict,
                            calculated_metric_ids: set[str] | None = None,
                            fixed_outline: dict | None = None) -> dict:
    """Validate a one-report chapter plan against stable scenario capabilities."""
    if not isinstance(outline, dict) or set(outline) - {"sections", "unit_names", "unit_levels"}:
        raise ScenarioError("report outline must contain only sections and unit scope")
    sections = _records(outline.get("sections"), "report outline.sections")
    if not sections:
        raise ScenarioError("report outline requires sections")
    selectors = _records(analysis["evidence_selectors"], "analysis.evidence_selectors")
    available = {**_records(analysis["metrics"], "analysis.metrics"),
                 **_records(analysis.get("period_comparisons", []), "analysis.period_comparisons"),
                 **_records(analysis["analysis_tasks"], "analysis.analysis_tasks")}
    available.update({metric_id: {} for metric_id in calculated_metric_ids or set()})
    orders = set()
    for section_id, section in sections.items():
        if {"font", "font_size_pt", "styles", "presentation"} & set(section):
            raise ScenarioError("chapter typography belongs in scenario.presentation styles")
        if not re.fullmatch(r"[a-z][a-z0-9_]*", section_id):
            raise ScenarioError(f"report outline.sections.{section_id}: unsafe section id")
        title = section.get("title")
        order = section.get("display_order")
        if not isinstance(title, str) or not title.strip() or "\n" in title or len(title) > 120 or type(order) is not int or order < 1 or order in orders or section.get("repeat_for") not in (None, "unit"):
            raise ScenarioError(f"report outline.sections.{section_id}: invalid title, order or repetition")
        orders.add(order)
        if "subheadings" in section:
            headings = section["subheadings"]
            if (not isinstance(headings, list) or any(not isinstance(title, str) or not title.strip()
                    or "\n" in title or len(title) > 120 for title in headings)
                    or len(headings) != len(set(headings))):
                raise ScenarioError(f"report outline.sections.{section_id}: invalid subheadings")
        required_subsections = section.get("required_subsections", {})
        if (not isinstance(required_subsections, dict)
                or any(parent not in section.get("subheadings", []) or not isinstance(children, list) or not children
                       or any(not isinstance(item, dict) or set(item) != {"title", "content"}
                              or item["content"] not in ("table", "narrative") for item in children)
                       or not _valid_table_labels([item["title"] for item in children])
                       for parent, children in required_subsections.items())):
            raise ScenarioError("invalid required subsection definition")
        table_rules = section.get("required_tables", [])
        if not isinstance(table_rules, list):
            raise ScenarioError("required_tables must be a list")
        for rule in table_rules:
            allowed = {"subheading", "child_heading", "columns", "required_fields", "total_row", "style"}
            if (not isinstance(rule, dict) or not {"subheading", "columns"} <= set(rule) or set(rule) - allowed
                    or rule["subheading"] not in section.get("subheadings", [])
                    or not _valid_table_labels(rule["columns"]) or len(rule["columns"]) < 2
                    or ("required_fields" in rule) == ("total_row" in rule)
                    or "child_heading" in rule and rule["child_heading"] not in
                       [item["title"] for item in required_subsections.get(rule["subheading"], [])]):
                raise ScenarioError("invalid required table definition")
            if "style" in rule and (not isinstance(rule["style"], str) or not re.fullmatch(r"[a-z][a-z0-9_]*", rule["style"])):
                raise ScenarioError("invalid required table style reference")
            if "required_fields" in rule:
                if not _valid_table_labels(rule["required_fields"]) or not rule["required_fields"] or len(rule["columns"]) != 2:
                    raise ScenarioError("invalid required table fields")
            else:
                total = rule["total_row"]
                if (not isinstance(total, dict) or set(total) != {"label_column", "label", "blank_columns", "sum_columns"}
                        or total["label_column"] not in rule["columns"] or not isinstance(total["label"], str)
                        or not total["label"].strip() or "\n" in total["label"]
                        or not _valid_table_labels(total["blank_columns"]) or not _valid_table_labels(total["sum_columns"])
                        or not total["sum_columns"] or not set(total["blank_columns"] + total["sum_columns"]) <= set(rule["columns"])
                        or total["label_column"] in total["blank_columns"] + total["sum_columns"]
                        or set(total["blank_columns"]) & set(total["sum_columns"])):
                    raise ScenarioError("invalid required table total row")
        if len({(rule["subheading"], rule.get("child_heading")) for rule in table_rules}) != len(table_rules):
            raise ScenarioError("duplicate required table subsection")
        _references(section.get("evidence_refs"), selectors, f"report outline.sections.{section_id}.evidence_refs")
        _references(section.get("analysis_refs"), available, f"report outline.sections.{section_id}.analysis_refs")
    _check_dag(sections)
    if fixed_outline and fixed_outline.get("fixed"):
        fields = ("id", "title", "display_order", "repeat_for", "subheadings", "required_tables", "required_subsections")
        def structure(items):
            return [{key: section.get(key) for key in fields}
                    for section in sorted(items, key=lambda item: item["display_order"])]
        if structure(list(sections.values())) != structure(fixed_outline["sections"]):
            raise ScenarioError("report outline must preserve fixed chapter titles, order and subheadings")
    names = outline.get("unit_names", scope.get("units", []))
    if not isinstance(names, list) or any(not isinstance(name, str) or not name.strip() for name in names) or len(names) != len(set(names)) or not set(names) <= set(scope.get("units", [])):
        raise ScenarioError("report outline.unit_names must be distinct project units")
    if any(section["repeat_for"] == "unit" for section in sections.values()) and not names:
        raise ScenarioError("report outline needs units for repeated section")
    levels = outline.get("unit_levels", {})
    if not isinstance(levels, dict) or any(name not in names or level not in (2, 3) for name, level in levels.items()):
        raise ScenarioError("report outline.unit_levels must name planned units")
    return {"sections": list(sections.values()), "unit_names": names, "unit_levels": levels}


def validate_source_mapping(profile: object, input_ids: set[str]) -> dict:
    if not isinstance(profile, dict) or not isinstance(profile.get("id"), str) or not profile["id"]:
        raise ScenarioError("source mapping needs an id")
    units, special = profile.get("units"), profile.get("special_subjects")
    aggregates, nested = profile.get("aggregate_subjects", []), profile.get("nested_subjects", [])
    if not isinstance(profile.get("report_period"), str) or not isinstance(profile.get("organization"), str) or not all(isinstance(group, list) for group in (units, special, aggregates, nested)) or any(not isinstance(name, str) or not name for group in (units, special, aggregates, nested) for name in group):
        raise ScenarioError("source mapping has invalid scope or period")
    subjects = {profile["organization"], *units, *special, *aggregates, *nested}
    for table_id, table in _records(profile.get("tables"), "source mapping.tables").items():
        filename = table.get("filename")
        column = table.get("subject_column")
        if not isinstance(filename, str) or Path(filename).name != filename or not filename.endswith(".xlsx") or not isinstance(column, str) or not re.fullmatch(r"[A-Z]+", column):
            raise ScenarioError(f"source mapping.{table_id}: unsafe source locator")
        if not isinstance(table.get("input_ids"), list) or any(role not in input_ids for role in table["input_ids"]):
            raise ScenarioError(f"source mapping.{table_id}: unknown input role")
        if not isinstance(table.get("sheet"), str) or not table["sheet"] or not isinstance(table.get("rows"), list) or not table["rows"] or not isinstance(table.get("fields"), list) or not table["fields"]:
            raise ScenarioError(f"source mapping.{table_id}: rows, fields and sheet are required")
        for row in table["rows"]:
            targets = row.get("targets")
            if type(row.get("row")) is not int or row["row"] < 1 or not isinstance(row.get("source_subject"), str) or not row["source_subject"] or not isinstance(targets, list) or not targets or any(not isinstance(target, str) or target not in subjects for target in targets):
                raise ScenarioError(f"source mapping.{table_id}: invalid row mapping")
        for field in table["fields"]:
            value_column = field.get("column")
            if not isinstance(value_column, str) or not re.fullmatch(r"[A-Z]+", value_column) or field.get("basis") not in table["input_ids"] or not isinstance(field.get("period"), str) or not isinstance(field.get("window"), str) or not isinstance(field.get("id"), str):
                raise ScenarioError(f"source mapping.{table_id}: invalid field mapping")
    return profile


@dataclass(frozen=True)
class Scenario:
    manifest: dict
    outline: dict
    analysis: dict
    quality: dict
    fingerprint: str

    @property
    def version(self) -> str:
        return self.manifest["version"]

    def summary(self) -> dict:
        return {
            "id": self.manifest["id"],
            "title": self.manifest["title"],
            "version": self.version,
            "fingerprint": self.fingerprint,
            "definition_missing": self.manifest.get("definition_missing", []),
        }

    def as_dict(self) -> dict:
        return {**self.summary(), "scenario": self.manifest, "outline": self.outline,
                "analysis": self.analysis, "quality": self.quality}


def load_scenario(scenario_id: str, root=None) -> Scenario:
    root = root or _root()
    if scenario_id not in scenario_ids(root):
        raise ScenarioError(f"unknown scenario: {scenario_id}")
    directory = root / scenario_id
    documents = {}
    digest = sha256()
    for filename in FILES:
        try:
            raw = (directory / filename).read_bytes()
        except OSError as error:
            raise ScenarioError(f"{scenario_id}/{filename}: {error.strerror}") from error
        digest.update(filename.encode() + b"\0" + raw)
        try:
            value = yaml.safe_load(raw)
        except yaml.YAMLError as error:
            raise ScenarioError(f"{scenario_id}/{filename}: invalid YAML: {error}") from error
        if not isinstance(value, dict):
            raise ScenarioError(f"{scenario_id}/{filename}: expected a mapping")
        documents[filename] = value

    manifest, outline, analysis, quality = (documents[name] for name in FILES)
    if manifest.get("schema_version") != 1 or manifest.get("id") != scenario_id:
        raise ScenarioError(f"{scenario_id}/scenario.yaml: schema_version or id mismatch")
    if not isinstance(manifest.get("title"), str) or not manifest["title"]:
        raise ScenarioError(f"{scenario_id}/scenario.yaml: title is required")
    if not isinstance(manifest.get("version"), str) or not manifest["version"]:
        raise ScenarioError(f"{scenario_id}/scenario.yaml: version is required")
    for field, expected in zip(("outline", "analysis", "quality"), FILES[1:]):
        if manifest.get(field) != expected:
            raise ScenarioError(f"{scenario_id}/scenario.yaml: {field} must reference {expected}")
    template = manifest.get("template")
    if not isinstance(template, str) or not template.startswith("templates/") or ".." in Path(template).parts or not (directory / template).is_file():
        raise ScenarioError(f"{scenario_id}/scenario.yaml: missing or unsafe template {template}")
    presentation = manifest.get("presentation")
    if not isinstance(presentation, dict) or any(not isinstance(presentation.get(key), str) or not presentation[key].strip() or len(presentation[key]) > 80 or "\n" in presentation[key] for key in ("body_font", "heading_font", "latin_font")):
        raise ScenarioError(f"{scenario_id}/scenario.yaml: presentation fonts are required")
    if type(presentation.get("allow_font_fallback", True)) is not bool:
        raise ScenarioError("scenario.presentation.allow_font_fallback must be boolean")
    if "amount_display" in presentation:
        try:
            validate_amount_display(presentation["amount_display"])
        except ValueError as error:
            raise ScenarioError(str(error)) from error
    for group in ("styles", "table_styles"):
        style_rules = presentation.get(group, {})
        if not isinstance(style_rules, dict):
            raise ScenarioError(f"presentation.{group} must be a mapping")
        for name, rule in style_rules.items():
            if (not isinstance(name, str) or (group == "styles" and name not in ("Title", "Heading 1", "Heading 2", "Normal"))
                    or group == "table_styles" and not re.fullmatch(r"[a-z][a-z0-9_]*", name)
                    or not isinstance(rule, dict) or set(rule) != {"font", "font_size_pt"}
                    or not isinstance(rule["font"], str) or not rule["font"].strip() or "\n" in rule["font"] or len(rule["font"]) > 80
                    or type(rule["font_size_pt"]) not in (int, float) or not 1 <= rule["font_size_pt"] <= 72
                    or rule["font_size_pt"] * 2 % 1):
                raise ScenarioError(f"invalid presentation.{group} style: {name}")
    cover = presentation.get("cover")
    if cover is not None:
        if (not isinstance(cover, dict) or set(cover) != {"title_template", "amount_selector", "amount_unit", "missing_amount", "timezone", "fields"}
                or any(not isinstance(cover[key], str) or not cover[key].strip() or "\n" in cover[key] or "\r" in cover[key]
                       or len(cover[key]) > 120 for key in ("title_template", "amount_selector", "missing_amount", "timezone"))
                or cover["amount_unit"] not in ("元", "万元", "亿元")
                or not all("{" + field + "}" in cover["title_template"] for field in ("business_unit", "credit_amount"))
                or any(char in cover["title_template"].replace("{business_unit}", "").replace("{credit_amount}", "") for char in "{}")
                or not isinstance(cover["fields"], list) or not cover["fields"]):
            raise ScenarioError("invalid presentation.cover definition")
        for field in cover["fields"]:
            if (not isinstance(field, dict) or set(field) not in ({"label", "source"}, {"label", "source", "default"})
                    or not isinstance(field["label"], str) or not field["label"].strip() or any(char in field["label"] for char in "\r\n") or len(field["label"]) > 80
                    or field["label"] in {"统计期间", "报告生成日期", "分析对象", "编制部门", "数据性质", "报告版本", "数据版本", "保密说明", "授信额度", "额度证据"}
                    or field["source"] not in ("prepared_by", "account_manager", "run_date")
                    or field["source"] == "run_date" and "default" in field
                    or field["source"] != "run_date" and (not isinstance(field.get("default"), str) or not field["default"].strip()
                                                               or any(char in field["default"] for char in "\r\n") or len(field["default"]) > 120)):
                raise ScenarioError("invalid presentation.cover field")
        if (len({field["label"] for field in cover["fields"]}) != len(cover["fields"])
                or len({field["source"] for field in cover["fields"]}) != len(cover["fields"])):
            raise ScenarioError("duplicate presentation.cover field")
        try:
            ZoneInfo(cover["timezone"])
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ScenarioError("invalid presentation.cover timezone") from error
    digest.update(template.encode() + b"\0" + (directory / template).read_bytes())

    definitions = manifest.get("business_definitions")
    missing = manifest.get("definition_missing")
    if not isinstance(definitions, dict) or not isinstance(missing, list) or any(not isinstance(key, str) for key in missing) or set(missing) != {key for key, value in definitions.items() if value is None}:
        raise ScenarioError(f"{scenario_id}/scenario.yaml: definition_missing must name null business definitions")

    inputs = _records(manifest.get("inputs"), "scenario.inputs")
    selectors = _records(analysis.get("evidence_selectors"), "analysis.evidence_selectors")
    if cover is not None and cover["amount_selector"] not in selectors:
        raise ScenarioError("unknown cover amount selector")
    if quality.get("financial_quality") is True and "financial_metrics" not in analysis:
        raise ScenarioError("financial quality requires registered financial_metrics")
    if "financial_metrics" in analysis:
        from long_report.financials import FINANCIAL_METRICS
        registered = analysis["financial_metrics"]
        if (scenario_id != "financial_due_diligence" or not isinstance(registered, list) or not registered
                or any(not isinstance(item, str) or item not in FINANCIAL_METRICS for item in registered)
                or len(set(registered)) != len(registered) or quality.get("financial_quality") is not True):
            raise ScenarioError("invalid financial metric or quality contract")
    metrics = _records(analysis.get("metrics"), "analysis.metrics")
    comparisons = _records(analysis.get("period_comparisons", []), "analysis.period_comparisons")
    tasks = _records(analysis.get("analysis_tasks"), "analysis.analysis_tasks")
    retrieval_tasks = _records(analysis.get("retrieval_tasks", []), "analysis.retrieval_tasks")
    retrieval = manifest.get("retrieval")
    if not isinstance(retrieval, dict) or type(retrieval.get("enabled")) is not bool:
        raise ScenarioError("scenario.retrieval: enabled must be boolean")
    _references(retrieval.get("task_refs"), retrieval_tasks, "scenario.retrieval.task_refs")
    for task_id, retrieval_task in retrieval_tasks.items():
        if retrieval_task.get("input") not in inputs or type(retrieval_task.get("ttl_days")) is not int or retrieval_task["ttl_days"] < 0:
            raise ScenarioError(f"analysis.retrieval_tasks.{task_id}: invalid input or ttl_days")
    if "source_profiles" in analysis:
        raise ScenarioError("analysis.source_profiles belongs in per-run source mappings")
    if metrics.keys() & tasks.keys() or comparisons.keys() & (metrics.keys() | tasks.keys()):
        raise ScenarioError("analysis: metric, period comparison and task ids must be distinct")
    sections = _records(outline.get("sections"), "outline.sections")
    if type(outline.get("fixed", False)) is not bool:
        raise ScenarioError("outline.fixed must be boolean")
    if outline.get("fixed"):
        validate_report_outline({"sections": list(sections.values())}, analysis, {})
        if any(section.get("repeat_for") is not None or "subheadings" not in section for section in sections.values()):
            raise ScenarioError("fixed outline requires unrepeated chapters with explicit subheadings")
    for section in sections.values():
        for table in section.get("required_tables", []):
            if "style" in table and table["style"] not in presentation.get("table_styles", {}):
                raise ScenarioError("unknown table style: " + table["style"])
    for selector_id, selector in selectors.items():
        if not isinstance(selector.get("input"), str) or selector["input"] not in inputs:
            raise ScenarioError(f"analysis.evidence_selectors.{selector_id}: unknown input {selector.get('input')}")
    for metric_id, metric in metrics.items():
        if not isinstance(metric.get("operator"), str) or metric["operator"] not in OPERATORS:
            raise ScenarioError(f"analysis.metrics.{metric_id}: unknown operator {metric.get('operator')}")
        _references(metric.get("inputs"), selectors, f"analysis.metrics.{metric_id}.inputs")
        if len(metric["inputs"]) != len(signature(OPERATORS[metric["operator"]]).parameters):
            raise ScenarioError(f"analysis.metrics.{metric_id}: wrong operator input count")
    for comparison_id, comparison in comparisons.items():
        if comparison.get("operator") not in OPERATORS or (len(signature(OPERATORS[comparison["operator"]]).parameters) != 2 and comparison["operator"] != "remaining_monthly_target") or comparison.get("basis") not in inputs or comparison.get("baseline_basis", comparison.get("basis")) not in inputs or comparison.get("window") not in ("month", "ytd") or comparison.get("baseline") not in ("previous_month", "previous_year_same_month", "annual_plan") or not isinstance(comparison.get("applies_to"), list) or not comparison["applies_to"] or any(not isinstance(metric, str) or not metric for metric in comparison["applies_to"]):
            raise ScenarioError(f"analysis.period_comparisons.{comparison_id}: invalid comparison")
        if comparison["baseline"] == "annual_plan" and comparison["window"] != "ytd":
            raise ScenarioError(f"analysis.period_comparisons.{comparison_id}: annual plan requires ytd actual")
        if comparison["operator"] == "remaining_monthly_target" and (comparison["baseline"] != "annual_plan" or comparison.get("baseline_basis") != "budget"):
            raise ScenarioError(f"analysis.period_comparisons.{comparison_id}: remaining target requires annual budget")
    paired = analysis.get("paired_indicators", {})
    if not isinstance(paired, dict) or any(not isinstance(key, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", key) or not isinstance(value, dict)
                                             or not re.fullmatch(r"[a-z][a-z0-9_]*", str(value.get("prior", "")))
                                             or not isinstance(value.get("label"), str) or not value["label"].strip()
                                             for key, value in paired.items()):
        raise ScenarioError("analysis.paired_indicators: invalid field rule")
    guidance = analysis.get("writing_guidance", {})
    if not isinstance(guidance, dict) or any(not isinstance(points, list) or not points or
                                             any(not isinstance(point, str) or not point.strip() for point in points)
                                             for points in guidance.values()):
        raise ScenarioError("analysis.writing_guidance: nonempty guidance lists are required")
    for section_id, section in sections.items():
        _references(section.get("evidence_refs"), selectors, f"outline.sections.{section_id}.evidence_refs")
        _references(section.get("analysis_refs"), {**metrics, **comparisons, **tasks}, f"outline.sections.{section_id}.analysis_refs")
    _check_dag(sections)
    if "profiles" in outline:
        raise ScenarioError("outline.profiles belongs in per-run report plans")
    _references(quality.get("required_inputs"), inputs, "quality.required_inputs")
    _references(quality.get("required_sections"), sections, "quality.required_sections")
    if outline.get("fixed") and set(quality["required_sections"]) != set(sections):
        raise ScenarioError("quality.required_sections must cover the fixed outline")
    if not isinstance(quality.get("checks"), list) or any(not isinstance(check, str) for check in quality["checks"]) or not REQUIRED_CHECKS.issubset(quality["checks"]):
        raise ScenarioError(f"{scenario_id}/quality.yaml: required checks missing")
    if scenario_id == "budget_operations":
        if quality.get("require_full_unit_scope") is not True or quality.get("require_material_disposition") is not True:
            raise ScenarioError("quality: budget scope and material disposition gates are required")
        required_metrics = quality.get("unit_required_calculations")
        blocks = quality.get("unit_required_blocks")
        if not isinstance(required_metrics, list) or not required_metrics or any(item not in metrics and item not in comparisons for item in required_metrics):
            raise ScenarioError("quality.unit_required_calculations: unknown metric")
        if not isinstance(blocks, list) or not blocks or any(not isinstance(item, str) or not item.strip() for item in blocks):
            raise ScenarioError("quality.unit_required_blocks: nonempty labels required")
        if any(type(quality.get(key)) is not int or quality[key] < 1 for key in ("unit_min_operating_calculations", "unit_min_operating_narrative_calculations")) or any(type(quality.get(key)) is not bool for key in ("unit_requires_source_citations", "unit_requires_numbered_tables_and_chart")):
            raise ScenarioError("quality: invalid budget unit detail gate")
        families = quality.get("unit_evidence_families")
        if (not isinstance(families, list) or not families
                or any(not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"]
                       or not isinstance(item.get("prefixes"), list) or not item["prefixes"]
                       or any(not isinstance(prefix, str) or not prefix.endswith(".") for prefix in item["prefixes"])
                       for item in families)
                or len({item["id"] for item in families}) != len(families)):
            raise ScenarioError("quality.unit_evidence_families: invalid budget evidence families")
    if quality.get("formal_requires") != "all_required_checks_pass":
        raise ScenarioError(f"{scenario_id}/quality.yaml: formal release gate is required")
    delivery = manifest.get("delivery")
    if not isinstance(delivery, dict) or not {"md", "docx"}.issubset(delivery.get("required_formats", [])):
        raise ScenarioError(f"{scenario_id}/scenario.yaml: md and docx are required")
    return Scenario(manifest, outline, analysis, quality, digest.hexdigest())
