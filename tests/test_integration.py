from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from hria.agent.pipeline import AgentPipeline
from hria.data.models import DatasetManifest, IngestionIssue, IssueCode
from hria.db import SessionLocal
from hria.evals.oracle import Oracle
from hria.evals.runner import EvalCase, evaluate_case, load_cases
from hria.skills.registry import TOOL_REGISTRY, schemas_for_planner
from hria.skills.store import ResultStore
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

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module", autouse=True)
def require_seeded_database() -> None:
    if os.environ.get("HRIA_RUN_INTEGRATION") != "1":
        pytest.skip("set HRIA_RUN_INTEGRATION=1 with a seeded HRIA database")
    with SessionLocal() as session:
        assert session.scalar(select(func.count()).select_from(DatasetManifest)) == 1


def test_oracle_and_dirty_data_are_visible() -> None:
    with SessionLocal() as session:
        oracle = Oracle.from_database(session)
        assert 0.60 <= oracle.censoring_fraction <= 0.75
        assert oracle.planted_entity("bad_lot") == "LOT-0042"
        counts = dict(
            session.execute(
                select(IngestionIssue.issue_code, func.count()).group_by(IngestionIssue.issue_code)
            ).all()
        )
    assert counts[IssueCode.DUPLICATE_SERIAL] > 0
    assert counts[IssueCode.MISSING_MEASUREMENTS] > 0
    assert counts[IssueCode.END_BEFORE_START] == 2
    assert counts[IssueCode.NEGATIVE_DURATION] == 1


def test_registered_tools_execute_and_produce_evidence() -> None:
    with SessionLocal() as session:
        schema = describe_schema(DescribeSchemaInput(), session)
        assert schema.status == "success"
        assert "unit_outcome" in schema.data["tables"]

        lookup = query_test_runs(
            QueryTestRunsInput(filters={"lot_code": "LOT-0042"}, limit=3), session
        )
        assert lookup.status == "success"
        assert lookup.data["returned_count"] == 3
        assert lookup.data["total_count"] > 3

        rate = failure_rate(
            FailureRateInput(filters={"part_number": "PN-4471"}, horizon_hours=500),
            session,
        )
        assert rate.status == "success"
        assert rate.data["groups"][0]["failure_probability_at_horizon"] > 0

        lifetime = fit_lifetime(FitLifetimeInput(filters={"part_number": "PN-4471"}), session)
        assert lifetime.status == "success"
        assert lifetime.data["method"] == "mle_censored"

        chart = plot_spec(PlotSpecInput(result_id=rate.provenance.result_id, chart="bar"), session)
        assert chart.status == "success"
        assert chart.data["vega_lite"]["data"]["name"] == rate.provenance.result_id


def test_planted_anomaly_and_drift_are_recovered() -> None:
    with SessionLocal() as session:
        anomaly = detect_anomalous_source(
            DetectAnomalousSourceInput(dimension="lot", filters={"part_number": "PN-4471"}),
            session,
        )
        trend = measurement_trend_tool(
            MeasurementTrendInput(station="STATION-007", param_name="contact_resistance"),
            session,
        )
    assert anomaly.status == "success"
    assert anomaly.data["ranked_levels"][0]["level"] == "LOT-0042"
    assert anomaly.data["ranked_levels"][0]["q_value_bh"] < 0.05
    assert trend.status == "success"
    assert trend.data["slope_95_ci"][0] > 0


def test_comparison_abstention_and_result_store() -> None:
    with SessionLocal() as session:
        comparison = compare_groups(
            CompareGroupsInput(dimension="lot", group_a="LOT-0001", group_b="LOT-0002"),
            session,
        )
        missing = failure_rate(FailureRateInput(filters={"lot_code": "LOT-9999"}), session)
    assert comparison.status in {"success", "insufficient_data"}
    assert missing.status == "insufficient_data"
    store = ResultStore(maximum_results=1)
    store.put(missing)
    assert store.get(missing.provenance.result_id) is missing


def test_agent_pipeline_answers_clarifies_and_chains_plot() -> None:
    pipeline = AgentPipeline()
    with SessionLocal() as session:
        answer = pipeline.run("What is the failure probability for PN-4471 by 500 hours?", session)
        clarification = pipeline.run("Is this part reliable?", session)
    assert answer.status == "answered"
    assert any("vega_lite" in result.get("data", {}) for result in answer.tool_results)
    assert answer.claims[0].evidence
    assert clarification.status == "clarification"


def test_eval_case_loading_and_scoring() -> None:
    cases = load_cases(Path("hria/evals/cases"), split="development")
    assert len(cases) == 40
    case = EvalCase(
        id="integration",
        family="ambiguous",
        question="Is this part reliable?",
        expects={"status": "clarification"},
    )
    result = evaluate_case(case)
    assert result.passed


def test_tool_registry_exposes_json_schemas() -> None:
    schemas = schemas_for_planner()
    assert len(schemas) == len(TOOL_REGISTRY) == 8
    assert all("input_schema" in schema for schema in schemas)


def test_http_api_query_metrics_and_result_lookup() -> None:
    from hria.api.main import app

    with TestClient(app) as client:
        live = client.get("/health/live")
        response = client.post("/api/query", json={"question": "What is the B10 life of PN-4471?"})
        metrics = client.get("/metrics")
        result_id = response.json()["claims"][0]["evidence"][0]["result_id"]
        evidence = client.get(f"/api/results/{result_id}")
        missing = client.get("/api/results/result-missing")
        catalog = client.get("/api/explorer/catalog")
        eval_report = client.get("/api/evals/latest")
    assert live.status_code == 200
    assert response.status_code == 200
    assert response.json()["status"] == "answered"
    assert "hria_request_latency_seconds" in metrics.text
    assert evidence.status_code == 200
    assert missing.status_code == 404
    assert "PN-4471" in catalog.json()["parts"]
    assert eval_report.json()["passed"] == 64


def test_manifest_truth_is_json() -> None:
    with SessionLocal() as session:
        raw = session.scalar(select(DatasetManifest.truth_json))
    assert json.loads(raw)["signals"]["bad_supplier"]["supplier"] == "SUPPLIER-03"
