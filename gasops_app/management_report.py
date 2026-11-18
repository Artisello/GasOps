"""Management briefing from existing declared session registers, no demo fallback."""
from datetime import date,timedelta
from calendar import monthrange
from math import isfinite
from decimal import Decimal
from .data import ROME
from .bso_kpis import closed_gas_day,operations_metrics,balancing_metrics,settlement_metrics,month_days
from .incentives import annual_amount
from .reconciliation import reconcile_days,score,reconcile_documents
from .market_efficiency import evaluate,SCOPES
from .source_health import session_health
from .intraday import decision_support
from .italiano import numero

SCHEMA="igor-management-v1"
PERIOD_NOTE="Mese di competenza: soli giorni gas conclusi. Scadenze, SAS intraday, credito e qualità riferiti alla data di elaborazione. IA per anno solare."
LIMIT="Dati di sessione e copertura dichiarata, non certificati. Nessuna azione, fattura, comunicazione o decisione ufficiale. Nessuna stima sostitutiva."
PRIORITY={"Alta":0,"Media":1,"Informativa":2}


def report(state,now,year,month,participant=None,*,inspections=None):
    if now.tzinfo is None:raise ValueError("Timestamp senza offset.")
    local=now.astimezone(ROME)
    if date(year,month,1)>local.date():raise ValueError("Mese futuro.")
    cutoff=closed_gas_day(now)
    days=len(month_days(year,month,cutoff))
    period=f"{year:04d}-{month:02d}"
    asof=local.isoformat(timespec="minutes")
    metrics=[]; signals=[]
    def metric(area,label,value,unit,per,scope,coverage,source,status):
        if value is not None and not isfinite(float(value)):value=None
        metrics.append(dict(area=area,label=label,value=value,unit=unit,period=per,scope=scope,
                            coverage=coverage,source=source,status=status if value is not None else "Non disponibile"))
    def flag(area,priority,title,detail,action):
        signals.append(dict(area=area,priority=priority,title=title,detail=detail,action=action))
    def section(area,fn):
        # Isolate incompatible/corrupt session registers: no partial calculations from a failed block.
        n,m=len(metrics),len(signals)
        try:fn()
        except (ValueError,TypeError,KeyError,AttributeError,IndexError,ArithmeticError):
            del metrics[n:];del signals[m:]
            flag(area,"Media","Controllo non elaborabile","Schema o dati della sessione da verificare.","Verificare il registro nella vista dedicata.")
    def operations():
        saved=state.get("bso_tasks_v1")
        if not saved:
            flag("Operations","Informativa","Registro attività assente","Nessun controllo delle scadenze.","Importare registro autorizzato.")
            return
        r=operations_metrics(saved["tasks"],now,year,month)
        scope="Tutte le attività dichiarate"
        metric("Operations","Attività aperte in ritardo",len(r["overdue"]),"",asof,scope,"Tutte le date del registro","Registro attività","Dichiarato")
        metric("Operations","Scadenze entro 24 ore",r["next24"],"",asof,scope,"Tutte le date del registro","Registro attività","Dichiarato")
        metric("Operations","Puntualità",r["on_time_pct"],"%",period,scope,f'{r["on_time"]}/{r["due"]} termini trascorsi',"Registro attività","Dichiarato")
        if r["overdue"]:flag("Operations","Alta","Attività oltre termine",f'{len(r["overdue"])} attività aperte dichiarate.',"Verificare esecuzione e aggiornare il registro.")
        if r["next24"]:flag("Operations","Media","Scadenze imminenti",f'{r["next24"]} attività entro 24 ore.',"Verificare priorità e assegnazioni.")
    def balancing():
        saved=state.get("jarvis_public_snapshot_v1")
        if not saved:
            flag("Balancing","Informativa","Stime SAS assenti","Nessuna pubblicazione importata.","Importare pubblicazioni autorizzate.")
            return
        r=balancing_metrics(saved["versions"],year,month,now)
        cov=f'{r["observed"]}/{r["expected"]} giorni conclusi'
        metric("Balancing","|SAS| medio",r["mean_abs_sas"],"GWh",period,"SRG · stime",cov,"Jarvis dichiarato","Parziale" if r["observed"]<r["expected"] else "Dichiarato")
        if r["observed"]<r["expected"]:flag("Balancing","Media","Copertura SAS parziale",cov,"Verificare pubblicazioni mancanti.")
        active=cutoff+timedelta(days=1)
        x=decision_support(saved["versions"],active,now)
        metric("Balancing","SAS pubblicato",x.get("published"),"GWh",active.isoformat(),"Giorno gas attivo",x.get("issued","Pubblicazione assente"),"Jarvis dichiarato",x["status"])
        if x["status"]=="candidate":
            metric("Balancing","SAS ultima stima prevista",x["candidate"]["estimate"],"GWh",active.isoformat(),"Giorno gas attivo",f'{x["n"]} coppie storiche',"Modello di revisione","Sperimentale · non consuntivo")
        elif x["status"] in ("missing","stale"):
            flag("Balancing","Media","SAS corrente da aggiornare","Pubblicazione assente oppure obsoleta.","Verificare Jarvis; nessuna azione di mercato automatica.")
    def settlement():
        saved=state.get("settlement_desk_csv_v1")
        if not saved or participant is None:
            flag("Settlement","Informativa","Perimetro settlement non selezionato","Registro assente o partecipante non selezionato.","Importare bilanci e selezionare un partecipante.")
            return
        rows=saved["rows"]
        if not any(r.user==participant for r in rows):raise ValueError("Partecipante non presente.")
        s=settlement_metrics(rows,participant,year,month,cutoff)
        scope="Singolo partecipante selezionato (ID omesso)"
        metric("Settlement","Definitivi utilizzabili",s["eligible_pct"],"%",period,scope,f'{s["eligible"]}/{s["expected"]} giorni',"Registro bilanci","Parziale" if not s["complete"] else "Dichiarato")
        if s["exceptions"]:flag("Settlement","Media","Bilanci con eccezioni",f'{s["exceptions"]} giorni, incluse assenze.',"Verificare versioni, prezzi e bilanci.")
        reported=state.get("settlement_reported_v1")
        if not reported:
            flag("Settlement","Informativa","Estratto di confronto assente","Quadratura indipendente non eseguita.","Importare esiti definitivi comunicati.")
        else:
            r=score(reconcile_days(rows,reported["rows"],participant,year,month,cutoff))
            cov=f'{r["compared"]}/{r["expected"]} giorni confrontabili; {r["matched"]} quadrati'
            metric("Settlement","Differenze assolute note",r["gross_difference"],"€",period,scope,cov,"Bilanci + esiti dichiarati","Parziale" if r["unknown"] else "Dichiarato")
            if r["exceptions"]:flag("Settlement","Alta" if r["gross_difference"] and r["gross_difference"]>0 else "Media",
                 "Partite da riconciliare",f'{r["exceptions"]} giorni con eccezioni, {r["unknown"]} non confrontabili.',"Esaminare differenze note e versioni non confrontabili.")
        docs=state.get("settlement_documents_v1")
        if docs:
            r=reconcile_documents(rows,docs["rows"],participant,year,month,cutoff)
            bad=sum(x["status"] not in ("QUADRA","NON DOVUTA") for x in r)
            if bad:flag("Settlement","Media","Documenti DS da verificare",f'{bad}/2 gruppi non quadrati o non confrontabili.',"Controllare le partite acquisto e vendita separatamente.")
    def credit():
        saved=state.get("credit_analytical_snapshot_v1")
        if not saved:
            flag("Credit Risk","Informativa","Snapshot analitico assente","La simulazione manuale non alimenta il report.","Importare snapshot analitico autorizzato.")
            return
        p=saved["position"]; d=date.fromisoformat(saved["as_of"])
        if d>local.date():raise ValueError("Snapshot futuro.")
        if d<local.date():
            flag("Credit Risk","Media","Snapshot credito storico",f'Data {d.isoformat()}; non rappresenta la posizione corrente.',"Aggiornare la posizione prima della revisione.")
        scope="Singolo partecipante dello snapshot (ID omesso)"
        if participant is not None and saved["user"]!=participant:
            scope+=" · diverso dal settlement"
        status="Storico · "+p["status"] if d<local.date() else "Studio · "+p["status"]
        metric("Credit Risk","EPSu",p["eps"],"€",str(d),scope,"Copertura dichiarata","Snapshot analitico",status)
        metric("Credit Risk","MEPSu",p["meps"],"€",str(d),scope,"Garanzie riconosciute dichiarate","Snapshot analitico",status)
        metric("Credit Risk","Utilizzo MEPSu",p["ratio"],"%",str(d),scope,"Rapporto solo con MEPSu positivo","Snapshot analitico",status)
        if p["status"]!="OK" and d==local.date():
            flag("Credit Risk","Alta" if p["status"]=="LIMITE" else "Media","Esito credito da verificare",p["status"]+" · calcolo di studio.", "Riconciliare con la posizione ufficiale; nessun blocco o avviso automatico.")
    def incentive():
        saved=state.get("bso_6pi_v1")
        if not saved:
            flag("Performance","Informativa","Indicatori 6PI assenti","IA non determinabile.","Importare p1–p6 autorizzati.")
            return
        if year not in range(2025,2029):return
        rows=tuple(r for r in saved[0] if r.day.year==year and r.day<=cutoff)
        expected=(date(year+1,1,1)-date(year,1,1)).days
        completed=sum(all(v is not None for v in r.incentives) and r.h is not None for r in rows)
        metric("Performance","Giorni 6PI calcolabili",completed,"",str(year),"RdB · anno solare",f"{completed}/{expected} giorni","Registro 6PI dichiarato","Studio")
        ia=annual_amount(rows,year)
        metric("Performance","IA annuale (studio)",ia,"€",str(year),"RdB · anno solare","Anno intero, tutti definitivi richiesti","Registro 6PI dichiarato","Studio")
        if ia is None:flag("Performance","Informativa","IA annuale non determinabile","Anno incompleto o dati non definitivi.","Non annualizzare gli importi parziali.")
    def market():
        saved=state.get("market_efficiency_v1")
        if not saved:
            flag("Market Operations","Informativa","Registro azioni assente","Costi e volumi non determinabili.","Importare estratto giornaliero autorizzato.")
            return
        scopes=sorted({r.scope for r in saved["rows"] if (r.day.year,r.day.month)==(year,month) and r.day<=cutoff})
        if not scopes:
            flag("Market Operations","Informativa","Nessuna azione nel registro del mese","Nessuna riga, non significa zero azioni.","Verificare estratto e periodo.")
        for scope in scopes:
            r,_=evaluate(saved["rows"],year,month,scope,cutoff)
            cov=f'{r["complete_days"]}/{r["expected_days"]} giorni completi'
            status="Dichiarato" if r["complete_period"] else "Parziale"
            metric("Market Operations","Costo netto azioni (non neutralità)",r["net_cost_eur"],"€",period,SCOPES[scope],cov,"Registro azioni",status)
            metric("Market Operations","Volume lordo azioni",r["gross_mwh"],"MWh",period,SCOPES[scope],cov,"Registro azioni",status)
            if not r["complete_period"]:flag("Market Operations","Media","Copertura azioni parziale",SCOPES[scope]+" · "+cov,"Completare estratto prima di interpretare il totale.")
    def quality():
        rows=session_health(state,now,inspections=inspections)
        good=sum(r["status"]=="Copertura verificata" for r in rows)
        absent=sum(r["status"].startswith("Non disponibile") or r["status"]=="Disattivato" for r in rows)
        review=len(rows)-good-absent
        metric("Data Quality","Serie con copertura verificata",good,"",asof,"Serie controllate, non provider",f"{good}/{len(rows)} · {absent} non disponibili/disattivate","Controllo sessione","Diagnostico")
        if absent or review:flag("Data Quality","Media" if review else "Informativa","Copertura fonti da completare",
                 f'{review} da verificare; {absent} non disponibili o disattivate su {len(rows)} serie.',"Consultare Monitoraggio fonti; verificare qualità e aggiornamento.")
    for area,fn in (("Operations",operations),("Balancing",balancing),("Settlement",settlement),
                    ("Credit Risk",credit),("Performance",incentive),("Market Operations",market),("Data Quality",quality)):
        section(area,fn)
    return {"schema":SCHEMA,"generated_at":asof,"month":period,"closed_days":days,"last_closed_day":str(cutoff),
            "period_note":PERIOD_NOTE,"notice":LIMIT,"metrics":metrics,
            "signals":sorted(signals,key=lambda s:(PRIORITY[s["priority"]],s["area"],s["title"]))}


def display_value(m):
    v=m["value"]
    return "N/D" if v is None else numero(v,0 if m["unit"]=="" else 2 if m["unit"]=="€" else 1)+(f' {m["unit"]}' if m["unit"] else "")


def markdown(r):
    # Only allowlisted derived values, no task titles, notes, IDs or raw records.
    def cell(x):return str(x).replace("|","\\|").replace("\n"," ")
    out=["# I.G.O.R. · Report direzionale BSO","",f'Elaborato: {r["generated_at"]} · Mese: {r["month"]} · Giorni gas conclusi nel mese: {r["closed_days"]}',
         "",r["period_note"],"",r["notice"],"","## Priorità di revisione",""]
    if not r["signals"]:out.append("Nessun rilievo nei controlli eseguiti; non certifica assenza di criticità.")
    for s in r["signals"]:out.append(f'- **{s["priority"]} · {s["area"]}** — {s["title"]}: {s["detail"]} {s["action"]}')
    out+=["","## Indicatori disponibili","","| Area | Indicatore | Valore | Periodo | Perimetro | Copertura / fonte | Stato |",
          "|---|---|---:|---|---|---|---|"]
    for m in r["metrics"]:
        out.append("| "+" | ".join(map(cell,(m["area"],m["label"],display_value(m),m["period"],m["scope"],m["coverage"]+" · "+m["source"],m["status"])))+" |")
    return "\n".join(out)+"\n"
