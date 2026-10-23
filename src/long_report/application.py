"""The current public application operations."""

from long_report.scenario import load_scenario, scenario_ids


def list_scenarios() -> list[dict]:
    return [load_scenario(scenario_id).summary() for scenario_id in scenario_ids()]


def get_scenario(scenario_id: str, version: str | None = None) -> dict:
    scenario = load_scenario(scenario_id)
    if version is not None and scenario.version != version:
        raise ValueError(f"{scenario_id}: requested version {version}, installed {scenario.version}")
    return scenario.as_dict()
