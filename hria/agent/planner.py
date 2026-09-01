from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from typing import Any

from hria.agent.contracts import ExecutionPlan, PlannedToolCall
from hria.config import get_settings
from hria.skills.contracts import Filters
from hria.skills.registry import schemas_for_planner


def _extract(pattern: str, question: str) -> str | None:
    match = re.search(pattern, question, re.IGNORECASE)
    return match.group(0).upper() if match else None


def extract_filters(question: str) -> Filters:
    revision_match = re.search(r"(?:revision|rev)\s+([A-Z])\b", question, re.IGNORECASE)
    return Filters(
        part_number=_extract(r"PN-\d+", question),
        lot_code=_extract(r"LOT-\d+", question),
        supplier=_extract(r"SUPPLIER-\d+", question),
        station=_extract(r"STATION-\d+", question),
        design_rev=revision_match.group(1).upper() if revision_match else None,
    )


class Planner(ABC):
    @abstractmethod
    def plan(self, question: str, validation_error: str | None = None) -> ExecutionPlan: ...


class RulePlanner(Planner):
    """Reproducible local planner for development, CI, and the no-key quickstart."""

    def plan(self, question: str, validation_error: str | None = None) -> ExecutionPlan:
        del validation_error
        lowered = question.lower()
        filters = extract_filters(question)
        filter_args = filters.model_dump(mode="json", exclude_none=True)
        if "schema" in lowered or "what data" in lowered:
            return ExecutionPlan(
                intent="schema_lookup",
                calls=[PlannedToolCall(tool="describe_schema", arguments={})],
            )
        if ("reliable" in lowered or "reliability" in lowered) and not any(filter_args.values()):
            return ExecutionPlan(
                intent="ambiguous_reliability",
                clarification=(
                    "Which part, lot, supplier, or design revision should I analyze, and do you "
                    "want observed failures, failure probability at a specific horizon, or B10 life?"
                ),
            )
        if not any(filter_args.values()) and any(
            phrase in lowered for phrase in ("b10", "lifetime", "weibull")
        ):
            return ExecutionPlan(
                intent="ambiguous_lifetime",
                clarification="Which part, lot, supplier, or design revision should I fit?",
            )
        if "b10" in lowered or "lifetime" in lowered or "weibull" in lowered:
            return ExecutionPlan(
                intent="lifetime_fit",
                calls=[
                    PlannedToolCall(tool="fit_lifetime", arguments={"filters": filter_args}),
                    PlannedToolCall(
                        tool="plot_spec",
                        arguments={"result_id": "$result:0", "chart": "survival"},
                        depends_on=[0],
                    ),
                ],
            )
        if "drift" in lowered or "trend" in lowered:
            station = filters.station
            parameter = next(
                (
                    value
                    for value in ("contact_resistance", "leakage_current", "output_voltage")
                    if value.replace("_", " ") in lowered or value in lowered
                ),
                "contact_resistance",
            )
            if station is None:
                return ExecutionPlan(
                    intent="ambiguous_trend",
                    clarification="Which station should I test for measurement drift?",
                )
            return ExecutionPlan(
                intent="trend_detection",
                calls=[
                    PlannedToolCall(
                        tool="measurement_trend",
                        arguments={"station": station, "param_name": parameter, "filters": {}},
                    )
                ],
            )
        if any(
            value in lowered for value in ("anomal", "which lot", "which supplier", "odd station")
        ):
            dimension = (
                "station"
                if "station" in lowered
                else "supplier"
                if "supplier" in lowered
                else "lot"
            )
            return ExecutionPlan(
                intent="anomaly_attribution",
                calls=[
                    PlannedToolCall(
                        tool="detect_anomalous_source",
                        arguments={"dimension": dimension, "filters": filter_args},
                    ),
                    PlannedToolCall(
                        tool="plot_spec",
                        arguments={"result_id": "$result:0", "chart": "point"},
                        depends_on=[0],
                    ),
                ],
            )
        if any(value in lowered for value in ("compare", "worse", "did revision", "fix")):
            lots = re.findall(r"LOT-\d+", question, re.IGNORECASE)
            suppliers = re.findall(r"SUPPLIER-\d+", question, re.IGNORECASE)
            revisions = re.findall(r"(?:revision|rev)\s+([A-Z])\b", question, re.IGNORECASE)
            if len(lots) >= 2:
                dimension, groups = "lot", [value.upper() for value in lots[:2]]
            elif len(suppliers) >= 2:
                dimension, groups = "supplier", [value.upper() for value in suppliers[:2]]
            elif len(revisions) >= 2:
                dimension, groups = "design_rev", [value.upper() for value in revisions[:2]]
            else:
                return ExecutionPlan(
                    intent="ambiguous_comparison",
                    clarification="Which two lots, suppliers, or design revisions should I compare?",
                )
            comparison_filters = {**filter_args}
            comparison_filters.pop(
                {"lot": "lot_code", "supplier": "supplier", "design_rev": "design_rev"}[dimension],
                None,
            )
            return ExecutionPlan(
                intent="group_comparison",
                calls=[
                    PlannedToolCall(
                        tool="compare_groups",
                        arguments={
                            "dimension": dimension,
                            "group_a": groups[0],
                            "group_b": groups[1],
                            "filters": comparison_filters,
                        },
                    )
                ],
            )
        if "run" in lowered and any(filter_args.values()):
            return ExecutionPlan(
                intent="test_run_lookup",
                calls=[PlannedToolCall(tool="query_test_runs", arguments={"filters": filter_args})],
            )
        if "failure" in lowered or "failed" in lowered:
            horizon_match = re.search(r"(?:by|at)\s+(\d+(?:\.\d+)?)\s*(?:h|hours?)", lowered)
            group_by = next(
                (value for value in ("lot", "supplier", "design_rev") if value in lowered), None
            )
            arguments: dict[str, Any] = {"filters": filter_args, "group_by": group_by}
            if horizon_match:
                arguments["horizon_hours"] = float(horizon_match.group(1))
            return ExecutionPlan(
                intent="failure_probability" if horizon_match else "observed_failure_proportion",
                calls=[
                    PlannedToolCall(tool="failure_rate", arguments=arguments),
                    PlannedToolCall(
                        tool="plot_spec",
                        arguments={"result_id": "$result:0", "chart": "bar"},
                        depends_on=[0],
                    ),
                ],
            )
        return ExecutionPlan(
            intent="unsupported",
            clarification=(
                "I can analyze failure probability, B10 lifetime, two-group survival, anomalous "
                "lots/suppliers/stations, measurement trends, or typed test-run history. Which do you need?"
            ),
        )


class OpenAIPlanner(Planner):
    """Optional Structured Outputs planner; tool execution remains entirely local."""

    def __init__(self) -> None:
        from openai import OpenAI

        settings = get_settings()
        self._model = settings.openai_model
        self._client = OpenAI(api_key=settings.openai_api_key)
        self.last_token_count = 0

    def plan(self, question: str, validation_error: str | None = None) -> ExecutionPlan:
        prompt = (
            "Create the smallest valid analysis plan. Ask one clarification when the statistical "
            "estimand, entity, horizon, or comparison groups are missing. Never calculate numbers. "
            "Only select from these tools:\n" + json.dumps(schemas_for_planner())
        )
        if validation_error:
            prompt += f"\nThe previous plan failed schema validation: {validation_error}"
        response = self._client.responses.parse(
            model=self._model,
            input=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": question},
            ],
            text_format=ExecutionPlan,
        )
        if response.output_parsed is None:
            raise RuntimeError("The planner returned no structured plan.")
        if response.usage is not None:
            self.last_token_count = response.usage.total_tokens
        return response.output_parsed


def build_planner() -> Planner:
    settings = get_settings()
    if settings.planner_provider == "openai":
        if not settings.openai_api_key:
            raise RuntimeError("PLANNER_PROVIDER=openai requires OPENAI_API_KEY")
        return OpenAIPlanner()
    return RulePlanner()
