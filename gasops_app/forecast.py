"""Previsioni a calendario e confronto cronologico su osservazioni comuni."""

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field
from sklearn.linear_model import Ridge

from . import bayesian

BAYESIAN = "Bayesian seasonal"
AUTOMATIC = "Automatic"
ModelName = Literal["Bayesian seasonal", "Seasonal regression", "Seasonal naive"]
ModelChoice = Literal["Automatic", "Bayesian seasonal", "Seasonal regression", "Seasonal naive"]
MODELS: tuple[ModelName, ...] = (BAYESIAN, "Seasonal regression", "Seasonal naive")
MODEL_CHOICES: tuple[ModelChoice, ...] = (AUTOMATIC, *MODELS)


class ForecastPoint(BaseModel):
    period: str
    estimate: float
    lower_80: float | None = None
    upper_80: float | None = None
    interval_samples: int = 0


class BacktestPoint(BaseModel):
    period: str
    train_end: str
    actual: float
    estimate: float


class Forecast(BaseModel):
    model: ModelName
    points: list[ForecastPoint] = Field(default_factory=list)
    backtest: list[BacktestPoint] = Field(default_factory=list)
    mae: float | None = None
    rmse: float | None = None
    interval_kind: Literal["posterior", "empirical"] = "empirical"
    interval_coverage: float | None = None
    coverage_samples: int = 0


@dataclass(frozen=True)
class Score:
    mae: float
    rmse: float
    periods: int


def compare(projections: dict[ModelName, Forecast]) -> dict[ModelName, Score]:
    """Measure one-period errors on exactly the same observed dates."""
    errors = {model: {p.period: p.actual - p.estimate for p in fit.backtest}
              for model, fit in projections.items() if fit.points and len(fit.backtest) >= 12}
    if not errors:
        return {}
    common = sorted(set.intersection(*(set(series) for series in errors.values())))
    if len(common) < 12:
        return {}
    scores = {}
    for model, series in errors.items():
        residuals = np.array([series[day] for day in common])
        scores[model] = Score(float(np.abs(residuals).mean()), float(np.sqrt(np.square(residuals).mean())), len(common))
    return scores


def choose(projections: dict[ModelName, Forecast], scores: dict[ModelName, Score], choice: ModelChoice) -> Forecast:
    if choice != AUTOMATIC and projections[choice].points:
        return projections[choice]
    if scores:
        return projections[min(scores, key=lambda model: scores[model].mae)]
    return next((projections[model] for model in MODELS if projections[model].points), projections[BAYESIAN])


def _features(dates: pd.DatetimeIndex, daily: bool) -> np.ndarray:
    days = (dates - pd.Timestamp("2020-01-01")).days.to_numpy()
    angle = 2 * np.pi * days / 365.2425
    seasonal = [np.sin(angle), np.cos(angle), np.sin(2 * angle), np.cos(2 * angle)]
    columns = [days / 365.2425, *seasonal]
    if daily:
        columns.extend((dates.dayofweek == day).astype(float) for day in range(6))
    return np.column_stack(columns)


def _baseline(train: pd.Series, future: pd.DatetimeIndex, daily: bool, model: ModelName) -> np.ndarray:
    if model == "Seasonal naive":
        season = 7 if daily else 12
        values = train.to_numpy()
        if len(train) < season:
            return np.full(len(future), np.nan)
        guesses = []
        for horizon in range(len(future)):
            idx = len(train) - season + horizon % season
            comparable = values[idx::-season]
            observed = comparable[np.isfinite(comparable)]
            guesses.append(observed[0] if observed.size else np.nan)
        return np.asarray(guesses)
    usable = train.dropna()
    if len(usable) < (120 if daily else 24):
        return np.full(len(future), np.nan)
    fitted = Ridge(alpha=2.0).fit(_features(usable.index, daily), usable.to_numpy())
    return fitted.predict(_features(future, daily)).clip(min=0)


def _predict(
    train: pd.Series, dates: pd.DatetimeIndex, daily: bool, model: ModelName
) -> tuple[np.ndarray, np.ndarray | None, np.ndarray | None]:
    if model == BAYESIAN:
        paths = bayesian.predict(train, dates, daily)
        return paths if paths is not None else (np.full(len(dates), np.nan), None, None)
    return _baseline(train, dates, daily, model), None, None


def forecast(series: pd.Series, grain: str, model: ModelName) -> Forecast:
    result = Forecast(model=model, interval_kind="posterior" if model == BAYESIAN else "empirical")
    if series.dropna().empty:
        return result
    daily = grain == "daily"
    freq, horizon, holdout = ("D", 14, 56) if daily else ("MS", 6, 30)
    series = series.asfreq(freq)
    future = pd.date_range(series.index[-1], freq=freq, periods=horizon + 1)[1:]
    fitted, lower_fit, upper_fit = _predict(series, future, daily, model)
    errors: list[list[float]] = [[] for _ in range(horizon)]
    covered = []
    for cutoff in range(max(1, len(series) - holdout), len(series)):
        actuals = series.iloc[cutoff:cutoff + horizon]
        train = series.iloc[:cutoff]
        estimates, low, high = _predict(train, actuals.index, daily, model)
        for step, (actual, estimate) in enumerate(zip(actuals.to_numpy(), estimates, strict=True)):
            if not (np.isfinite(actual) and np.isfinite(estimate)):
                continue
            if step == 0:
                result.backtest.append(BacktestPoint(
                    period=actuals.index[step].date().isoformat(),
                    train_end=train.index[-1].date().isoformat(),
                    actual=float(actual), estimate=float(estimate),
                ))
                if low is not None:
                    covered.append(low[step] <= actual <= high[step])
            errors[step].append(float(actual - estimate))
    if errors[0]:
        residuals = np.asarray(errors[0])
        result.mae = float(np.mean(np.abs(residuals)))
        result.rmse = float(np.sqrt(np.mean(np.square(residuals))))
    if covered:
        result.interval_coverage = float(np.mean(covered))
        result.coverage_samples = len(covered)

    for i, (day, estimate) in enumerate(zip(future, fitted, strict=True)):
        if not np.isfinite(estimate):
            continue
        sample_size = len(errors[i])
        lower, upper = None, None
        if lower_fit is not None:
            lower, upper = float(lower_fit[i]), float(upper_fit[i])
        elif sample_size >= 20:
            qlow, qhigh = np.quantile(errors[i], [0.10, 0.90])
            lower = max(0.0, min(float(estimate), float(estimate + qlow)))
            upper = max(float(estimate), float(estimate + qhigh))
        result.points.append(ForecastPoint(
            period=day.date().isoformat(), estimate=float(estimate),
            lower_80=lower, upper_80=upper, interval_samples=sample_size,
        ))
    return result
