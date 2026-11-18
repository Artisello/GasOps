"""Previsione probabilistica con regressione bayesiana, stagionalità e calendario."""

from statistics import NormalDist

import numpy as np
import pandas as pd
from sklearn.linear_model import BayesianRidge

QUANTILE_90 = NormalDist().inv_cdf(0.90)
FIXED_HOLIDAYS = (101, 106, 425, 501, 602, 815, 1101, 1208, 1225, 1226)


def _calendar(index: pd.DatetimeIndex, daily: bool) -> np.ndarray:
    years = (index - pd.Timestamp("2020-01-01")).days.to_numpy() / 365.2425
    phase = years if daily else (index.month.to_numpy() - 1) / 12
    angle = 2 * np.pi * phase
    columns = [years]
    for harmonic in range(1, 5):
        columns.extend((np.sin(harmonic * angle), np.cos(harmonic * angle)))
    if daily:
        columns.extend((index.dayofweek == day).astype(float) for day in range(7))
        month_day = 100 * index.month.to_numpy() + index.day.to_numpy()
        columns.extend((np.isin(month_day, FIXED_HOLIDAYS), (month_day >= 1224) | (month_day <= 106)))
    return np.column_stack(columns)


def predict(
    history: pd.Series, future: pd.DatetimeIndex, daily: bool
) -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
    # The daily window adapts to recent seasonal levels. The shorter monthly series uses its full history.
    train = history.iloc[-730:] if daily else history
    available = train.notna().to_numpy()
    if available.sum() < (120 if daily else 24):
        return None
    observed = train[available]
    values = observed.to_numpy()
    exposure = 1 if daily else future.days_in_month.to_numpy()
    if not daily:
        # Model the daily rate to make February and 31-day months comparable.
        values = np.log1p(values / observed.index.days_in_month.to_numpy())

    current = _calendar(observed.index, daily)
    center = current.mean(axis=0)
    scale = current.std(axis=0)
    scale[scale < 1e-10] = 1.0
    design = np.column_stack((np.ones(len(observed)), (current - center) / scale))
    future_design = np.column_stack((np.ones(len(future)), (_calendar(future, daily) - center) / scale))
    level = float(values.mean())
    fitted = BayesianRidge(fit_intercept=False).fit(design, values - level)
    expected = fitted.predict(future_design) + level
    variance = np.full(len(future), 1 / fitted.alpha_)
    condition = future_design

    if daily:
        residuals = np.full(len(train), np.nan)
        residuals[available] = values - level - fitted.predict(design)
        consecutive = np.isfinite(residuals[1:]) & np.isfinite(residuals[:-1])
        if consecutive.sum() >= 20:
            ar = BayesianRidge(fit_intercept=False).fit(
                residuals[:-1][consecutive, None], residuals[1:][consecutive],
            )
            phi = float(np.clip(ar.coef_[0], -0.98, 0.98))
            lag = (future - observed.index[-1]).days.to_numpy()
            persistence = phi ** lag
            expected += persistence * residuals[available][-1]
            condition = future_design - persistence[:, None] * design[-1]
            variance = (1 - persistence**2) / ((1 - phi**2) * ar.alpha_)
            # First-order contribution of uncertainty in the autoregressive coefficient.
            derivative = lag * phi ** (lag - 1) * residuals[available][-1]
            variance += derivative**2 * ar.sigma_[0, 0]

    # The posterior predictive band combines coefficient and observation uncertainty.
    variance += np.einsum("ij,jk,ik->i", condition, fitted.sigma_, condition)
    radius = QUANTILE_90 * np.sqrt(np.maximum(variance, 0))
    paths = np.stack((expected, expected - radius, expected + radius))
    if not daily:
        paths = np.expm1(paths) * exposure
    estimate, lower, upper = paths.clip(min=0)
    return estimate, lower, upper



def posterior_regression(train, point, columns, *, target="actual", offset=0., residual=False):
    """Empirical-Bayes regression; scaling and noise estimated on training only.

    Conditional predictive interval, including observation noise and coefficient
    uncertainty. Does not propagate uncertainty of exogenous input forecasts.
    """
    from sklearn.preprocessing import StandardScaler
    scaler=StandardScaler()
    x=scaler.fit_transform(train[columns])
    z=scaler.transform(point[columns])
    y=train[target].to_numpy(dtype=float)
    if residual:y=y-train["demand"].to_numpy(dtype=float)
    model=BayesianRidge().fit(x,y)
    mean,sd=model.predict(z,return_std=True)
    estimate=float(mean[0]+offset)
    radius=float(QUANTILE_90*sd[0])
    if not np.isfinite([estimate,radius]).all():
        raise ValueError("Posterior non finito.")
    return {"estimate":max(0.,estimate),"low":max(0.,estimate-radius),"high":max(0.,estimate+radius)}
