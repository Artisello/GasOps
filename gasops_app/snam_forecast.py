"""Jarvis annual publication-vintage backtest, not a certified live forecast.

Selection window 06:00–15:00 local on nominal publication gas-day G.
Target = G + sheet offset. G-1 is provisional allocated redelivery.
Never use closing estimates as definitive labels or sum intraday vintages.
"""
from datetime import datetime,timedelta,date
from hashlib import sha256
from io import BytesIO
import re,posixpath,zipfile
from xml.etree import ElementTree as ET

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .jarvis_native import safezip,xml,N,REL,MAX_BYTES

SHEETS={"Storico_G-1":-1,"Storico_G":0,"Storico_G+1":1,"Storico_G+2":2}
COLS=("A","B","C","E","AA")
HEADERS={"A":"pubblicazione","B":"aggiornato il","C":"IMMESSO","E":"RICONSEGNATO (1)","AA":"Gradi Giorno Medi Ponderali Italia 18°C"}
FIELDS=("origin","h","published","slot","target","demand","injection","hdd","file","sha256","sheet","row")
FEATURES=["demand","injection","hdd"]
MODELS=("weekly","official","igor")
MIN_TRAIN=180
HOLDOUT=90
MIN_TEST=30
MAX_ROWS=200000
MAX_FILES=6


def parse_stamp(value):
    if not value:
        raise ValueError("Timestamp assente")
    if "/" in value:
        return datetime.strptime(value,"%d/%m/%Y %H:%M:%S")
    if not re.fullmatch(r"\d{5}(?:\.\d+)?",value):
        raise ValueError("Timestamp non riconosciuto")
    # The inspected workbooks use Excel's 1900 date system.
    return datetime(1899,12,30)+timedelta(seconds=round(float(value)*86400))


def num(value):
    try:
        n=float(value)
    except (ValueError,TypeError,OverflowError):
        return np.nan
    return n if np.isfinite(n) and 0<=n<=1e10 else np.nan


def extract_rows(rows,sheet,filename,digest):
    """Rows are (physical row, exact selected cells). Unrecognized schema fails."""
    offset=SHEETS[sheet]
    out=[]
    bad=0
    for i,r in rows:
        if i==1:
            if any(r.get(k)!=v for k,v in HEADERS.items()):
                raise ValueError("Intestazioni annuali Jarvis non riconosciute")
            continue
        a=r.get("A") or ""
        if not re.fullmatch(r"\d{4}_\d{2}_\d{2}_\d{2}(?:_\d+)?",a):
            continue
        try:
            origin=datetime.strptime(a[:10],"%Y_%m_%d")
            stamp=parse_stamp(r.get("B"))
        except (ValueError,OverflowError):
            bad+=1
            continue
        if not 2000<=origin.year<=2100:
            raise ValueError("Anno non supportato")
        if not 6<=int(a[11:13])<=15 or not origin.replace(hour=6)<=stamp<=origin.replace(hour=15):
            continue
        out.append((origin,offset,stamp,a,origin+timedelta(days=offset),
                    num(r.get("E")),num(r.get("C")),num(r.get("AA")),
                    filename,digest,sheet,i))
    return out,bad


def sheet_rows(z,path,strings):
    raw=z.read(path)
    # Reject external entity / alternate encoding content before XML parsing.
    t=raw.decode("utf-8-sig")
    if "<!DOCTYPE" in t.upper() or "<!ENTITY" in t.upper() or "\x00" in t:
        raise ValueError("XML non supportato")
    del t
    for _,r in ET.iterparse(BytesIO(raw),events=["end"]):
        if r.tag!=N+"row":
            continue
        cells={}
        for c in r.iter(N+"c"):
            col=re.sub(r"\d","",c.get("r",""))
            if col not in COLS:
                continue
            v=c.find(N+"v")
            val=v.text if v is not None else "".join(x.text or "" for x in c.iter(N+"t"))
            if c.get("t")=="s" and val:
                val=strings[int(val)]
            if val and "confidential" in val.casefold():
                raise ValueError("Documento marcato Confidential")
            cells[col]=val
        yield int(r.get("r")),cells
        r.clear()


def read_annual(raw,name):
    if len(raw)>MAX_BYTES:
        raise ValueError("File superiore a 16 MiB")
    if name.lower().endswith(".zip"):
        with safezip(raw) as archive:
            members=[x for x in archive.infolist() if not x.is_dir()]
            if len(members)!=1 or not members[0].filename.lower().endswith(".xlsx") or members[0].file_size>MAX_BYTES:
                raise ValueError("Lo ZIP annuale deve contenere un solo XLSX")
            name=posixpath.basename(members[0].filename)
            raw=archive.read(members[0])
    if not re.fullmatch(r"DatiOperativi_\d{4}-IT\.xlsx",name,re.I):
        raise ValueError("Atteso DatiOperativi_AAAA-IT.xlsx")
    year=int(re.search(r"\d{4}",name)[0])
    fingerprint=sha256(raw).hexdigest()
    records=[]
    bad=0
    seen=set()
    try:
        with safezip(raw) as z:
            w=xml(z,"xl/workbook.xml")
            properties=w.find(N+"workbookPr")
            if properties is not None and properties.get("date1904") in ("1","true"):
                raise ValueError("Calendario Excel 1904 non supportato")
            rel={x.get("Id"):x.get("Target") for x in xml(z,"xl/_rels/workbook.xml.rels") if x.get("TargetMode")!="External"}
            strings=["".join(v.text or "" for v in x.iter(N+"t")) for x in xml(z,"xl/sharedStrings.xml")] if "xl/sharedStrings.xml" in z.namelist() else []
            if any("confidential" in x.casefold() for x in strings):
                raise ValueError("Documento marcato Confidential")
            for sh in w.iter(N+"sheet"):
                sheet=sh.get("name")
                if sheet not in SHEETS:continue
                path=rel[sh.get(REL)]
                path=path.lstrip("/") if path.startswith("/") else posixpath.normpath(posixpath.join("xl",path))
                if not re.fullmatch(r"xl/worksheets/sheet\d+\.xml",path) or sheet in seen:
                    raise ValueError("Struttura workbook non riconosciuta")
                rows,invalid=extract_rows(sheet_rows(z,path,strings),sheet,name,fingerprint)
                if not rows or any(r[0].year!=year for r in rows):
                    raise ValueError("Anno o foglio privo di pubblicazioni utilizzabili")
                records.extend(rows);bad+=invalid;seen.add(sheet)
                if len(records)>MAX_ROWS:
                    raise ValueError("Troppe righe")
        if seen!=set(SHEETS):
            raise ValueError("Servono i quattro fogli Storico")
    except (zipfile.BadZipFile,ET.ParseError,UnicodeError,KeyError,IndexError,OverflowError) as exc:
        raise ValueError("Formato annuale non valido") from exc
    return {"year":year,"sha256":fingerprint,"name":name,"bad":bad,
            "frame":pd.DataFrame.from_records(records,columns=FIELDS)}


def daily_vintages(frame,asof):
    """One as-of selection per origin/sheet; ambiguous latest timestamp excluded."""
    if asof.tzinfo is not None:
        raise ValueError("Atteso orario locale senza offset")
    f=frame[frame.origin+pd.Timedelta(hours=15)<=asof].copy()
    f=f.sort_values(["origin","h","published","row"])
    selected=[]
    conflicts=0
    for _,group in f.groupby(["origin","h"],sort=False):
        latest=group[group.published==group.published.iloc[-1]]
        if len(latest[FEATURES].drop_duplicates())>1:
            conflicts+=1
            continue
        selected.append(latest.iloc[-1])
    return pd.DataFrame(selected,columns=FIELDS),conflicts


def samples(vintages,horizon):
    if horizon not in (0,1,2):raise ValueError("Orizzonte non valido")
    actual=vintages[vintages.h==-1].set_index("target")
    d=vintages[vintages.h==horizon].set_index("target").sort_index().copy()
    d["actual"]=actual.demand.reindex(d.index)
    d["actual_published"]=actual.published.reindex(d.index)
    d["actual_sha256"]=actual.sha256.reindex(d.index)
    d["actual_row"]=actual.row.reindex(d.index)
    d["weekly"]=actual.demand.reindex(d.index-pd.Timedelta(days=7)).to_numpy()
    d["weekly_published"]=actual.published.reindex(d.index-pd.Timedelta(days=7)).to_numpy()
    # A label is made available conservatively at 15:00 on G+1, even if
    # its selected G-1 publication was earlier.
    d["label_cutoff"]=d.index+pd.Timedelta(days=1,hours=15)
    return d


def _fit(train,row):
    model=make_pipeline(StandardScaler(),Ridge(alpha=10.0))
    model.fit(train[FEATURES],train.actual-train.demand)
    result=float(row.demand+model.predict(row[FEATURES].to_frame().T)[0])
    if not np.isfinite(result):
        raise ValueError("Previsione non finita")
    return max(0.,result)


def evaluate(vintages,horizon,asof):
    d=samples(vintages,horizon)
    complete=d.dropna(subset=[*FEATURES,"weekly","actual","actual_published","weekly_published"])
    complete=complete[(complete.label_cutoff<=asof)&
        (complete.weekly_published<=complete.origin+pd.Timedelta(hours=15))]
    if complete.empty:
        raise ValueError("Nessuna coppia previsione/consuntivo")
    end=complete.index.max()
    start=end-pd.Timedelta(days=HOLDOUT-1)
    records=[]
    for target,row in complete.loc[start:end].iterrows():
        cutoff=row.origin+pd.Timedelta(hours=15)
        train=complete[(complete.label_cutoff<=cutoff)&(complete.actual_published<=cutoff)]
        if len(train)<MIN_TRAIN:continue
        records.append({"target":target.date().isoformat(),"origin":row.origin.date().isoformat(),
            "published":row.published.isoformat(),"actual_published":row.actual_published.isoformat(),
            "train_target_end":train.index.max().date().isoformat(),"train_n":len(train),
            "weekly":float(row.weekly),"official":float(row.demand),"igor":_fit(train,row),"actual":float(row.actual),
            "source_sha256":row.sha256,"source_sheet":row.sheet,"source_row":int(row.row),
            "actual_sha256":row.actual_sha256,"actual_row":int(row.actual_row)})
    if len(records)<MIN_TEST:
        raise ValueError(f"Solo {len(records)}/{HOLDOUT} giornate valutabili; servono {MIN_TEST} test e {MIN_TRAIN} training per origine.")
    f=pd.DataFrame(records)
    scores={}
    for k in MODELS:
        e=f[k]-f.actual
        scores[k]={"mae":float(e.abs().mean()),"rmse":float(np.sqrt((e**2).mean())),
            "bias":float(e.mean()),"wape":float(100*e.abs().sum()/f.actual.sum()) if f.actual.sum()>0 else None}
    candidate=None
    if not d.empty:
        target,row=next(iter(d.tail(1).iterrows()))
        cutoff=row.origin+pd.Timedelta(hours=15)
        train=complete[(complete.label_cutoff<=cutoff)&(complete.actual_published<=cutoff)]
        if len(train)>=MIN_TRAIN and row[FEATURES].notna().all():
            candidate={"target":target.date().isoformat(),"origin":row.origin.date().isoformat(),
                       "published":row.published.isoformat(),"official":float(row.demand),"igor":_fit(train,row),
                       "source_sha256":row.sha256}
    return {"records":records,"scores":scores,"candidate":candidate,
            "start":start.date().isoformat(),"end":end.date().isoformat(),"n":len(records)}
