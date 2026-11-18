"""BSO monitoring: proposed metrics, separate public milestones and task evidence."""
import csv
import io
import re
from calendar import monthrange
from datetime import date, datetime, time, timedelta, timezone
from math import isfinite

from .data import ROME
from .settlement_desk import daily_controls, monthly_summary, csv_text

FIELDS=("task_id","area","activity","due_at","completed_at")
AREAS=("balancing","settlement","operations")
MAX_BYTES=1_000_000
MAX_TASKS=5000
UTC=timezone.utc
NEWS="https://www.snam.it/it/apis/news-commerciale.html"
CODE="https://www.snam.it/it/i-nostri-business/trasporto/codice-di-rete-tariffe-area-comitato-e-consultazioni/codice-di-rete.html"
JARVIS="https://www.snam.it/it/i-nostri-business/trasporto/informazioni-commerciali/portale-jarvis.html"
# Dated reference, not a recurring rule or a confirmed completion.
PUBLIC_MILESTONES=(
    ("2026-10-15","settlement","Esiti provvisori delle partite fisiche","2026-10-06","Sessione di aggiustamento annuale 2026 (competenza 2025)"),
    ("2026-10-22","settlement","Richieste ex cap. 9, par. 5, punto 1","2026-10-06","Sessione di aggiustamento annuale 2026 (competenza 2025)"),
    ("2026-10-22","settlement","Segnalazioni punti ex cap. 9, par. 5, punto 2","2026-10-06","Sessione di aggiustamento annuale 2026 (competenza 2025)"),
    ("2026-11-15","settlement","Richieste di rettifica degli UdB","2026-10-06","Sessione di aggiustamento annuale 2026 (competenza 2025)"),
    ("2026-12-15","settlement","Esiti definitivi delle partite fisiche (previsti)","2026-10-06","Sessione di aggiustamento annuale 2026 (competenza 2025)"),
    ("2026-11-24","operations","Go live nomina/rinomina e programmazione trasporto su Jarvis","2026-10-23","Migrazione Jarvis · data di avvio, non orario limite"),
)


def parse_date_time(value):
    """Date-only values retain day precision; timed values must be offset-aware."""
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}",value):
        return date.fromisoformat(value)
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:\d{2})",value):
        raise ValueError("Data ISO o timestamp ISO con offset richiesto.")
    parsed=datetime.fromisoformat(value.replace("Z","+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Offset mancante.")
    return parsed


def is_timed(value):
    return isinstance(value,datetime)


def local_day(value):
    return value.astimezone(ROME).date() if is_timed(value) else value


def deadline(value):
    # Date-only deadlines expire at the start of the next local calendar day.
    return (value if is_timed(value) else datetime.combine(value+timedelta(days=1),time.min,ROME)).astimezone(UTC)


def parse_tasks(raw):
    if not raw or len(raw)>MAX_BYTES:
        raise ValueError("CSV vuoto o superiore a 1 MB.")
    try:
        reader=csv.DictReader(io.StringIO(raw.decode("utf-8-sig")),strict=True)
        if tuple(reader.fieldnames or ())!=FIELDS:
            raise ValueError("Usa le intestazioni del modello attività.")
        rows=[]
        seen=set()
        for no,row in enumerate(reader,2):
            if len(rows)>=MAX_TASKS or None in row or any(v is None for v in row.values()):
                raise ValueError("CSV non valido o superiore a 5.000 attività.")
            task,area,activity=(row[k].strip() for k in ("task_id","area","activity"))
            if (not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,39}",task) or task in seen
                or area not in AREAS or not 1<=len(activity)<=120 or activity[0] in "=+-@"
                or any(ord(ch)<32 for ch in activity)):
                raise ValueError(f"Riga {no}: ID, area o descrizione non validi.")
            try:
                due=parse_date_time(row["due_at"].strip())
                done=parse_date_time(row["completed_at"].strip()) if row["completed_at"].strip() else None
                if done is not None and is_timed(due) and not is_timed(done):
                    raise ValueError("Orario di completamento necessario.")
                if not 2000<=due.year<=2100 or (done is not None and not 2000<=done.year<=2100):
                    raise ValueError("Data fuori intervallo.")
                # Validate boundaries, including date overflow.
                deadline(due)
                if done is not None:
                    deadline(done)
            except (ValueError,OverflowError):
                raise ValueError(f"Riga {no}: date non valide o precisione insufficiente.") from None
            rows.append({"task_id":task,"area":area,"activity":activity,"due_at":due,"completed_at":done})
            seen.add(task)
        if not rows:
            raise ValueError("Nessuna attività importata.")
        return rows
    except (UnicodeError,csv.Error):
        raise ValueError("CSV non leggibile.") from None


def task_demo():
    raw="""task_id,area,activity,due_at,completed_at
DEMO-01,balancing,Pubblicazione dati di sistema,2026-11-18T09:00+01:00,2026-11-18T08:55+01:00
DEMO-02,settlement,Validazione allocazioni,2026-11-17,2026-11-17
DEMO-03,settlement,Controllo rettifiche,2026-11-16,2026-11-17
DEMO-04,operations,Controllo flussi,2026-11-17T15:00+01:00,
DEMO-05,balancing,Verifica prelievi attesi,2026-11-18T16:00+01:00,
DEMO-06,settlement,Riconciliazione partite,2026-11-20,
DEMO-07,operations,Verifica garanzie,2026-11-24,
DEMO-08,settlement,Verifica dati di competenza,2026-10-30,
DEMO-09,operations,Controllo misure,2026-11-15,2026-11-14
"""
    return parse_tasks(raw.encode())


def task_template():
    return task_csv(task_demo())


def task_csv(tasks):
    return csv_text([{k:(v.isoformat() if isinstance(v,date) else v) for k,v in row.items() if k in FIELDS} for row in tasks],FIELDS)


def actual_completion(value,now):
    if value is None:
        return None
    if is_timed(value):
        return value if value.astimezone(UTC)<=now.astimezone(UTC) else None
    # A date-only completion within the current day has no evidence of time.
    return value if value<=now.astimezone(ROME).date() else None


def classify(tasks,now,area="all"):
    if now.tzinfo is None:
        raise ValueError("As-of must be offset-aware")
    at=now.astimezone(UTC)
    result=[]
    for row in tasks:
        if area!="all" and row["area"]!=area:
            continue
        due=row["due_at"]
        end=deadline(due)
        done=actual_completion(row["completed_at"],now)
        if done is not None:
            timely=done.astimezone(UTC)<=end if is_timed(due) else local_day(done)<=local_day(due)
            status="In tempo" if timely else "Chiusa in ritardo"
        else:
            # Exactly at an explicit timestamp the deadline is reached.
            status="Scaduta" if at>end or (not is_timed(due) and at>=end) else "Aperta"
        result.append({**row,"completed_at":done,"status":status,"remaining_hours":(end-at).total_seconds()/3600,
                       "deadline_utc":end})
    return sorted(result,key=lambda r:(r["deadline_utc"],r["task_id"]))


def operations_metrics(tasks,now,year,month,area="all"):
    classified=classify(tasks,now,area)
    at=now.astimezone(UTC)
    # Fix the cohort to deadlines elapsed as of the reference instant. Open overdue
    # items count against punctuality; tasks not yet due never inflate the rate.
    cohort=[r for r in classified if (local_day(r["due_at"]).year,local_day(r["due_at"]).month)==(year,month)
            and (r["deadline_utc"]<at or (not is_timed(r["due_at"]) and r["deadline_utc"]==at))]
    timely=sum(r["status"]=="In tempo" for r in cohort)
    overdue=[r for r in classified if r["status"]=="Scaduta"]
    upcoming=[r for r in classified if r["status"]=="Aperta" and 0<=r["remaining_hours"]<=168]
    return {"rows":classified,"cohort":cohort,"on_time":timely,"due":len(cohort),
            "on_time_pct":100*timely/len(cohort) if cohort else None,
            "overdue":overdue,"next24":sum(r["remaining_hours"]<=24 for r in upcoming),
            "next7":len(upcoming),"upcoming":upcoming,
            "late":sum(r["status"]=="Chiusa in ritardo" for r in cohort)}


def month_days(year,month,cutoff):
    return [date(year,month,d) for d in range(1,monthrange(year,month)[1]+1)
            if date(year,month,d)<=cutoff]


def finite(value):
    try:
        v=float(value)
        return v if isfinite(v) else None
    except (TypeError,ValueError):
        return None


def closed_gas_day(now):
    local=now.astimezone(ROME)
    # Latest completed gas day: the active 06:00-06:00 gas day is excluded.
    active=local.date() if local.hour>=6 else local.date()-timedelta(days=1)
    return active-timedelta(days=1)


def balancing_metrics(versions,year,month,now,band=None):
    """Last available publication per completed gas day; estimates, not actual SAS."""
    days=month_days(year,month,closed_gas_day(now))
    by_day={}
    if versions is not None:
        for r in versions.sort_values("published_at").to_dict("records"):
            if r["published_at"]<=now:
                by_day[r["gas_day"]]=r
    records=[]
    for day in days:
        r=by_day.get(day,{})
        records.append({"day":day.isoformat(),"sas_gwh":finite(r.get("sas_gwh")),
                        "published_at":str(r["published_at"]) if r else None})
    valid=[r["sas_gwh"] for r in records if r["sas_gwh"] is not None]
    return {"records":records,"expected":len(days),"observed":len(valid),
            "mean_abs_sas":sum(map(abs,valid))/len(valid) if valid else None,
            "peak_abs_sas":max(map(abs,valid)) if valid else None,
            "outside_band":sum(abs(v)>band for v in valid) if band is not None and valid else None}


def settlement_metrics(rows,user,year,month,cutoff):
    # Month-end coverage, not a timeliness KPI: the file has no release timestamps.
    days=[r for r in daily_controls(rows,user,year,month) if date.fromisoformat(r["day"])<=cutoff]
    result=monthly_summary(days)
    definitive=sum(r["stage"]=="definitive" for r in days)
    comparable=[r for r in days if r["delta_ds_mwh"] is not None]
    revised=sum(r["delta_ds_mwh"]!=0 or (r["delta_cash_eur"] is not None and r["delta_cash_eur"]!=0)
                for r in comparable)
    return {**result,"records":days,"definitive":definitive,
            "eligible_pct":100*result["eligible"]/result["expected"] if result["expected"] else None,
            "revision_pairs":len(comparable),"revised":revised}


def balancing_demo():
    """Fixed, explicitly synthetic SAS estimates shared by both demo views."""
    import pandas as pd
    days=[date(2026,11,d) for d in range(1,18) if d!=7]
    return pd.DataFrame([{"gas_day":d,"published_at":datetime(d.year,d.month,d.day,18,tzinfo=ROME),
                          "sas_gwh":float((d.day*13)%71-35)} for d in days])
