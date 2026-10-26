"""Read and validate immutable, installed four-file scenario definitions."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from importlib import resources
from inspect import signature
from pathlib import Path
from typing import Any
import re

import yaml

from long_report.operators import OPERATORS


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


def validate_report_outline(outline: object, analysis: dict, scope: dict,
                            calculated_metric_ids: set[str] | None = None) -> dict:
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
        if not re.fullmatch(r"[a-z][a-z0-9_]*", section_id):
            raise ScenarioError(f"report outline.sections.{section_id}: unsafe section id")
        title = section.get("title")
        order = section.get("display_order")
        if not isinstance(title, str) or not title.strip() or "\n" in title or len(title) > 120 or type(order) is not int or order < 1 or order in orders or section.get("repeat_for") not in (None, "unit"):
            raise ScenarioError(f"report outline.sections.{section_id}: invalid title, order or repetition")
        orders.add(order)
        _references(section.get("evidence_refs"), selectors, f"report outline.sections.{section_id}.evidence_refs")
        _references(section.get("analysis_refs"), available, f"report outline.sections.{section_id}.analysis_refs")
    _check_dag(sections)
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
    digest.update(template.encode() + b"\0" + (directory / template).read_bytes())

    definitions = manifest.get("business_definitions")
    missing = manifest.get("definition_missing")
    if not isinstance(definitions, dict) or not isinstance(missing, list) or any(not isinstance(key, str) for key in missing) or set(missing) != {key for key, value in definitions.items() if value is None}:
        raise ScenarioError(f"{scenario_id}/scenario.yaml: definition_missing must name null business definitions")

    inputs = _records(manifest.get("inputs"), "scenario.inputs")
    selectors = _records(analysis.get("evidence_selectors"), "analysis.evidence_selectors")
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
