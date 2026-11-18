"""Deterministic sentinel: inspect the selected observation window, never invent data."""
from math import isfinite

import pandas as pd
import streamlit as st

from .models import Kind
from .italiano import numero,GRAVITA
from .visuals import rows


def snapshot(context):
    origin=context.bundle.origin
    series=context.inspection.usable["demand_gwh"]
    window=7 if origin.grain=="daily" else 12
    values=series.tail(window)
    observed=int(values.notna().sum())
    expected=len(values)
    findings=[f for f in context.inspection.findings if f.severity!="info"]
    next_steps=[]
    if not observed:
        next_steps.append("Verifica la disponibilità della fonte prima di usare i risultati.")
    elif observed<expected or expected<window:
        next_steps.append("Controlla i periodi mancanti o esclusi; non interpretarli come consumi nulli.")
    if any(f.id=="stale" or f.id.startswith("public-cache") for f in findings):
        next_steps.append("Aggiorna la fonte e verifica la data dell’ultima osservazione.")
    if any(f.severity=="high" for f in findings):
        next_steps.append("Esamina i rilievi prioritari prima di utilizzare i calcoli.")
    delta=context.facts.get("demand_gwh_change_pct")
    # Illustrative threshold only; not an operational risk limit.
    trend=delta is not None and isfinite(delta) and abs(delta)>=15
    if trend:
        next_steps.append("Variazione significativa rispetto al periodo precedente: approfondisci domanda e driver.")
    points=context.projection.points
    point=points[0] if points else None
    if not point:
        next_steps.append("Previsione non disponibile: verifica la copertura storica.")
    elif point.lower_80 is None or point.upper_80 is None:
        next_steps.append("Intervallo previsionale non disponibile: non usare la sola stima come garanzia.")
    return {"observed":observed,"expected":expected,"window":window,"findings":findings,
            "trend":trend,"delta":delta,"actions":next_steps,
            "demo":origin.archive or origin.kind==Kind.SYNTHETIC}


def panel(context):
    report=snapshot(context)
    origin=context.bundle.origin
    st.subheader("Sentinella")
    st.caption("Controlli sui dati selezionati · eseguiti all’apertura/aggiornamento, non in continuo.")
    if report["demo"]:
        st.caption("Archivio storico o simulazione: non rappresenta il mercato corrente.")
    coverage=f'{report["observed"]}/{report["expected"]}' if report["expected"] else "—"
    rows([("Periodi utilizzabili · finestra recente",coverage),
          ("Rilievi da verificare",str(len(report["findings"]))),
          ("Ultima osservazione",context.facts.get("label","Non disponibile"))])
    if report["trend"]:
        st.caption("Variazione: "+numero(report["delta"],1,signed=True)+"% · soglia esplorativa ±15%, non limite Snam.")
    for f in report["findings"]:
        if f.severity=="high":
            st.warning(f.title)
    if report["actions"]:
        st.markdown("**Da controllare**")
        for action in report["actions"][:3]:
            st.caption(action)
    else:
        st.caption("Nessun nuovo segnale dai controlli eseguiti; non è una certificazione.")
    with st.expander("Dettaglio controlli"):
        st.caption(f"Finestra: fino a {report['window']} periodi ({'giorni gas' if origin.grain=='daily' else 'mesi'}); include eventuali lacune finali.")
        for f in context.inspection.findings:
            st.markdown("**"+f.title+"** · "+GRAVITA[f.severity])
            st.caption(f.detail)
        if len(report["actions"])>3:
            for action in report["actions"][3:]:
                st.caption(action)
