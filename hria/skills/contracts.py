from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class Filters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    part_number: str | None = None
    lot_code: str | None = None
    supplier: str | None = None
    design_rev: str | None = None
    protocol: str | None = None
    station: str | None = None
    built_from: date | None = None
    built_to: date | None = None


class Provenance(BaseModel):
    tool_call_id: str
    result_id: str
    dataset_version: str
    sql: str
    row_count: int = Field(ge=0)
    excluded_row_count: int = Field(default=0, ge=0)
    filters_applied: dict[str, Any]
    elapsed_ms: float = Field(ge=0)
    generated_at: datetime


class ToolSuccess(BaseModel):
    status: Literal["success"] = "success"
    data: dict[str, Any]
    provenance: Provenance
    caveats: list[str] = Field(default_factory=list)


class InsufficientData(BaseModel):
    status: Literal["insufficient_data"] = "insufficient_data"
    reason: str
    observed: dict[str, Any]
    required: dict[str, Any]
    provenance: Provenance
    caveats: list[str] = Field(default_factory=list)


class InvalidData(BaseModel):
    status: Literal["invalid_data"] = "invalid_data"
    reason: str
    issue_counts: dict[str, int]
    provenance: Provenance
    caveats: list[str] = Field(default_factory=list)


class ExecutionFailure(BaseModel):
    status: Literal["execution_failure"] = "execution_failure"
    reason: str
    retryable: bool = False
    tool_call_id: str


ToolResult = ToolSuccess | InsufficientData | InvalidData | ExecutionFailure


def new_tool_call_id() -> str:
    return f"call-{uuid4().hex}"


def new_result_id() -> str:
    return f"result-{uuid4().hex}"
