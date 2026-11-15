"""Predictive analytics: sales, revenue, expense, demand, cash and churn.

Every forecast states its method, its validation metrics and its assumptions. If
the history is too short the engine returns INSUFFICIENT_HISTORICAL_DATA rather
than inventing a number.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from app.analytics.data_collector import BusinessDataCollector
from app.analytics.dataset_builder import CASH_IN_CATEGORIES
from app.analytics.forecasting.forecast_metrics import calculate_metrics
from app.analytics.forecasting.forecast_validator import residual_interval, walk_forward
from app.analytics.forecasting.model_selector import MIN_POINTS_FOR_MODELS, candidate_models
from app.analytics.periods import AnalyticsPeriod, monthly_buckets, resolve_period
from app.analytics.schemas import ForecastOutcome, ForecastPoint, money
from app.core.logging_config import get_logger
from app.utils.date_utils import to_local, utcnow

logger = get_logger("analytics.forecasting")

ZERO = Decimal("0.00")
MIN_POINTS = 4  # below this, no forecast at all


class PredictiveAnalyticsEngine:
    """Forecasting with chronological validation and honest sufficiency checks."""

    def __init__(self, collector: BusinessDataCollector, *, lookback_months: int = 12) -> None:
        self._collector = collector
        self._lookback_months = lookback_months

    # -- public API --------------------------------------------------------
    def forecast_sales(self, *, horizon: int = 1, end: datetime | None = None) -> ForecastOutcome:
        series = self._monthly_orders_series(end)
        return self._run("SALES", "monthly sales revenue", series, horizon, unit="₹")

    def forecast_revenue(self, *, horizon: int = 1, end: datetime | None = None) -> ForecastOutcome:
        outcome = self.forecast_sales(horizon=horizon, end=end)
        outcome.target = "REVENUE"
        outcome.metric = "monthly revenue"
        return outcome

    def forecast_expenses(self, *, horizon: int = 1, end: datetime | None = None) -> ForecastOutcome:
        series = self._monthly_expense_series(end)
        return self._run("EXPENSES", "monthly operating expenses", series, horizon, unit="₹")

    def forecast_demand(
        self, product_id: int, *, horizon: int = 1, end: datetime | None = None
    ) -> ForecastOutcome:
        series = self._monthly_demand_series(product_id, end)
        return self._run(
            "DEMAND", f"monthly units for product #{product_id}", series, horizon, unit="units"
        )

    def forecast_cash_flow(self, *, horizon: int = 1, end: datetime | None = None) -> ForecastOutcome:
        inflow = self._monthly_cash_series(end)
        outflow = self._monthly_expense_series(end)
        outcome = self._run("CASH_INFLOW", "monthly cash received", inflow, horizon, unit="₹")
        if outcome.status == "COMPLETED":
            outcome.assumptions.append(
                "Cash inflow assumes collections continue at the historical pattern; "
                "outstanding invoices are not assumed to be paid on time."
            )
            if outflow:
                outcome.assumptions.append(
                    "Recorded expenses are assumed to continue at their historical level; "
                    "known commitments outside the expense records are not included."
                )
        return outcome

    def churn_risk(self, customers: list[dict], *, at_risk_days: int = 60, inactive_days: int = 90) -> dict:
        """Rule-based churn indicators — no trained model, because labels do not exist."""
        now = utcnow()
        high: list[dict] = []
        medium: list[dict] = []
        for customer in customers:
            last = customer.get("last_purchase")
            if last is None:
                continue
            days = (now - last).days
            orders = customer.get("orders") or 0
            if days > inactive_days:
                high.append(
                    {
                        "customer": customer["name"],
                        "days_since_purchase": days,
                        "orders": orders,
                        "indicator": "no purchase for more than the inactivity threshold",
                    }
                )
            elif days > at_risk_days:
                medium.append(
                    {
                        "customer": customer["name"],
                        "days_since_purchase": days,
                        "orders": orders,
                        "indicator": "purchase gap approaching the inactivity threshold",
                    }
                )
        return {
            "method": "RULE_BASED",
            "method_note": "Days since last purchase compared with configurable thresholds. "
            "No predictive model is trained because no labelled churn history exists.",
            "thresholds": {"at_risk_days": at_risk_days, "inactive_days": inactive_days},
            "high_risk": high,
            "medium_risk": medium,
        }

    # -- core --------------------------------------------------------------
    def _run(
        self, target: str, metric: str, series: list[tuple[str, datetime, Decimal]], horizon: int, *, unit: str
    ) -> ForecastOutcome:
        values = [value for _, _, value in series]
        outcome = ForecastOutcome(
            target=target,
            metric=metric,
            horizon=horizon,
            data_points=len(values),
            assumptions=[
                f"Forecast is based on {len(values)} monthly observation(s) of recorded data.",
                "The forecast extends the recent pattern; it is not a guarantee.",
            ],
            limitations=[
                "Forecast values are estimates and are never shown as actual results.",
            ],
        )
        if len(values) < MIN_POINTS:
            outcome.status = "INSUFFICIENT_HISTORICAL_DATA"
            outcome.insufficient_reason = (
                f"Only {len(values)} monthly observation(s) are available; at least {MIN_POINTS} "
                "are required for a forecast."
            )
            outcome.actuals = [
                ForecastPoint(label=label, period_start=start, value=money(value), is_forecast=False)
                for label, start, value in series
            ]
            return outcome

        validation_points = max(2, min(len(values) // 4, len(values) - 2))
        candidates: list[dict] = []
        best = None
        baseline_metrics = None
        for model in candidate_models(len(values)):
            test, predictions, metrics = walk_forward(model, values, validation_points)
            if not test:
                continue
            candidates.append(
                {
                    "model": model.name,
                    "description": model.description,
                    "mae": str(metrics.mae),
                    "rmse": str(metrics.rmse),
                    "validation_points": metrics.validation_points,
                }
            )
            if model.name == "NAIVE":
                baseline_metrics = metrics
            if best is None or (metrics.mae or ZERO) < (best[2].mae or ZERO):
                best = (model, predictions, metrics)

        if best is None:
            outcome.status = "INSUFFICIENT_HISTORICAL_DATA"
            outcome.insufficient_reason = "No candidate model could be validated on this history."
            return outcome

        model, predictions, metrics = best
        outcome.method = model.name
        outcome.method_note = model.description
        outcome.metrics = metrics
        outcome.baseline_metrics = baseline_metrics
        outcome.candidates = candidates
        if baseline_metrics and model.name != "NAIVE" and (metrics.mae or ZERO) >= (baseline_metrics.mae or ZERO):
            outcome.limitations.append(
                "The selected model did not beat the naive baseline on validation error; "
                "treat the forecast as a rough indication."
            )

        outcome.train_period = f"{series[0][0]} – {series[max(0, len(series) - validation_points - 1)][0]}"
        outcome.validation_period = f"{series[len(series) - validation_points][0]} – {series[-1][0]}"

        # Actuals: the observed series (never mixed with forecast values).
        outcome.actuals = [
            ForecastPoint(label=label, period_start=start, value=money(value), is_forecast=False)
            for label, start, value in series
        ]

        # Forecast: refit on the full history, then step forward.
        half_width = residual_interval(values, model, predictions)
        history = list(values)
        last_label, last_start, _ = series[-1]
        forecast: list[ForecastPoint] = []
        for step in range(1, horizon + 1):
            prediction = model.fit_predict(history)
            next_start = self._next_month(last_start, step)
            forecast.append(
                ForecastPoint(
                    label=next_start.strftime("%b %Y"),
                    period_start=next_start,
                    value=money(prediction),
                    lower=money(max(ZERO, prediction - half_width)),
                    upper=money(prediction + half_width),
                    is_forecast=True,
                )
            )
            history.append(prediction)
        outcome.forecast = forecast
        if half_width > ZERO:
            outcome.assumptions.append(
                f"Prediction interval is ±{half_width:,.2f}, from the validation residuals "
                "(not a statistical confidence interval)."
            )
        outcome.model_version = "1.0"
        return outcome

    # -- series builders ---------------------------------------------------
    def _window(self, end: datetime | None) -> tuple[datetime, datetime]:
        period = resolve_period("MONTHLY", reference=end)
        start = period.local_start - timedelta(days=31 * (self._lookback_months - 1))
        return start.replace(day=1, hour=0, minute=0, second=0, microsecond=0), period.local_end

    def _monthly_orders_series(self, end: datetime | None):
        start, finish = self._window(end)
        period = self._period_for(start, finish)
        dataset = self._collector.collect_business_data(period)
        buckets = monthly_buckets(period)
        totals = {label: ZERO for label, _, _ in buckets}
        for order in dataset.orders:
            local = to_local(order["created_at"])
            for label, bstart, bend in buckets:
                if local and bstart <= local <= bend:
                    totals[label] += Decimal(str(order["total"]))
                    break
        return self._trim_leading_zeros(
            [(label, bstart, totals[label]) for label, bstart, _ in buckets]
        )

    def _monthly_expense_series(self, end: datetime | None):
        start, finish = self._window(end)
        period = self._period_for(start, finish)
        dataset = self._collector.collect_business_data(period)
        buckets = monthly_buckets(period)
        totals = {label: ZERO for label, _, _ in buckets}
        for expense in dataset.expenses:
            local = to_local(expense["date"])
            for label, bstart, bend in buckets:
                if local and bstart <= local <= bend:
                    totals[label] += Decimal(str(expense["amount"]))
                    break
        return self._trim_leading_zeros(
            [(label, bstart, totals[label]) for label, bstart, _ in buckets]
        )

    def _monthly_demand_series(self, product_id: int, end: datetime | None):
        start, finish = self._window(end)
        period = self._period_for(start, finish)
        dataset = self._collector.collect_business_data(period)
        buckets = monthly_buckets(period)
        totals = {label: ZERO for label, _, _ in buckets}
        for line in dataset.lines:
            if line["product_id"] != product_id:
                continue
            local = to_local(line["created_at"])
            for label, bstart, bend in buckets:
                if local and bstart <= local <= bend:
                    totals[label] += Decimal(int(line["quantity"]))
                    break
        return self._trim_leading_zeros(
            [(label, bstart, totals[label]) for label, bstart, _ in buckets]
        )

    def _monthly_cash_series(self, end: datetime | None):
        start, finish = self._window(end)
        period = self._period_for(start, finish)
        dataset = self._collector.collect_business_data(period)
        buckets = monthly_buckets(period)
        totals = {label: ZERO for label, _, _ in buckets}
        for row in dataset.transactions:
            if row["category"] not in CASH_IN_CATEGORIES:
                continue
            local = to_local(row["date"])
            for label, bstart, bend in buckets:
                if local and bstart <= local <= bend:
                    totals[label] += Decimal(str(row["amount"]))
                    break
        return self._trim_leading_zeros(
            [(label, bstart, totals[label]) for label, bstart, _ in buckets]
        )

    def _trim_leading_zeros(self, series: list[tuple[str, datetime, Decimal]]):
        """Months before the first recorded activity are not observations."""
        first = next(
            (index for index, (_, _, value) in enumerate(series) if value > ZERO), None
        )
        if first is None:
            return []
        return series[first:]

    def _period_for(self, start: datetime, finish: datetime) -> AnalyticsPeriod:
        return resolve_period("CUSTOM", start=start, end=finish)

    def _next_month(self, value: datetime, step: int) -> datetime:
        year = value.year + (value.month - 1 + step) // 12
        month = (value.month - 1 + step) % 12 + 1
        return value.replace(year=year, month=month, day=1)
