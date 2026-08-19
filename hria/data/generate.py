from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from itertools import batched
from typing import Any

import numpy as np
from sqlalchemy import delete, insert
from sqlalchemy.orm import Session

from hria.data.models import (
    Base,
    DatasetManifest,
    FailureMode,
    IngestionIssue,
    IssueCode,
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
from hria.db import engine
from hria.stats.lifetime import acceleration_factor

GENERATOR_VERSION = "1.1"
REFERENCE_DATE = date(2026, 1, 1)
DRIFT_START = date(2025, 3, 1)
REVISION_FIX_DATE = date(2025, 1, 1)
BAD_LOT = "LOT-0042"
DRIFT_STATION = "STATION-007"
BAD_SUPPLIER = "SUPPLIER-03"
BAD_SUPPLIER_ETA_MULTIPLIER = 0.30
REVISION_FIX_ETA_MULTIPLIER = 6.0


@dataclass(frozen=True)
class FailureSpec:
    beta: float
    eta_use_hours: float
    character: str


FAILURE_SPECS = {
    FailureMode.INFANT_MORTALITY: FailureSpec(0.6, 260_000, "decreasing hazard"),
    FailureMode.FIRMWARE_HANG: FailureSpec(1.0, 390_000, "constant hazard"),
    FailureMode.DIELECTRIC_BREAKDOWN: FailureSpec(1.3, 325_000, "mild wear-out"),
    FailureMode.SOLDER_JOINT_CRACK: FailureSpec(3.5, 45_000, "strong wear-out"),
    FailureMode.CONNECTOR_WEAR: FailureSpec(2.4, 195_000, "wear-out"),
}


@dataclass(frozen=True)
class Profile:
    parts: int
    lots: int
    units: int
    stations: int
    protocols: int
    runs_per_unit: int
    measurements_per_run: int
    special_lot_every: int


PROFILES = {
    "smoke": Profile(12, 60, 2_000, 12, 3, 4, 6, 20),
    "full": Profile(200, 1_200, 60_000, 40, 5, 4, 12, 200),
}


def _part_rows(count: int) -> list[dict[str, Any]]:
    rows = [
        {"id": 1, "part_number": "PN-4471", "design_rev": "A"},
        {"id": 2, "part_number": "PN-4471", "design_rev": "B"},
        {"id": 3, "part_number": "PN-4471", "design_rev": "C"},
    ]
    for part_id in range(4, count + 1):
        rows.append(
            {
                "id": part_id,
                "part_number": f"PN-{4400 + part_id:04d}",
                "design_rev": chr(ord("A") + part_id % 3),
            }
        )
    return rows[:count]


def _insert_many(session: Session, model, rows: list[dict[str, Any]]) -> None:
    if rows:
        session.execute(insert(model), rows)


def _clear(session: Session) -> None:
    for model in (
        Measurement,
        UnitOutcome,
        TestRun,
        TestEpisode,
        IngestionIssue,
        Unit,
        Lot,
        Part,
        Supplier,
        TestStation,
        TestProtocol,
        DatasetManifest,
    ):
        session.execute(delete(model))


def load_dataset(profile_name: str, seed: int, *, replace: bool = True) -> dict[str, Any]:
    profile = PROFILES[profile_name]
    rng = np.random.default_rng(seed)
    Base.metadata.create_all(engine)
    generated_at = datetime.now(UTC)
    dataset_version = f"seed-{seed}-{profile_name}-v1.1"

    part_rows = _part_rows(profile.parts)
    supplier_rows = [{"id": value, "name": f"SUPPLIER-{value:02d}"} for value in range(1, 11)]
    station_rows = [
        {
            "id": value,
            "name": f"STATION-{value:03d}",
            "fixture_id": f"FIXTURE-{value:03d}",
            "last_calibration_date": REFERENCE_DATE - timedelta(days=30 + value),
        }
        for value in range(1, profile.stations + 1)
    ]
    protocol_rows = [
        {
            "id": value,
            "name": f"ALT-{value:02d}",
            "use_condition_temp_c": 25.0,
            "use_condition_voltage_v": 3.3,
            "planned_duration_hours": 600.0 + 100.0 * ((value - 1) % 5),
        }
        for value in range(1, profile.protocols + 1)
    ]

    lot_rows: list[dict[str, Any]] = []
    for lot_id in range(1, profile.lots + 1):
        # Ensure the documented anomaly belongs to the documented part.
        part_id = 2 if lot_id == 42 else 1 + ((lot_id - 1) % profile.parts)
        supplier_id = 3 if lot_id % 13 == 0 else 1 + ((lot_id * 7) % 10)
        lot_rows.append(
            {
                "id": lot_id,
                "lot_code": f"LOT-{lot_id:04d}",
                "part_id": part_id,
                "supplier_id": supplier_id,
                "manufacture_date": REFERENCE_DATE - timedelta(days=int(rng.integers(90, 900))),
            }
        )

    truth = {
        "seed": seed,
        "profile": profile_name,
        "failure_modes": {mode.value: asdict(spec) for mode, spec in FAILURE_SPECS.items()},
        "acceleration": {"activation_energy_ev": 0.7, "voltage_exponent": 3.0},
        "signals": {
            "bad_lot": {"lot_code": BAD_LOT, "mode": "solder_joint_crack", "eta_multiplier": 0.55},
            "drifting_station": {"station": DRIFT_STATION, "after": DRIFT_START.isoformat()},
            "bad_supplier": {
                "supplier": BAD_SUPPLIER,
                "mode": "infant_mortality",
                "eta_multiplier": BAD_SUPPLIER_ETA_MULTIPLIER,
            },
            "revision_fix": {
                "part_number": "PN-4471",
                "design_rev": "C",
                "after": REVISION_FIX_DATE.isoformat(),
                "mode": "connector_wear",
                "eta_multiplier": REVISION_FIX_ETA_MULTIPLIER,
            },
        },
    }

    counters = {
        "parts": len(part_rows),
        "lots": len(lot_rows),
        "units": 0,
        "episodes": 0,
        "runs": 0,
        "measurements": 0,
        "outcomes": 0,
        "failures": 0,
        "issues": 0,
    }
    lot_lookup = {row["id"]: row for row in lot_rows}
    part_lookup = {row["id"]: row for row in part_rows}

    with Session(engine) as session:
        if replace:
            _clear(session)
        _insert_many(session, Supplier, supplier_rows)
        _insert_many(session, Part, part_rows)
        _insert_many(session, Lot, lot_rows)
        _insert_many(session, TestStation, station_rows)
        _insert_many(session, TestProtocol, protocol_rows)

        measurement_id = 1
        run_id = 1
        issue_id = 1
        for unit_ids in batched(range(1, profile.units + 1), 500):
            unit_rows: list[dict[str, Any]] = []
            episode_rows: list[dict[str, Any]] = []
            run_rows: list[dict[str, Any]] = []
            measurement_rows: list[dict[str, Any]] = []
            outcome_rows: list[dict[str, Any]] = []
            issue_rows: list[dict[str, Any]] = []

            for unit_id in unit_ids:
                lot_id = (
                    42
                    if unit_id % profile.special_lot_every == 0
                    else 1 + ((unit_id - 1) % profile.lots)
                )
                lot = lot_lookup[lot_id]
                part = part_lookup[lot["part_id"]]
                build_date = lot["manufacture_date"] + timedelta(days=int(rng.integers(1, 45)))
                serial = f"SN-{unit_id:08d}"
                unit_rows.append(
                    {"id": unit_id, "serial": serial, "lot_id": lot_id, "build_date": build_date}
                )
                if unit_id <= max(1, round(profile.units * 0.005)):
                    issue_rows.append(
                        {
                            "id": issue_id,
                            "issue_code": IssueCode.DUPLICATE_SERIAL,
                            "entity_type": "raw_unit_import",
                            "source_key": serial,
                            "detail": json.dumps({"serial": serial, "rejected_copy": 2}),
                            "excluded_from_analysis": True,
                            "created_at": generated_at,
                        }
                    )
                    issue_id += 1

                protocol_id = 1 + ((unit_id * 11) % profile.protocols)
                protocol = protocol_rows[protocol_id - 1]
                episode_id = unit_id
                start_date = datetime.combine(
                    build_date + timedelta(days=int(rng.integers(5, 60))),
                    datetime.min.time(),
                    tzinfo=UTC,
                )
                planned_duration = float(protocol["planned_duration_hours"])
                episode_rows.append(
                    {
                        "id": episode_id,
                        "unit_id": unit_id,
                        "protocol_id": protocol_id,
                        "started_at": start_date,
                        "planned_duration_hours": planned_duration,
                    }
                )

                candidate_use_lives: dict[FailureMode, float] = {}
                for mode, spec in FAILURE_SPECS.items():
                    eta = spec.eta_use_hours
                    if lot["lot_code"] == BAD_LOT and mode == FailureMode.SOLDER_JOINT_CRACK:
                        eta *= 0.55
                    if lot["supplier_id"] == 3 and mode == FailureMode.INFANT_MORTALITY:
                        eta *= BAD_SUPPLIER_ETA_MULTIPLIER
                    if (
                        part["part_number"] == "PN-4471"
                        and part["design_rev"] == "C"
                        and build_date >= REVISION_FIX_DATE
                        and mode == FailureMode.CONNECTOR_WEAR
                    ):
                        eta *= REVISION_FIX_ETA_MULTIPLIER
                    candidate_use_lives[mode] = eta * float(rng.weibull(spec.beta))
                winning_mode = min(candidate_use_lives, key=candidate_use_lives.get)
                failure_exposure = candidate_use_lives[winning_mode]

                segment_count = profile.runs_per_unit + (1 if unit_id % 6 == 0 else 0)
                segment_hours = planned_duration / segment_count
                elapsed = 0.0
                exposure = 0.0
                terminal_run_id: int | None = None
                event_observed = False
                missing_measurement_run = unit_id % 997 == 0
                for segment in range(segment_count):
                    station_id = 1 + ((unit_id + segment * 3) % profile.stations)
                    temp_c = float(45 + 10 * ((protocol_id + segment) % 3))
                    voltage_v = float(3.6 + 0.4 * ((unit_id + segment) % 3))
                    factor = float(
                        acceleration_factor(
                            stress_temp_c=[temp_c],
                            use_temp_c=25.0,
                            stress_voltage_v=[voltage_v],
                            use_voltage_v=3.3,
                        )[0]
                    )
                    possible_exposure = factor * segment_hours
                    actual_hours = segment_hours
                    if exposure + possible_exposure >= failure_exposure:
                        actual_hours = max(1e-6, (failure_exposure - exposure) / factor)
                        event_observed = True
                    segment_start = start_date + timedelta(hours=elapsed)
                    segment_end = segment_start + timedelta(hours=actual_hours)
                    current_run_id = run_id
                    run_rows.append(
                        {
                            "id": current_run_id,
                            "episode_id": episode_id,
                            "station_id": station_id,
                            "start_at": segment_start,
                            "end_at": segment_end,
                            "stress_temp_c": temp_c,
                            "stress_voltage_v": voltage_v,
                            "humidity_pct": float(35 + (unit_id + segment) % 45),
                        }
                    )
                    run_id += 1
                    elapsed += actual_hours
                    exposure += factor * actual_hours
                    terminal_run_id = current_run_id

                    if missing_measurement_run and segment == 0:
                        issue_rows.append(
                            {
                                "id": issue_id,
                                "issue_code": IssueCode.MISSING_MEASUREMENTS,
                                "entity_type": "test_run",
                                "source_key": str(current_run_id),
                                "detail": "No measurements were received for this valid run.",
                                "excluded_from_analysis": False,
                                "created_at": generated_at,
                            }
                        )
                        issue_id += 1
                    else:
                        for index in range(profile.measurements_per_run):
                            param_index = index % 3
                            if param_index == 0:
                                param, baseline, sigma, uom, low, high = (
                                    "contact_resistance",
                                    50.0,
                                    1.5,
                                    "mohm",
                                    45.0,
                                    60.0,
                                )
                            elif param_index == 1:
                                param, baseline, sigma, uom, low, high = (
                                    "leakage_current",
                                    5.0,
                                    0.3,
                                    "uA",
                                    0.0,
                                    8.0,
                                )
                            else:
                                param, baseline, sigma, uom, low, high = (
                                    "output_voltage",
                                    3.3,
                                    0.03,
                                    "V",
                                    3.1,
                                    3.5,
                                )
                            captured_at = segment_start + timedelta(
                                hours=actual_hours
                                * (index + 1)
                                / (profile.measurements_per_run + 1)
                            )
                            value = baseline + float(rng.normal(0, sigma))
                            if (
                                station_id == 7
                                and param == "contact_resistance"
                                and captured_at.date() >= DRIFT_START
                            ):
                                value += 0.025 * (captured_at.date() - DRIFT_START).days
                            measurement_rows.append(
                                {
                                    "id": measurement_id,
                                    "run_id": current_run_id,
                                    "param_name": param,
                                    "value": value,
                                    "uom": uom,
                                    "limit_low": low,
                                    "limit_high": high,
                                    "captured_at": captured_at,
                                }
                            )
                            measurement_id += 1
                    if event_observed:
                        break

                if unit_id == profile.units:
                    issue_rows.append(
                        {
                            "id": issue_id,
                            "issue_code": IssueCode.NEGATIVE_DURATION,
                            "entity_type": "raw_unit_outcome",
                            "source_key": str(episode_id),
                            "detail": json.dumps({"duration_hours": -4.0}),
                            "excluded_from_analysis": True,
                            "created_at": generated_at,
                        }
                    )
                    issue_id += 1
                else:
                    outcome_rows.append(
                        {
                            "id": episode_id,
                            "episode_id": episode_id,
                            "observed_duration_hours": elapsed,
                            "event_observed": event_observed,
                            "failure_mode": winning_mode if event_observed else None,
                            "event_at": start_date + timedelta(hours=elapsed)
                            if event_observed
                            else None,
                            "terminal_run_id": terminal_run_id,
                        }
                    )
                if unit_id in {profile.units - 1, profile.units - 2}:
                    issue_rows.append(
                        {
                            "id": issue_id,
                            "issue_code": IssueCode.END_BEFORE_START,
                            "entity_type": "raw_test_run",
                            "source_key": f"rejected-{unit_id}",
                            "detail": json.dumps({"start": "2025-01-02", "end": "2025-01-01"}),
                            "excluded_from_analysis": True,
                            "created_at": generated_at,
                        }
                    )
                    issue_id += 1

            _insert_many(session, Unit, unit_rows)
            _insert_many(session, TestEpisode, episode_rows)
            _insert_many(session, TestRun, run_rows)
            _insert_many(session, Measurement, measurement_rows)
            _insert_many(session, UnitOutcome, outcome_rows)
            _insert_many(session, IngestionIssue, issue_rows)
            counters["units"] += len(unit_rows)
            counters["episodes"] += len(episode_rows)
            counters["runs"] += len(run_rows)
            counters["measurements"] += len(measurement_rows)
            counters["outcomes"] += len(outcome_rows)
            counters["failures"] += sum(row["event_observed"] for row in outcome_rows)
            counters["issues"] += len(issue_rows)
            session.commit()

        truth["counts"] = counters
        truth["censoring_fraction"] = 1.0 - counters["failures"] / counters["outcomes"]
        _insert_many(
            session,
            DatasetManifest,
            [
                {
                    "id": 1,
                    "dataset_version": dataset_version,
                    "seed": seed,
                    "profile": profile_name,
                    "generator_version": GENERATOR_VERSION,
                    "generated_at": generated_at,
                    "truth_json": json.dumps(truth, sort_keys=True),
                }
            ],
        )
        session.commit()
    return truth


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate deterministic HRIA reliability data")
    parser.add_argument("--profile", choices=PROFILES, default="smoke")
    parser.add_argument("--seed", type=int, default=4471)
    parser.add_argument("--load", action="store_true", help="load directly into DATABASE_URL")
    args = parser.parse_args()
    if not args.load:
        parser.error("--load is required; file export is intentionally not implemented")
    truth = load_dataset(args.profile, args.seed)
    print(json.dumps(truth, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
