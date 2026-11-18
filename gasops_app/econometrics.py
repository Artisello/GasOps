"""Bounded state-space forecasting; no imputation and no future demand inputs."""
from dataclasses import dataclass
import warnings

import numpy as np
import pandas as pd
from statsmodels.tsa.statespace.sarimax import SARIMAX
from statsmodels.tools.sm_exceptions import ConvergenceWarning
from threadpoolctl import threadpool_limits

from .forecast import BacktestPoint, Forecast, ForecastPoint

FIXED_HOLIDAYS = (101, 106, 425, 501, 602, 815, 1101, 1208, 1225, 1226)


def exposure(index, daily):
    return np.ones(len(index)) if daily else index.days_in_month.to_numpy(dtype=float)


def calendar(index, daily):
    # Known at the forecast origin; no measured future weather.
    if not daily:
        return None
    days = (index - pd.Timestamp("2020-01-01")).days.to_numpy()
    phase = 2*np.pi*days/365.2425
    month_day = index.month.to_numpy()*100 + index.day.to_numpy()
    return np.column_stack((np.sin(phase), np.cos(phase), np.sin(2*phase),
                           np.cos(2*phase), np.isin(month_day, FIXED_HOLIDAYS).astype(float)))


@dataclass
class State:
    fit: object
    scale: float
    daily: bool
    model: str
    order: tuple
    seasonal: tuple

    def exog(self, dates):
        return calendar(dates, self.daily) if self.model == "SARIMAX" else None

    def predict(self, dates):
        kwargs = {} if self.exog(dates) is None else {"exog": self.exog(dates)}
        pred = self.fit.get_forecast(steps=len(dates), **kwargs)
        scale = self.scale * exposure(dates, self.daily)
        mean = np.asarray(pred.predicted_mean) * scale
        interval = np.asarray(pred.conf_int(alpha=.2)) * scale[:, None]
        point = np.maximum(mean, 0)
        lower = np.maximum(np.minimum(interval[:, 0], point), 0)
        upper = np.maximum(interval[:, 1], point)
        return point, lower, upper

    def advance(self, observation):
        values = observation.to_numpy(dtype=float) / exposure(observation.index, self.daily) / self.scale
        self.fit = self.fit.extend(values, exog=self.exog(observation.index))


def fit_state(history, daily, model):
    # Daily 2-year window, monthly 10-year maximum; fit only the training prefix.
    train = history.iloc[-730 if daily else -120:]
    values = train.to_numpy(dtype=float) / exposure(train.index, daily)
    observed = values[np.isfinite(values)]
    if len(observed) < (120 if daily else 36) or np.std(observed) < 1e-10:
        return None
    scale = max(float(np.mean(np.abs(observed))), 1.0)
    season = 7 if daily else 12
    if model == "ARIMA":
        candidates = [((1, 1, 1), (0, 0, 0, 0), "n"), ((1, 1, 0), (0, 0, 0, 0), "n")]
        exog = None
    else:
        candidates = [((1, 0, 0), (1, 0, 0, season), "c"),
                      ((1, 0, 0), (0, 1, 0, season), "n")]
        exog = calendar(train.index, daily)
    for order, seasonal, trend in candidates:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", ConvergenceWarning)
                with threadpool_limits(limits=1):
                    fit = SARIMAX(values/scale, exog=exog, order=order,
                                  seasonal_order=seasonal, trend=trend,
                                  enforce_stationarity=True, enforce_invertibility=True).fit(disp=False, maxiter=80)
            if fit.mle_retvals.get("converged", False) and np.isfinite(fit.params).all():
                return State(fit, scale, daily, model, order, seasonal)
        except (ValueError, RuntimeError, ArithmeticError, np.linalg.LinAlgError):
            continue
    return None


def econometric_forecast(series, grain, model):
    result = Forecast(model=model, interval_kind="model_based")
    if series.dropna().empty:
        return result
    daily = grain == "daily"
    freq, horizon, holdout = ("D", 14, 56) if daily else ("MS", 6, 30)
    series = series.asfreq(freq)
    cutoff = max(1, len(series)-holdout)
    final = fit_state(series, daily, model)
    if final is None:
        result.details = "Storico insufficiente, serie costante o stima non convergente."
        return result
    future = pd.date_range(series.index[-1], freq=freq, periods=horizon+1)[1:]
    try:
        estimates, lower, upper = final.predict(future)
        if not np.isfinite(np.concatenate((estimates, lower, upper))).all():
            raise ValueError("Nonfinite forecast")
        result.points = [ForecastPoint(period=day.date().isoformat(), estimate=float(m),
                                       lower_80=float(lo), upper_80=float(hi))
                         for day,m,lo,hi in zip(future, estimates, lower, upper, strict=True)]
    except (ValueError, RuntimeError, ArithmeticError, np.linalg.LinAlgError):
        result.details = "Previsione non disponibile: errore numerico."
        return result
    result.details = f"Ordine finale {final.order}, stagionale {final.seasonal}; massima verosimiglianza; fascia predittiva condizionata ai parametri stimati."
    # Fixed coefficients fitted once before holdout; update Kalman state one step at a time.
    state = fit_state(series.iloc[:cutoff], daily, model)
    if state is None:
        result.details += " Backtest non disponibile: stima iniziale non convergente o storico breve."
        return result
    result.details += f" Backtest: parametri fissi {state.order}/{state.seasonal}, stato aggiornato dopo ogni osservazione."
    covered = []
    try:
        for i in range(cutoff, len(series)):
            obs = series.iloc[i:i+1]
            mean, low, high = state.predict(obs.index)
            actual = float(obs.iloc[0])
            if np.isfinite([actual, mean[0], low[0], high[0]]).all():
                result.backtest.append(BacktestPoint(period=obs.index[0].date().isoformat(),
                    train_end=series.index[i-1].date().isoformat(), actual=actual, estimate=float(mean[0])))
                covered.append(bool(low[0] <= actual <= high[0]))
            state.advance(obs)
    except (ValueError, RuntimeError, ArithmeticError, np.linalg.LinAlgError):
        result.backtest.clear()
        result.details += " Backtest interrotto: errore numerico."
        covered.clear()
    if result.backtest:
        errors = np.array([p.actual-p.estimate for p in result.backtest])
        result.mae = float(np.abs(errors).mean())
        result.rmse = float(np.sqrt(np.square(errors).mean()))
        result.interval_coverage = float(np.mean(covered))
        result.coverage_samples = len(covered)
    return result
