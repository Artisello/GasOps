"""Compact presentation of the shared read-only system-status model."""
from dataclasses import asdict
from html import escape
import json

import streamlit as st

from .italiano import data_it, numero
from .system_status import StatusPolicy
from .visuals import chip, kpi_grid, local_time
from .freshness import measure_evidence, label as freshness_label
from .models import utc_now

DAY_KEY = "system_status_gas_day"
SELECTED_DAY = "system_status_selected_gas_day"
REQUESTED_DAY = "system_status_requested_gas_day"
ARCHIVE_KEY = "operational_historical_archive"
KINDS = {"observed":"Osservato", "estimated":"Stimato", "historical":"Storico", "unavailable":"N/A"}


def policy():
    return StatusPolicy(capacity_pct=st.session_state.get("system_capacity_pct", 90),
        deviation_pct=st.session_state.get("system_deviation_pct", 30),
        baseline_min_days=st.session_state.get("system_baseline_min_days", 14))


def header(status):
    st.session_state[SELECTED_DAY] = status.gas_day
    with st.container(key="system_status_header"):
        label, date_col, settings = st.columns([3, 1.2, .6], vertical_alignment="bottom")
        with label:
            day_status = {"active":"Giorno gas attivo", "last_completed":"Ultimo giorno gas concluso", "historical":"Giorno gas storico"}[status.gas_day_status]
            data_status = {"stale":"Dati da aggiornare", "partial":"Dati parziali", "observed":"Dati osservati", "unavailable":"Dati non disponibili"}[status.source_status]
            st.html('<div class="gas-map-status">'+chip(day_status, "historical" if status.gas_day_status == "historical" else "ok")
                    +chip(data_status, "review" if status.source_status != "observed" else "ok")+'</div>')
            st.caption(f"{status.source_coverage.valid}/{status.source_coverage.expected} componenti · "
                       f"06:00–06:00 Europe/Rome · {status.hours} ore")
        with date_col:
            if REQUESTED_DAY not in st.session_state and DAY_KEY in st.session_state:
                st.session_state[DAY_KEY] = status.gas_day
            st.date_input("Giorno gas", value=status.gas_day,
                max_value=status.active_gas_day, min_value=status.active_gas_day.replace(year=2000, month=1, day=1),
                key=DAY_KEY, format="DD/MM/YYYY", on_change=_remember_day)
        with settings, st.popover("Soglie", width="stretch"):
            st.caption("Soglie informative I.G.O.R.")
            st.number_input("Utilizzo capacità · %", min_value=1, max_value=200, value=90, key="system_capacity_pct")
            st.number_input("Scarto dalla mediana · %", min_value=1, max_value=1000, value=30, key="system_deviation_pct")
            st.number_input("Giorni minimi della baseline", min_value=3, max_value=28, value=14, key="system_baseline_min_days")
            latest = data_it(status.latest_observed_gas_day) if status.latest_observed_gas_day else "N/A"
            st.caption(f"Ultimo giorno osservato: {latest} · ultimo giorno concluso: {data_it(status.last_completed_gas_day)}")
    demand = status.demand_forecast if status.demand_actual.value is None and status.demand_forecast.value is not None else status.demand_actual
    cards = []
    for label, m in (("Ingressi stimati dalla fonte" if status.entry_flow_observed.status == "estimated" else "Ingressi osservati", status.entry_flow_observed), ("Send-out GNL", status.lng_sendout),
                     ("Giacenza stoccaggi", status.storage_level),
                     ("Prelievi SRG" if demand is status.demand_actual else "Prelievi SRG · previsione", demand)):
        detail = f"{m.source} · {data_it(m.gas_day)} · {m.coverage.valid}/{m.coverage.expected}"
        if m.value is not None and m.gas_day != status.gas_day:
            detail += " · Ultima giacenza pubblicata"
        if m.status == "estimated":
            detail += " · Stimato"
        if m.freshness == "stale":
            detail += " · ultima copia valida"
        cards.append((label, m.value, m.unit, detail, 1, ""))
    with st.container(key="system_status_kpis"):
        kpi_grid(cards)
    from .gme_market import api_configured as gme_configured
    if gme_configured():
        from .gme_market_page import overview_kpis
        overview_kpis(status.gas_day)


def _remember_day():
    st.session_state[SELECTED_DAY] = st.session_state[DAY_KEY]
    st.session_state[REQUESTED_DAY] = st.session_state[DAY_KEY]


def balance(status, *, compact=False):
    coverage=f"{status.source_coverage.valid}/{status.source_coverage.expected} componenti"
    layout=st.expander("Bilancio giornaliero · "+coverage) if compact else st.container(key="system_daily_balance")
    with layout:
        if not compact:
            st.subheader("Bilancio giornaliero")
            st.caption(coverage+" · "+data_it(status.gas_day))
        for side, label in (("supply", "Afflussi"), ("outflow", "Domanda e uscite")):
            cells = []
            for component in status.components:
                if component.side != side:
                    continue
                m = component.measure
                value = numero(m.value, 1) if m.value is not None else "N/A"
                warnings = " · ".join(m.warnings)
                tooltip = f"{m.scope}. {warnings}. Pubblicato: {local_time(m.observed_at)}. Acquisito: {local_time(m.retrieved_at)}"
                cells.append('<div class="gas-balance-cell" title="'+escape(tooltip, quote=True)+'">'
                    +'<span class="gas-balance-label">'+escape(component.label)+'</span>'
                    +'<strong>'+escape(value)+' <small>'+escape(m.unit)+'</small></strong>'
                    +'<span class="gas-balance-meta">'+escape(m.source)+' · '+escape(data_it(m.gas_day))+'</span>'
                    +'<span class="gas-balance-meta">'+KINDS[m.status]+f' · {m.coverage.valid}/{m.coverage.expected}'+'</span>'
                    +('</div>' if not warnings else '<span class="gas-balance-note">'+escape(warnings)+'</span></div>'))
            st.html('<div class="gas-balance-side">'+label+'</div><div class="gas-balance-strip">'+''.join(cells)+'</div>')
        st.caption(status.balance_message)
        with st.expander("Dati, periodi e copertura"):
            st.caption("La copertura conta componenti disponibili, comprese quelle osservate solo in parte. Non misura una quota del bilancio fisico. Gli ingressi escludono il GNL; i prelievi SRG sono distinti dalle importazioni. Nessuna somma tra aggregati sovrapposti.")
            st.dataframe([{"Componente":c.label, "Valore":str(c.measure.value) if c.measure.value is not None else None,
                "Unità":c.measure.unit, "Giorno gas":c.measure.gas_day, "Fonte":c.measure.source_id,
                "Stato":KINDS[c.measure.status], "Freschezza":freshness_label(measure_evidence(c.measure,utc_now())),
                "Copertura":f"{c.measure.coverage.valid}/{c.measure.coverage.expected}",
                "Pubblicato":local_time(c.measure.observed_at), "Acquisito":local_time(c.measure.retrieved_at),
                "Perimetro":c.measure.scope, "Note":" · ".join(c.measure.warnings)} for c in status.components],
                hide_index=True, width="stretch")
            st.caption("Qualità delle fonti · controlli già disponibili nella sessione")
            st.dataframe([{"Fonte":r["source"], "Stato":r["status"], "Ultimo periodo":r["latest"],
                "Copertura":f"{r['valid']}/{r['expected']}"} for r in status.source_health], hide_index=True, width="stretch")
            st.caption(f"Avvisi ENTSOG consultati su {status.event_coverage.valid}/{status.event_coverage.expected} punti/direzioni. Copertura non nazionale; nessuna conclusione sull’assenza di indisponibilità.")
            st.download_button("Esporta stato e provenienza", json.dumps(asdict(status), ensure_ascii=False, indent=2,
                default=lambda v:v.isoformat() if hasattr(v,"isoformat") else str(v)),
                "igor-system-status.json", "application/json", key="system_status_export")
    if compact:st.caption(status.balance_message)


def attention(status, network, open_point, *, compact=False):
    with st.container(key="system_operational_attention"):
        st.subheader("Attenzione operativa")
        st.caption("Indicatori di attenzione calcolati da I.G.O.R.")
        names = {i.id:i.name.replace("_", " – ") for i in network.infrastructure}
        categories = {"quality":"Qualità dati", "capacity":"Capacità", "deviation":"Scostamento", "event":"Evento pubblicato"}
        if not status.attention:
            st.caption("Nessuna regola attivata sui dati confrontabili. Le componenti N/A e la copertura degli avvisi restano indicate sopra.")
        def row(f):
            info, action = st.columns([5, 1], vertical_alignment="top")
            with info, st.expander(categories[f.category]+" · "+f.description):
                st.caption("Regola: "+f.rule+" · severità informativa")
                st.caption("Valore: "+(numero(f.observed_value,1)+" "+f.unit if f.observed_value is not None else "N/A")
                           +" · soglia: "+(numero(f.threshold,1)+" "+f.unit if f.threshold is not None else "N/A"))
                st.caption("Fonte: "+f.source_id)
                st.caption("Pubblicato: "+local_time(f.observed_at)+" · acquisito: "+local_time(f.retrieved_at))
                if f.evidence_ids:
                    st.caption("Riferimenti: "+", ".join(f.evidence_ids))
                if f.baseline is not None:
                    st.caption(f"Mediana: {numero(f.baseline,1)} GWh/d · {f.baseline_n} giorni precedenti validi · finestra massima 28 giorni")
                st.caption("ID: "+f.id)
            if f.infrastructure_id in names:
                action.button("Apri punto", key="system_attention_"+f.id, width="stretch",
                    help=names[f.infrastructure_id], on_click=open_point,
                    args=(f.infrastructure_id, status.gas_day, status.gas_day, f.direction))
        findings=[f for f in status.attention if f.category!="quality"] if compact else status.attention
        for f in findings[:5]:
            row(f)
        if len(findings) > 5:
            with st.expander(f"Altri {len(findings)-5} indicatori"):
                for f in findings[5:]:
                    row(f)
        quality=[f for f in status.attention if f.category=="quality"] if compact else []
        if quality:
            with st.expander(f"Qualità delle fonti · {len(quality)} segnalazioni"):
                st.dataframe([{"Segnalazione":f.description,"Fonte":f.source_id,"Regola":f.rule,
                    "Valore":numero(f.observed_value,1) if f.observed_value is not None else None,
                    "Soglia":numero(f.threshold,1) if f.threshold is not None else None,"Unità":f.unit,
                    "Pubblicato":local_time(f.observed_at),"Acquisito":local_time(f.retrieved_at),
                    "Riferimenti":", ".join(f.evidence_ids),"ID":f.id} for f in quality],hide_index=True,width="stretch")
                for f in quality:
                    if f.infrastructure_id in names:
                        st.button("Apri "+names[f.infrastructure_id],key="system_attention_"+f.id,
                            on_click=open_point,args=(f.infrastructure_id,status.gas_day,status.gas_day,f.direction))
