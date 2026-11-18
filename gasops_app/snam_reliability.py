"""Common-sample challenger and sequential empirical uncertainty. No auto selection."""
import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from .snam_forecast import FEATURES, EXTRA_FIELDS, samples, MIN_TRAIN, MIN_TEST, HOLDOUT

MODELS=("weekly","official","igor","extended")
MIN_CAL=30
CAL_WINDOW=90
NOMINAL=.9


def fit(train,row,features):
    model=make_pipeline(StandardScaler(),Ridge(alpha=10.0))
    model.fit(train[features],train.actual-train.demand)
    p=float(row.demand+model.predict(row[features].to_frame().T)[0])
    if not np.isfinite(p):
        raise ValueError("Previsione non finita.")
    return max(0.,p)


def band(history,cutoff,estimate):
    known=[abs(r["actual"]-r["extended"]) for r in history if r["_label_available"]<=cutoff][-CAL_WINDOW:]
    if len(known)<MIN_CAL:
        return None
    rank=min(len(known),int(np.ceil((len(known)+1)*NOMINAL)))
    radius=sorted(known)[rank-1]
    return {"low":max(0.,estimate-radius),"high":estimate+radius,"cal_n":len(known)}


def evaluate_extended(vintages,horizon,asof):
    features=[*FEATURES,*EXTRA_FIELDS]
    if not set(features)<=set(vintages.columns):
        raise ValueError("Ricarica gli archivi annuali per estrarre le variabili estese.")
    d=samples(vintages,horizon)
    base=d.dropna(subset=[*FEATURES,"weekly","actual","actual_published","weekly_published"])
    base=base[(base.label_cutoff<=asof)&(base.actual_published<=asof)&
              (base.weekly_published<=base.origin+pd.Timedelta(15, unit="h"))]
    if base.empty:
        raise ValueError("Nessuna coppia di base confrontabile.")
    end=base.index.max()
    start=end-pd.Timedelta(HOLDOUT-1, unit="D")
    complete=base.dropna(subset=features)
    complete=complete[np.isfinite(complete[features]).all(axis=1)&(complete[features]>=0).all(axis=1)&
                      (complete.actual>=0)&(complete.weekly>=0)]
    history=[];records=[]
    warm=start-pd.Timedelta(CAL_WINDOW+45, unit="D")
    for target,row in complete.loc[warm:end].iterrows():
        cutoff=row.origin+pd.Timedelta(15, unit="h")
        train=complete[(complete.label_cutoff<=cutoff)&(complete.actual_published<=cutoff)]
        if len(train)<MIN_TRAIN:continue
        r={"target":target.date().isoformat(),"origin":row.origin.date().isoformat(),
            "published":row.published.isoformat(),"actual_published":row.actual_published.isoformat(),
            "train_target_end":train.index.max().date().isoformat(),"train_n":len(train),
            "weekly":float(row.weekly),"official":float(row.demand),"igor":fit(train,row,FEATURES),
            "extended":fit(train,row,features),"actual":float(row.actual),
            "source_sha256":row.sha256,"source_sheet":row.sheet,"source_row":int(row.row),
            "actual_sha256":row.actual_sha256,"actual_row":int(row.actual_row),
            "_label_available":max(row.label_cutoff,row.actual_published)}
        b=band(history,cutoff,r["extended"])
        if b:r.update(b)
        history.append(r)
        if target>=start:records.append({k:v for k,v in r.items() if k!="_label_available"})
    if len(records)<MIN_TEST:
        raise ValueError(f"Solo {len(records)}/{HOLDOUT} date comuni: storico esteso insufficiente.")
    f=pd.DataFrame(records)
    scores={}
    for k in MODELS:
        e=f[k]-f.actual
        scores[k]={"mae":float(e.abs().mean()),"rmse":float(np.sqrt((e**2).mean())),
                   "bias":float(e.mean()),"wape":float(100*e.abs().sum()/f.actual.sum()) if f.actual.sum()>0 else None}
    covered=[r for r in records if "low" in r]
    empirical={"n":len(covered),"coverage":100*sum(r["low"]<=r["actual"]<=r["high"] for r in covered)/len(covered) if covered else None,
               "mean_width":sum(r["high"]-r["low"] for r in covered)/len(covered) if covered else None}
    candidate=None
    if not d.empty:
        target,row=next(iter(d.tail(1).iterrows()))
        cutoff=row.origin+pd.Timedelta(15, unit="h")
        train=complete[(complete.label_cutoff<=cutoff)&(complete.actual_published<=cutoff)]
        if len(train)>=MIN_TRAIN and row[features].notna().all() and (row[features]>=0).all():
            candidate={"target":target.date().isoformat(),"origin":row.origin.date().isoformat(),
                       "published":row.published.isoformat(),"official":float(row.demand),
                       "igor":fit(train,row,FEATURES),"extended":fit(train,row,features)}
            candidate.update(band(history,cutoff,candidate["extended"]) or {})
    return {"records":records,"scores":scores,"candidate":candidate,"empirical":empirical,
            "n":len(records),"start":start.date().isoformat(),"end":end.date().isoformat()}
