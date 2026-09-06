from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from hria.data.models import DatasetManifest


@dataclass(frozen=True)
class Oracle:
    """Independent access to generator truth; never imported by agent or tool code."""

    truth: dict[str, Any]

    @classmethod
    def from_database(cls, session: Session) -> Oracle:
        raw = session.scalar(select(DatasetManifest.truth_json).order_by(DatasetManifest.id.desc()))
        if raw is None:
            raise RuntimeError("No generated dataset manifest is available.")
        return cls(json.loads(raw))

    def planted_entity(self, signal: str) -> str:
        value = self.truth["signals"][signal]
        for key in ("lot_code", "station", "supplier", "part_number"):
            if key in value:
                return str(value[key])
        raise KeyError(f"signal {signal!r} has no entity")

    @property
    def censoring_fraction(self) -> float:
        return float(self.truth["censoring_fraction"])
