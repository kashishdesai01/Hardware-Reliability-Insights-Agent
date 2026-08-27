from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel
from sqlalchemy.orm import Session

from hria.skills.contracts import ToolResult
from hria.skills.tools import (
    CompareGroupsInput,
    DescribeSchemaInput,
    DetectAnomalousSourceInput,
    FailureRateInput,
    FitLifetimeInput,
    MeasurementTrendInput,
    PlotSpecInput,
    QueryTestRunsInput,
    compare_groups,
    describe_schema,
    detect_anomalous_source,
    failure_rate,
    fit_lifetime,
    measurement_trend_tool,
    plot_spec,
    query_test_runs,
)


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    input_model: type[BaseModel]
    function: Callable[[Any, Session], ToolResult]
    description: str


TOOL_REGISTRY = {
    definition.name: definition
    for definition in [
        ToolDefinition(
            "describe_schema",
            DescribeSchemaInput,
            describe_schema,
            "Describe typed tables and enums.",
        ),
        ToolDefinition(
            "query_test_runs",
            QueryTestRunsInput,
            query_test_runs,
            "Return a bounded typed test-run projection.",
        ),
        ToolDefinition(
            "failure_rate",
            FailureRateInput,
            failure_rate,
            "Estimate observed proportions and optional fixed-horizon risk.",
        ),
        ToolDefinition(
            "fit_lifetime",
            FitLifetimeInput,
            fit_lifetime,
            "Fit a right-censored accelerated Weibull lifetime model.",
        ),
        ToolDefinition(
            "compare_groups",
            CompareGroupsInput,
            compare_groups,
            "Compare two censored survival distributions by log-rank test.",
        ),
        ToolDefinition(
            "detect_anomalous_source",
            DetectAnomalousSourceInput,
            detect_anomalous_source,
            "Rank levels against pooled rest with BH correction.",
        ),
        ToolDefinition(
            "measurement_trend",
            MeasurementTrendInput,
            measurement_trend_tool,
            "Estimate a measurement trend and candidate breakpoint.",
        ),
        ToolDefinition(
            "plot_spec",
            PlotSpecInput,
            plot_spec,
            "Create a safe Vega-Lite template for a prior result.",
        ),
    ]
}


def schemas_for_planner() -> list[dict[str, Any]]:
    return [
        {
            "name": definition.name,
            "description": definition.description,
            "input_schema": definition.input_model.model_json_schema(),
        }
        for definition in TOOL_REGISTRY.values()
    ]
