from datetime import UTC, datetime

from hria.agent.grounding import ungrounded_numerals, validate_claims
from hria.agent.planner import RulePlanner
from hria.agent.synthesis import synthesize
from hria.skills.contracts import Provenance, ToolSuccess


def provenance() -> Provenance:
    return Provenance(
        tool_call_id="call-test",
        result_id="result-test",
        dataset_version="test",
        sql="SELECT 1",
        row_count=100,
        excluded_row_count=0,
        filters_applied={},
        elapsed_ms=1.0,
        generated_at=datetime.now(UTC),
    )


def test_rule_planner_requests_clarification_for_ambiguous_reliability() -> None:
    plan = RulePlanner().plan("Is this part reliable?")
    assert plan.clarification
    assert plan.calls == []


def test_rule_planner_extracts_lifetime_filter() -> None:
    plan = RulePlanner().plan("What is the B10 life of PN-4471 at use conditions?")
    assert plan.calls[0].tool == "fit_lifetime"
    assert plan.calls[0].arguments["filters"]["part_number"] == "PN-4471"


def test_synthesis_numbers_are_linked_to_result_paths() -> None:
    result = ToolSuccess(
        data={
            "b10_use_hours": 1200.0,
            "b10_95_ci": [900.0, 1500.0],
            "n_failed": 8,
            "n_censored": 22,
            "confidence_level": 0.95,
        },
        provenance=provenance(),
    )
    text, claims, status = synthesize([result])
    assert status == "answered"
    assert validate_claims(claims, [result]) == []
    assert ungrounded_numerals(text, claims) == []


def test_ungrounded_number_is_detected() -> None:
    assert ungrounded_numerals("The estimate is 17.2%.", []) == ["17.2%"]
