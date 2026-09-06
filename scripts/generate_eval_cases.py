from __future__ import annotations

from pathlib import Path

import yaml

OUT = Path("hria/evals/cases")


def case(case_id, family, question, expects, index):
    return {
        "id": case_id,
        "family": family,
        "split": "development" if index < 5 else "held_out",
        "question": question,
        "expects": expects,
    }


cases = []
for index, lot in enumerate(range(1, 9)):
    cases.append(
        case(
            f"lookup-{index + 1:03d}",
            "lookup",
            f"Show test runs for LOT-{lot:04d}",
            {
                "tools": ["query_test_runs"],
                "args_contain": {"filters": {"lot_code": f"LOT-{lot:04d}"}},
                "status": "answered",
            },
            index,
        )
    )
for index, horizon in enumerate((300, 400, 500, 600, 700, 800, 900, 1000)):
    cases.append(
        case(
            f"aggregation-{index + 1:03d}",
            "grouped_aggregation",
            f"What is the failure probability for PN-4471 by {horizon} hours?",
            {
                "tools": ["failure_rate"],
                "args_contain": {
                    "horizon_hours": float(horizon),
                    "filters": {"part_number": "PN-4471"},
                },
                "status": "answered",
            },
            index,
        )
    )
for index, entity in enumerate(
    (
        "PN-4471",
        "LOT-0042",
        "SUPPLIER-03",
        "PN-4471",
        "LOT-0042",
        "SUPPLIER-03",
        "PN-4471",
        "LOT-0042",
    )
):
    cases.append(
        case(
            f"lifetime-{index + 1:03d}",
            "lifetime_fit",
            f"What is the B10 lifetime of {entity} at use conditions?",
            {"tools": ["fit_lifetime"], "status": "answered"},
            index,
        )
    )
for index, pair in enumerate(
    ((1, 2), (3, 4), (5, 6), (7, 8), (9, 10), (11, 12), (13, 14), (15, 16))
):
    left, right = pair
    cases.append(
        case(
            f"comparison-{index + 1:03d}",
            "group_comparison",
            f"Compare LOT-{left:04d} with LOT-{right:04d}; which is worse?",
            {
                "tools": ["compare_groups"],
                "args_contain": {
                    "dimension": "lot",
                    "group_a": f"LOT-{left:04d}",
                    "group_b": f"LOT-{right:04d}",
                },
            },
            index,
        )
    )
for index in range(8):
    cases.append(
        case(
            f"anomaly-{index + 1:03d}",
            "anomaly_attribution",
            "Which lot of PN-4471 is anomalous?",
            {
                "tools": ["detect_anomalous_source"],
                "args_contain": {"dimension": "lot", "filters": {"part_number": "PN-4471"}},
            },
            index,
        )
    )
for index, parameter in enumerate(
    (
        "contact resistance",
        "contact resistance",
        "leakage current",
        "output voltage",
        "contact resistance",
        "leakage current",
        "output voltage",
        "contact resistance",
    )
):
    cases.append(
        case(
            f"trend-{index + 1:03d}",
            "trend_detection",
            f"Is STATION-007 {parameter} drifting?",
            {"tools": ["measurement_trend"], "args_contain": {"station": "STATION-007"}},
            index,
        )
    )
for index, lot in enumerate(range(9001, 9009)):
    cases.append(
        case(
            f"insufficient-{index + 1:03d}",
            "insufficient_data",
            f"What is the failure rate for LOT-{lot:04d}?",
            {"tools": ["failure_rate"], "status": "insufficient_data"},
            index,
        )
    )
ambiguous = [
    "Is this part reliable?",
    "Is it failing?",
    "Did it improve?",
    "Is the station okay?",
    "What is the lifetime?",
    "Compare these lots",
    "Is reliability good?",
    "What changed?",
]
for index, question in enumerate(ambiguous):
    cases.append(
        case(
            f"ambiguous-{index + 1:03d}", "ambiguous", question, {"status": "clarification"}, index
        )
    )

assert len(cases) == 64
OUT.mkdir(parents=True, exist_ok=True)
for value in cases:
    (OUT / f"{value['id']}.yaml").write_text(yaml.safe_dump(value, sort_keys=False))
