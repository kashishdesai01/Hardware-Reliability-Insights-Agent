from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from time import perf_counter
from typing import Any, Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field
from scipy.stats import fisher_exact
from sqlalchemy import Select, and_, func, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from hria.config import get_settings
from hria.data.models import (
    Base,
    DatasetManifest,
    FailureMode,
    Lot,
    Measurement,
    Part,
    Supplier,
    TestEpisode,
    TestProtocol,
    TestRun,
    TestStation,
    Unit,
    UnitOutcome,
)
from hria.skills.contracts import (
    Filters,
    InsufficientData,
    Provenance,
    ToolResult,
    ToolSuccess,
    new_result_id,
    new_tool_call_id,
)
from hria.skills.store import result_store
from hria.stats.lifetime import acceleration_factor, fit_weibull_censored
from hria.stats.multiple import benjamini_hochberg
from hria.stats.proportions import wilson_interval
from hria.stats.survival import kaplan_meier_at, log_rank_test
from hria.stats.trend import measurement_trend


class ToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DescribeSchemaInput(ToolInput):
    pass


class QueryTestRunsInput(ToolInput):
    filters: Filters = Field(default_factory=Filters)
    limit: int = Field(default=50, ge=1, le=200)


class FailureRateInput(ToolInput):
    filters: Filters = Field(default_factory=Filters)
    group_by: Literal["lot", "supplier", "design_rev"] | None = None
    horizon_hours: float | None = Field(default=None, gt=0)
    minimum_units: int = Field(default=30, ge=5)


class FitLifetimeInput(ToolInput):
    filters: Filters = Field(default_factory=Filters)
    minimum_failures: int = Field(default=5, ge=5)


class CompareGroupsInput(ToolInput):
    dimension: Literal["lot", "supplier", "design_rev"]
    group_a: str
    group_b: str
    filters: Filters = Field(default_factory=Filters)
    minimum_units: int = Field(default=30, ge=5)
    minimum_failures: int = Field(default=5, ge=1)


class DetectAnomalousSourceInput(ToolInput):
    dimension: Literal["lot", "supplier", "station"]
    filters: Filters = Field(default_factory=Filters)
    minimum_units: int = Field(default=30, ge=5)


class MeasurementTrendInput(ToolInput):
    station: str
    param_name: str
    filters: Filters = Field(default_factory=Filters)


class PlotSpecInput(ToolInput):
    result_id: str
    chart: Literal["bar", "point", "survival"] = "bar"


def _compiled(statement: Select[Any]) -> str:
    return str(
        statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": False})
    )


def _dataset_version(session: Session) -> str:
    value = session.scalar(
        select(DatasetManifest.dataset_version).order_by(DatasetManifest.id.desc())
    )
    return value or get_settings().dataset_version


def _filters_dict(filters: Filters) -> dict[str, Any]:
    return filters.model_dump(mode="json", exclude_none=True)


def _base_outcome_statement() -> Select[Any]:
    return (
        select(
            TestEpisode.id.label("episode_id"),
            UnitOutcome.observed_duration_hours,
            UnitOutcome.event_observed,
            UnitOutcome.failure_mode,
            Unit.id.label("unit_id"),
            Unit.build_date,
            Lot.lot_code,
            Supplier.name.label("supplier"),
            Part.part_number,
            Part.design_rev,
            TestProtocol.name.label("protocol"),
        )
        .join(UnitOutcome, UnitOutcome.episode_id == TestEpisode.id)
        .join(Unit, Unit.id == TestEpisode.unit_id)
        .join(Lot, Lot.id == Unit.lot_id)
        .join(Supplier, Supplier.id == Lot.supplier_id)
        .join(Part, Part.id == Lot.part_id)
        .join(TestProtocol, TestProtocol.id == TestEpisode.protocol_id)
    )


def _apply_filters(statement: Select[Any], filters: Filters) -> Select[Any]:
    conditions = []
    if filters.part_number:
        conditions.append(Part.part_number == filters.part_number)
    if filters.lot_code:
        conditions.append(Lot.lot_code == filters.lot_code)
    if filters.supplier:
        conditions.append(Supplier.name == filters.supplier)
    if filters.design_rev:
        conditions.append(Part.design_rev == filters.design_rev)
    if filters.protocol:
        conditions.append(TestProtocol.name == filters.protocol)
    if filters.built_from:
        conditions.append(Unit.build_date >= filters.built_from)
    if filters.built_to:
        conditions.append(Unit.build_date <= filters.built_to)
    return statement.where(and_(*conditions)) if conditions else statement


def _provenance(
    *,
    session: Session,
    call_id: str,
    result_id: str,
    statement: Select[Any],
    row_count: int,
    filters: dict[str, Any],
    started: float,
    excluded: int = 0,
) -> Provenance:
    return Provenance(
        tool_call_id=call_id,
        result_id=result_id,
        dataset_version=_dataset_version(session),
        sql=_compiled(statement),
        row_count=row_count,
        excluded_row_count=excluded,
        filters_applied=filters,
        elapsed_ms=(perf_counter() - started) * 1_000,
        generated_at=datetime.now(UTC),
    )


def _store(result: ToolResult) -> ToolResult:
    result_store.put(result)
    return result


def describe_schema(_: DescribeSchemaInput, session: Session) -> ToolResult:
    started, call_id, result_id = perf_counter(), new_tool_call_id(), new_result_id()
    statement = select(DatasetManifest.dataset_version).limit(1)
    tables = {
        table.name: {
            "columns": [column.name for column in table.columns],
            "primary_key": [column.name for column in table.primary_key.columns],
        }
        for table in Base.metadata.sorted_tables
    }
    result = ToolSuccess(
        data={
            "tables": tables,
            "enums": {"failure_mode": [value.value for value in FailureMode]},
        },
        provenance=_provenance(
            session=session,
            call_id=call_id,
            result_id=result_id,
            statement=statement,
            row_count=len(tables),
            filters={},
            started=started,
        ),
    )
    return _store(result)


def query_test_runs(args: QueryTestRunsInput, session: Session) -> ToolResult:
    started, call_id, result_id = perf_counter(), new_tool_call_id(), new_result_id()
    statement = (
        select(
            TestRun.id,
            Unit.serial,
            Lot.lot_code,
            Part.part_number,
            TestStation.name.label("station"),
            TestRun.start_at,
            TestRun.end_at,
            TestRun.stress_temp_c,
            TestRun.stress_voltage_v,
        )
        .join(TestEpisode, TestEpisode.id == TestRun.episode_id)
        .join(Unit, Unit.id == TestEpisode.unit_id)
        .join(Lot, Lot.id == Unit.lot_id)
        .join(Supplier, Supplier.id == Lot.supplier_id)
        .join(Part, Part.id == Lot.part_id)
        .join(TestProtocol, TestProtocol.id == TestEpisode.protocol_id)
        .join(TestStation, TestStation.id == TestRun.station_id)
    )
    statement = _apply_filters(statement, args.filters)
    if args.filters.station:
        statement = statement.where(TestStation.name == args.filters.station)
    total = session.scalar(select(func.count()).select_from(statement.subquery())) or 0
    rows = (
        session.execute(statement.order_by(TestRun.start_at.desc()).limit(args.limit))
        .mappings()
        .all()
    )
    data_rows = [
        {
            key: str(value) if not isinstance(value, (str, int, float, type(None))) else value
            for key, value in row.items()
        }
        for row in rows
    ]
    result = ToolSuccess(
        data={"rows": data_rows, "total_count": total, "returned_count": len(rows)},
        provenance=_provenance(
            session=session,
            call_id=call_id,
            result_id=result_id,
            statement=statement,
            row_count=total,
            filters=_filters_dict(args.filters),
            started=started,
        ),
        caveats=[f"Only the first {args.limit} typed records are returned."]
        if total > args.limit
        else [],
    )
    return _store(result)


def failure_rate(args: FailureRateInput, session: Session) -> ToolResult:
    started, call_id, result_id = perf_counter(), new_tool_call_id(), new_result_id()
    statement = _apply_filters(_base_outcome_statement(), args.filters)
    rows = session.execute(statement).mappings().all()
    provenance = _provenance(
        session=session,
        call_id=call_id,
        result_id=result_id,
        statement=statement,
        row_count=len(rows),
        filters=_filters_dict(args.filters),
        started=started,
    )
    if len(rows) < args.minimum_units:
        return _store(
            InsufficientData(
                reason="The cohort is below the configured precision floor.",
                observed={"n_units": len(rows)},
                required={"minimum_units": args.minimum_units},
                provenance=provenance,
            )
        )

    group_field = {"lot": "lot_code", "supplier": "supplier", "design_rev": "design_rev"}.get(
        args.group_by
    )
    grouped: dict[str, list[Any]] = defaultdict(list)
    for row in rows:
        grouped[str(row[group_field]) if group_field else "all"].append(row)
    outputs = []
    caveats: list[str] = []
    for name, values in sorted(grouped.items()):
        if len(values) < args.minimum_units:
            outputs.append({"group": name, "status": "insufficient_data", "n_units": len(values)})
            continue
        failed = sum(bool(value["event_observed"]) for value in values)
        proportion = wilson_interval(failed, len(values))
        group_data: dict[str, Any] = {
            "group": name,
            "n_units": len(values),
            "n_failed": failed,
            "observed_failure_proportion": proportion.proportion,
            "wilson_95_ci": list(proportion.confidence_interval),
        }
        censoring_fraction = 1.0 - failed / len(values)
        if args.horizon_hours is not None:
            survival = kaplan_meier_at(
                [float(value["observed_duration_hours"]) for value in values],
                [bool(value["event_observed"]) for value in values],
                args.horizon_hours,
            )
            group_data["horizon_hours"] = args.horizon_hours
            group_data["failure_probability_at_horizon"] = survival.failure_probability
            group_data["failure_probability_95_ci"] = list(survival.confidence_interval)
            group_data["survival_method"] = survival.method
        elif censoring_fraction > 0.5:
            caveats.append(
                f"Group {name} is {censoring_fraction:.1%} censored; the observed proportion is not lifetime risk."
            )
        outputs.append(group_data)
    return _store(
        ToolSuccess(
            data={"groups": outputs, "confidence_level": 0.95},
            provenance=provenance,
            caveats=caveats,
        )
    )


def _episode_exposures(
    statement: Select[Any], session: Session
) -> tuple[list[float], list[bool], int]:
    rows = session.execute(statement).mappings().all()
    episodes: dict[int, dict[str, Any]] = {}
    for row in rows:
        episode = episodes.setdefault(
            row["episode_id"],
            {"duration": 0.0, "event": bool(row["event_observed"])},
        )
        segment_duration = (row["end_at"] - row["start_at"]).total_seconds() / 3_600
        factor = acceleration_factor(
            stress_temp_c=[float(row["stress_temp_c"])],
            use_temp_c=float(row["use_condition_temp_c"]),
            stress_voltage_v=[float(row["stress_voltage_v"])],
            use_voltage_v=float(row["use_condition_voltage_v"]),
        )[0]
        episode["duration"] += segment_duration * float(factor)
    return (
        [value["duration"] for value in episodes.values()],
        [value["event"] for value in episodes.values()],
        len(rows),
    )


def _lifetime_statement(filters: Filters) -> Select[Any]:
    statement = (
        select(
            TestEpisode.id.label("episode_id"),
            UnitOutcome.event_observed,
            TestRun.start_at,
            TestRun.end_at,
            TestRun.stress_temp_c,
            TestRun.stress_voltage_v,
            TestProtocol.use_condition_temp_c,
            TestProtocol.use_condition_voltage_v,
        )
        .join(UnitOutcome, UnitOutcome.episode_id == TestEpisode.id)
        .join(Unit, Unit.id == TestEpisode.unit_id)
        .join(Lot, Lot.id == Unit.lot_id)
        .join(Supplier, Supplier.id == Lot.supplier_id)
        .join(Part, Part.id == Lot.part_id)
        .join(TestProtocol, TestProtocol.id == TestEpisode.protocol_id)
        .join(TestRun, TestRun.episode_id == TestEpisode.id)
    )
    return _apply_filters(statement, filters)


def fit_lifetime(args: FitLifetimeInput, session: Session) -> ToolResult:
    started, call_id, result_id = perf_counter(), new_tool_call_id(), new_result_id()
    statement = _lifetime_statement(args.filters)
    durations, events, row_count = _episode_exposures(statement, session)
    provenance = _provenance(
        session=session,
        call_id=call_id,
        result_id=result_id,
        statement=statement,
        row_count=row_count,
        filters=_filters_dict(args.filters),
        started=started,
    )
    failures = sum(events)
    if failures < args.minimum_failures:
        return _store(
            InsufficientData(
                reason="A stable censored Weibull fit requires more observed failures.",
                observed={"n_units": len(events), "n_failed": failures},
                required={"minimum_failures": args.minimum_failures},
                provenance=provenance,
            )
        )
    try:
        fit = fit_weibull_censored(durations, events, minimum_failures=args.minimum_failures)
    except (ValueError, RuntimeError) as exc:
        return _store(
            InsufficientData(
                reason=str(exc),
                observed={"n_units": len(events), "n_failed": failures},
                required={"identifiable_fit": True},
                provenance=provenance,
            )
        )
    data = {
        "beta": fit.beta,
        "beta_95_ci": list(fit.beta_ci),
        "eta_use_hours": fit.eta,
        "eta_95_ci": list(fit.eta_ci),
        "b10_use_hours": fit.b10,
        "b10_95_ci": list(fit.b10_ci),
        "n_failed": fit.n_failed,
        "n_censored": fit.n_censored,
        "confidence_level": 0.95,
        "method": fit.method,
    }
    caveats = [
        "All stress segments were transformed to equivalent use-condition exposure before fitting."
    ]
    return _store(ToolSuccess(data=data, provenance=provenance, caveats=caveats))


def compare_groups(args: CompareGroupsInput, session: Session) -> ToolResult:
    started, call_id, result_id = perf_counter(), new_tool_call_id(), new_result_id()
    column = {"lot": Lot.lot_code, "supplier": Supplier.name, "design_rev": Part.design_rev}[
        args.dimension
    ]
    statement = _lifetime_statement(args.filters).add_columns(column.label("comparison_group"))
    statement = statement.where(column.in_([args.group_a, args.group_b]))
    rows = session.execute(statement).mappings().all()
    grouped_rows = {
        value: [row for row in rows if row["comparison_group"] == value]
        for value in (args.group_a, args.group_b)
    }
    grouped: dict[str, tuple[list[float], list[bool]]] = {}
    for name, values in grouped_rows.items():
        episode_values: dict[int, tuple[float, bool]] = {}
        for row in values:
            duration, event = episode_values.get(
                row["episode_id"], (0.0, bool(row["event_observed"]))
            )
            segment = (row["end_at"] - row["start_at"]).total_seconds() / 3_600
            factor = acceleration_factor(
                stress_temp_c=[float(row["stress_temp_c"])],
                use_temp_c=float(row["use_condition_temp_c"]),
                stress_voltage_v=[float(row["stress_voltage_v"])],
                use_voltage_v=float(row["use_condition_voltage_v"]),
            )[0]
            episode_values[row["episode_id"]] = (duration + segment * float(factor), event)
        grouped[name] = (
            [value[0] for value in episode_values.values()],
            [value[1] for value in episode_values.values()],
        )
    provenance = _provenance(
        session=session,
        call_id=call_id,
        result_id=result_id,
        statement=statement,
        row_count=len(rows),
        filters={**_filters_dict(args.filters), "dimension": args.dimension},
        started=started,
    )
    for name, (durations, events) in grouped.items():
        if len(durations) < args.minimum_units or sum(events) < args.minimum_failures:
            return _store(
                InsufficientData(
                    reason=f"Group {name} is below the comparison floor.",
                    observed={"group": name, "n_units": len(durations), "n_failed": sum(events)},
                    required={
                        "minimum_units": args.minimum_units,
                        "minimum_failures": args.minimum_failures,
                    },
                    provenance=provenance,
                )
            )
    result = log_rank_test(*grouped[args.group_a], *grouped[args.group_b])
    return _store(
        ToolSuccess(
            data={
                "group_a": args.group_a,
                "group_b": args.group_b,
                "n_a": len(grouped[args.group_a][0]),
                "n_b": len(grouped[args.group_b][0]),
                "log_rank_chi_square": result.chi_square,
                "p_value": result.p_value,
                "method": result.method,
            },
            provenance=provenance,
            caveats=["The log-rank test does not estimate a hazard ratio."],
        )
    )


def detect_anomalous_source(args: DetectAnomalousSourceInput, session: Session) -> ToolResult:
    started, call_id, result_id = perf_counter(), new_tool_call_id(), new_result_id()
    if args.dimension == "station":
        statement = _apply_filters(_base_outcome_statement(), args.filters)
        statement = (
            statement.add_columns(TestStation.name.label("level"))
            .join(TestRun, TestRun.id == UnitOutcome.terminal_run_id)
            .join(TestStation, TestStation.id == TestRun.station_id)
        )
    else:
        statement = _apply_filters(_base_outcome_statement(), args.filters)
        field = Lot.lot_code if args.dimension == "lot" else Supplier.name
        statement = statement.add_columns(field.label("level"))
    rows = session.execute(statement).mappings().all()
    levels: dict[str, list[bool]] = defaultdict(list)
    for row in rows:
        levels[str(row["level"])].append(bool(row["event_observed"]))
    provenance = _provenance(
        session=session,
        call_id=call_id,
        result_id=result_id,
        statement=statement,
        row_count=len(rows),
        filters={**_filters_dict(args.filters), "dimension": args.dimension},
        started=started,
    )
    eligible = {
        name: values for name, values in levels.items() if len(values) >= args.minimum_units
    }
    if len(eligible) < 3:
        return _store(
            InsufficientData(
                reason="Anomaly detection requires at least three eligible levels.",
                observed={"eligible_levels": len(eligible), "total_levels": len(levels)},
                required={"minimum_levels": 3, "minimum_units_per_level": args.minimum_units},
                provenance=provenance,
            )
        )
    p_values = []
    summaries = []
    for name, values in eligible.items():
        own_failed = sum(values)
        rest = [event for other, group in eligible.items() if other != name for event in group]
        rest_failed = sum(rest)
        odds_ratio, p_value = fisher_exact(
            [[own_failed, len(values) - own_failed], [rest_failed, len(rest) - rest_failed]],
            alternative="greater",
        )
        p_values.append(p_value)
        summaries.append(
            {
                "level": name,
                "n_units": len(values),
                "n_failed": own_failed,
                "observed_failure_proportion": own_failed / len(values),
                "odds_ratio_vs_pooled_rest": float(odds_ratio),
                "p_value": float(p_value),
            }
        )
    q_values = benjamini_hochberg(p_values)
    for summary, q_value in zip(summaries, q_values, strict=True):
        summary["q_value_bh"] = float(q_value)
    summaries.sort(key=lambda value: (value["q_value_bh"], -value["observed_failure_proportion"]))
    return _store(
        ToolSuccess(
            data={"dimension": args.dimension, "ranked_levels": summaries},
            provenance=provenance,
            caveats=[
                "Each level is compared with the pooled eligible remainder; q-values use Benjamini-Hochberg correction.",
                "Observed proportions do not estimate lifetime risk when follow-up differs.",
            ],
        )
    )


def measurement_trend_tool(args: MeasurementTrendInput, session: Session) -> ToolResult:
    started, call_id, result_id = perf_counter(), new_tool_call_id(), new_result_id()
    statement = (
        select(Measurement.value, Measurement.captured_at)
        .join(TestRun, TestRun.id == Measurement.run_id)
        .join(TestStation, TestStation.id == TestRun.station_id)
        .where(TestStation.name == args.station, Measurement.param_name == args.param_name)
        .order_by(Measurement.captured_at)
    )
    rows = session.execute(statement).all()
    provenance = _provenance(
        session=session,
        call_id=call_id,
        result_id=result_id,
        statement=statement,
        row_count=len(rows),
        filters={"station": args.station, "param_name": args.param_name},
        started=started,
    )
    if not rows:
        return _store(
            InsufficientData(
                reason="No measurements matched the requested station and parameter.",
                observed={"n_points": 0},
                required={"minimum_points": 20, "minimum_span_days": 14},
                provenance=provenance,
            )
        )
    first = rows[0].captured_at
    days = [(row.captured_at - first).total_seconds() / 86_400 for row in rows]
    values = np.asarray([float(row.value) for row in rows])
    residuals = values - np.median(values)
    try:
        result = measurement_trend(days, residuals)
    except ValueError as exc:
        return _store(
            InsufficientData(
                reason=str(exc),
                observed={"n_points": len(rows), "span_days": max(days) - min(days)},
                required={"minimum_points": 20, "minimum_span_days": 14},
                provenance=provenance,
            )
        )
    return _store(
        ToolSuccess(
            data={
                "station": args.station,
                "param_name": args.param_name,
                "slope_per_day": result.slope_per_day,
                "slope_95_ci": list(result.slope_ci),
                "p_value": result.p_value,
                "breakpoint_day": result.breakpoint_day,
                "n_points": result.n_points,
                "span_days": result.span_days,
                "method": result.method,
            },
            provenance=provenance,
            caveats=[
                "Values are median-centered within the selected parameter; v1 does not adjust for changing part mix."
            ],
        )
    )


def plot_spec(args: PlotSpecInput, session: Session) -> ToolResult:
    started, call_id, result_id = perf_counter(), new_tool_call_id(), new_result_id()
    source = result_store.get(args.result_id)
    statement = select(DatasetManifest.dataset_version).limit(1)
    provenance = _provenance(
        session=session,
        call_id=call_id,
        result_id=result_id,
        statement=statement,
        row_count=1 if source else 0,
        filters={"source_result_id": args.result_id, "chart": args.chart},
        started=started,
    )
    if source is None or source.status != "success":
        return _store(
            InsufficientData(
                reason="The referenced successful result is not available in this process.",
                observed={"result_id": args.result_id},
                required={"successful_result": True},
                provenance=provenance,
            )
        )
    data = source.data
    chart_values: list[dict[str, float]] | None = None
    if "groups" in data:
        spec = {
            "$schema": "https://vega.github.io/schema/vega-lite/v6.json",
            "data": {"name": args.result_id},
            "mark": {"type": "bar", "tooltip": True},
            "encoding": {
                "x": {"field": "group", "type": "nominal"},
                "y": {"field": "observed_failure_proportion", "type": "quantitative"},
            },
        }
    elif "ranked_levels" in data:
        spec = {
            "$schema": "https://vega.github.io/schema/vega-lite/v6.json",
            "data": {"name": args.result_id},
            "mark": {"type": "point", "tooltip": True},
            "encoding": {
                "x": {"field": "level", "type": "nominal"},
                "y": {"field": "observed_failure_proportion", "type": "quantitative"},
                "color": {"field": "q_value_bh", "type": "quantitative"},
            },
        }
    elif {"beta", "eta_use_hours"}.issubset(data):
        beta, eta = float(data["beta"]), float(data["eta_use_hours"])
        times = np.linspace(0.0, eta * 1.25, 61)
        chart_values = [
            {
                "use_condition_hours": float(value),
                "survival_probability": float(np.exp(-((value / eta) ** beta))),
            }
            for value in times
        ]
        spec = {
            "$schema": "https://vega.github.io/schema/vega-lite/v6.json",
            "data": {"name": args.result_id},
            "mark": {"type": "line", "tooltip": True},
            "encoding": {
                "x": {
                    "field": "use_condition_hours",
                    "type": "quantitative",
                    "title": "Use-condition hours",
                },
                "y": {
                    "field": "survival_probability",
                    "type": "quantitative",
                    "title": "Survival probability",
                    "scale": {"domain": [0, 1]},
                },
            },
        }
    else:
        spec = {
            "$schema": "https://vega.github.io/schema/vega-lite/v6.json",
            "data": {"name": args.result_id},
            "mark": {"type": "point", "tooltip": True},
        }
    return _store(
        ToolSuccess(
            data={
                "source_result_id": args.result_id,
                "vega_lite": spec,
                **({"chart_values": chart_values} if chart_values is not None else {}),
            },
            provenance=provenance,
            caveats=[
                "The specification references validated result data and embeds no generated values."
            ],
        )
    )
