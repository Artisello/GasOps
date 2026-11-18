"""Small point-in-time model of the last published Jarvis estimate.

Neither realised physical imbalance nor the final commercial balance is a label.
"""
from datetime import datetime,time,timedelta,timezone
from hashlib import sha256
import math
import pandas as pd
import numpy as np
from .data import ROME
from .operational_sources import JARVIS_COLUMNS,parse_jarvis

STATE="jarvis_public_snapshot_v1"
LIMIT=2000
MIN_TRAIN=30
MIN_TEST=20
METRICS=("sas_gwh","expected_linepack_gwh","expected_withdrawal_gwh")


def gas_end(day):
    return datetime.combine(day+timedelta(days=1),time(6),ROME).astimezone(timezone.utc)


def archive_csv(frame):
    f=frame[list(JARVIS_COLUMNS)].copy()
    f["published_at"]=pd.to_datetime(f.published_at,utc=True).map(lambda x:x.isoformat())
    return f.to_csv(index=False,lineterminator="\n")


def merge_snapshot(previous,raw,now):
    """Exact repeated records deduplicate; conflicting versions fail atomically."""
    new=parse_jarvis(raw,now=now)
    if not previous:return {**new,"hashes":(new["sha256"],)}
    combined=pd.concat([previous["versions"],new["versions"]],ignore_index=True)
    combined["published_at"]=pd.to_datetime(combined.published_at,utc=True)
    combined=combined.drop_duplicates(subset=list(JARVIS_COLUMNS))
    if combined.duplicated(["gas_day","published_at"]).any():
        raise ValueError("Versioni in conflitto: archivio precedente conservato.")
    if len(combined)>LIMIT:raise ValueError("Archivio al limite: esporta prima di rimuovere le stime.")
    combined=combined.sort_values(["gas_day","published_at"]).reset_index(drop=True)
    hashes=tuple(dict.fromkeys((*previous.get("hashes",(previous["sha256"],)),new["sha256"])))
    if len(hashes)>200:raise ValueError("Limite estratti distinti: esporta l’archivio.")
    return {"versions":combined,"latest":combined.drop_duplicates("gas_day",keep="last").reset_index(drop=True),
            "sha256":sha256(archive_csv(combined).encode()).hexdigest(),
            "hashes":hashes}


def _pairs(frame,metric,day,issued,now):
    """Same minutes-to-close (within one hour before equivalent cutoff).

    Require observed closing publication <= gas-day end and within 90 min of
    close; prior gas days must be closed before the issuance being corrected.
    Use UTC instants across DST transitions.
    """
    end=gas_end(day)
    remaining=end-issued
    if remaining<=timedelta(minutes=90) or remaining>timedelta(hours=25):return []
    f=frame.loc[frame.gas_day<day,["gas_day","published_at",metric]].copy()
    f["published_at"]=pd.to_datetime(f.published_at,utc=True)
    f[metric]=pd.to_numeric(f[metric],errors="coerce")
    out=[]
    for d,g in f.groupby("gas_day",sort=True):
        close=gas_end(d)
        if close>min(issued,now):continue
        cutoff=close-remaining
        g=g.sort_values("published_at")
        candidates=g[(g.published_at<=cutoff)&(g.published_at>=cutoff-timedelta(hours=1))]
        labels=g[(g.published_at<close)&(g.published_at>=close-timedelta(minutes=90))]
        if candidates.empty or labels.empty:continue
        a,b=candidates.iloc[-1],labels.iloc[-1]
        if a.published_at>=b.published_at or not np.isfinite([a[metric],b[metric]]).all():continue
        out.append({"day":d,"base":float(a[metric]),"closing":float(b[metric]),"error":float(b[metric]-a[metric])})
    return out[-365:]


def _estimate(value,errors,metric):
    q=np.quantile(errors,[.1,.5,.9]);lo,center,hi=(float(value+x) for x in q)
    if metric!="sas_gwh":lo,center,hi=(max(0.,x) for x in (lo,center,hi))
    return {"low":lo,"estimate":center,"high":hi}


def evaluate(versions,day,metric,now):
    if metric not in METRICS or now.tzinfo is None:raise ValueError("Metrica o timestamp non valido.")
    h=versions[versions.gas_day==day].copy()
    h["published_at"]=pd.to_datetime(h.published_at,utc=True)
    h=h[h.published_at<=now].sort_values("published_at")
    if h.empty:return None
    row=h.iloc[-1];issued=row.published_at.to_pydatetime()
    value=pd.to_numeric(row[metric],errors="coerce")
    if pd.isna(value) or not math.isfinite(float(value)):return None
    # Current-day estimate only if reasonably fresh; historic day explicitly retrospective.
    if gas_end(day)>now and now-issued>timedelta(hours=3):return None
    pairs=_pairs(versions,metric,day,issued,now)
    if len(pairs)<MIN_TRAIN:return {"n":len(pairs),"required":MIN_TRAIN}
    errors=[p["error"] for p in pairs];out=_estimate(value,errors,metric)
    tests=[]
    for i in range(MIN_TRAIN,len(pairs)):
        p=pairs[i];z=_estimate(p["base"],errors[:i],metric)
        tests.append((abs(p["error"]),abs(z["estimate"]-p["closing"]),z["low"]<=p["closing"]<=z["high"]))
    scores=None
    if len(tests)>=MIN_TEST:
        a=np.asarray(tests,dtype=float)
        scores={"n":len(a),"mae_raw":float(a[:,0].mean()),"mae_corrected":float(a[:,1].mean()),"coverage_80":float(100*a[:,2].mean())}
    return {**out,"n":len(pairs),"issued":issued.isoformat(),"first":str(pairs[0]["day"]),"last":str(pairs[-1]["day"]),
            "published":float(value),"scores":scores,"remaining_hours":(gas_end(day)-issued).total_seconds()/3600}


# Study gates, not operating thresholds or Snam-approved acceptance criteria.
MIN_IMPROVEMENT = .05
MIN_COVERAGE = 70.


def replay_times(versions, day, now):
    """Only admissible SAS publications for an explicitly historical replay."""
    if now.tzinfo is None:
        raise ValueError("Timestamp senza offset.")
    end=gas_end(day)
    if end>now:
        return []
    f=versions.loc[versions.gas_day==day,["published_at","sas_gwh"]].copy()
    f["published_at"]=pd.to_datetime(f.published_at,utc=True)
    values=pd.to_numeric(f.sas_gwh,errors="coerce")
    valid=f[np.isfinite(values)&(f.published_at<end-timedelta(minutes=90))&
            (f.published_at>=gas_end(day-timedelta(days=1)))]
    return sorted(set(t.to_pydatetime() for t in valid.published_at),reverse=True)


def _sign_distribution(value,errors):
    outcomes=np.asarray(errors,dtype=float)+value
    return dict(negative=float(np.mean(outcomes<0)),
                zero=float(np.mean(outcomes==0)),
                positive=float(np.mean(outcomes>0)))


def decision_support(versions,day,now,*,as_of=None):
    """Decision support for the closing SAS publication, NOT realised imbalance.

    The benchmark is the declared source SAS available at the issuance time.
    Historical replay never uses later publications of the selected gas day.
    """
    if now.tzinfo is None or (as_of is not None and as_of.tzinfo is None):
        raise ValueError("Timestamp senza offset.")
    end=gas_end(day)
    start=gas_end(day-timedelta(days=1))
    historical=end<=now
    if as_of is not None and (as_of>now or not historical or not start<=as_of<end):
        raise ValueError("Replay consentito solo sul giorno gas concluso.")
    cutoff=as_of if as_of is not None else now
    result={"historical":historical,"status":"missing","ends_at":end.isoformat(),
            "hours_to_close":max(0.,(end-cutoff).total_seconds()/3600)}
    if not historical and not start<=now<end:
        return result
    if historical and as_of is None:
        result["status"]="replay_required"
        return result
    f=versions.loc[versions.gas_day==day,["published_at","sas_gwh"]].copy()
    f["published_at"]=pd.to_datetime(f.published_at,utc=True)
    f=f[(f.published_at<=cutoff)&(f.published_at>=start)&(f.published_at<end)].sort_values("published_at")
    if f.empty:return result
    row=f.iloc[-1]
    value=pd.to_numeric(row.sas_gwh,errors="coerce")
    if not np.isfinite(value):return result
    issued=row.published_at.to_pydatetime()
    value=float(value)
    result.update(published=value,issued=issued.isoformat(),age_hours=(cutoff-issued).total_seconds()/3600)
    if cutoff-issued>timedelta(hours=3):
        result["status"]="stale"
        return result
    if end-cutoff<=timedelta(minutes=90) or end-issued<=timedelta(minutes=90):
        result["status"]="near_close"
        return result
    pairs=_pairs(versions,"sas_gwh",day,issued,cutoff)
    result.update(n=len(pairs),required=MIN_TRAIN)
    if len(pairs)<MIN_TRAIN:
        result["status"]="insufficient"
        return result
    errors=[p["error"] for p in pairs]
    candidate=_estimate(value,errors,"sas_gwh")
    distribution=_sign_distribution(value,errors)
    diagnostics=[]
    for i in range(MIN_TRAIN,len(pairs)):
        p=pairs[i]
        training=errors[:i]
        estimate=_estimate(p["base"],training,"sas_gwh")
        probs=_sign_distribution(p["base"],training)
        actual=p["closing"]
        observed=(actual<0,actual==0,actual>0)
        baseline=(p["base"]<0,p["base"]==0,p["base"]>0)
        brier=sum((prob-float(obs))**2 for prob,obs in zip(probs.values(),observed))
        raw_brier=sum((float(prob)-float(obs))**2 for prob,obs in zip(baseline,observed))
        diagnostics.append((abs(p["error"]),abs(estimate["estimate"]-actual),
                            estimate["low"]<=actual<=estimate["high"],brier,raw_brier))
    result.update(candidate=candidate,distribution=distribution,first=str(pairs[0]["day"]),
                  last=str(pairs[-1]["day"]),scores=None,status="unvalidated")
    if len(diagnostics)<MIN_TEST:
        return result
    a=np.asarray(diagnostics,dtype=float)
    raw,corrected,covered,brier,raw_brier=map(float,a.mean(axis=0))
    improvement=(raw-corrected)/raw if raw>0 else None
    result["scores"]={"n":len(a),"mae_raw":raw,"mae_corrected":corrected,
                      "coverage_80":100*covered,"improvement":improvement,
                      "brier":brier,"brier_raw":raw_brier}
    result["status"]=("candidate" if improvement is not None and improvement>=MIN_IMPROVEMENT
                      and 100*covered>=MIN_COVERAGE and brier<=raw_brier+1e-12 else "benchmark")
    return result
