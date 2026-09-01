from __future__ import annotations

import re
from typing import Any

from hria.agent.contracts import AnswerClaim, EvidenceNumber
from hria.skills.contracts import ToolResult

NUMBER_PATTERN = re.compile(r"(?<![A-Za-z0-9-])[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?%?")


def resolve_path(document: dict[str, Any], path: str) -> Any:
    if not path.startswith("$."):
        raise ValueError("evidence path must start with $.")
    value: Any = document
    for component in path[2:].replace("]", "").replace("[", ".").split("."):
        value = value[int(component)] if isinstance(value, list) else value[component]
    return value


def validate_claims(claims: list[AnswerClaim], results: list[ToolResult]) -> list[str]:
    by_id = {
        result.provenance.result_id: result
        for result in results
        if hasattr(result, "provenance") and result.status == "success"
    }
    errors: list[str] = []
    for claim in claims:
        for evidence in claim.evidence:
            result = by_id.get(evidence.result_id)
            if result is None:
                errors.append(f"unknown successful result {evidence.result_id}")
                continue
            try:
                actual = resolve_path(result.data, evidence.json_path)
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                errors.append(f"invalid evidence path {evidence.json_path}: {exc}")
                continue
            if not isinstance(actual, (int, float)) or abs(
                float(actual) - float(evidence.value)
            ) > max(1e-9, abs(float(actual)) * 1e-9):
                errors.append(
                    f"evidence value mismatch at {evidence.json_path}: expected {actual}, got {evidence.value}"
                )
    return errors


def ungrounded_numerals(text: str, claims: list[AnswerClaim]) -> list[str]:
    allowed = {evidence.display.replace(",", "") for claim in claims for evidence in claim.evidence}
    return [
        match.group(0)
        for match in NUMBER_PATTERN.finditer(text.replace(",", ""))
        if match.group(0) not in allowed
    ]


def number(
    *,
    result_id: str,
    path: str,
    value: float | int,
    display: str,
    unit: str | None = None,
) -> EvidenceNumber:
    return EvidenceNumber(
        result_id=result_id,
        json_path=path,
        value=value,
        display=display,
        unit=unit,
    )
