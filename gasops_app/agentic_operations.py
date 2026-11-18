"""Deterministic, read-only BSO triage and human review.
An issue is not a certified breach; a decision never executes an outside action.
"""
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from math import isfinite

from .bso_kpis import operations_metrics, balancing_metrics, settlement_metrics, closed_gas_day
from .monitoring import parse_report

MAX_CASES=600
MAX_EVENTS=20
STATES=("Da verificare","In revisione","Verificato","Archiviato")
TRANSITIONS={
    "Da verificare":("In revisione","Archiviato"),
    "In revisione":("Verificato","Archiviato","Da verificare"),
    "Verificato":("In revisione","Archiviato"),
    "Archiviato":("In revisione",),
}
PRIORITIES={"Alta":0,"Media":1,"Informativa":2}


def digest(obj):
    return sha256(json.dumps(obj,sort_keys=True,ensure_ascii=False,separators=(",",":"),default=str).encode()).hexdigest()


@dataclass(frozen=True)
class Proposal:
    key: str
    id: str
    agent: str
    priority: str
    title: str
    period: str
    evidence: str
    source: str
    action: str


def proposal(agent,identity,priority,title,period,evidence,source,action):
    key=digest([agent,identity])
    body=dict(key=key,agent=agent,priority=priority,title=title,period=period,
              evidence=evidence,source=source,action=action)
    return Proposal(id=digest(body),**body)


def scan(*,now,year,month,tasks=None,versions=None,balances=None,participant=None,monitor=None,mode="session"):
    if mode not in ("session","demo") or now.tzinfo is None:
        raise ValueError("Perimetro del controllo non valido.")
    cases=[]
    checks={}
    imported="Demo sintetica" if mode=="demo" else "Importazione dichiarata"
    def add(agent,identity,priority,title,period,evidence,source,action):
        cases.append(proposal(agent,identity,priority,title,period,evidence,source,action))
    if tasks is None:
        checks["Operations"]="Registro non disponibile"
    else:
        r=operations_metrics(tasks,now,year,month)
        checks["Operations"]=f'{len(r["rows"])} attività esaminate (tutte le date)'
        for item in r["overdue"]+r["upcoming"]:
            late=item["status"]=="Scaduta"
            # Upcoming window: only the next 24 h; no hypothetical deadline.
            if not late and item["remaining_hours"]>24:
                continue
            due=item["due_at"].isoformat()
            code=digest([item["task_id"],item["area"]])[:12]
            add("Operations",["task",item["task_id"],item["area"]],"Alta" if late else "Media",
                "Attività oltre termine" if late else "Attività entro 24 ore",due,
                f'Ref. {code} · area {item["area"]} · stato {item["status"]} · scadenza dichiarata {due}',
                imported+" · registro attività",
                "Controllare l'effettivo completamento e aggiornare il registro autorizzato; non presumere un inadempimento.")
    if versions is None:
        checks["Balancing"]="Stime SAS non caricate"
    else:
        r=balancing_metrics(versions,year,month,now)
        checks["Balancing"]=f'{r["observed"]}/{r["expected"]} giorni gas con stima numerica'
        for row in r["records"]:
            if row["sas_gwh"] is None:
                add("Balancing",["sas",row["day"]],"Media","Stima SAS non disponibile",row["day"],
                    "Stima numerica assente nel registro disponibile; ultima pubblicazione "+str(row["published_at"] or "non presente"),
                    imported+" · stime SAS","Verificare disponibilità e versione della pubblicazione; nessuna sostituzione con zero.")
    if not balances or not participant:
        checks["Settlement"]="Registro o partecipante non selezionato"
    else:
        r=settlement_metrics(balances,participant,year,month,closed_gas_day(now))
        checks["Settlement"]=f'{r["eligible"]}/{r["expected"]} giorni definitivi utilizzabili'
        for row in r["records"]:
            issues=row["issues"]
            revised=any(row[k] is not None and row[k]!=0 for k in ("delta_ds_mwh","delta_cash_eur"))
            if not issues and not revised:
                continue
            # Scope versions to a single participant; the raw identifier is not exported.
            ref=digest(participant)[:12]
            ev=f'Ref. partecipante {ref} · versione {row["version"]} · fase {row["stage"]}'
            if issues:
                ev+=" · "+"; ".join(issues)
            if revised:
                ev+=f' · Δ DS (MWh): {row["delta_ds_mwh"]} · Δ euro: {row["delta_cash_eur"]}'
            severe=any(x in issues for x in ("Regressione definitiva → provvisoria","Prezzo applicabile mancante","Variazione stoccaggio tra versioni"))
            add("Settlement",["participant",participant,row["day"]],"Alta" if severe else "Media",
                "Eccezione di settlement" if issues else "Rettifica da riconciliare",row["day"],ev,
                imported+" · registro bilanci","Riconciliare versioni, unità, prezzi ed effetti; documentare l'esito prima di ogni processo reale.")
    if monitor is None:
        checks["Data Quality"]="Report monitor non disponibile"
    else:
        report=parse_report(json.dumps(monitor).encode())
        stamp=datetime.fromisoformat(report["checked_at"])
        checks["Data Quality"]=f'{len(report["sources"])} fonti nel report dichiarato · {report["checked_at"]}'
        if stamp>now or now-stamp>timedelta(hours=36):
            add("Data Quality","report_recency","Media","Report non recente o futuro",report["checked_at"],
                "Timestamp fuori dalla finestra informativa di 36 ore (non SLA).",
                "Report monitor dichiarato","Acquisire un report autorizzato più recente e verificare il timestamp.")
        for row in report["sources"]:
            flags=sorted(set(row["alerts"]))
            if row["status"] not in ("failed","partial","raw_pending") and not flags:
                continue
            if row["status"]=="failed":
                priority="Alta"
            elif row["status"]=="raw_pending" and not flags:
                priority="Informativa"
            else:
                priority="Media"
            add("Data Quality",["provider",row["source"]],priority,"Fonte da verificare: "+row["source"],
                report["checked_at"],f'Stato {row["status"]} · validi {row["valid"]}/{row["expected"]} · segnali {", ".join(flags) or "—"} · revisioni {row["revisions"]} · anomalie {row["outliers"]}',
                "Report monitor dichiarato · "+row["source"],"Controllare fonte, schema, copertura e aggiornamento; non usare valori mancanti come osservazioni.")
    if len(cases)>MAX_CASES:
        raise ValueError("Troppe proposte per una coda di sessione: ridurre il perimetro o il registro.")
    return sorted(cases,key=lambda c:(PRIORITIES[c.priority],c.agent,c.period,c.id)),checks


def merge_cases(existing,proposals,now):
    """Append exact evidence versions; never overwrite a human decision."""
    if now.tzinfo is None:
        raise ValueError("Timestamp privo di offset.")
    known={r["id"]:r for r in existing}
    if len(known)!=len(existing) or len(set(known)|{p.id for p in proposals})>MAX_CASES:
        raise ValueError("Limite del registro raggiunto: esportare e avviare un nuovo registro.")
    for p in proposals:
        if p.id not in known:
            known[p.id]={**asdict(p),"created":now.isoformat(),"status":STATES[0],"history":[]}
    return list(known.values())


def decide(case,status,note,now):
    if status not in TRANSITIONS[case["status"]] or now.tzinfo is None:
        raise ValueError("Transizione non consentita.")
    note=note.strip()
    if not 1<=len(note)<=400 or len(case["history"])>=MAX_EVENTS:
        raise ValueError("Motivazione obbligatoria (max 400 caratteri) o storico esaurito.")
    event={"at":now.isoformat(),"from":case["status"],"to":status,"note":note}
    return {**case,"status":status,"history":[*case["history"],event]}


def handover(cases,current_ids,checks,mode,scan_at,*,regulatory=()):
    # JSON only: notes are untrusted user annotations, never rendered as HTML.
    return json.dumps({"schema":1,"mode":mode,"scan_at":scan_at,"checks":checks,
        "notice":"Proposte di revisione e annotazioni di sessione; nessuna azione esterna eseguita o certificata.",
        "cases":[{**r,"in_latest_scan":r["id"] in current_ids} for r in cases],
        "regulatory_references":list(regulatory) if mode=="session" else []},ensure_ascii=False,indent=2)
