"""Read and validate immutable, installed four-file scenario definitions."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from importlib import resources
from inspect import signature
from pathlib import Path
from typing import Any

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
    digest.update(template.encode() + b"\0" + (directory / template).read_bytes())

    definitions = manifest.get("business_definitions")
    missing = manifest.get("definition_missing")
    if not isinstance(definitions, dict) or not isinstance(missing, list) or any(not isinstance(key, str) for key in missing) or set(missing) != {key for key, value in definitions.items() if value is None}:
        raise ScenarioError(f"{scenario_id}/scenario.yaml: definition_missing must name null business definitions")

    inputs = _records(manifest.get("inputs"), "scenario.inputs")
    selectors = _records(analysis.get("evidence_selectors"), "analysis.evidence_selectors")
    metrics = _records(analysis.get("metrics"), "analysis.metrics")
    tasks = _records(analysis.get("analysis_tasks"), "analysis.analysis_tasks")
    if metrics.keys() & tasks.keys():
        raise ScenarioError("analysis: metric and task ids must be distinct")
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
    for section_id, section in sections.items():
        _references(section.get("evidence_refs"), selectors, f"outline.sections.{section_id}.evidence_refs")
        _references(section.get("analysis_refs"), {**metrics, **tasks}, f"outline.sections.{section_id}.analysis_refs")
    _check_dag(sections)
    _references(quality.get("required_inputs"), inputs, "quality.required_inputs")
    _references(quality.get("required_sections"), sections, "quality.required_sections")
    if not isinstance(quality.get("checks"), list) or any(not isinstance(check, str) for check in quality["checks"]) or not REQUIRED_CHECKS.issubset(quality["checks"]):
        raise ScenarioError(f"{scenario_id}/quality.yaml: required checks missing")
    if quality.get("formal_requires") != "all_required_checks_pass":
        raise ScenarioError(f"{scenario_id}/quality.yaml: formal release gate is required")
    delivery = manifest.get("delivery")
    if not isinstance(delivery, dict) or not {"md", "docx"}.issubset(delivery.get("required_formats", [])):
        raise ScenarioError(f"{scenario_id}/scenario.yaml: md and docx are required")
    return Scenario(manifest, outline, analysis, quality, digest.hexdigest())
