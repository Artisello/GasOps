"""Reproducible aggregate, one-period scenario risk; not regulatory settlement."""
from dataclasses import dataclass
from fractions import Fraction
from math import isfinite, sqrt

import numpy as np
from pydantic import BaseModel, Field


class RiskSettings(BaseModel):
    simulations: int = Field(default=10000, ge=1000, le=100000)
    seed: int = Field(default=42, ge=0, le=2**32-1)
    demand_cv: float = Field(default=0.075, ge=0, le=1, allow_inf_nan=False)
    supply_cv: float = Field(default=0.04, ge=0, le=1, allow_inf_nan=False)
    price_sd: float = Field(default=8, ge=0, le=1000, allow_inf_nan=False)
    rho_ds: float = Field(default=-0.2, ge=-1, le=1, allow_inf_nan=False)
    rho_dp: float = Field(default=0.4, ge=-1, le=1, allow_inf_nan=False)


def tail_metrics(losses, confidence: float) -> dict:
    """Empirical VaR (inverse CDF) and ES: exact worst tail mass, including ties."""
    values = np.sort(np.asarray(losses, dtype=float))
    if values.ndim != 1 or not values.size or not np.isfinite(values).all():
        raise ValueError("Loss sample must be one-dimensional, finite and nonempty.")
    alpha = Fraction(str(confidence))
    if not 0 < alpha < 1:
        raise ValueError("Confidence must be between zero and one.")
    n = len(values)
    # Exact fractions avoid off-by-one errors at e.g. 95% of 10,000.
    rank = alpha * n
    index = (rank.numerator + rank.denominator - 1) // rank.denominator - 1
    mass = (1-alpha)*n
    whole = mass.numerator // mass.denominator
    remainder = float(mass-whole)
    total = float(values[-whole:].sum()) if whole else 0.0
    if remainder:
        total += remainder*float(values[n-whole-1])
    return {"var": float(values[index]), "cvar": total/float(mass),
            "tail_sample_mass": float(mass)}


def quantiles(values):
    return dict(zip(("p05", "p50", "p95"), map(float, np.quantile(values, [.05,.5,.95])), strict=True))


@dataclass
class RiskSimulation:
    summary: dict
    gap: np.ndarray
    loss: np.ndarray | None


def simulate(demand_gwh: float, supply_gwh: float, price_eur_mwh: float | None,
             settings: RiskSettings | None = None, *, demand_sd: float | None = None,
             demand_sd_source: str = "Ipotesi relativa dell’operatore") -> RiskSimulation:
    """Correlated Gaussian shocks, clipped volumes; price may be negative.

    rho_ds and rho_dp are latent shock correlations. Supply-price correlation
    is implied as rho_ds*rho_dp (conditionally independent residual shocks).
    Cost proxy = unmet GWh * 1000 * max(price, 0); gross adverse expenditure,
    not signed settlement or official security-of-supply exposure.
    """
    s = settings or RiskSettings()
    demand, supply = float(demand_gwh), float(supply_gwh)
    if not all(isfinite(v) and 0 <= v <= 1e12 for v in (demand, supply)):
        raise ValueError("Domanda e offerta devono essere finite, non negative e <= 10^12 GWh.")
    price = None if price_eur_mwh is None else float(price_eur_mwh)
    if price is not None and (not isfinite(price) or abs(price) > 1e6):
        raise ValueError("Prezzo non valido.")
    sd = demand*s.demand_cv if demand_sd is None else float(demand_sd)
    if not isfinite(sd) or not 0 <= sd <= 1e12:
        raise ValueError("Deviazione standard della domanda non valida.")
    rng = np.random.default_rng(s.seed)
    z, e_supply, e_price = rng.standard_normal((3, s.simulations))
    zs = s.rho_ds*z + sqrt(max(0, 1-s.rho_ds**2))*e_supply
    zp = s.rho_dp*z + sqrt(max(0, 1-s.rho_dp**2))*e_price
    raw_d = demand + sd*z
    raw_s = supply + supply*s.supply_cv*zs
    d, a = np.maximum(raw_d, 0), np.maximum(raw_s, 0)
    gap = a-d
    shortage = np.maximum(-gap, 0)
    prob = float(np.mean(shortage > 0))
    # Wilson interval: simulation sampling error only, not model uncertainty.
    n = s.simulations
    w = 1.959963984540054
    den = 1+w*w/n
    center = (prob+w*w/(2*n))/den
    radius = w*sqrt(prob*(1-prob)/n+w*w/(4*n*n))/den
    loss = None if price is None else shortage*1000*np.maximum(price+s.price_sd*zp, 0)
    tail = None if loss is None else {"95": tail_metrics(loss, .95), "99": tail_metrics(loss, .99)}
    out = {
        "kind": "SIMULATION", "horizon": "one native source period",
        "method": "correlated_gaussian_clipped_volumes_v1",
        "settings": s.model_dump(mode="json"),
        "inputs": {"demand_gwh": demand, "supply_gwh": supply, "price_eur_mwh": price,
                   "demand_sd_gwh": sd, "demand_sd_source": demand_sd_source,
                   "supply_price_latent_correlation": s.rho_ds*s.rho_dp},
        "probability_deficit": prob,
        "probability_deficit_mc_interval95": [max(0., center-radius), min(1., center+radius)],
        "expected_deficit_gwh": float(shortage.mean()),
        "conditional_deficit_gwh": float(shortage[shortage>0].mean()) if prob else None,
        "demand_gwh": quantiles(d), "supply_gwh": quantiles(a),
        "gap_gwh": quantiles(gap), "deficit_gwh": quantiles(shortage),
        "deficit_tail_gwh": {"95": tail_metrics(shortage,.95), "99": tail_metrics(shortage,.99)},
        "expected_gross_cost_eur": None if loss is None else float(loss.mean()),
        "gross_cost_tail_eur": tail,
        "clipped_demand_fraction": float(np.mean(raw_d<0)),
        "clipped_supply_fraction": float(np.mean(raw_s<0)),
        "loss_definition": "max(domanda-offerta,0) GWh × 1000 × max(prezzo EUR/MWh,0)",
        "limitations": "Ipotesi illustrative; shock gaussiani, non calibrati congiuntamente; un solo periodo; "
                       "nessuna valutazione ufficiale di sicurezza o regolazione economica."
    }
    return RiskSimulation(out, gap, loss)


def forecast_uncertainty(projection):
    """Use available one-step out-of-sample forecast residuals, not in-sample fit."""
    errors = np.asarray([p.actual-p.estimate for p in projection.backtest], dtype=float)
    errors = errors[np.isfinite(errors)]
    if len(errors) < 20:
        return None, len(errors)
    return float(errors.std(ddof=1)), len(errors)
