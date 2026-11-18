"""Fixed lagged Terna challenger on matched Jarvis samples; no future features."""
from datetime import timedelta
import numpy as np
import pandas as pd
from .data import ROME
from .terna_history import batch_id,stamp,merge
from .snam_forecast import FEATURES,EXTRA_FIELDS,samples,MIN_TRAIN,MIN_TEST,HOLDOUT
from .snam_reliability import fit

LAG=3
GEN=("Thermal","Wind","Photovoltaic")
MODELS=("weekly","official","extended","power")


def join_power(d,batches,asof,*,strict,load):
    metrics=(*GEN,"load") if load else GEN
    grouped={}
    # Imports are declared, not authenticated. A historical backfill is never
    # eligible under the acquisition-time mode before its real declared timestamp.
    for batch in merge([],batches):
        acquired=stamp(batch["acquired_at"])
        local=acquired.astimezone(ROME).replace(tzinfo=None)
        if local>asof:continue
        by={}
        for r in batch["rows"]:
            if r["metric"] in metrics:
                by.setdefault(r["day"],{})[r["metric"]]=r["gwh"]
        for day,values in by.items():
            if set(values)==set(metrics):
                grouped.setdefault(day,[]).append((local,batch_id(batch),values))
    rows=[]
    for target,row in d.iterrows():
        origin=row.origin
        day=(origin-pd.Timedelta(days=LAG)).date().isoformat()
        cutoff=origin+pd.Timedelta(hours=15)
        candidates=[x for x in grouped.get(day,[]) if not strict or x[0]<=cutoff]
        if not candidates:continue
        newest=max(x[0] for x in candidates)
        latest=[x for x in candidates if x[0]==newest]
        if len({tuple(x[2][m] for m in metrics) for x in latest})!=1:
            continue
        local,key,values=sorted(latest,key=lambda x:x[1])[-1]
        rows.append({"target":target,"power_day":day,"power_acquired":local.isoformat(),"power_sha256":key,
                     **{"power_"+m:values[m] for m in metrics}})
    cols=["power_"+m for m in metrics]
    if not rows:
        return d.assign(**{k:np.nan for k in cols}),cols
    return d.join(pd.DataFrame(rows).set_index("target")),cols


def evaluate(vintages,batches,horizon,asof,*,strict=True,load=True,forward=False):
    base_features=[*FEATURES,*EXTRA_FIELDS]
    if not set(base_features)<=set(vintages.columns):
        raise ValueError("Ricarica le annualità Jarvis con il modello esteso.")
    d=samples(vintages,horizon)
    if forward:
        from .terna_forward import join_forward
        if not strict:raise ValueError("Le previsioni richiedono acquisition-time cutoff.")
        original,cols=join_forward(d,batches,asof)
    else:original,cols=join_power(d,batches,asof,strict=strict,load=load)
    base=d.dropna(subset=[*base_features,"weekly","actual","actual_published","weekly_published"])
    base=base[(base.label_cutoff<=asof)&(base.actual_published<=asof)&
              (base.weekly_published<=base.origin+pd.Timedelta(hours=15))]
    if base.empty:raise ValueError("Nessun consuntivo maturo Jarvis.")
    end=base.index.max()
    start=end-pd.Timedelta(days=HOLDOUT-1)
    complete=original.loc[base.index].dropna(subset=cols)
    features=[*base_features,*cols]
    records=[]
    for target,row in complete.loc[start:end].iterrows():
        cutoff=row.origin+pd.Timedelta(hours=15)
        train=complete[(complete.label_cutoff<=cutoff)&(complete.actual_published<=cutoff)]
        if len(train)<MIN_TRAIN:continue
        records.append({"target":target.date().isoformat(),"origin":row.origin.date().isoformat(),
            "train_n":len(train),"train_target_end":train.index.max().date().isoformat(),
            "actual":float(row.actual),"weekly":float(row.weekly),"official":float(row.demand),
            "extended":fit(train,row,base_features),"power":fit(train,row,features),
            "power_day":row.power_day,"power_acquired_local":row.power_acquired,"power_sha256":row.power_sha256,
            "source_sha256":row.sha256,"source_row":int(row.row),"actual_sha256":row.actual_sha256,"actual_row":int(row.actual_row)})
    if len(records)<MIN_TEST:
        raise ValueError(f"{len(complete)} giorni con dati comuni; {len(records)} test validi. Servono almeno {MIN_TRAIN} training e {MIN_TEST} test nella finestra di {HOLDOUT} giorni. Amplia lo storico, non sostituire i mancanti.")
    f=pd.DataFrame(records)
    scores={}
    for k in MODELS:
        errors=f[k]-f.actual
        scores[k]={"mae":float(errors.abs().mean()),"rmse":float(np.sqrt((errors**2).mean())),
                   "bias":float(errors.mean()),"wape":float(100*errors.abs().sum()/f.actual.sum()) if f.actual.sum()>0 else None}
    return {"records":records,"scores":scores,"n":len(records),"start":start.date().isoformat(),"end":end.date().isoformat(),
            "overlap":len(complete),"strict":strict,"load":load}
