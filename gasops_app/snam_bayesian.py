"""Bayesian residual challenger with multiple acquisition-time feature groups."""
from datetime import timedelta
import numpy as np
import pandas as pd
from .bayesian import posterior_regression
from .snam_forecast import samples,FEATURES,EXTRA_FIELDS,MIN_TRAIN,MIN_TEST,HOLDOUT
from .snam_reliability import fit

BASE=[*FEATURES,*EXTRA_FIELDS]
MODELS=("official","ridge","bayesian_base","bayesian_multi")


def groups(state):
    """Only explicit scopes; no accidental sums across regions or points."""
    from .terna_history import STATE as HIST,batch_id
    from .terna_forward import STATE as FWD,digest as fd
    from .terna_context import STATE as CTX,SELECT as CTX_SELECT,scopes,digest as cd
    from .entsog_vintages import STATE as NET,SELECT as NET_SELECT,points,digest as nd
    out={}
    def add(key,label,batches,hash_fn,args=()):
        if batches:out[key]={"label":label,"batches":batches,"hashes":tuple(hash_fn(b) for b in batches),"args":args}
    add("power","Terna · consuntivi G−3",state.get(HIST,[]),batch_id)
    add("forward","Terna · carico/eolico previsti",state.get(FWD,[]),fd)
    b=state.get(CTX,[])
    for kind in ("capacity","industry","exchange"):
        scope=state.get(CTX_SELECT,{}).get(kind)
        if scope in scopes(b,kind):
            add(kind,"Terna · "+kind+" · "+" / ".join(scope),b,cd,(kind,scope))
    b=state.get(NET,[]);point=state.get(NET_SELECT)
    if point in points(b):
        for ind in ("Nomination","Renomination"):
            if any(x["point"]==point and x["complete"] and any(r["indicator"]==ind and not r["assumed"] for r in x["rows"]) for x in b):
                add("network_"+ind,"ENTSOG · "+ind+" · "+point,b,nd,(point,ind))
    return out


def signature(options,keys):
    return tuple((k,options[k]["hashes"],options[k]["args"]) for k in keys)


def align(d,options,keys,asof):
    # Joining each feature group independently prevents collisions of provenance
    # columns; all groups must exist on the same original prediction date.
    from .snam_power_forecast import join_power
    from .terna_forward import join_forward
    from .terna_context import join_context
    from .entsog_vintages import join_programmes
    frame=d.copy();columns=[];lineage=[]
    if len(keys)>4 or len(set(keys))!=len(keys) or any(k not in options for k in keys):
        raise ValueError("Seleziona al massimo quattro gruppi disponibili.")
    for key in keys:
        g=options[key];b=g["batches"]
        if key=="power":v,cols=join_power(d,b,asof,strict=True,load=True)
        elif key=="forward":v,cols=join_forward(d,b,asof)
        elif key.startswith("network_"):v,cols=join_programmes(d,b,*g["args"],asof)
        else:v,cols=join_context(d,b,*g["args"],asof)
        for c in cols:
            name=key+"_"+c
            frame[name]=v[c]
            columns.append(name)
        for c in ("power_day","power_acquired","power_sha256"):
            if c in v:
                name=key+"_"+c
                frame[name]=v[c]
                lineage.append(name)
    return frame,columns,lineage


def evaluate(vintages,horizon,asof,options,keys=()):
    d=samples(vintages,horizon)
    if not set(BASE)<=set(d):raise ValueError("Ricarica le annualità Jarvis per le variabili estese.")
    d,external,lineage=align(d,options,keys,asof)
    cols=BASE+external
    cutoff=d.origin+pd.Timedelta(15, unit="h")
    published=d.published<=cutoff
    base=d.loc[published].dropna(subset=[*BASE,"weekly","actual","actual_published","weekly_published"])
    base=base[(base.label_cutoff<=asof)&(base.actual_published<=asof)&
              (base.weekly_published<=base.origin+pd.Timedelta(15, unit="h"))]
    base=base[np.isfinite(base[BASE+["actual","weekly"]]).all(axis=1)&(base[BASE+["actual","weekly"]]>=0).all(axis=1)]
    if base.empty:raise ValueError("Nessun consuntivo maturo.")
    end=base.index.max();start=end-pd.Timedelta(HOLDOUT-1, unit="D")
    complete=base.dropna(subset=external)
    complete=complete[np.isfinite(complete[cols]).all(axis=1)]
    def train_at(c):
        return complete[(complete.label_cutoff<=c)&(complete.actual_published<=c)].tail(730)
    def predict(train,row):
        point=row[cols].to_frame().T
        out={"ridge":fit(train,row,BASE)}
        for name,cc in (("bayesian_base",BASE),("bayesian_multi",cols)):
            p=posterior_regression(train,point,cc,offset=float(row.demand),residual=True)
            out.update({name:p["estimate"],name+"_low":p["low"],name+"_high":p["high"]})
        return out
    records=[]
    for target,row in complete.loc[start:end].iterrows():
        c=row.origin+pd.Timedelta(15, unit="h")
        train=train_at(c)
        if len(train)<MIN_TRAIN:continue
        records.append({"target":str(target.date()),"origin":str(row.origin.date()),
            "actual":float(row.actual),"official":float(row.demand),"train_n":len(train),
            "train_target_end":str(train.index.max().date()),"source_sha256":row.sha256,
            **predict(train,row),**{k:row[k] for k in lineage}})
    if len(records)<MIN_TEST:
        raise ValueError(f"{len(complete)} giorni comuni; {len(records)}/{HOLDOUT} test validi. Servono {MIN_TRAIN} training e {MIN_TEST} test. Riduci i gruppi o amplia i vintage.")
    f=pd.DataFrame(records);scores={}
    for k in MODELS:
        e=f[k]-f.actual
        scores[k]={"mae":float(e.abs().mean()),"rmse":float(np.sqrt((e**2).mean())),"bias":float(e.mean()),
                   "wape":float(100*e.abs().sum()/f.actual.sum()) if f.actual.sum()>0 else None}
        if k.startswith("bayesian"):
            scores[k]["coverage_80"]=float(100*((f[k+"_low"]<=f.actual)&(f.actual<=f[k+"_high"])).mean())
            scores[k]["mean_width"]=float((f[k+"_high"]-f[k+"_low"]).mean())
    candidate=None
    if not d.empty:
        row=d.iloc[-1];target=d.index[-1];c=row.origin+pd.Timedelta(15, unit="h")
        # Never use a later acquisition or train on a label after asof.
        if row.published<=min(c,asof) and row[cols].notna().all() and np.isfinite(row[cols].astype(float)).all() and (row[BASE]>=0).all():
            train=train_at(min(c,asof))
            # External joins use the original cutoff, but asof already bounds acquisitions.
            if len(train)>=MIN_TRAIN:
                candidate={"target":str(target.date()),"origin":str(row.origin.date()),"official":float(row.demand),
                           **predict(train,row),**{k:row[k] for k in lineage}}
    return {"records":records,"scores":scores,"candidate":candidate,"n":len(records),"overlap":len(complete),
            "start":str(start.date()),"end":str(end.date()),"features":cols,
            "groups":[options[k]["label"] for k in keys]}
