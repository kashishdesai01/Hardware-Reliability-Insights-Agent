from __future__ import annotations

import argparse
import json
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any

import yaml
from prometheus_client import Gauge
from pydantic import BaseModel, Field

from hria.agent.pipeline import AgentPipeline
from hria.db import SessionLocal

EVAL_PASS_RATE = Gauge("hria_eval_pass_rate", "Latest evaluation pass rate", ["family"])


class NumericExpectation(BaseModel):
    path: str
    minimum: float | None = None
    maximum: float | None = None
    tolerance_of: float | None = None
    tolerance: float | None = None


class Expectations(BaseModel):
    tools: list[str] = Field(default_factory=list)
    args_contain: dict[str, Any] = Field(default_factory=dict)
    answer_contains_entity: str | None = None
    status: str | None = None
    numeric: list[NumericExpectation] = Field(default_factory=list)


class EvalCase(BaseModel):
    id: str
    family: str
    split: str = "development"
    question: str
    expects: Expectations


@dataclass
class CaseResult:
    case_id: str
    family: str
    passed: bool
    checks: dict[str, bool]
    latency_ms: float
    answer: str


def _contains(document: Any, expected: Any) -> bool:
    if isinstance(expected, dict):
        return isinstance(document, dict) and all(
            key in document and _contains(document[key], value) for key, value in expected.items()
        )
    if isinstance(expected, list):
        return isinstance(document, list) and all(value in document for value in expected)
    return document == expected


def _find_key(document: Any, key: str) -> list[Any]:
    values = []
    if isinstance(document, dict):
        for current_key, value in document.items():
            if current_key == key:
                values.append(value)
            values.extend(_find_key(value, key))
    elif isinstance(document, list):
        for value in document:
            values.extend(_find_key(value, key))
    return values


def evaluate_case(case: EvalCase) -> CaseResult:
    started = perf_counter()
    with SessionLocal() as session:
        answer = AgentPipeline().run(case.question, session)
    elapsed = (perf_counter() - started) * 1_000
    actual_tools = [call.tool for call in answer.plan.calls]
    checks = {
        "tool_selection": set(case.expects.tools).issubset(actual_tools),
        "argument_exactness": all(
            any(_contains(call.arguments, expected) for call in answer.plan.calls)
            for expected in ([case.expects.args_contain] if case.expects.args_contain else [])
        ),
        "entity": case.expects.answer_contains_entity is None
        or case.expects.answer_contains_entity.lower() in answer.answer.lower(),
        "status": case.expects.status is None or answer.status == case.expects.status,
    }
    serialized = answer.model_dump(mode="json")
    for index, expectation in enumerate(case.expects.numeric):
        values = [
            float(value)
            for value in _find_key(serialized, expectation.path)
            if isinstance(value, (int, float))
        ]
        numeric_pass = bool(values)
        if expectation.minimum is not None:
            numeric_pass = numeric_pass and any(value >= expectation.minimum for value in values)
        if expectation.maximum is not None:
            numeric_pass = numeric_pass and any(value <= expectation.maximum for value in values)
        if expectation.tolerance_of is not None and expectation.tolerance is not None:
            numeric_pass = numeric_pass and any(
                abs(value - expectation.tolerance_of) <= expectation.tolerance for value in values
            )
        checks[f"numeric_{index}"] = numeric_pass
    return CaseResult(
        case_id=case.id,
        family=case.family,
        passed=all(checks.values()),
        checks=checks,
        latency_ms=elapsed,
        answer=answer.answer,
    )


def load_cases(path: Path, split: str | None = None) -> list[EvalCase]:
    cases = [
        EvalCase.model_validate(yaml.safe_load(file.read_text()))
        for file in sorted(path.glob("*.yaml"))
    ]
    return [case for case in cases if split is None or case.split == split]


def run(cases_path: Path, split: str | None = None) -> dict[str, Any]:
    results = [evaluate_case(case) for case in load_cases(cases_path, split)]
    families: dict[str, list[CaseResult]] = defaultdict(list)
    for result in results:
        families[result.family].append(result)
    per_family = {
        family: {
            "passed": sum(result.passed for result in values),
            "total": len(values),
            "pass_rate": sum(result.passed for result in values) / len(values),
            "p95_latency_ms": sorted(result.latency_ms for result in values)[
                min(len(values) - 1, int(0.95 * len(values)))
            ],
        }
        for family, values in families.items()
    }
    for family, metrics in per_family.items():
        EVAL_PASS_RATE.labels(family=family).set(metrics["pass_rate"])
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "split": split or "all",
        "passed": sum(result.passed for result in results),
        "total": len(results),
        "per_family": per_family,
        "cases": [asdict(result) for result in results],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=Path, default=Path("hria/evals/cases"))
    parser.add_argument("--split", choices=["development", "held_out"])
    parser.add_argument("--output", type=Path, default=Path("hria/evals/reports/latest.json"))
    args = parser.parse_args()
    report = run(args.cases, args.split)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True))
    print(json.dumps(report["per_family"], indent=2, sort_keys=True))
    if report["passed"] != report["total"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
