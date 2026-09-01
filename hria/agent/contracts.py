from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class PlannedToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[int] = Field(default_factory=list)


class ExecutionPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: str
    calls: list[PlannedToolCall] = Field(default_factory=list)
    clarification: str | None = None


class EvidenceNumber(BaseModel):
    result_id: str
    json_path: str
    value: float | int
    display: str
    unit: str | None = None


class AnswerClaim(BaseModel):
    text: str
    evidence: list[EvidenceNumber] = Field(default_factory=list)


class AgentAnswer(BaseModel):
    status: Literal["answered", "clarification", "insufficient_data", "failed"]
    answer: str
    claims: list[AnswerClaim] = Field(default_factory=list)
    tool_results: list[dict[str, Any]] = Field(default_factory=list)
    plan: ExecutionPlan
