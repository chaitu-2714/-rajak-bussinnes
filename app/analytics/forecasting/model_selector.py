"""Forecast model candidates.

Only simple, explainable methods are used. Each returns one prediction for the
next step given the history it is shown, which is what walk-forward validation
needs. Nothing is trained on data it would not have had at the time.
"""

from __future__ import annotations

from decimal import Decimal

ZERO = Decimal("0.00")

MIN_POINTS_FOR_MODELS = 8
MIN_POINTS_FOR_SEASONAL = 14


class NaiveModel:
    name = "NAIVE"
    description = "Repeats the most recent observed value."

    def fit_predict(self, history: list[Decimal], step: int = 1) -> Decimal:
        return history[-1] if history else ZERO


class MovingAverageModel:
    name = "MOVING_AVERAGE_3"
    description = "Mean of the last three observations."

    def __init__(self, window: int = 3) -> None:
        self.window = window

    def fit_predict(self, history: list[Decimal], step: int = 1) -> Decimal:
        window = history[-self.window :]
        if not window:
            return ZERO
        return (sum(window, ZERO) / Decimal(len(window))).quantize(Decimal("0.01"))


class ExponentialSmoothingModel:
    name = "EXPONENTIAL_SMOOTHING"
    description = "Simple exponential smoothing with alpha = 0.3."

    def __init__(self, alpha: Decimal = Decimal("0.3")) -> None:
        self.alpha = alpha

    def fit_predict(self, history: list[Decimal], step: int = 1) -> Decimal:
        if not history:
            return ZERO
        level = history[0]
        for value in history[1:]:
            level = self.alpha * value + (Decimal("1") - self.alpha) * level
        return level.quantize(Decimal("0.01"))


class SeasonalNaiveModel:
    name = "SEASONAL_NAIVE"
    description = "Repeats the value from the same season one cycle earlier."

    def __init__(self, season: int = 7) -> None:
        self.season = season

    def fit_predict(self, history: list[Decimal], step: int = 1) -> Decimal:
        if len(history) >= self.season:
            return history[-self.season]
        return history[-1] if history else ZERO


def candidate_models(data_points: int) -> list:
    """Models that the available history can actually support."""
    models: list = [NaiveModel(), MovingAverageModel()]
    if data_points >= MIN_POINTS_FOR_MODELS:
        models.append(ExponentialSmoothingModel())
    if data_points >= MIN_POINTS_FOR_SEASONAL:
        models.append(SeasonalNaiveModel(season=7))
    return models
