from __future__ import annotations

from collections.abc import Callable
from time import perf_counter
from typing import Any

from opentelemetry import trace
from prometheus_client import Counter, Histogram
from pydantic import ValidationError
from sqlalchemy.orm import Session

from hria.agent.contracts import AgentAnswer, ExecutionPlan
from hria.agent.grounding import ungrounded_numerals, validate_claims
from hria.agent.planner import Planner, build_planner
from hria.agent.synthesis import synthesize
from hria.skills.contracts import ExecutionFailure, ToolResult
from hria.skills.registry import TOOL_REGISTRY

TOOL_LATENCY = Histogram("hria_tool_latency_seconds", "Tool latency", ["tool"])
TOOL_ERRORS = Counter("hria_tool_errors_total", "Tool execution errors", ["tool"])
ABSTENTIONS = Counter("hria_abstentions_total", "Typed tool abstentions", ["tool"])
UNGROUNDED_NUMBERS = Counter(
    "hria_ungrounded_number_total", "Numerals not linked to validated evidence"
)
TOKENS_PER_QUESTION = Histogram(
    "hria_tokens_per_question",
    "Planner tokens used per question",
    ["provider"],
    buckets=(0, 50, 100, 250, 500, 1_000, 2_500, 5_000),
)
TRACER = trace.get_tracer("hria.agent")

EventCallback = Callable[[str, dict[str, Any]], None]


class AgentPipeline:
    def __init__(self, planner: Planner | None = None) -> None:
        self.planner = planner or build_planner()

    def _validated_plan(self, question: str) -> ExecutionPlan:
        validation_error = None
        for _ in range(3):
            with TRACER.start_as_current_span("plan") as span:
                span.set_attribute("planner", type(self.planner).__name__)
                span.set_attribute("retry", validation_error is not None)
                plan = self.planner.plan(question, validation_error)
            try:
                for call in plan.calls:
                    definition = TOOL_REGISTRY.get(call.tool)
                    if definition is None:
                        raise ValueError(f"unknown tool: {call.tool}")
                    definition.input_model.model_validate(call.arguments)
                return plan
            except (ValidationError, ValueError) as exc:
                validation_error = str(exc)
        raise ValueError(
            f"planner arguments remained invalid after two retries: {validation_error}"
        )

    def run(
        self,
        question: str,
        session: Session,
        on_event: EventCallback | None = None,
    ) -> AgentAnswer:
        emit = on_event or (lambda _name, _payload: None)
        with TRACER.start_as_current_span("intent_parse"):
            plan = self._validated_plan(question)
        TOKENS_PER_QUESTION.labels(provider=type(self.planner).__name__).observe(
            getattr(self.planner, "last_token_count", 0)
        )
        emit("plan_created", plan.model_dump(mode="json"))
        if plan.clarification:
            return AgentAnswer(status="clarification", answer=plan.clarification, plan=plan)

        results: list[ToolResult] = []
        for index, call in enumerate(plan.calls):
            definition = TOOL_REGISTRY[call.tool]
            resolved_arguments = dict(call.arguments)
            result_reference = resolved_arguments.get("result_id")
            if isinstance(result_reference, str) and result_reference.startswith("$result:"):
                dependency_index = int(result_reference.split(":", 1)[1])
                dependency = results[dependency_index]
                provenance = getattr(dependency, "provenance", None)
                if provenance is None:
                    resolved_arguments["result_id"] = "unavailable"
                else:
                    resolved_arguments["result_id"] = provenance.result_id
            arguments = definition.input_model.model_validate(resolved_arguments)
            emit(
                "tool_started",
                {"index": index, "tool": call.tool, "arguments": resolved_arguments},
            )
            started = perf_counter()
            with TRACER.start_as_current_span("tool_call") as span:
                span.set_attribute("tool.name", call.tool)
                try:
                    result = definition.function(arguments, session)
                except Exception as exc:  # keep transport alive and expose a typed visible failure
                    TOOL_ERRORS.labels(tool=call.tool).inc()
                    span.record_exception(exc)
                    result = ExecutionFailure(
                        reason=f"{type(exc).__name__}: {exc}",
                        retryable=False,
                        tool_call_id=f"failed-{index}",
                    )
                provenance = getattr(result, "provenance", None)
                span.set_attribute("tool.abstained", result.status == "insufficient_data")
                if provenance is not None:
                    span.set_attribute("tool.row_count", provenance.row_count)
            TOOL_LATENCY.labels(tool=call.tool).observe(perf_counter() - started)
            if result.status == "insufficient_data":
                ABSTENTIONS.labels(tool=call.tool).inc()
            results.append(result)
            emit(
                "tool_completed",
                {"index": index, "tool": call.tool, "result": result.model_dump(mode="json")},
            )

        with TRACER.start_as_current_span("synthesis"):
            answer, claims, status = synthesize(results)
        evidence_errors = validate_claims(claims, results)
        ungrounded = ungrounded_numerals(answer, claims)
        if evidence_errors or ungrounded:
            UNGROUNDED_NUMBERS.inc(len(ungrounded) or 1)
            answer = (
                "I could not validate every numerical claim. The structured tool results are returned "
                "without an unverified prose summary."
            )
            claims = []
            status = "failed"
        else:
            emit("claims_validated", {"claim_count": len(claims)})
        return AgentAnswer(
            status=status,
            answer=answer,
            claims=claims,
            tool_results=[result.model_dump(mode="json") for result in results],
            plan=plan,
        )
