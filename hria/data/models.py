from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class FailureMode(StrEnum):
    INFANT_MORTALITY = "infant_mortality"
    FIRMWARE_HANG = "firmware_hang"
    DIELECTRIC_BREAKDOWN = "dielectric_breakdown"
    SOLDER_JOINT_CRACK = "solder_joint_crack"
    CONNECTOR_WEAR = "connector_wear"


class IssueCode(StrEnum):
    DUPLICATE_SERIAL = "duplicate_serial"
    MISSING_MEASUREMENTS = "missing_measurements"
    END_BEFORE_START = "end_before_start"
    NEGATIVE_DURATION = "negative_duration"


class Supplier(Base):
    __tablename__ = "supplier"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    lots: Mapped[list[Lot]] = relationship(back_populates="supplier")


class Part(Base):
    __tablename__ = "part"
    __table_args__ = (UniqueConstraint("part_number", "design_rev"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    part_number: Mapped[str] = mapped_column(String(40), index=True)
    design_rev: Mapped[str] = mapped_column(String(12))
    lots: Mapped[list[Lot]] = relationship(back_populates="part")


class Lot(Base):
    __tablename__ = "lot"
    __table_args__ = (
        Index("ix_lot_part_supplier", "part_id", "supplier_id"),
        UniqueConstraint("lot_code"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lot_code: Mapped[str] = mapped_column(String(40))
    part_id: Mapped[int] = mapped_column(ForeignKey("part.id"))
    supplier_id: Mapped[int] = mapped_column(ForeignKey("supplier.id"))
    manufacture_date: Mapped[date] = mapped_column(Date)

    part: Mapped[Part] = relationship(back_populates="lots")
    supplier: Mapped[Supplier] = relationship(back_populates="lots")
    units: Mapped[list[Unit]] = relationship(back_populates="lot")


class Unit(Base):
    __tablename__ = "unit"
    __table_args__ = (Index("ix_unit_lot_build", "lot_id", "build_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    serial: Mapped[str] = mapped_column(String(64), unique=True)
    lot_id: Mapped[int] = mapped_column(ForeignKey("lot.id"))
    build_date: Mapped[date] = mapped_column(Date)

    lot: Mapped[Lot] = relationship(back_populates="units")
    episodes: Mapped[list[TestEpisode]] = relationship(back_populates="unit")


class TestStation(Base):
    __tablename__ = "test_station"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    fixture_id: Mapped[str] = mapped_column(String(80))
    last_calibration_date: Mapped[date] = mapped_column(Date)


class TestProtocol(Base):
    __tablename__ = "test_protocol"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    use_condition_temp_c: Mapped[Decimal] = mapped_column(Numeric(7, 3))
    use_condition_voltage_v: Mapped[Decimal] = mapped_column(Numeric(9, 4))
    planned_duration_hours: Mapped[Decimal] = mapped_column(Numeric(12, 3))


class TestEpisode(Base):
    """One independent lifetime observation for one non-repairable unit."""

    __tablename__ = "test_episode"
    __table_args__ = (
        UniqueConstraint("unit_id", "protocol_id"),
        Index("ix_episode_protocol_unit", "protocol_id", "unit_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    unit_id: Mapped[int] = mapped_column(ForeignKey("unit.id"))
    protocol_id: Mapped[int] = mapped_column(ForeignKey("test_protocol.id"))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    planned_duration_hours: Mapped[Decimal] = mapped_column(Numeric(12, 3))

    unit: Mapped[Unit] = relationship(back_populates="episodes")
    protocol: Mapped[TestProtocol] = relationship()
    runs: Mapped[list[TestRun]] = relationship(back_populates="episode")
    outcome: Mapped[UnitOutcome | None] = relationship(back_populates="episode", uselist=False)


class TestRun(Base):
    """A constant-stress segment within a test episode."""

    __tablename__ = "test_run"
    __table_args__ = (
        Index("ix_run_station_start", "station_id", "start_at"),
        Index("ix_run_episode_start", "episode_id", "start_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    episode_id: Mapped[int] = mapped_column(ForeignKey("test_episode.id"))
    station_id: Mapped[int] = mapped_column(ForeignKey("test_station.id"))
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    stress_temp_c: Mapped[Decimal] = mapped_column(Numeric(7, 3))
    stress_voltage_v: Mapped[Decimal] = mapped_column(Numeric(9, 4))
    humidity_pct: Mapped[Decimal] = mapped_column(Numeric(6, 3))

    episode: Mapped[TestEpisode] = relationship(back_populates="runs")
    station: Mapped[TestStation] = relationship()
    measurements: Mapped[list[Measurement]] = relationship(back_populates="run")


class Measurement(Base):
    __tablename__ = "measurement"
    __table_args__ = (
        Index("ix_measurement_run_param_time", "run_id", "param_name", "captured_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("test_run.id"))
    param_name: Mapped[str] = mapped_column(String(80))
    value: Mapped[Decimal] = mapped_column(Numeric(18, 8))
    uom: Mapped[str] = mapped_column(String(24))
    limit_low: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    limit_high: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    run: Mapped[TestRun] = relationship(back_populates="measurements")


class UnitOutcome(Base):
    __tablename__ = "unit_outcome"
    __table_args__ = (
        CheckConstraint("observed_duration_hours >= 0", name="ck_outcome_nonnegative_duration"),
        CheckConstraint(
            "(event_observed AND failure_mode IS NOT NULL) OR "
            "(NOT event_observed AND failure_mode IS NULL)",
            name="ck_outcome_failure_mode",
        ),
        Index("ix_outcome_event_mode", "event_observed", "failure_mode"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    episode_id: Mapped[int] = mapped_column(ForeignKey("test_episode.id"), unique=True)
    observed_duration_hours: Mapped[Decimal] = mapped_column(Numeric(12, 4))
    event_observed: Mapped[bool] = mapped_column(Boolean)
    failure_mode: Mapped[FailureMode | None] = mapped_column(Enum(FailureMode, name="failure_mode"))
    event_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    terminal_run_id: Mapped[int | None] = mapped_column(ForeignKey("test_run.id"))

    episode: Mapped[TestEpisode] = relationship(back_populates="outcome")
    terminal_run: Mapped[TestRun | None] = relationship(foreign_keys=[terminal_run_id])


class IngestionIssue(Base):
    __tablename__ = "ingestion_issue"
    __table_args__ = (Index("ix_issue_code_entity", "issue_code", "entity_type"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    issue_code: Mapped[IssueCode] = mapped_column(Enum(IssueCode, name="issue_code"))
    entity_type: Mapped[str] = mapped_column(String(40))
    source_key: Mapped[str] = mapped_column(String(120))
    detail: Mapped[str] = mapped_column(Text)
    excluded_from_analysis: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class DatasetManifest(Base):
    __tablename__ = "dataset_manifest"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dataset_version: Mapped[str] = mapped_column(String(80), unique=True)
    seed: Mapped[int] = mapped_column(Integer)
    profile: Mapped[str] = mapped_column(String(30))
    generator_version: Mapped[str] = mapped_column(String(30))
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    truth_json: Mapped[str] = mapped_column(Text)
