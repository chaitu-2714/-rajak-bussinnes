"""Phase 7 models: analytics snapshots, KPIs, anomalies, forecasts, risk, simulations."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.utils.date_utils import utcnow


class AnalyticsSnapshot(Base):
    """A derived, point-in-time analytics payload (never a copy of raw business data)."""

    __tablename__ = "analytics_snapshots"
    __table_args__ = (UniqueConstraint("snapshot_key", name="uq_analytics_snapshots_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    snapshot_key: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    snapshot_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    period_start: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    period_end: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    granularity: Mapped[str] = mapped_column(String(20), nullable=False, default="MONTHLY")
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    data_points: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completeness: Mapped[str] = mapped_column(String(20), nullable=False, default="COMPLETE")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow, index=True)


class BusinessKPI(Base):
    """A stored KPI reading with its formula and provenance."""

    __tablename__ = "business_kpis"
    __table_args__ = (UniqueConstraint("kpi_key", name="uq_business_kpis_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kpi_key: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    kpi_name: Mapped[str] = mapped_column(String(120), nullable=False)
    category: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    formula: Mapped[str] = mapped_column(Text, nullable=False, default="")
    period_label: Mapped[str] = mapped_column(String(40), nullable=False)
    period_start: Mapped[datetime | None] = mapped_column(DateTime)
    period_end: Mapped[datetime | None] = mapped_column(DateTime)
    actual_value: Mapped[float | None] = mapped_column(Numeric(18, 4))
    comparison_value: Mapped[float | None] = mapped_column(Numeric(18, 4))
    unit: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    data_completeness: Mapped[str] = mapped_column(String(20), nullable=False, default="COMPLETE")
    source_records: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    limitation: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow, index=True)


class DetectedAnomaly(Base):
    """A review finding produced by anomaly detection (never a data change)."""

    __tablename__ = "detected_anomalies"
    __table_args__ = (UniqueConstraint("anomaly_id", name="uq_detected_anomalies_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    anomaly_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    anomaly_type: Mapped[str] = mapped_column(String(60), nullable=False)
    affected_record: Mapped[str] = mapped_column(String(120), nullable=False)
    affected_record_id: Mapped[int | None] = mapped_column(Integer)
    detection_method: Mapped[str] = mapped_column(String(60), nullable=False)
    observed_value: Mapped[float | None] = mapped_column(Numeric(18, 4))
    expected_value: Mapped[float | None] = mapped_column(Numeric(18, 4))
    deviation: Mapped[float | None] = mapped_column(Numeric(18, 4))
    severity: Mapped[str] = mapped_column(String(10), nullable=False, default="LOW", index=True)
    evidence: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    explanation: Mapped[str] = mapped_column(Text, nullable=False, default="")
    detected_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow, index=True)
    review_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="NEW", index=True, server_default=text("'NEW'")
    )


class AnomalyReview(Base):
    """A human review decision on an anomaly."""

    __tablename__ = "anomaly_reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    anomaly_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    decision: Mapped[str] = mapped_column(String(20), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)


class ForecastRun(Base):
    """One forecasting run with its validation record."""

    __tablename__ = "forecast_runs"
    __table_args__ = (UniqueConstraint("run_ref", name="uq_forecast_runs_ref"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_ref: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    target: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    metric: Mapped[str] = mapped_column(String(60), nullable=False)
    method: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="COMPLETED", index=True)
    data_points: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    horizon: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    train_start: Mapped[datetime | None] = mapped_column(DateTime)
    train_end: Mapped[datetime | None] = mapped_column(DateTime)
    validation_start: Mapped[datetime | None] = mapped_column(DateTime)
    validation_end: Mapped[datetime | None] = mapped_column(DateTime)
    model_version: Mapped[str] = mapped_column(String(40), nullable=False, default="1.0")
    trained_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow, index=True)
    notes: Mapped[str | None] = mapped_column(Text)
    insufficient_reason: Mapped[str | None] = mapped_column(Text)

    values: Mapped[list["ForecastValue"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    metrics: Mapped[list["ForecastModelMetric"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class ForecastValue(Base):
    """A forecast (or the actual comparison) for one period."""

    __tablename__ = "forecast_values"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("forecast_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    period_label: Mapped[str] = mapped_column(String(20), nullable=False)
    period_start: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    value: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    lower_bound: Mapped[float | None] = mapped_column(Numeric(18, 4))
    upper_bound: Mapped[float | None] = mapped_column(Numeric(18, 4))
    is_forecast: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    run: Mapped["ForecastRun"] = relationship(back_populates="values")


class ForecastModelMetric(Base):
    """A measured validation metric (MAE, RMSE, MAPE, sMAPE, bias)."""

    __tablename__ = "forecast_model_metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("forecast_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    metric_name: Mapped[str] = mapped_column(String(20), nullable=False)
    value: Mapped[float | None] = mapped_column(Float)
    note: Mapped[str | None] = mapped_column(String(160))

    run: Mapped["ForecastRun"] = relationship(back_populates="metrics")


class BusinessRiskAssessment(Base):
    """A risk finding with a transparent score."""

    __tablename__ = "business_risk_assessments"
    __table_args__ = (UniqueConstraint("risk_key", name="uq_business_risk_assessments_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    risk_key: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    likelihood: Mapped[str] = mapped_column(String(20), nullable=False, default="MEDIUM")
    impact: Mapped[str] = mapped_column(String(20), nullable=False, default="MEDIUM")
    severity: Mapped[str] = mapped_column(String(10), nullable=False, default="MEDIUM", index=True)
    score: Mapped[float | None] = mapped_column(Numeric(6, 2))
    formula: Mapped[str] = mapped_column(Text, nullable=False, default="")
    mitigation: Mapped[str] = mapped_column(Text, nullable=False, default="")
    data_limitations: Mapped[str | None] = mapped_column(Text)
    assessed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow, index=True)


class BusinessSimulation(Base):
    """A hypothetical scenario. Never modifies business records."""

    __tablename__ = "business_simulations"
    __table_args__ = (UniqueConstraint("simulation_ref", name="uq_business_simulations_ref"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    simulation_ref: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    scenario_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    parameters: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    baseline: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    assumptions: Mapped[list[Any] | None] = mapped_column(JSON)
    limitations: Mapped[list[Any] | None] = mapped_column(JSON)
    label: Mapped[str] = mapped_column(
        String(60), nullable=False, default="HYPOTHETICAL SCENARIO — NOT AN ACTUAL BUSINESS RESULT"
    )
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow, index=True)

    results: Mapped[list["SimulationResult"]] = relationship(
        back_populates="simulation", cascade="all, delete-orphan"
    )


class SimulationResult(Base):
    """One metric comparison from a simulation."""

    __tablename__ = "simulation_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    simulation_id: Mapped[int] = mapped_column(
        ForeignKey("business_simulations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    metric: Mapped[str] = mapped_column(String(60), nullable=False)
    baseline_value: Mapped[float | None] = mapped_column(Numeric(18, 4))
    simulated_value: Mapped[float | None] = mapped_column(Numeric(18, 4))
    delta: Mapped[float | None] = mapped_column(Numeric(18, 4))
    delta_percent: Mapped[float | None] = mapped_column(Numeric(10, 2))
    unit: Mapped[str] = mapped_column(String(20), nullable=False, default="")

    simulation: Mapped["BusinessSimulation"] = relationship(back_populates="results")


class AnalyticsReportHistory(Base):
    """A generated analytics report."""

    __tablename__ = "analytics_report_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    report_ref: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    report_type: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    period_label: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    period_start: Mapped[datetime | None] = mapped_column(DateTime)
    period_end: Mapped[datetime | None] = mapped_column(DateTime)
    file_format: Mapped[str] = mapped_column(String(10), nullable=False, default="PDF")
    file_name: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    generated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow, index=True)
