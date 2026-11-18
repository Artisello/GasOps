"""Portable session history and private SQLite backfill for validated Terna days."""
from datetime import date,datetime,timedelta,timezone
from contextlib import closing
from hashlib import sha256
from pathlib import Path
import argparse,json,math,os,sqlite3,time

from .data import ROME,ROOT
from .models import utc_now
from .terna_power import credentials,load_power,latest_day,SOURCES
from .public_data import SourceUnavailable

STATE="terna_history_v1"
METRICS=(*SOURCES,"load")
MAX_BATCHES=400
MAX_BYTES=12_000_000
CONVENTION="assumed_interval_start_rome_0600"
UTC=timezone.utc


def canonical(x):
    return json.dumps(x,ensure_ascii=True,sort_keys=True,separators=(",",":"),allow_nan=False)


def stamp(raw):
    d=datetime.fromisoformat(raw)
    if d.tzinfo is None:
        raise ValueError("Timestamp senza offset")
    return d.astimezone(UTC)


def validate(batch):
    if set(batch)!={"acquired_at","first","last","convention","rows"} or batch["convention"]!=CONVENTION:
        raise ValueError("Schema archivio Terna non valido")
    acquired=stamp(batch["acquired_at"])
    first,last=date.fromisoformat(batch["first"]),date.fromisoformat(batch["last"])
    if not 0<=(last-first).days<14 or last>latest_day(acquired):
        raise ValueError("Finestra Terna non valida")
    if not isinstance(batch["rows"],list) or not 1<=len(batch["rows"])<=14*len(METRICS):
        raise ValueError("Copertura non valida")
    seen=set()
    for row in batch["rows"]:
        if set(row)!={"day","metric","gwh","slots"}:
            raise ValueError("Record non valido")
        day=date.fromisoformat(row["day"])
        metric=row["metric"]
        key=(day,metric)
        if key in seen or not first<=day<=last or metric not in METRICS:
            raise ValueError("Giorno/metrica duplicato o non valido")
        seen.add(key)
        value=row["gwh"]
        a=datetime.combine(day,datetime.min.time().replace(hour=6),ROME).astimezone(UTC)
        b=datetime.combine(day+timedelta(days=1),datetime.min.time().replace(hour=6),ROME).astimezone(UTC)
        expected=int((b-a).total_seconds()//(900 if metric=="load" else 3600))
        if type(row["slots"]) is not int or row["slots"]!=expected or type(value) not in (int,float) or not math.isfinite(value) or not 0<=value<=1e9:
            raise ValueError("Valore o copertura non validi")
    return batch


def make_batch(power,completed):
    if completed.tzinfo is None or completed<stamp(power["acquired"]):
        raise ValueError("Timestamp di acquisizione incoerente")
    rows=[]
    for r in power["rows"]:
        if r["metric"] in METRICS and r["gwh"] is not None and r["valid_slots"]==r["expected_slots"]:
            rows.append({"day":r["gas_day"],"metric":r["metric"],"gwh":float(r["gwh"]),"slots":r["valid_slots"]})
    return validate({"acquired_at":completed.astimezone(UTC).isoformat(),"first":str(power["first"]),"last":str(power["last"]),
                     "convention":CONVENTION,"rows":sorted(rows,key=lambda x:(x["day"],x["metric"]))})


def batch_id(batch):
    return sha256(canonical(batch).encode()).hexdigest()


def merge(existing,incoming):
    combined={}
    for b in [*existing,*incoming]:
        validate(b)
        combined[batch_id(b)]=b
    if len(combined)>MAX_BATCHES:
        raise ValueError("Limite archivio: esporta e conserva le versioni su host privato.")
    return sorted(combined.values(),key=lambda b:(stamp(b["acquired_at"]),batch_id(b)))


def export(batches):
    return canonical({"version":1,"batches":merge([],batches)})


def parse(raw,now):
    if len(raw)>MAX_BYTES:
        raise ValueError("Archivio troppo grande")
    obj=json.loads(raw)
    if not isinstance(obj,dict) or set(obj)!={"version","batches"} or obj["version"]!=1 or not isinstance(obj["batches"],list) or len(obj["batches"])>MAX_BATCHES:
        raise ValueError("Formato archivio non riconosciuto")
    records=merge([],obj["batches"])
    if any(stamp(b["acquired_at"])>now for b in records):
        raise ValueError("Acquisizione futura")
    return records


def summary(batches):
    days={m:set() for m in METRICS}
    for b in batches:
        for r in b["rows"]:
            days[r["metric"]].add(r["day"])
    return [{"metric":m,"days":len(ds),"first":min(ds) if ds else None,"last":max(ds) if ds else None} for m,ds in days.items()]


def store_batch(path,batch):
    """Private operator-controlled database; no credentials or raw responses."""
    validate(batch)
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    with closing(sqlite3.connect(path,timeout=10)) as db,db:
        db.execute("CREATE TABLE IF NOT EXISTS terna_batches (id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
        db.execute("BEGIN IMMEDIATE")
        count=db.execute("SELECT count(*) FROM terna_batches").fetchone()[0]
        key=batch_id(batch)
        if count>=MAX_BATCHES and db.execute("SELECT 1 FROM terna_batches WHERE id=?",(key,)).fetchone() is None:
            raise ValueError("Archivio privato pieno: esporta e ruota il database conservando le versioni.")
        db.execute("INSERT OR IGNORE INTO terna_batches VALUES(?,?)",(key,canonical(batch)))


def read_db(path):
    with closing(sqlite3.connect(Path(path).resolve().as_uri()+"?mode=ro",uri=True)) as db:
        rows=db.execute("SELECT payload FROM terna_batches LIMIT ?",(MAX_BATCHES+1,)).fetchall()
    return merge([], [json.loads(r[0]) for r in rows])


def windows(first,last):
    if first>last or (last-first).days>=730:
        raise ValueError("Intervallo ammesso: 1–730 giorni")
    while first<=last:
        end=min(first+timedelta(days=13),last)
        yield first,end
        first=end+timedelta(days=1)


def main():
    p=argparse.ArgumentParser(description="Private Terna historical collector, no public artifacts")
    p.add_argument("--db",type=Path,default=Path(os.getenv("GASOPS_STATE_DIR") or ROOT/".gasops")/"terna-history.sqlite3")
    p.add_argument("--first",type=date.fromisoformat)
    p.add_argument("--last",type=date.fromisoformat)
    p.add_argument("--max-windows",type=int,default=1)
    p.add_argument("--export",type=Path)
    p.add_argument("--confirm-terms",action="store_true")
    args=p.parse_args()
    if args.export:
        if args.first or args.last:
            p.error("Export separato dalla raccolta")
        # Exclusive creation avoids accidentally overwriting a previous backup.
        with args.export.open("x",encoding="utf-8") as f:
            f.write(export(read_db(args.db)))
        return 0
    if not args.confirm_terms or not 1<=args.max_windows<=53:
        p.error("Confermare termini e convenzione intervallo; max 1–53 finestre")
    client,secret=credentials()
    if not client or not secret:
        p.error("Credenziali server mancanti")
    now=utc_now()
    last=args.last or latest_day(now)
    first=args.first or last-timedelta(days=13)
    if last>latest_day(now):
        p.error("Fine oltre D-2")
    try:
        periods=list(windows(first,last))
        if len(periods)>args.max_windows:
            p.error("Più finestre del limite esplicito")
        for i,(a,b) in enumerate(periods):
            if i:time.sleep(60)
            power=load_power(client,secret,a,b,now=utc_now())
            store_batch(args.db,make_batch(power,utc_now()))
            print(f"{a} — {b}: acquisizione archiviata")
            if power["warning"]:
                print("Carico non disponibile; generazione conservata. Verificare prima di proseguire.")
                return 2
    except (SourceUnavailable,ValueError,OSError,sqlite3.Error):
        print("Acquisizione interrotta; finestre precedenti conservate. Verificare quote, copertura e accesso.")
        return 1
    return 0


if __name__=="__main__":
    raise SystemExit(main())
