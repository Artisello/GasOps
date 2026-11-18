"""Read-only monitor diagnostics; no network or database access from the UI."""
from datetime import datetime,timedelta
import pandas as pd
import streamlit as st
from .models import utc_now
from .monitoring import default_report,parse_report

STATE="monitor_report_v1"
NAMES={"entsog":"ENTSOG SRG","acer":"ACER TERMINAL","mase":"MASE UNMIG","gie":"GIE AGSI+ IT","terna":"Terna"}
LABELS={"ok":"Acquisito","partial":"Da verificare","raw_pending":"Solo struttura CSV","failed":"Non riuscito","skipped":"Non configurato"}
ALERTS={"coverage":"Copertura parziale","stale":"Osservazioni non recenti","revision":"Revisioni numeriche",
        "outlier":"Scostamento statistico","metadata":"Metadati da verificare","provider":"Fonte o validazione non disponibile"}


def panel():
    st.subheader("Monitoraggio automatico")
    st.caption("Diagnostica delle fonti · nessuna richiesta di rete da questa vista")
    with st.expander("Carica report di monitoraggio"):
        st.markdown("[Workflow GitHub Actions](https://github.com/Artisello/GasOps/actions/workflows/public-monitor.yml)")
        f=st.file_uploader("Report JSON generato dal monitor",type=["json"],key="monitor_file")
        if st.button("Importa report",key="monitor_import"):
            try:
                if f is None or f.size>100_000: raise ValueError("Report assente o troppo grande")
                st.session_state[STATE]=parse_report(f.getvalue())
            except (ValueError,TypeError,KeyError):
                st.error("Report non valido. Report precedente invariato.")
        if STATE in st.session_state and st.button("Rimuovi report",key="monitor_clear"):
            st.session_state.pop(STATE,None)
            st.rerun()
    report=st.session_state.get(STATE)
    if report is None:
        try:
            path=default_report()
            with path.open("rb") as f:
                report=parse_report(f.read(100_001))
        except (OSError,ValueError,TypeError,KeyError):
            st.info("Nessun report disponibile. Esegui il monitor autorizzato o scarica il report da GitHub Actions e importalo.")
            return
    when=datetime.fromisoformat(report["checked_at"])
    if when>utc_now() or utc_now()-when>timedelta(hours=36):
        st.warning("Report non recente o timestamp futuro.")
    st.caption("Ultima verifica dichiarata: "+when.isoformat()+" · "+("archivio privato" if report["mode"]=="private_archive" else "sola diagnostica (nessuno storico persistente)"))
    rows=report["sources"]
    a,b,c=st.columns(3)
    a.metric("Fonti controllate",len(rows))
    b.metric("Acquisite / parziali",sum(r["status"] in ("ok","partial") for r in rows))
    c.metric("Non riuscite",sum(r["status"]=="failed" for r in rows))
    st.dataframe([{"Fonte":NAMES[r["source"]],"Stato":LABELS[r["status"]],"Valori validi":r["valid"],
                   "Attesi / righe (MASE)":r["expected"],"Ultimo periodo":r["latest"],"Revisioni":r["revisions"],
                   "Anomalie":r["outliers"],"Segnalazioni":" · ".join(ALERTS[a] for a in r["alerts"]),"URL":r["url"]} for r in rows],
                  hide_index=True,width="stretch",column_config={"URL":st.column_config.LinkColumn("Fonte")})
    st.caption("MASE: controllo strutturale, non KPI. Revisioni e anomalie richiedono archivio privato accumulato; null significa non calcolato. Soglie esplorative, non regole Snam. Il report importato non è autenticato indipendentemente.")
