from __future__ import annotations

from hria.agent.contracts import AnswerClaim
from hria.agent.grounding import number
from hria.skills.contracts import ToolResult


def _percent(value: float) -> str:
    return f"{value * 100:.1f}%"


def synthesize(results: list[ToolResult]) -> tuple[str, list[AnswerClaim], str]:
    if not results:
        return "No analysis was executed.", [], "failed"
    abstentions = [result for result in results if result.status == "insufficient_data"]
    if abstentions:
        result = abstentions[0]
        answer = f"I cannot answer this reliably. {result.reason}"
        return answer, [AnswerClaim(text=answer)], "insufficient_data"
    successes = [result for result in results if result.status == "success"]
    if not successes:
        return "The analysis failed before producing a validated result.", [], "failed"
    result = next(
        (value for value in successes if "vega_lite" not in value.data),
        successes[-1],
    )
    result_id = result.provenance.result_id
    data = result.data

    if "b10_use_hours" in data:
        b10 = float(data["b10_use_hours"])
        lower, upper = map(float, data["b10_95_ci"])
        failed, censored = int(data["n_failed"]), int(data["n_censored"])
        text = (
            f"Estimated B10 life at use conditions is {b10:,.0f} hours "
            f"(95% CI {lower:,.0f} to {upper:,.0f}), based on {failed} failures and "
            f"{censored} right-censored units."
        )
        claim = AnswerClaim(
            text=text,
            evidence=[
                number(
                    result_id=result_id,
                    path="$.b10_use_hours",
                    value=b10,
                    display=f"{b10:,.0f}",
                    unit="hours",
                ),
                number(
                    result_id=result_id,
                    path="$.b10_95_ci[0]",
                    value=lower,
                    display=f"{lower:,.0f}",
                    unit="hours",
                ),
                number(
                    result_id=result_id,
                    path="$.b10_95_ci[1]",
                    value=upper,
                    display=f"{upper:,.0f}",
                    unit="hours",
                ),
                number(
                    result_id=result_id,
                    path="$.n_failed",
                    value=failed,
                    display=str(failed),
                    unit="units",
                ),
                number(
                    result_id=result_id,
                    path="$.n_censored",
                    value=censored,
                    display=str(censored),
                    unit="units",
                ),
                number(
                    result_id=result_id,
                    path="$.confidence_level",
                    value=0.95,
                    display="95%",
                ),
            ],
        )
        return text, [claim], "answered"

    if "groups" in data:
        claims = []
        lines = []
        for index, group in enumerate(data["groups"]):
            if group.get("status") == "insufficient_data":
                lines.append(f"{group['group']}: insufficient data.")
                continue
            n_units = int(group["n_units"])
            n_failed = int(group["n_failed"])
            if "failure_probability_at_horizon" in group:
                estimate = float(group["failure_probability_at_horizon"])
                low, high = map(float, group["failure_probability_95_ci"])
                text = (
                    f"{group['group']}: failure probability is {_percent(estimate)} "
                    f"(95% CI {_percent(low)} to {_percent(high)}) from {n_units} units."
                )
                evidence = [
                    number(
                        result_id=result_id,
                        path=f"$.groups[{index}].failure_probability_at_horizon",
                        value=estimate,
                        display=_percent(estimate),
                    ),
                    number(
                        result_id=result_id,
                        path=f"$.groups[{index}].failure_probability_95_ci[0]",
                        value=low,
                        display=_percent(low),
                    ),
                    number(
                        result_id=result_id,
                        path=f"$.groups[{index}].failure_probability_95_ci[1]",
                        value=high,
                        display=_percent(high),
                    ),
                    number(
                        result_id=result_id,
                        path=f"$.groups[{index}].n_units",
                        value=n_units,
                        display=str(n_units),
                        unit="units",
                    ),
                    number(
                        result_id=result_id,
                        path="$.confidence_level",
                        value=0.95,
                        display="95%",
                    ),
                ]
            else:
                estimate = float(group["observed_failure_proportion"])
                low, high = map(float, group["wilson_95_ci"])
                text = (
                    f"{group['group']}: {n_failed} of {n_units} units failed; the observed "
                    f"proportion is {_percent(estimate)} "
                    f"(Wilson 95% CI {_percent(low)} to {_percent(high)})."
                )
                evidence = [
                    number(
                        result_id=result_id,
                        path=f"$.groups[{index}].n_failed",
                        value=n_failed,
                        display=str(n_failed),
                        unit="units",
                    ),
                    number(
                        result_id=result_id,
                        path=f"$.groups[{index}].n_units",
                        value=n_units,
                        display=str(n_units),
                        unit="units",
                    ),
                    number(
                        result_id=result_id,
                        path=f"$.groups[{index}].observed_failure_proportion",
                        value=estimate,
                        display=_percent(estimate),
                    ),
                    number(
                        result_id=result_id,
                        path=f"$.groups[{index}].wilson_95_ci[0]",
                        value=low,
                        display=_percent(low),
                    ),
                    number(
                        result_id=result_id,
                        path=f"$.groups[{index}].wilson_95_ci[1]",
                        value=high,
                        display=_percent(high),
                    ),
                    number(
                        result_id=result_id,
                        path="$.confidence_level",
                        value=0.95,
                        display="95%",
                    ),
                ]
            lines.append(text)
            claims.append(AnswerClaim(text=text, evidence=evidence))
        return "\n".join(lines), claims, "answered"

    if "log_rank_chi_square" in data:
        statistic, p_value = float(data["log_rank_chi_square"]), float(data["p_value"])
        n_a, n_b = int(data["n_a"]), int(data["n_b"])
        text = (
            f"The survival distributions differ with log-rank χ²={statistic:.3f}, "
            f"p={p_value:.4g}, using {n_a} units in {data['group_a']} and {n_b} in {data['group_b']}."
        )
        claim = AnswerClaim(
            text=text,
            evidence=[
                number(
                    result_id=result_id,
                    path="$.log_rank_chi_square",
                    value=statistic,
                    display=f"{statistic:.3f}",
                ),
                number(
                    result_id=result_id, path="$.p_value", value=p_value, display=f"{p_value:.4g}"
                ),
                number(
                    result_id=result_id, path="$.n_a", value=n_a, display=str(n_a), unit="units"
                ),
                number(
                    result_id=result_id, path="$.n_b", value=n_b, display=str(n_b), unit="units"
                ),
            ],
        )
        return text, [claim], "answered"

    if "ranked_levels" in data:
        top = data["ranked_levels"][0]
        rate, q_value = float(top["observed_failure_proportion"]), float(top["q_value_bh"])
        n_units = int(top["n_units"])
        text = (
            f"{top['level']} ranks highest: {_percent(rate)} observed failures across "
            f"{n_units} units, with BH-adjusted q={q_value:.4g}."
        )
        claim = AnswerClaim(
            text=text,
            evidence=[
                number(
                    result_id=result_id,
                    path="$.ranked_levels[0].observed_failure_proportion",
                    value=rate,
                    display=_percent(rate),
                ),
                number(
                    result_id=result_id,
                    path="$.ranked_levels[0].n_units",
                    value=n_units,
                    display=str(n_units),
                    unit="units",
                ),
                number(
                    result_id=result_id,
                    path="$.ranked_levels[0].q_value_bh",
                    value=q_value,
                    display=f"{q_value:.4g}",
                ),
            ],
        )
        return text, [claim], "answered"

    if "slope_per_day" in data:
        slope, p_value = float(data["slope_per_day"]), float(data["p_value"])
        points, span = int(data["n_points"]), float(data["span_days"])
        text = (
            f"The estimated slope is {slope:.4g} per day (p={p_value:.4g}) from "
            f"{points} measurements spanning {span:.1f} days."
        )
        claim = AnswerClaim(
            text=text,
            evidence=[
                number(
                    result_id=result_id,
                    path="$.slope_per_day",
                    value=slope,
                    display=f"{slope:.4g}",
                    unit="per day",
                ),
                number(
                    result_id=result_id, path="$.p_value", value=p_value, display=f"{p_value:.4g}"
                ),
                number(
                    result_id=result_id,
                    path="$.n_points",
                    value=points,
                    display=str(points),
                    unit="measurements",
                ),
                number(
                    result_id=result_id,
                    path="$.span_days",
                    value=span,
                    display=f"{span:.1f}",
                    unit="days",
                ),
            ],
        )
        return text, [claim], "answered"

    return "The validated structured result is available in the evidence drawer.", [], "answered"
