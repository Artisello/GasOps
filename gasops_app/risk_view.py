"""Paired illustrative stress tests and compact chart aggregates."""
import numpy as np
from pydantic import BaseModel, Field

from .risk import RiskSettings, simulate


class Stress(BaseModel):
    demand_pct: float = Field(default=0, ge=-100, le=300, allow_inf_nan=False)
    supply_pct: float = Field(default=0, ge=-100, le=300, allow_inf_nan=False)
    price_delta: float = Field(default=0, ge=-1000, le=1000, allow_inf_nan=False)


PRESETS={
    "Base":Stress(),
    "Picco domanda":Stress(demand_pct=10),
    "Riduzione offerta":Stress(supply_pct=-10),
    "Rincaro del gas":Stress(price_delta=10),
    "Stress combinato":Stress(demand_pct=10,supply_pct=-10,price_delta=10),
}


def compare_stress(demand,supply,price,settings:RiskSettings,stress:Stress,*,demand_sd=None,demand_sd_source="Ipotesi relativa dell’operatore"):
    """Common random numbers; stress shifts central values, not shock correlations.

    A historical residual SD, if provided, remains an absolute SD in GWh.
    Otherwise relative demand and supply volatilities apply to each scenario's
    own central values. The fixed price SD is unchanged.
    """
    kwargs={"demand_sd":demand_sd,"demand_sd_source":demand_sd_source}
    base=simulate(demand,supply,price,settings,**kwargs)
    if not any((stress.demand_pct,stress.supply_pct,stress.price_delta)):
        return base,base.summary
    result=simulate(demand*(1+stress.demand_pct/100),supply*(1+stress.supply_pct/100),
                    None if price is None else price+stress.price_delta,settings,**kwargs)
    return result,base.summary


def gap_distribution(gap,bins_per_side=24):
    """Aggregate at most 48 bins, with zero as an edge; never mix signs."""
    values=np.asarray(gap,dtype=float)
    if values.ndim!=1 or not len(values) or not np.isfinite(values).all():
        raise ValueError("Distribuzione non valida.")
    extent=max(1.,float(np.max(np.abs(values))))
    edges=np.linspace(-extent,extent,2*bins_per_side+1)
    edges[bins_per_side]=0.
    counts,_=np.histogram(values,bins=edges)
    return {"center":(edges[1:]+edges[:-1])/2,"width":np.diff(edges),
            "pct":counts*100/len(values),"counts":counts,"negative":edges[1:]<=0}


def cost_distribution(loss,bins=40):
    """Positive costs only; zero mass reported separately, percentages of all runs."""
    values=np.asarray(loss,dtype=float)
    if values.ndim!=1 or not len(values) or not np.isfinite(values).all() or np.any(values<0):
        raise ValueError("Distribuzione costi non valida.")
    positive=values[values>0]
    if not len(positive):
        return {"zero_pct":100.,"center":np.array([]),"width":np.array([]),"pct":np.array([])}
    edges=np.linspace(0.,float(positive.max()),bins+1)
    counts,_=np.histogram(positive,bins=edges)
    return {"zero_pct":float(100*np.mean(values==0)),"center":(edges[1:]+edges[:-1])/2,
            "width":np.diff(edges),"pct":counts*100/len(values)}
