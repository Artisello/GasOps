"""Calendar-based forecasts with chronological backtests."""

from typing import Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field
from sklearn.linear_model import Ridge

ModelName = Literal["Seasonal regression", "Seasonal naive"]
MODELS = ("Seasonal regression", "Seasonal naive")


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


def _features(dates: pd.DatetimeIndex, daily: bool) -> np.ndarray:
    days = (dates - pd.Timestamp("2020-01-01")).days.to_numpy()
    angle = 2 * np.pi * days / 365.2425
    seasonal = [np.sin(angle), np.cos(angle), np.sin(2 * angle), np.cos(2 * angle)]
    columns = [days / 365.2425, *seasonal]
    if daily:
        columns.extend((dates.dayofweek == day).astype(float) for day in range(6))
    return np.column_stack(columns)


def _predict(train: pd.Series, future: pd.DatetimeIndex, daily: bool, model: ModelName) -> np.ndarray:
    if model == "Seasonal naive":
        season = 7 if daily else 12
        values = train.to_numpy()
        if len(train) < season:
            return np.full(len(future), np.nan)
        guesses = []
        for horizon in range(len(future)):
            # Earlier observations at the same seasonal position can fill a missing lag.
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


def forecast(series: pd.Series, grain: str, model: ModelName) -> Forecast:
    result = Forecast(model=model)
    if series.dropna().empty:
        return result
    daily = grain == "daily"
    freq, horizon, holdout = ("D", 14, 56) if daily else ("MS", 6, 30)
    future = pd.date_range(series.index[-1], freq=freq, periods=horizon + 1)[1:]
    fitted = _predict(series, future, daily, model)
    errors: list[list[float]] = [[] for _ in range(horizon)]
    for cutoff in range(max(1, len(series) - holdout), len(series)):
        actuals = series.iloc[cutoff:cutoff + horizon]
        train = series.iloc[:cutoff]
        estimates = _predict(train, actuals.index, daily, model)
        for step, (actual, estimate) in enumerate(zip(actuals.to_numpy(), estimates, strict=True)):
            if not (np.isfinite(actual) and np.isfinite(estimate)):
                continue
            errors[step].append(float(actual - estimate))
            if step == 0:
                result.backtest.append(BacktestPoint(
                    period=actuals.index[step].date().isoformat(),
                    train_end=train.index[-1].date().isoformat(),
                    actual=float(actual), estimate=float(estimate),
                ))
    if errors[0]:
        residuals = np.asarray(errors[0])
        result.mae = float(np.mean(np.abs(residuals)))
        result.rmse = float(np.sqrt(np.mean(np.square(residuals))))
    for i, (day, estimate) in enumerate(zip(future, fitted, strict=True)):
        if not np.isfinite(estimate):
            continue
        sample_size = len(errors[i])
        lower, upper = None, None
        if sample_size >= 20:
            qlow, qhigh = np.quantile(errors[i], [0.10, 0.90])
            lower, upper = max(0.0, float(estimate + qlow)), max(0.0, float(estimate + qhigh))
        result.points.append(ForecastPoint(
            period=day.date().isoformat(), estimate=float(estimate),
            lower_80=lower, upper_80=upper, interval_samples=sample_size,
        ))
    return result
