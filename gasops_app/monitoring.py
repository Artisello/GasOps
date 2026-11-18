"""Bounded public-source monitoring, independent of app cache and session data."""
import argparse
from collections import defaultdict
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import sqlite3
from statistics import median
import tempfile
from uuid import uuid4

import requests

from .data import ROOT, ROME
from .models import utc_now
from .public_data import SourceUnavailable
from . import entsog, acer_market, warehouse, operational_sources as gie, terna_power as terna

SOURCES=("entsog","acer","mase","gie","terna")
PUBLIC=("entsog","acer","mase")
URLS={"entsog":entsog.SOURCE,"acer":acer_market.TERMINAL,"mase":warehouse.MASE_URL,
      "gie":gie.AGSI_SOURCE,"terna":terna.PORTAL}
SCHEMA="""
CREATE TABLE IF NOT EXISTS snapshots(
 source TEXT NOT NULL, digest TEXT NOT NULL, format TEXT NOT NULL, payload BLOB NOT NULL,
 PRIMARY KEY(source,digest));
CREATE TABLE IF NOT EXISTS acquisitions(
 id TEXT PRIMARY KEY, source TEXT NOT NULL, digest TEXT NOT NULL, acquired_at TEXT NOT NULL,
 FOREIGN KEY(source,digest) REFERENCES snapshots(source,digest));
CREATE TABLE IF NOT EXISTS observations(
 acquisition_id TEXT NOT NULL REFERENCES acquisitions(id), period TEXT NOT NULL,
 scope TEXT NOT NULL, metric TEXT NOT NULL, unit TEXT NOT NULL, value TEXT NOT NULL,
 PRIMARY KEY(acquisition_id,period,scope,metric,unit));
CREATE INDEX IF NOT EXISTS observations_series ON observations(scope,metric,unit,period);
CREATE INDEX IF NOT EXISTS acquisitions_source ON acquisitions(source,acquired_at);
"""
MAX_BYTES=2_000_000
STATUS=("ok","partial","raw_pending","failed","skipped")
ALERTS=("coverage","stale","revision","outlier","metadata","provider")


def default_db():
    return Path(os.getenv("GASOPS_STATE_DIR") or ROOT/".gasops")/"monitor.sqlite3"


def default_report():
    return default_db().with_name("monitor-report.json")


def download(url,params=None,headers=None):
    with requests.get(url,params=params,headers=headers,stream=True,timeout=(5,25),allow_redirects=False) as r:
        if r.status_code!=200:
            raise SourceUnavailable("HTTP "+str(r.status_code))
        raw=bytearray()
        for chunk in r.iter_content(16384):
            raw.extend(chunk)
            if len(raw)>MAX_BYTES:
                raise ValueError("Download above limit")
    if not raw:
        raise ValueError("Empty response")
    return bytes(raw)


def obs(period,scope,metric,unit,value):
    if value is None:
        return None
    v=Decimal(str(value))
    if not v.is_finite():
        return None
    return (str(period),scope,metric,unit,str(v))


def result(payload,fmt,rows,valid,expected,latest,status="ok",alerts=()):
    return dict(payload=payload,format=fmt,rows=[r for r in rows if r is not None],
                valid=valid,expected=expected,latest=latest,status=status,alerts=list(alerts))


def collect(source,now):
    if source=="entsog":
        last=entsog._last_completed(now); first=last-timedelta(days=6)
        raw=download(entsog.URL,entsog.query_params(first,last))
        m=entsog.parse_month(json.loads(raw),first,last,now,allow_partial=True)
        rows=[obs(d,"SRG",k,"GWh/gas_day",v) for (d,k),v in m.values.items() if v is not None]
        complete=[]
        for i in range(7):
            d=first+timedelta(days=i)
            vals=[m.values.get((d,k)) for k in entsog.FIELDS]
            if all(v is not None for v in vals):
                rows.append(obs(d,"SRG","demand_gwh","GWh/gas_day",sum(vals)))
                complete.append(d)
        latest=max(complete).isoformat() if complete else None
        alerts=["metadata"] if m.metadata_warning else []
        if latest and (last-date.fromisoformat(latest)).days>2:
            alerts.append("stale")
        if m.valid_slots<m.expected_slots:
            alerts.append("coverage")
        return result(raw,"original_json",rows,m.valid_slots,m.expected_slots,latest,"partial" if alerts else "ok",alerts)
    if source=="acer":
        raw=download(acer_market.CSV_URL)
        r=acer_market.parse_lng(raw.decode("utf-8-sig"),now)
        # Retain full original download privately; normalize each observed price.
        rows=[obs(row["date"],"ACER:"+k,k,"EUR/MWh",row[k]) for row in r.rows for k in acer_market.FIELDS]
        valid=sum(x is not None for x in rows)
        latest=max(row["date"] for row in r.rows if any(row[k] is not None for k in acer_market.FIELDS))
        alerts=[]
        if valid<len(rows): alerts.append("coverage")
        if (now.astimezone(ROME).date()-date.fromisoformat(latest)).days>4: alerts.append("stale")
        return result(raw,"original_csv",rows,valid,len(rows),latest,"partial" if alerts else "ok",alerts)
    if source=="mase":
        raw=warehouse.fetch_mase()
        shape=warehouse.inspect_csv(raw)
        # Do not invent native columns. Structural check only.
        return result(raw,"original_csv_pending",[],None,shape["records_including_header"]-1,None,"raw_pending")
    if source=="gie":
        key=gie.gie_key()
        if not key:
            return None
        last=now.astimezone(ROME).date()-timedelta(days=1)
        first=last-timedelta(days=13)
        raw=download(gie.AGSI_URL,{"from":first.isoformat(),"to":last.isoformat(),"size":100,"page":1,"country":"IT"},
                     {"x-key":key,"Accept":"application/json"})
        r=gie.parse_agsi(raw.decode("utf-8-sig"),now,scope="IT")
        frame=r["frame"]
        frame=frame[(frame.gas_day>=first)&(frame.gas_day<=last)]
        rows=[obs(item["gas_day"],"IT",metric,unit,item[metric]) for item in frame.to_dict("records")
              for metric,unit in (("stock_twh","TWh"),("fill_pct","%"))]
        valid=sum(x is not None for x in rows)
        days=frame.loc[frame.stock_twh.notna(),"gas_day"]
        if days.empty:
            raise ValueError("No current stock")
        latest=max(days).isoformat()
        alerts=[]
        if valid<28: alerts.append("coverage")
        if (last-date.fromisoformat(latest)).days>2: alerts.append("stale")
        if frame.review.any(): alerts.append("metadata")
        return result(raw,"original_json",rows,valid,28,latest,"partial" if alerts else "ok",alerts)
    if source=="terna":
        client,secret=terna.credentials()
        # The interval-start convention remains experimental; require explicit opt-in.
        if not client or not secret or os.getenv("GASOPS_TERNA_INTERVAL_START")!="1":
            return None
        last=terna.latest_day(now); first=last-timedelta(days=13)
        r=terna.load_power(client,secret,first,last,now=now)
        rows=[obs(x["gas_day"],"IT:electricity",x["metric"],"GWh_electric/gas_day",x["gwh"]) for x in r["rows"]
              if x["metric"] in (*terna.SOURCES,"load") and x["expected_slots"]>0 and x["valid_slots"]==x["expected_slots"]]
        valid=sum(x is not None for x in rows)
        expected=14*(len(terna.SOURCES)+1)
        latest=max((x[0] for x in rows if x is not None),default=None)
        alerts=["coverage"] if valid<expected or r["warning"] else []
        if latest and (last-date.fromisoformat(latest)).days>2: alerts.append("stale")
        # Token and provider response are never archived; normalized rows only.
        raw=json.dumps(r["rows"],default=str,sort_keys=True,separators=(",",":")).encode()
        return result(raw,"normalized_experimental_json",rows,valid,expected,latest,"partial" if alerts else "ok",alerts)
    raise ValueError("Unknown source")


class Archive:
    def __init__(self,path):
        self.path=Path(path)
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with closing(self.connect()) as db,db:
            db.executescript(SCHEMA)

    def connect(self):
        db=sqlite3.connect(self.path,timeout=10)
        db.execute("PRAGMA foreign_keys=ON")
        return db

    def save(self,source,data,now):
        """Atomically store each successful acquisition, including repeated payloads."""
        digest=sha256(data["payload"]).hexdigest()
        stamp=now.astimezone(timezone.utc).isoformat()
        aid=uuid4().hex
        revisions=outliers=0
        with closing(self.connect()) as db,db:
            db.execute("BEGIN IMMEDIATE")
            # Most recent previously acquired nonmissing value per natural key.
            prior={}
            for period,scope,metric,unit,value in db.execute("""
                SELECT o.period,o.scope,o.metric,o.unit,o.value FROM observations o
                JOIN acquisitions a ON a.id=o.acquisition_id
                WHERE a.source=? AND a.acquired_at<? ORDER BY a.acquired_at,a.id""",(source,stamp)):
                prior[(period,scope,metric,unit)]=Decimal(value)
            rows=data["rows"]
            if len({r[:4] for r in rows})!=len(rows):
                raise ValueError("Duplicate observation key")
            series=defaultdict(dict)
            for (p,s,m,u),v in prior.items():
                series[(s,m,u)][p]=v
            for p,s,m,u,v in rows:
                n=Decimal(v); old=prior.get((p,s,m,u))
                if old is not None and old!=n:
                    revisions+=1
                # New dates only; prior 28 calendar days and >=14 observations.
                # Robust exploratory signal, never technical/regulatory threshold.
                if old is None and m not in ("load_forecast",):
                    cutoff=(date.fromisoformat(p)-timedelta(days=28)).isoformat()
                    hist=[float(x) for day,x in series[(s,m,u)].items() if cutoff<=day<p]
                    if len(hist)>=14:
                        center=median(hist); mad=median(abs(x-center) for x in hist)
                        limit=max(6*1.4826*mad,.1*abs(center),1e-6)
                        if abs(float(n)-center)>limit: outliers+=1
            db.execute("INSERT OR IGNORE INTO snapshots VALUES(?,?,?,?)",(source,digest,data["format"],data["payload"]))
            db.execute("INSERT INTO acquisitions VALUES(?,?,?,?)",(aid,source,digest,stamp))
            db.executemany("INSERT INTO observations VALUES(?,?,?,?,?,?)",[(aid,*r) for r in rows])
        return revisions,outliers

    def as_of(self,source,when):
        """Last acquired nonmissing observation as of a real collection timestamp."""
        if when.tzinfo is None:
            raise ValueError("Offset required")
        with closing(self.connect()) as db:
            rows=db.execute("""SELECT o.period,o.scope,o.metric,o.unit,o.value,a.acquired_at,a.digest
              FROM observations o JOIN acquisitions a ON a.id=o.acquisition_id
              WHERE a.source=? AND a.acquired_at<=? ORDER BY a.acquired_at,a.id""",
              (source,when.astimezone(timezone.utc).isoformat())).fetchall()
        return list({r[:4]:r for r in rows}.values())


def run(sources,now,archive=None,collector=collect,*,clock=None):
    statuses=[]
    for source in sources:
        if source not in SOURCES:
            raise ValueError("Unknown source")
        row={"source":source,"url":URLS[source],"status":"skipped","valid":None,"expected":None,
             "latest":None,"revisions":None,"outliers":None,"alerts":[]}
        try:
            started=clock() if clock else now
            data=collector(source,started)
            acquired=clock() if clock else now
            if acquired.tzinfo is None or acquired<started:
                raise ValueError("Invalid acquisition clock")
            if data is not None:
                row.update({k:data[k] for k in ("status","valid","expected","latest","alerts")})
                if archive is not None:
                    rev,out=archive.save(source,data,acquired)
                    row.update(revisions=rev,outliers=out)
                    if rev: row["alerts"].append("revision")
                    if out: row["alerts"].append("outlier")
        except (requests.RequestException,SourceUnavailable,ValueError,TypeError,KeyError,IndexError,OverflowError,ArithmeticError,OSError,sqlite3.Error):
            # Controlled status only: never dump payloads, URLs with keys, or exceptions.
            row.update(status="failed",valid=None,expected=None,latest=None,revisions=None,outliers=None,alerts=["provider"])
        statuses.append(row)
    checked=clock() if clock else now
    return {"version":1,"checked_at":checked.astimezone(timezone.utc).isoformat(),
            "mode":"private_archive" if archive else "diagnostic_only","sources":statuses}


def write_report(report,path):
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w",encoding="utf-8",dir=path.parent,delete=False) as f:
        temp=Path(f.name)
        json.dump(report,f,indent=2,ensure_ascii=False)
    try:
        os.replace(temp,path)
    finally:
        temp.unlink(missing_ok=True)


def parse_report(raw):
    if len(raw)>100_000:
        raise ValueError("Report too large")
    r=json.loads(raw)
    if not isinstance(r,dict) or set(r)!={"version","checked_at","mode","sources"} or r["version"]!=1 or r["mode"] not in ("private_archive","diagnostic_only"):
        raise ValueError("Invalid report")
    stamp=datetime.fromisoformat(r["checked_at"])
    if stamp.tzinfo is None or not isinstance(r["sources"],list) or len(r["sources"])>5:
        raise ValueError("Invalid report timestamp or sources")
    seen=set()
    for item in r["sources"]:
        if not isinstance(item,dict) or set(item)!={"source","url","status","valid","expected","latest","revisions","outliers","alerts"}:
            raise ValueError("Invalid row")
        s=item["source"]
        if s not in SOURCES or s in seen or item["url"]!=URLS[s] or item["status"] not in STATUS:
            raise ValueError("Invalid source or status")
        seen.add(s)
        for k in ("valid","expected","revisions","outliers"):
            if item[k] is not None and (type(item[k]) is not int or not 0<=item[k]<=10_000_000):
                raise ValueError("Invalid count")
        if item["valid"] is not None and item["expected"] is not None and item["valid"]>item["expected"]:
            raise ValueError("Valid count exceeds expected")
        if item["status"] in ("failed","skipped") and any(item[k] is not None for k in ("valid","expected","latest","revisions","outliers")):
            raise ValueError("Failed/skipped source has observations")
        if item["status"]=="ok" and (item["valid"] is None or item["expected"] is None or item["valid"]!=item["expected"] or item["latest"] is None):
            raise ValueError("Success without complete observations")
        if item["latest"] is not None:
            latest=date.fromisoformat(item["latest"])
            if latest>stamp.astimezone(ROME).date():
                raise ValueError("Future observation")
        if not isinstance(item["alerts"],list) or len(item["alerts"])>len(ALERTS) or any(a not in ALERTS for a in item["alerts"]):
            raise ValueError("Invalid alert")
    return r


def main():
    p=argparse.ArgumentParser(description="I.G.O.R. public data monitor")
    p.add_argument("--sources",nargs="+",choices=SOURCES,required=True)
    p.add_argument("--confirm-terms",action="store_true")
    p.add_argument("--diagnostic-only",action="store_true")
    p.add_argument("--db",type=Path,default=default_db())
    p.add_argument("--report",type=Path,default=default_report())
    args=p.parse_args()
    if not args.confirm_terms:
        p.error("Verify source terms and explicitly confirm before collection.")
    if args.diagnostic_only and any(s not in PUBLIC for s in args.sources):
        p.error("Hosted diagnostic supports keyless sources only.")
    archive=None if args.diagnostic_only else Archive(args.db)
    report=run(list(dict.fromkeys(args.sources)),utc_now(),archive,clock=utc_now)
    write_report(report,args.report)
    # Only status and source codes in logs.
    for row in report["sources"]:
        print(row["source"]+": "+row["status"])
    return 1 if any(r["status"]=="failed" for r in report["sources"]) else 0


if __name__=="__main__":
    raise SystemExit(main())
