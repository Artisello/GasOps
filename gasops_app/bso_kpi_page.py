"""Minimal KPI desk for Balancing, Settlement & Operations."""
from datetime import date, datetime, timedelta
from hashlib import sha256

import pandas as pd
import streamlit as st

from .data import ROME
from .models import utc_now
from .italiano import data_it, numero
from .operations_ledger import sample_rows
from .settlement_desk_page import STATE as SETTLEMENT_STATE
from .visuals import info, kpi_grid, header
from .bso_kpis import (PUBLIC_MILESTONES,NEWS,CODE,JARVIS,MAX_BYTES,AREAS,
                       task_demo,balancing_demo,task_template,task_csv,parse_tasks,operations_metrics,
                       balancing_metrics,settlement_metrics,closed_gas_day,is_timed,local_day)

STATE="bso_tasks_v1"
AREA_LABEL={"all":"Tutte","balancing":"Bilanciamento","settlement":"Settlement","operations":"Operazioni gas"}
DEMO_NOW=datetime(2026,11,18,14,tzinfo=ROME)


def stamp(d):
    if d is None:
        return "—"
    return d.astimezone(ROME).strftime("%d/%m/%Y %H:%M %Z") if is_timed(d) else d.strftime("%d/%m/%Y")


def month_option(values,key):
    return st.selectbox("Periodo",values,format_func=lambda x:data_it(date(x[0],x[1],1),day=False),key=key)


def _import_tasks():
    with st.expander("Importa registro attività",expanded=STATE not in st.session_state):
        st.caption("Dati pubblici o sintetici · solo sessione, senza dati riservati.")
        st.download_button("Modello CSV",task_template(),"igor-attivita-modello.csv","text/csv",key="bso_template")
        info("Formato","ID fittizio, area, descrizione, scadenza, completamento. Date YYYY-MM-DD oppure timestamp ISO con offset (+01:00/+02:00 o Z). Completamento vuoto = aperto nel registro. Una scadenza con orario richiede un completamento con orario. Nessun invio al modello AI, nessun salvataggio persistente.")
        with st.form("bso_import",clear_on_submit=True):
            f=st.file_uploader("Registro CSV",type=["csv"])
            submit=st.form_submit_button("Importa")
        if submit:
            if f is None:
                st.warning("Seleziona un CSV.")
            elif f.size>MAX_BYTES:
                st.error("CSV superiore a 1 MB.")
            else:
                try:
                    raw=f.getvalue()
                    st.session_state[STATE]={"tasks":parse_tasks(raw),"sha256":sha256(raw).hexdigest()}
                    st.success("Registro importato.")
                except ValueError as error:
                    st.error(str(error)+". Registro precedente invariato.")
        if STATE in st.session_state and st.button("Rimuovi registro",key="bso_clear"):
            st.session_state.pop(STATE,None)
            st.rerun()


def _deadlines(demo,now):
    if not demo:
        _import_tasks()
    saved=st.session_state.get(STATE)
    tasks=task_demo() if demo else saved["tasks"] if saved else []
    if not tasks:
        st.info("Importa il registro delle attività per monitorare scadenze e puntualità.")
        return
    source="Registro sintetico" if demo else "CSV utente · stato dichiarato"
    st.caption(f"{source} · situazione al {stamp(now)}")
    a,b,settings=st.columns([2,2,1.25],vertical_alignment="bottom")
    with a:
        area=st.selectbox("Area",["all",*AREAS],format_func=AREA_LABEL.__getitem__,key="bso_area")
    with b:
        months=sorted({(now.year,now.month),*((local_day(x["due_at"]).year,local_day(x["due_at"]).month) for x in tasks)},reverse=True)
        ym=(now.year,now.month)
        y,m=st.selectbox("Mese di riferimento",months,index=months.index(ym),
                         format_func=lambda x:data_it(date(x[0],x[1],1),day=False),key="bso_ops_month")
    with settings, st.popover("Info e obiettivo",icon=":material/info:",width="stretch"):
        target=st.number_input("Puntualità target (%)",0.,100.,100.,step=1.,key="bso_sla_target")
        st.caption("Target di studio, non SLA Snam. Puntualità = attività completate entro termine / attività con termine trascorso nel mese. Le attività aperte in ritardo sono nel denominatore; quelle non ancora dovute sono escluse. Conteggi di agenda: tutte le date del registro, area selezionata. Date senza orario: scadenza a fine giorno locale; completamento datato senza ora non certifica l'orario.")
        if not demo:
            st.text("SHA-256: "+saved["sha256"])
    r=operations_metrics(tasks,now,y,m,area)
    kpi_grid([("In ritardo",len(r["overdue"]),"","Anche mesi precedenti",0,"rose" if r["overdue"] else ""),
              ("Entro 24 ore",r["next24"],"","Attività aperte",0,""),
              ("Entro 7 giorni",r["next7"],"","Include le prossime 24 h",0,""),
              ("Puntualità",r["on_time_pct"],"%",f'{r["on_time"]}/{r["due"]} · target {numero(target,0)}%',1,
               "rose" if r["on_time_pct"] is not None and r["on_time_pct"]<target else "")])
    groups={"Priorità":r["overdue"]+r["upcoming"],"Scadute":r["overdue"],"Entro 7 giorni":r["upcoming"],
            "Tutte":r["rows"],"Completate":[x for x in r["rows"] if x["completed_at"] is not None]}
    filter_=st.radio("Mostra attività",tuple(groups),horizontal=True,key="bso_task_filter",
                     format_func=lambda key:f"{key} · {len(groups[key])}")
    rows=groups[filter_]
    if rows:
        st.dataframe([{"Attività":x["activity"],"Area":AREA_LABEL[x["area"]],"Scadenza":stamp(x["due_at"]),
                       "Stato":x["status"],"Completamento":stamp(x["completed_at"]),"Ore residue":round(x["remaining_hours"],1) if x["completed_at"] is None else None}
                      for x in rows],hide_index=True,width="stretch")
    else:
        st.caption("Nessuna attività per questo filtro.")
    st.download_button("Esporta registro",task_csv(tasks),"igor-attivita.csv","text/csv",key="bso_export_tasks",on_click="ignore")


def _public(now):
    st.subheader("Calendario pubblico Snam")
    st.caption("Riferimenti datati · stato di esecuzione non noto")
    rows=[]
    for deadline,area,activity,published,scope in sorted(PUBLIC_MILESTONES):
        day=date.fromisoformat(deadline)
        delta=(day-now.date()).days
        rows.append({"Data":day,"Evento":activity,"Area":AREA_LABEL[area],"Giorni alla data":delta,
                     "Stato data":"Trascorsa" if delta<0 else "Oggi" if delta==0 else "Futura",
                     "Pubblicato il":date.fromisoformat(published),"Contesto":scope,"Fonte":NEWS})
    st.dataframe(rows,hide_index=True,width="stretch",
                 column_config={"Fonte":st.column_config.LinkColumn("Fonte",display_text="Comunicazione")})
    st.markdown("[Comunicazioni commerciali Snam]("+NEWS+") · [Codice di Rete]("+CODE+") · [Jarvis]("+JARVIS+")")
    from .operating_rules_page import calendar_panel
    calendar_panel(now)
    info("Calendario","Snapshot delle comunicazioni del 6 e 23 ottobre 2026, consultate il 18 novembre 2026. Nessun aggiornamento automatico. Le milestone possono essere rettificate: verificare la fonte. Date ufficialmente comunicate senza inventare orari o adempimenti completati. Non entrano nel KPI di puntualità.")


def _balancing(demo,now):
    st.subheader("Balancing")
    if demo:
        # Explicit synthetic snapshots, not the published Jarvis feed.
        frame=balancing_demo()
        st.caption("SAS sintetico · novembre 2026")
    else:
        imported=st.session_state.get("jarvis_public_snapshot_v1")
        if not imported:
            st.info("Nessuna pubblicazione importata. [Importa dati Jarvis](/balancing).")
            return
        frame=imported["versions"]
        st.caption("Italia · rete Snam · stime Jarvis importate, non verificate")
    values=sorted({(d.year,d.month) for d in frame["gas_day"]},reverse=True)
    y,m=month_option(values,"bso_bal_month")
    with st.popover("Soglia di studio",icon=":material/info:"):
        enabled=st.checkbox("Attiva fascia SAS",value=False,key="bso_sas_band_enabled")
        band=st.number_input("|SAS| massimo (GWh)",min_value=0.,max_value=100000.,value=50.,key="bso_sas_band",disabled=not enabled)
        st.caption("Soglia impostata dall’utente, non limite tecnico Snam. Si usa l’ultima stima importata per ogni giorno gas concluso alle 06:00 locali; nessuna stima mancante è trattata come zero. SAS atteso, non sbilanciamento fisico misurato.")
    r=balancing_metrics(frame,y,m,now,band if enabled else None)
    kpi_grid([("|SAS| medio",r["mean_abs_sas"],"GWh",f'{r["observed"]}/{r["expected"]} giorni gas',1,""),
              ("Picco |SAS|",r["peak_abs_sas"],"GWh","Stime importate o demo",1,""),
              ("Fuori fascia",r["outside_band"],"","Soglia facoltativa",0,""),
              ("Copertura SAS",(100*r["observed"]/r["expected"]) if r["expected"] else None,"%",f'{r["observed"]}/{r["expected"]}',1,"")])
    if r["observed"]<r["expected"]:
        st.warning("Copertura parziale: indicatori riferiti ai soli giorni disponibili.")
    if r["observed"]:
        chart=pd.DataFrame(r["records"])
        chart["day"]=pd.to_datetime(chart["day"])
        st.line_chart(chart,x="day",y="sas_gwh")


def _settlement(demo,now):
    st.subheader("Settlement")
    saved=st.session_state.get(SETTLEMENT_STATE)
    if not demo and not saved:
        st.info("Nessun registro bilanci importato. [Importa CSV](/balancing).")
        return
    rows=sample_rows() if demo else saved["rows"]
    st.caption("Bilanci sintetici · IVA esclusa" if demo else "CSV utente · non verificato · IVA esclusa")
    user=st.selectbox("Partecipante",sorted({r.user for r in rows}),key="bso_participant")
    y,m=month_option(sorted({(r.day.year,r.day.month) for r in rows if r.user==user},reverse=True),"bso_set_month")
    r=settlement_metrics(rows,user,y,m,closed_gas_day(now))
    info("Definizioni","Copertura dei giorni gas conclusi con un bilancio definitivo valorizzabile e privo delle eccezioni implementate. Non misura puntualità di pubblicazione: il registro non contiene timestamp di rilascio. Gli importi sono simulazioni calcolate dal CSV; nessuna fattura ufficiale. I giorni non ancora conclusi non entrano nel denominatore.")
    kpi_grid([("Definitivi utilizzabili",r["eligible_pct"],"%",f'{r["eligible"]}/{r["expected"]} giorni gas',1,""),
              ("Giorni con eccezioni",r["exceptions"],"",f'{r["definitive"]} definitivi presenti',0,"rose" if r["exceptions"] else ""),
              ("Impatto rettifiche",r["revision_abs"],"€",f'{r["comparable"]} coppie valorizzabili',2,""),
              ("Giorni rettificati",r["revised"],"",f'{r["revision_pairs"]} coppie confrontabili',0,"")])
    if r["expected"] and not r["complete"]:
        st.warning("Copertura non completa: non usare come totale definitivo del mese.")
    exceptions=[{"Giorno gas":x["day"],"Fase":x["stage"],"Δ DS (MWh)":x["delta_ds_mwh"],
                 "Δ €":x["delta_cash_eur"],"Eccezioni":"; ".join(x["issues"])} for x in r["records"] if x["issues"] or x["delta_ds_mwh"] not in (None,0) or x["delta_cash_eur"] not in (None,0)]
    if exceptions:
        st.dataframe(exceptions,hide_index=True,width="stretch")
    elif r["records"]:
        st.caption("Nessuna eccezione o rettifica rilevata.")


def page():
    from .workspace import apply_intent, guide, picker
    apply_intent("kpi")
    header("Operazioni gas", "")
    view=picker("Vista operazioni gas",["Registro operativo","Panoramica","Monitoraggio fonti","Executive demo","Centro operativo"],
                key="bso_view",index=1,labels={"Panoramica":"Indicatori","Registro operativo":"Agenda e scadenze","Executive demo":"Esempio completo","Monitoraggio fonti":"Stato fonti","Centro operativo":"Strumenti avanzati"})
    if view=="Centro operativo":
        from .agentic_operations_page import panel
        panel()
        return
    if view=="Executive demo":
        from .executive_demo import panel
        panel()
        return
    if view=="Monitoraggio fonti":
        from .monitoring_page import panel
        panel()
        return
    if view=="Panoramica":
        from .advanced_kpi_page import panel
        panel()
        return
    source,section_control=st.columns([2,1],vertical_alignment="bottom")
    labels={"Scadenze":"Agenda","Calendario Snam":"Calendario Snam","Balancing":"Indicatori bilanciamento","Settlement":"Indicatori bilanci"}
    section=section_control.selectbox("Consulta",tuple(labels),key="bso_register_section",format_func=labels.__getitem__)
    if section=="Calendario Snam":
        if "bso_mode" in st.session_state:
            st.session_state["bso_mode"]=st.session_state["bso_mode"]
        _public(utc_now().astimezone(ROME))
        return
    saved=st.session_state.get(SETTLEMENT_STATE,{})
    has_import={"Scadenze":bool(st.session_state.get(STATE,{}).get("tasks")),
                "Balancing":bool(st.session_state.get("jarvis_public_snapshot_v1")),
                "Settlement":bool(saved.get("rows")) and saved.get("authorized") is True and saved.get("origin")=="user_upload"}[section]
    if has_import:
        st.session_state["bso_mode"]="Dati importati"
        selection="Dati importati"
    else:
        selection=source.radio("Dati da utilizzare",["Dati importati","Demo"],horizontal=True,key="bso_mode",
                               format_func=lambda value:"Esempio guidato" if value=="Demo" else value)
    demo=selection=="Demo"
    now=DEMO_NOW if demo else utc_now().astimezone(ROME)
    if section!="Scadenze":
        st.caption(("Esempio · " if demo else "Situazione al ")+stamp(now))
    if section=="Scadenze":
        _deadlines(demo,now)
    elif section=="Balancing":
        _balancing(demo,now)
    else:
        _settlement(demo,now)
    guide("operations")
