"""Bounded, read-only analytical planning. The model never executes code."""
from datetime import date
from itertools import combinations
import json,math,re
import numpy as np
import pandas as pd
from .data_analyst import analyse,MAX_SELECTED,MIN_PAIRS

TOOLS={
    "summary":"Statistics: latest/first, mean, min/max, change, observation count.",
    "correlation":"Pearson on common observed gas days; at least 14 pairs; not causal.",
    "trend":"Descriptive linear slope per calendar day on gas-day series; at least 14 observations.",
    "volatility":"Sample standard deviation and median/IQR of observations; at least 14.",
    "revisions":"Matched provisional/final native Jarvis aggregate balances, same metric and unit.",
    "benchmarks":"Published reference KPI, its own period (not filtered by series dates).",
    "forecasts":"Existing compatible backtest metrics or current issued weather outlook, their own periods; no new forecast."
}
MAX_CATALOG=48


def manifest(items,benchmarks,forecasts,question,today,*,remote):
    # Restricted source metadata as well as values is withheld remotely.
    eligible={k:v for k,v in items.items() if not remote or v.remote_allowed}
    terms=set(re.findall(r"\w+",question.casefold()))
    def rank(k):
        v=eligible[k]
        words=set(re.findall(r"\w+",(v.label+" "+v.source+" "+v.scope+" "+k).casefold()))
        return (-sum(len(w) for w in terms&words if len(w)>2), -date.fromisoformat(v.values.index[-1]).toordinal(), k.startswith("jarvis_coef_"),k)
    keys=sorted(eligible,key=rank)[:MAX_CATALOG]
    return {
        "today":today.isoformat(),"tools":TOOLS,
        "series":[{"id":k,"label":eligible[k].label[:120],"source":eligible[k].source[:80],
                   "scope":eligible[k].scope[:120],"unit":eligible[k].unit[:70],"grain":eligible[k].grain,
                   "status":eligible[k].status[:180],
                   "first":eligible[k].values.index[0],"last":eligible[k].values.index[-1],
                   "n":len(eligible[k].values)} for k in keys],
        "benchmarks":[{k:r[k] for k in ("id","label","period","unit","source")} for r in benchmarks],
        "forecasts":[{k:r[k] for k in ("id","source","horizon","from","to","n")} for r in forecasts],
        "omitted_eligible":len(eligible)-len(keys),
        "restricted_sources_excluded":len(items)>len(eligible)
    }


def validate_plan(raw,available,today):
    """Validate against exactly the catalog shown to the model."""
    fields={"series","tools","from","to","benchmarks","forecasts"}
    if not isinstance(raw,dict) or set(raw)!=fields:
        raise ValueError("Piano AI non valido.")
    def ids(key,allowed,limit):
        v=raw[key]
        if not isinstance(v,list) or len(v)>limit or any(type(x) is not str or x not in allowed for x in v) or len(set(v))!=len(v):
            raise ValueError("Identificatori o strumenti non autorizzati.")
        return v
    series=ids("series",{r["id"] for r in available["series"]},MAX_SELECTED)
    tools=ids("tools",set(TOOLS),4)
    bench=ids("benchmarks",{r["id"] for r in available["benchmarks"]},6)
    forecasts=ids("forecasts",{r["id"] for r in available["forecasts"]},2)
    first,last=raw["from"],raw["to"]
    if any(type(x) is not str or not re.fullmatch(r"\d{4}-\d{2}-\d{2}",x) for x in (first,last)):
        raise ValueError("Date non valide.")
    if not date(1900,1,1)<=date.fromisoformat(first)<=date.fromisoformat(last)<=today:
        raise ValueError("Periodo del piano non valido.")
    series_tools=set(tools)-{"benchmarks","forecasts"}
    if bool(series)!=bool(series_tools) or bool(bench)!=("benchmarks" in tools) or bool(forecasts)!=("forecasts" in tools):
        raise ValueError("Piano incoerente con le fonti selezionate.")
    if "correlation" in tools and len(series)<2:
        raise ValueError("Servono due serie per correlare.")
    if "revisions" in tools and not any(set(pair)<=set(series) for pair in REVISION_PAIRS):
        raise ValueError("Servono due fasi della stessa metrica Jarvis.")
    # Empty plan is a legitimate abstention. Never substitute a default series.
    return {**raw,"series":series,"tools":tools,"benchmarks":bench,"forecasts":forecasts}


REVISION_PAIRS=tuple((f"jarvis_{m}_provvisorio",f"jarvis_{m}_definitivo") for m in ("withdrawal","injection"))


def window(item,first,last):
    v=item.values
    return v.loc[(v.index>=first)&(v.index<=last)].sort_index()


def execute_plan(plan,items,benchmarks,forecasts):
    keys=plan["series"];tools=plan["tools"];first,last=plan["from"],plan["to"]
    # Existing verified engine supplies dates, units, source and common-day correlation.
    out=analyse(items,keys,first,last) if keys else {"from":first,"to":last,"series":[],"correlations":[],"missing":[]}
    if "correlation" not in tools:out["correlations"]=[]
    out["benchmarks"]=[x for x in benchmarks if x["id"] in plan["benchmarks"]]
    out["forecasts"]=[x for x in forecasts if x["id"] in plan["forecasts"]]
    out["statistics"]=[];out["unavailable"]=[]
    def add(tool,key,**data):
        out["statistics"].append({"id":tool+"_"+key,"tool":tool,"series":[key],**data})
    for key in keys:
        v=window(items[key],first,last)
        if "trend" in tools:
            if items[key].grain!="gas_day" or len(v)<MIN_PAIRS:
                out["unavailable"].append({"tool":"trend","series":[key],"reason":"Servono almeno 14 osservazioni giornaliere gas."})
            else:
                days=(pd.to_datetime(v.index)-pd.Timestamp(v.index[0])).days.to_numpy(dtype=float)
                slope=float(np.polyfit(days,v.to_numpy(dtype=float),1)[0])
                if math.isfinite(slope):
                    add("trend",key,n=len(v),first=v.index[0],last=v.index[-1],slope_per_calendar_day=slope,
                        unit=items[key].unit+" per giorno di calendario",limitation="Trend lineare descrittivo, non previsione; lacune non imputate.")
        if "volatility" in tools:
            if len(v)<MIN_PAIRS:
                out["unavailable"].append({"tool":"volatility","series":[key],"reason":"Servono almeno 14 osservazioni."})
            else:
                sd=float(v.std(ddof=1)); q1,q3=(float(x) for x in v.quantile([.25,.75]))
                if all(math.isfinite(x) for x in (sd,q1,q3)):
                    add("volatility",key,n=len(v),first=v.index[0],last=v.index[-1],unit=items[key].unit,
                        sample_sd=sd,median=float(v.median()),q1=q1,q3=q3,iqr=q3-q1,
                        limitation="Dispersione dei livelli osservati, non volatilità dei rendimenti.")
    if "correlation" in tools:
        valid={frozenset(x["series"]) for x in out["correlations"]}
        for a,b in combinations(keys,2):
            if frozenset((a,b)) not in valid:
                out["unavailable"].append({"tool":"correlation","series":[a,b],"reason":"Frequenza non compatibile, meno di 14 coppie o serie costante."})
    if "revisions" in tools:
        for a,b in REVISION_PAIRS:
            if not {a,b}<=set(keys):continue
            x,y=items[a],items[b]
            if x.unit!=y.unit or x.scope!=y.scope or x.grain!=y.grain or x.grain!="gas_day":
                out["unavailable"].append({"tool":"revisions","series":[a,b],"reason":"Unità o perimetro non compatibili."})
                continue
            f=pd.concat([window(x,first,last).rename("p"),window(y,first,last).rename("d")],axis=1,join="inner")
            if f.empty:
                out["unavailable"].append({"tool":"revisions","series":[a,b],"reason":"Nessun giorno comune."})
                continue
            delta=f.d-f.p
            out["statistics"].append({"id":"revision_"+a+"_"+b,"tool":"revisions","series":[a,b],
                "n":len(f),"first":f.index[0],"last":f.index[-1],"unit":x.unit,
                "mean_delta_final_minus_provisional":float(delta.mean()),"sum_absolute_deltas":float(delta.abs().sum()),
                "max_absolute_delta":float(delta.abs().max()),
                "limitation":"Confronto aggregato su giorni univoci per fase, unità inferita; ordine di pubblicazione ignoto; non importo economico."})
    # Series summaries are always supporting evidence for selected statistical tools.
    return out
