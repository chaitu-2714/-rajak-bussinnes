"""Chronological, walk-forward validation for time series.

Records are never shuffled: the model is always asked to predict a period using
only the observations that came before it.
"""

from __future__ import annotations

from decimal import Decimal

from app.analytics.forecasting.forecast_metrics import calculate_metrics
from app.analytics.schemas import ModelMetrics

ZERO = Decimal("0.00")


def split_chronologically(values: list[Decimal], validation_points: int) -> tuple[list[Decimal], list[Decimal]]:
    """Split into (train, test) preserving order — the newest points are the test set."""
    if validation_points <= 0 or validation_points >= len(values):
        return values, []
    return values[:-validation_points], values[-validation_points:]


def walk_forward(
    model, values: list[Decimal], validation_points: int
) -> tuple[list[Decimal], list[Decimal], ModelMetrics]:
    """Predict each validation point from the history available before it."""
    train, test = split_chronologically(values, validation_points)
    predictions: list[Decimal] = []
    history = list(train)
    for actual in test:
        predictions.append(model.fit_predict(history))
        history.append(actual)  # walk forward: the actual becomes history
    metrics = calculate_metrics(test, predictions) if test else ModelMetrics()
    return test, predictions, metrics


def residual_interval(values: list[Decimal], model, predictions: list[Decimal], z: Decimal = Decimal("1.96")) -> Decimal:
    """A simple prediction interval half-width from validation residuals."""
    if not predictions:
        return ZERO
    actuals = values[-len(predictions) :]
    errors = [abs(a - p) for a, p in zip(actuals, predictions)]
    mean_error = sum(errors, ZERO) / Decimal(len(errors))
    return (mean_error * z).quantize(Decimal("0.01"))
