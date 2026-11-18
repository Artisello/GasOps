"""Session-local human-in-the-loop BSO command centre."""
from datetime import date, datetime
import json
import streamlit as st

from .data import ROME
from .models import utc_now
from .bso_kpis import task_demo,balancing_demo
from .operations_ledger import sample_rows
from .monitoring import default_report,parse_report
from .agentic_operations import scan,merge_cases,decide,handover,TRANSITIONS,PRIORITIES

MODES={"Dati di sessione":"session","Demo sintetica":"demo"}
PREFIX="bso_agentic_v1_"


def _report(state):
    if state.get("monitor_report_v1") is not None:
        return state["monitor_report_v1"]
    try:
        with default_report().open("rb") as f:
            return parse_report(f.read(100_001))
    except (OSError,ValueError,TypeError,KeyError):
        return None


def panel():
    st.subheader("Centro operativo BSO")
    st.caption("Agenti a regole deterministiche · coda di revisione · nessuna esecuzione esterna")
    mode=MODES[st.radio("Perimetro",list(MODES),horizontal=True,key="agentic_mode")]
    key=PREFIX+mode
    state=st.session_state
    now=utc_now().astimezone(ROME)
    if mode=="demo":
        now=datetime(2026,11,18,14,tzinfo=ROME)
        st.warning("SIMULAZIONE · attività e SAS novembre 2026 · settlement settembre 2026 · nessun dato operativo Snam.")
        tasks=task_demo(); versions=balancing_demo(); balances=sample_rows(); participant="DEMO-001"; monitor=None
        year,month=2026,11
    else:
        tasks=state.get("bso_tasks_v1",{}).get("tasks")
        versions=state.get("jarvis_public_snapshot_v1",{}).get("versions")
        balances=state.get("settlement_desk_csv_v1",{}).get("rows")
        users=sorted({r.user for r in balances}) if balances else []
        chosen=st.date_input("Mese di controllo",value=now.date().replace(day=1),min_value=date(2000,1,1),max_value=now.date(),key="agentic_month")
        year,month=chosen.year,chosen.month
        participant=st.selectbox("Partecipante (registro importato)",[None,*users],format_func=lambda u:u or "Non selezionato",key="agentic_user")
        monitor=_report(state)
        st.caption("Solo dati già caricati. Importa registri autorizzati; nessun dato riservato. Nessuna chiamata API o AI da questa vista.")
    if st.button("Esegui controlli",type="primary",key="agentic_scan"):
        try:
            proposals,checks=scan(now=now,year=year,month=month,tasks=tasks,versions=versions,
                balances=balances if mode!="demo" else None,participant=participant,monitor=monitor,mode=mode)
            if mode=="demo":
                extra,settle=scan(now=now,year=2026,month=9,balances=balances,participant=participant,mode=mode)
                proposals+=extra
                checks["Settlement"]=settle["Settlement"]
            prior=state.get(key,{}).get("cases",[])
            state[key]={"cases":merge_cases(prior,proposals,utc_now()),"current":[p.id for p in proposals],
                        "checks":checks,"at":utc_now().isoformat()}
        except (ValueError,TypeError,KeyError):
            st.error("Controllo non completato: perimetro, report o limite del registro da verificare. Registro precedente invariato.")
    saved=state.get(key)
    if not saved:
        st.info("Esegui i controlli per costruire la coda. L'assenza di un registro non equivale all'assenza di anomalie.")
        return
    st.caption("Ultimo controllo in sessione: "+saved["at"]+" · modifiche alle fonti richiedono una nuova esecuzione.")
    current=set(saved["current"])
    cases=saved["cases"]
    active=[r for r in cases if r["id"] in current]
    a,b,c=st.columns(3)
    a.metric("Proposte nella scansione",len(active))
    b.metric("Da verificare / in revisione",sum(r["status"] in ("Da verificare","In revisione") for r in active))
    c.metric("Priorità alta aperte",sum(r["priority"]=="Alta" and r["status"] in ("Da verificare","In revisione") for r in active))
    st.markdown("**Copertura dei controlli**")
    st.dataframe([{"Agente":agent,"Esito":value} for agent,value in saved["checks"].items()],hide_index=True,width="stretch")
    st.caption("Priorità proposte per revisione, non SLA o criticità tecniche ufficiali. Un controllo senza input non è superato.")
    view=st.radio("Coda",["Ultima scansione","Registro completo"],horizontal=True,key="agentic_queue")
    pool=active if view=="Ultima scansione" else cases
    pool=sorted(pool,key=lambda r:(PRIORITIES[r["priority"]],r["agent"],r["period"],r["id"]))
    if pool:
        st.dataframe([{"Area":r["agent"],"Priorità":r["priority"],"Rilievo":r["title"],"Periodo":r["period"],
            "Stato":r["status"],"Nell'ultima scansione":r["id"] in current} for r in pool],hide_index=True,width="stretch")
        choice=st.selectbox("Proposta da esaminare",[r["id"] for r in pool],
            format_func=lambda i:next(f'{r["title"]} · {r["period"]} · {i[:8]}' for r in pool if r["id"]==i),key="agentic_case_"+mode)
        case=next(r for r in pool if r["id"]==choice)
        st.text(case["evidence"])
        st.caption(case["source"])
        st.markdown("**Azione proposta (da eseguire fuori da I.G.O.R.)**")
        st.text(case["action"])
        with st.form("agentic_decision_"+mode+"_"+case["id"],clear_on_submit=True):
            decision=st.selectbox("Decisione",TRANSITIONS[case["status"]])
            note=st.text_area("Motivazione · non inserire dati riservati",max_chars=400)
            confirm=st.form_submit_button("Registra decisione")
        if confirm:
            try:
                updated=decide(case,decision,note,utc_now())
                state[key]={**saved,"cases":[updated if r["id"]==choice else r for r in cases]}
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
        if case["history"]:
            with st.expander("Storico decisioni"):
                st.dataframe(case["history"],hide_index=True,width="stretch")
    else:
        st.caption("Nessuna proposta per il perimetro; controlla la copertura prima di interpretare il risultato.")
    st.download_button("Esporta passaggio di consegne JSON",handover(cases,current,saved["checks"],mode,saved["at"]),
        "igor-bso-handover-"+mode+".json","application/json",key="agentic_export_"+mode)
    st.caption("Registro solo di sessione con storico limitato; non autenticato. Una proposta non più presente nella scansione non è automaticamente risolta.")
    with st.expander("Gestione registro"):
        clear=st.checkbox("Ho esportato il registro e confermo la rimozione dalla sessione.",key="agentic_clear_check_"+mode)
        if st.button("Svuota registro",disabled=not clear,key="agentic_clear_"+mode):
            state.pop(key,None)
            st.rerun()
