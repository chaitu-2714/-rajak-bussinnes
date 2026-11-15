"""Analytics service: RBAC, persistence and exports for the BI layer."""

from __future__ import annotations

import hashlib
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session, sessionmaker

from app.analytics.analytics_engine import AnalyticsBundle, BusinessAnalyticsEngine
from app.analytics.periods import resolve_period
from app.analytics.schemas import (
    AnomalyFinding,
    ForecastOutcome,
    KPIItem,
    RiskItem,
    SimulationOutcome,
)
from app.core.constants import MODULE_ANALYTICS, AuditAction
from app.core.exceptions import NotFoundError, ValidationError
from app.core.logging_config import get_logger
from app.database.models.analytics import (
    AnalyticsReportHistory,
    AnalyticsSnapshot,
    AnomalyReview,
    BusinessKPI,
    BusinessRiskAssessment,
    BusinessSimulation,
    DetectedAnomaly,
    ForecastModelMetric,
    ForecastRun,
    ForecastValue,
    SimulationResult,
)
from app.services.audit_service import AuditService
from app.services.base_service import AuthContext, BaseService
from app.utils.date_utils import utcnow

logger = get_logger("services.analytics")

ZERO = Decimal("0.00")


class AnalyticsService(BaseService):
    """The UI and the AI tools talk to the analytics engine through this."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        auth_context: AuthContext,
        *,
        engine: BusinessAnalyticsEngine,
        audit_service: AuditService,
        export_service: Any,
    ) -> None:
        super().__init__(session_factory, auth_context)
        self._engine = engine
        self._audit = audit_service
        self._export = export_service

    # -- analysis ----------------------------------------------------------
    def analyze(
        self,
        granularity: str = "MONTHLY",
        *,
        reference: datetime | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        persist: bool = True,
    ) -> AnalyticsBundle:
        with self.unit_of_work(write=False) as db:
            self._authorize(db, "analytics.view")
        bundle = self._engine.analyze_business_performance(
            granularity, reference=reference, start=start, end=end
        )
        if persist:
            self._persist_bundle(bundle)
        return bundle

    def summary(self, granularity: str = "MONTHLY", **kwargs) -> dict[str, Any]:
        bundle = self.analyze(granularity, **kwargs)
        return {
            "period": bundle.period.label,
            "period_start": bundle.period.start,
            "period_end": bundle.period.end,
            "comparison_period": bundle.comparison.label if bundle.comparison else None,
            "quality": bundle.quality.model_dump(mode="json"),
            "financial": bundle.financial.model_dump(mode="json"),
            "sales": bundle.sales.model_dump(mode="json"),
            "customers": bundle.customers.model_dump(mode="json"),
            "inventory": bundle.inventory.model_dump(mode="json"),
            "suppliers": bundle.suppliers.model_dump(mode="json"),
            "insights": self._engine.generate_business_insights(bundle),
            "gaps": self._engine.identify_performance_gaps(bundle),
        }

    def insights(self, granularity: str = "MONTHLY", **kwargs) -> list[str]:
        return self._engine.generate_business_insights(self.analyze(granularity, **kwargs))

    def kpis(self, granularity: str = "MONTHLY", **kwargs) -> list[KPIItem]:
        bundle = self.analyze(granularity, **kwargs)
        return bundle.kpis

    def risks(self, granularity: str = "MONTHLY", **kwargs) -> list[RiskItem]:
        return self.analyze(granularity, **kwargs).risks

    def trend_series(self, months: int = 6) -> dict[str, Any]:
        """Revenue and expenses per month over a lookback window (chart data)."""
        with self.unit_of_work(write=False) as db:
            self._authorize(db, "analytics.view")
        from app.analytics.periods import resolve_period
        from datetime import timedelta

        end = resolve_period("MONTHLY").local_end
        start = (end.replace(day=1) - timedelta(days=31 * (months - 1))).replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        )
        period = resolve_period("CUSTOM", start=start, end=end)
        dataset = self._engine.collect_business_data(period, with_comparison=False)
        revenue = self._engine.builder.series_from_orders(dataset.orders, period)
        expenses = self._engine.builder.series_from_expenses(dataset.expenses, period)
        return {
            "period": period.label,
            "labels": [point.label for point in revenue],
            "revenue": [str(point.value) for point in revenue],
            "expenses": [str(point.value) for point in expenses],
        }

    # -- anomalies ---------------------------------------------------------
    def anomalies(self, granularity: str = "MONTHLY", **kwargs) -> list[AnomalyFinding]:
        with self.unit_of_work(write=False) as db:
            self._authorize(db, "analytics.view")
        bundle = self._engine.analyze_business_performance(granularity, **kwargs)
        return self._persist_anomalies(bundle)

    def list_anomalies(self, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        with self.unit_of_work(write=False) as db:
            self._authorize(db, "analytics.view")
            query = select(DetectedAnomaly).order_by(DetectedAnomaly.id.desc()).limit(limit)
            if status:
                query = (
                    select(DetectedAnomaly)
                    .where(DetectedAnomaly.review_status == status)
                    .order_by(DetectedAnomaly.id.desc())
                    .limit(limit)
                )
            rows = db.scalars(query).all()
            return [
                {
                    "anomaly_id": row.anomaly_id,
                    "category": row.category,
                    "anomaly_type": row.anomaly_type,
                    "affected_record": row.affected_record,
                    "detection_method": row.detection_method,
                    "observed_value": str(row.observed_value) if row.observed_value is not None else None,
                    "expected_value": str(row.expected_value) if row.expected_value is not None else None,
                    "deviation": str(row.deviation) if row.deviation is not None else None,
                    "severity": row.severity,
                    "evidence": row.evidence or {},
                    "explanation": row.explanation,
                    "detected_at": row.detected_at,
                    "review_status": row.review_status,
                }
                for row in rows
            ]

    def review_anomaly(self, anomaly_id: str, *, decision: str, note: str | None = None) -> dict[str, Any]:
        decision = (decision or "").upper()
        if decision not in ("ACKNOWLEDGED", "DISMISSED", "ESCALATED", "RESOLVED"):
            raise ValidationError(
                "A review decision must be ACKNOWLEDGED, DISMISSED, ESCALATED or RESOLVED"
            )
        with self.unit_of_work() as db:
            user = self._authorize(db, "analytics.manage")
            row = db.scalars(
                select(DetectedAnomaly).where(DetectedAnomaly.anomaly_id == anomaly_id)
            ).first()
            if row is None:
                raise NotFoundError(f"Anomaly '{anomaly_id}' was not found")
            row.review_status = decision
            db.add(
                AnomalyReview(
                    anomaly_id=anomaly_id, decision=decision, note=note, reviewed_by=user.id
                )
            )
            self._audit.record(
                db,
                actor_id=user.id,
                action=AuditAction.ANOMALY_REVIEWED,
                module=MODULE_ANALYTICS,
                entity_type="DetectedAnomaly",
                entity_id=anomaly_id,
                new_values={"decision": decision, "note": note},
            )
            return {"anomaly_id": anomaly_id, "review_status": decision}

    # -- forecasting -------------------------------------------------------
    def forecast(
        self,
        target: str = "SALES",
        *,
        horizon: int = 1,
        product_id: int | None = None,
    ) -> ForecastOutcome:
        with self.unit_of_work(write=False) as db:
            self._authorize(db, "analytics.view")
        target = (target or "SALES").upper()
        if horizon < 1 or horizon > 12:
            raise ValidationError("The forecast horizon must be between 1 and 12 periods")
        if target == "SALES":
            outcome = self._engine.forecasting.forecast_sales(horizon=horizon)
        elif target == "REVENUE":
            outcome = self._engine.forecasting.forecast_revenue(horizon=horizon)
        elif target == "EXPENSES":
            outcome = self._engine.forecasting.forecast_expenses(horizon=horizon)
        elif target == "CASH_FLOW":
            outcome = self._engine.forecasting.forecast_cash_flow(horizon=horizon)
        elif target == "DEMAND":
            if product_id is None:
                raise ValidationError("Demand forecasting needs a product")
            outcome = self._engine.forecasting.forecast_demand(product_id, horizon=horizon)
        else:
            raise ValidationError(
                f"Unknown forecast target '{target}'. Use SALES, REVENUE, EXPENSES, "
                "CASH_FLOW or DEMAND"
            )
        self._persist_forecast(outcome)
        return outcome

    def churn_risk(self) -> dict[str, Any]:
        with self.unit_of_work(write=False) as db:
            self._authorize(db, "analytics.view")
        bundle = self._engine.analyze_business_performance("MONTHLY", include_anomalies=False)
        return self._engine.forecasting.churn_risk(bundle.dataset.customers)

    def forecast_history(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.unit_of_work(write=False) as db:
            self._authorize(db, "analytics.view")
            rows = db.scalars(
                select(ForecastRun).order_by(ForecastRun.id.desc()).limit(limit)
            ).all()
            return [
                {
                    "run_ref": row.run_ref,
                    "target": row.target,
                    "method": row.method,
                    "status": row.status,
                    "data_points": row.data_points,
                    "horizon": row.horizon,
                    "trained_at": row.trained_at,
                    "metrics": {
                        metric.metric_name: metric.value for metric in row.metrics
                    },
                }
                for row in rows
            ]

    # -- simulation --------------------------------------------------------
    def simulate(
        self, scenario: str, *, parameters: dict | None = None, granularity: str = "MONTHLY"
    ) -> SimulationOutcome:
        with self.unit_of_work(write=False) as db:
            user = self._authorize(db, "analytics.manage")
            actor = user.id
        bundle = self._engine.analyze_business_performance(
            granularity, include_anomalies=False, include_risks=False
        )
        outcome = self._engine.simulation.simulate(
            scenario,
            parameters=parameters or {},
            financial=bundle.financial,
            sales=bundle.sales,
            inventory=bundle.inventory,
            customers=bundle.customers,
        )
        self._persist_simulation(outcome, actor)
        return outcome

    # -- reports -----------------------------------------------------------
    def generate_report(
        self, report_type: str, *, file_format: str = "PDF", granularity: str = "MONTHLY"
    ) -> dict[str, Any]:
        with self.unit_of_work(write=False) as db:
            user = self._authorize(db, "reports.view")
            actor = user.id
        bundle = self._engine.analyze_business_performance(granularity)
        extra: dict[str, Any] = {}
        if report_type.upper() == "FORECAST":
            extra["forecasts"] = [self._engine.forecasting.forecast_sales(horizon=3)]
        if report_type.upper() == "SIMULATION":
            extra["simulation"] = self._engine.simulation.simulate(
                "SALES_DECLINE",
                parameters={"percent": 10},
                financial=bundle.financial,
                sales=bundle.sales,
                inventory=bundle.inventory,
            )
        from app.analytics.reports.analytics_report_service import AnalyticsReportService

        service = AnalyticsReportService(self._engine._services)
        table = service.build_report(report_type, bundle, extra=extra)
        stamp = utcnow().strftime("%Y%m%d_%H%M%S")
        base = f"{report_type.lower()}_{bundle.period.start:%Y%m}_" + stamp
        if file_format.upper() == "CSV":
            path = self._export.write_report_csv(table, f"{base}.csv")
            file_format = "CSV"
        else:
            path = self._export.write_pdf_report(table, f"{base}.pdf")
            file_format = "PDF"
        with self.unit_of_work() as db:
            db.add(
                AnalyticsReportHistory(
                    report_ref=f"rep-{stamp}",
                    report_type=report_type.upper(),
                    period_label=bundle.period.label,
                    period_start=bundle.period.start,
                    period_end=bundle.period.end,
                    file_format=file_format,
                    file_name=path.name,
                    generated_by=actor,
                )
            )
            self._audit.record(
                db,
                actor_id=actor,
                action=AuditAction.ANALYTICS_REPORT_GENERATED,
                module=MODULE_ANALYTICS,
                entity_type="AnalyticsReport",
                entity_id=path.name,
                new_values={"report_type": report_type, "format": file_format},
            )
        return {
            "report_type": report_type.upper(),
            "period": bundle.period.label,
            "file": path.name,
            "path": str(path),
            "format": file_format,
            "rows": len(table.rows),
        }

    def report_history(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.unit_of_work(write=False) as db:
            self._authorize(db, "analytics.view")
            rows = db.scalars(
                select(AnalyticsReportHistory)
                .order_by(AnalyticsReportHistory.id.desc())
                .limit(limit)
            ).all()
            return [
                {
                    "report_ref": row.report_ref,
                    "report_type": row.report_type,
                    "period": row.period_label,
                    "format": row.file_format,
                    "file": row.file_name,
                    "created_at": row.created_at,
                }
                for row in rows
            ]

    # -- persistence -------------------------------------------------------
    def _persist_bundle(self, bundle: AnalyticsBundle) -> None:
        with self.unit_of_work() as db:
            payload = {
                "financial": bundle.financial.model_dump(mode="json"),
                "sales": bundle.sales.model_dump(mode="json"),
                "customers": bundle.customers.model_dump(mode="json"),
                "inventory": bundle.inventory.model_dump(mode="json"),
                "suppliers": bundle.suppliers.model_dump(mode="json"),
                "quality": bundle.quality.model_dump(mode="json"),
            }
            values = {
                "snapshot_key": f"bundle:{bundle.period.granularity}:{bundle.period.label}",
                "snapshot_type": "PERIOD_BUNDLE",
                "period_start": bundle.period.start,
                "period_end": bundle.period.end,
                "granularity": bundle.period.granularity,
                "payload": payload,
                "data_points": len(bundle.dataset.orders) if bundle.dataset else 0,
                "completeness": bundle.quality.completeness,
                "created_at": utcnow(),
            }
            # Upsert: concurrent refreshes must not collide on the unique key.
            db.execute(
                sqlite_insert(AnalyticsSnapshot)
                .values(**values)
                .on_conflict_do_update(
                    index_elements=["snapshot_key"],
                    set_={
                        "payload": payload,
                        "data_points": values["data_points"],
                        "completeness": values["completeness"],
                        "period_start": values["period_start"],
                        "period_end": values["period_end"],
                    },
                )
            )
            for kpi in bundle.kpis:
                self._upsert_kpi(db, kpi, bundle)
        self._persist_anomalies(bundle)
        self._persist_risks(bundle)

    def _upsert_kpi(self, db: Session, kpi: KPIItem, bundle: AnalyticsBundle) -> None:
        key = f"{kpi.kpi_key}:{bundle.period.label}"
        values = {
            "kpi_key": key,
            "kpi_name": kpi.kpi_name,
            "category": kpi.category,
            "formula": kpi.formula,
            "period_label": kpi.period_label,
            "period_start": bundle.period.start,
            "period_end": bundle.period.end,
            "actual_value": float(kpi.actual) if kpi.actual is not None else None,
            "comparison_value": float(kpi.comparison) if kpi.comparison is not None else None,
            "unit": kpi.unit,
            "data_completeness": kpi.completeness,
            "source_records": kpi.source_records,
            "limitation": kpi.limitation,
            "updated_at": utcnow(),
        }
        db.execute(
            sqlite_insert(BusinessKPI)
            .values(**values)
            .on_conflict_do_update(
                index_elements=["kpi_key"],
                set_={k: v for k, v in values.items() if k != "kpi_key"},
            )
        )

    def _persist_anomalies(self, bundle: AnalyticsBundle) -> list[AnomalyFinding]:
        with self.unit_of_work() as db:
            existing = {
                row.anomaly_id: row.review_status
                for row in db.scalars(select(DetectedAnomaly)).all()
            }
            for finding in bundle.anomalies:
                deterministic = "anm-" + hashlib.sha1(
                    f"{finding.category}|{finding.anomaly_type}|{finding.affected_record}|"
                    f"{bundle.period.label}".encode()
                ).hexdigest()[:12]
                finding.anomaly_id = deterministic
                values = {
                    "anomaly_id": deterministic,
                    "category": finding.category,
                    "anomaly_type": finding.anomaly_type,
                    "affected_record": finding.affected_record,
                    "affected_record_id": finding.affected_record_id,
                    "detection_method": finding.detection_method,
                    "observed_value": float(finding.observed_value)
                    if finding.observed_value is not None
                    else None,
                    "expected_value": float(finding.expected_value)
                    if finding.expected_value is not None
                    else None,
                    "deviation": float(finding.deviation) if finding.deviation is not None else None,
                    "severity": finding.severity,
                    "evidence": finding.evidence,
                    "explanation": finding.explanation,
                    "detected_at": finding.detected_at or utcnow(),
                    # A human review decision is never overwritten by a refresh.
                    "review_status": existing.get(deterministic, "NEW"),
                }
                db.execute(
                    sqlite_insert(DetectedAnomaly)
                    .values(**values)
                    .on_conflict_do_update(
                        index_elements=["anomaly_id"],
                        set_={
                            key: value
                            for key, value in values.items()
                            if key not in ("anomaly_id", "review_status")
                        },
                    )
                )
        return bundle.anomalies

    def _persist_risks(self, bundle: AnalyticsBundle) -> None:
        with self.unit_of_work() as db:
            for risk in bundle.risks:
                values = {
                    "risk_key": f"{risk.risk_key}:{bundle.period.label}",
                    "category": risk.category,
                    "description": risk.description,
                    "evidence": risk.evidence,
                    "likelihood": risk.likelihood,
                    "impact": risk.impact,
                    "severity": risk.severity,
                    "score": float(risk.score),
                    "formula": risk.formula,
                    "mitigation": risk.mitigation,
                    "data_limitations": risk.data_limitations,
                    "assessed_at": utcnow(),
                }
                db.execute(
                    sqlite_insert(BusinessRiskAssessment)
                    .values(**values)
                    .on_conflict_do_update(
                        index_elements=["risk_key"],
                        set_={k: v for k, v in values.items() if k != "risk_key"},
                    )
                )

    def _persist_forecast(self, outcome: ForecastOutcome) -> None:
        with self.unit_of_work() as db:
            run = ForecastRun(
                run_ref=f"fc-{utcnow().strftime('%Y%m%d%H%M%S')}-{outcome.target.lower()}",
                target=outcome.target,
                metric=outcome.metric,
                method=outcome.method or "NONE",
                status=outcome.status,
                data_points=outcome.data_points,
                horizon=outcome.horizon,
                model_version=outcome.model_version,
                notes=outcome.method_note,
                insufficient_reason=outcome.insufficient_reason,
            )
            if outcome.actuals:
                run.train_start = outcome.actuals[0].period_start
                run.train_end = outcome.actuals[-1].period_start
            if outcome.forecast:
                run.validation_start = outcome.forecast[0].period_start
                run.validation_end = outcome.forecast[-1].period_start
            db.add(run)
            db.flush()
            for point in outcome.actuals:
                db.add(
                    ForecastValue(
                        run_id=run.id,
                        period_label=point.label,
                        period_start=point.period_start,
                        value=float(point.value),
                        is_forecast=False,
                    )
                )
            for point in outcome.forecast:
                db.add(
                    ForecastValue(
                        run_id=run.id,
                        period_label=point.label,
                        period_start=point.period_start,
                        value=float(point.value),
                        lower_bound=float(point.lower) if point.lower is not None else None,
                        upper_bound=float(point.upper) if point.upper is not None else None,
                        is_forecast=True,
                    )
                )
            metrics = outcome.metrics
            for name, value in (
                ("MAE", metrics.mae),
                ("RMSE", metrics.rmse),
                ("MAPE", metrics.mape),
                ("SMAPE", metrics.smape),
                ("BIAS", metrics.bias),
            ):
                db.add(
                    ForecastModelMetric(
                        run_id=run.id,
                        metric_name=name,
                        value=float(value) if value is not None else None,
                        note=f"validation points: {metrics.validation_points}",
                    )
                )
            outcome.run_ref = run.run_ref

    def _persist_simulation(self, outcome: SimulationOutcome, actor_id: int) -> None:
        with self.unit_of_work() as db:
            simulation = BusinessSimulation(
                simulation_ref=outcome.simulation_ref or f"sim-{utcnow().strftime('%Y%m%d%H%M%S')}",
                scenario_type=outcome.scenario_type,
                parameters=outcome.parameters,
                baseline={"label": outcome.label},
                assumptions=outcome.assumptions,
                limitations=outcome.limitations,
                label=outcome.label,
                created_by=actor_id,
            )
            db.add(simulation)
            db.flush()
            for line in outcome.lines:
                db.add(
                    SimulationResult(
                        simulation_id=simulation.id,
                        metric=line.metric,
                        baseline_value=float(line.baseline) if line.baseline is not None else None,
                        simulated_value=float(line.simulated) if line.simulated is not None else None,
                        delta=float(line.delta) if line.delta is not None else None,
                        delta_percent=(
                            float(line.delta_percent) if line.delta_percent is not None else None
                        ),
                        unit=line.unit,
                    )
                )
            outcome.simulation_ref = simulation.simulation_ref
