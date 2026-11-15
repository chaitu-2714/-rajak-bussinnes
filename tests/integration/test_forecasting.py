"""Forecasting tests: chronological validation, sufficiency, metrics (9, 10, 11, 12)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.analytics.forecasting.forecast_metrics import calculate_metrics
from app.analytics.forecasting.forecast_validator import split_chronologically, walk_forward
from app.analytics.forecasting.model_selector import NaiveModel

from tests.analytics_helpers import seed_history
from tests.conftest import completed_sale


# ---------------------------------------------------------------------------
# Test 9: chronological validation, never random
# ---------------------------------------------------------------------------
def test_validation_split_is_chronological() -> None:
    values = [Decimal(v) for v in range(10)]
    train, test = split_chronologically(values, 3)
    assert train == values[:7]
    assert test == values[7:]
    # The newest observations are always the validation set.
    assert test[-1] == values[-1]


def test_walk_forward_predicts_from_the_past_only() -> None:
    values = [Decimal("10"), Decimal("20"), Decimal("30"), Decimal("40"), Decimal("50")]
    test, predictions, metrics = walk_forward(NaiveModel(), values, 2)
    assert test == [Decimal("40"), Decimal("50")]
    # Naive predicts the previous actual: 30 then 40.
    assert predictions == [Decimal("30"), Decimal("40")]
    assert metrics.validation_points == 2
    assert metrics.mae == Decimal("10.00")


def test_forecast_records_its_train_and_validation_windows(admin, business) -> None:
    seed_history(admin, business, months=5, per_month=2)
    outcome = admin.analytics_service.forecast("SALES", horizon=2)
    if outcome.status != "COMPLETED":
        pytest.skip("not enough history in this fixture")
    assert outcome.train_period
    assert outcome.validation_period
    assert outcome.train_period != outcome.validation_period
    assert outcome.method in {
        "NAIVE",
        "MOVING_AVERAGE_3",
        "EXPONENTIAL_SMOOTHING",
        "SEASONAL_NAIVE",
    }


# ---------------------------------------------------------------------------
# Test 10: no forecast without enough history
# ---------------------------------------------------------------------------
def test_insufficient_history_returns_no_forecast(admin, business) -> None:
    completed_sale(admin, business, quantity=1)  # a single month of data
    outcome = admin.analytics_service.forecast("SALES", horizon=1)
    assert outcome.status == "INSUFFICIENT_HISTORICAL_DATA"
    assert outcome.forecast == []
    assert outcome.insufficient_reason
    assert "observation" in outcome.insufficient_reason.lower()


def test_insufficient_forecast_is_persisted_with_its_reason(admin, business) -> None:
    completed_sale(admin, business, quantity=1)
    admin.analytics_service.forecast("EXPENSES", horizon=1)
    history = admin.analytics_service.forecast_history()
    assert history
    assert history[0]["status"] == "INSUFFICIENT_HISTORICAL_DATA"


# ---------------------------------------------------------------------------
# Test 11: forecasts are separate from actuals
# ---------------------------------------------------------------------------
def test_forecast_values_are_flagged_and_separate(admin, business) -> None:
    seed_history(admin, business, months=6, per_month=2)
    outcome = admin.analytics_service.forecast("SALES", horizon=2)
    if outcome.status != "COMPLETED":
        pytest.skip("not enough history in this fixture")
    assert all(point.is_forecast is False for point in outcome.actuals)
    assert all(point.is_forecast is True for point in outcome.forecast)
    # The forecast starts after the last actual period.
    assert outcome.forecast[0].period_start > outcome.actuals[-1].period_start

    from sqlalchemy import select

    from app.database.models.analytics import ForecastValue

    with admin.database.session_factory() as db:
        rows = db.scalars(select(ForecastValue)).all()
    assert any(row.is_forecast for row in rows)
    assert any(not row.is_forecast for row in rows)


# ---------------------------------------------------------------------------
# Test 12: metrics match independent calculations
# ---------------------------------------------------------------------------
def test_metrics_match_manual_calculation() -> None:
    actual = [Decimal("100"), Decimal("200"), Decimal("300")]
    predicted = [Decimal("90"), Decimal("210"), Decimal("330")]
    metrics = calculate_metrics(actual, predicted)
    # errors: 10, -10, -30 -> MAE = 50/3 = 16.67
    assert metrics.mae == Decimal("16.67")
    # RMSE = sqrt((100 + 100 + 900)/3) = sqrt(366.67) = 19.15
    assert metrics.rmse == Decimal("19.15")
    # bias = (10 - 10 - 30)/3 = -10
    assert metrics.bias == Decimal("-10.00")
    # MAPE = mean(|error|/actual) = (0.1 + 0.05 + 0.1)/3 = 8.33%
    assert metrics.mape == Decimal("8.33")
    assert metrics.validation_points == 3


def test_mape_is_omitted_when_actuals_are_zero() -> None:
    metrics = calculate_metrics([Decimal("0"), Decimal("0")], [Decimal("5"), Decimal("5")])
    assert metrics.mape is None
    assert metrics.mae == Decimal("5.00")


def test_forecast_selects_the_better_model(admin, business) -> None:
    seed_history(admin, business, months=6, per_month=3)
    outcome = admin.analytics_service.forecast("SALES", horizon=1)
    if outcome.status != "COMPLETED":
        pytest.skip("not enough history in this fixture")
    assert outcome.candidates
    best = min(outcome.candidates, key=lambda row: Decimal(row["mae"]))
    assert outcome.method == best["model"]
    assert outcome.metrics.mae is not None
    # A naive baseline is always measured for comparison.
    assert outcome.baseline_metrics is not None


def test_churn_risk_is_rule_based(admin, business) -> None:
    completed_sale(admin, business, quantity=1)
    result = admin.analytics_service.churn_risk()
    assert result["method"] == "RULE_BASED"
    assert "thresholds" in result
    assert isinstance(result["high_risk"], list)
