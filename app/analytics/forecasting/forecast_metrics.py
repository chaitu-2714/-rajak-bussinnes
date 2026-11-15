"""Forecast error metrics, computed only from real validation pairs."""

from __future__ import annotations

from decimal import Decimal

from app.analytics.schemas import ModelMetrics

ZERO = Decimal("0.00")


def calculate_metrics(
    actual: list[Decimal], predicted: list[Decimal]
) -> ModelMetrics:
    """MAE, RMSE, MAPE, sMAPE and bias for paired actual/predicted values."""
    if not actual or len(actual) != len(predicted):
        return ModelMetrics(validation_points=0)

    n = Decimal(len(actual))
    errors = [a - p for a, p in zip(actual, predicted)]
    mae = (sum((abs(e) for e in errors), ZERO) / n).quantize(Decimal("0.01"))
    mse = sum((e * e for e in errors), ZERO) / n
    rmse = Decimal(str(float(mse) ** 0.5)).quantize(Decimal("0.01"))
    bias = (sum(errors, ZERO) / n).quantize(Decimal("0.01"))

    mape: Decimal | None = None
    non_zero = [(a, p) for a, p in zip(actual, predicted) if a != ZERO]
    if non_zero:
        total = sum((abs((a - p) / a) for a, p in non_zero), ZERO)
        mape = (total / Decimal(len(non_zero)) * 100).quantize(Decimal("0.01"))

    smape_terms = []
    for a, p in zip(actual, predicted):
        denominator = (abs(a) + abs(p)) / Decimal("2")
        if denominator > ZERO:
            smape_terms.append(abs(a - p) / denominator)
    smape = (
        (sum(smape_terms, ZERO) / Decimal(len(smape_terms)) * 100).quantize(Decimal("0.01"))
        if smape_terms
        else None
    )

    return ModelMetrics(
        mae=mae,
        rmse=rmse,
        mape=mape,
        smape=smape,
        bias=bias,
        validation_points=len(actual),
    )
