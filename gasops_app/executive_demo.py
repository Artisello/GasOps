"""Offline executive walkthrough. Synthetic fixtures never enter operational state."""
from datetime import datetime, timezone
from html import escape
import pandas as pd
import streamlit as st

from .data import ROME, jrc_archive
from .quality import inspect
from .acer_baf_2026 import report_2026_rows, all_baf_rows, zone_changes
from .acer_market import REPORT_2026, REPORT_2025
from .bso_kpis import task_demo, balancing_demo, operations_metrics, balancing_metrics, settlement_metrics, closed_gas_day
from .operations_ledger import sample_rows
from .predictive import evaluate, MODELS
from .visuals import kpi_grid
from .italiano import numero

STAGES=("Contesto","Controllo BSO","Previsioni","Dalla demo al pilot")
TITLES=("Il contesto del bilanciamento","Una cabina di controllo BSO",
        "Previsioni verificabili","Dal prototipo al pilot")
DESCRIPTIONS=("Indicatori pubblici europei per inquadrare il mercato italiano.",
              "Un caso sintetico riproducibile: scadenze, stime SAS e controlli sui definitivi.",
              "Confronto cronologico su dati storici pubblici, senza chiamate AI.",
              "Evidenze disponibili, verifiche necessarie e prossimi passi.")
STUDY="executive_forecast_v1"
DEMO_CLOCK=datetime(2026,11,18,14,tzinfo=ROME)


def benchmark():
    it={r["metric"]:r["value"] for r in report_2026_rows() if r["zone"]=="IT" and r["gas_year"]=="2024/2025"}
    return it,zone_changes(all_baf_rows(),"imbalance_share")


def operational_case():
    o=operations_metrics(task_demo(),DEMO_CLOCK,2026,11)
    b=balancing_metrics(balancing_demo(),2026,11,DEMO_CLOCK)
    s=settlement_metrics(sample_rows(),"DEMO-001",2026,9,closed_gas_day(DEMO_CLOCK))
    return o,b,s


def historical_study():
    bundle=jrc_archive()
    frame=inspect(bundle,datetime.now(timezone.utc)).usable.tail(730)
    return {"source":bundle.origin.name,"url":bundle.origin.url,"fingerprint":bundle.fingerprint,
            "result":evaluate(frame,(),1)}


def _change(delta):
    i=STAGES.index(st.session_state.get("executive_stage",STAGES[0]))
    st.session_state["executive_stage"]=STAGES[min(len(STAGES)-1,max(0,i+delta))]


def _context():
    it,compare=benchmark()
    st.caption("Dati storici pubblici · Italia · anno gas 2024/2025 · ACER 2026")
    kpi_grid([("Sbilanciamenti / volume",float(it["imbalance_share"]),"%","Mercato fisico · p. 15",1,"teal"),
              ("Neutralità netta rettificata",float(it["net_adjusted_neutrality"]),"€/MWh","Valore unitario · p. 19",2,""),
              ("Quota acquisti TSO",float(it["tso_buy_share"]),"%","Azioni di bilanciamento · p. 16",0,"")])
    chart=pd.DataFrame([r for r in compare if r["zone"] in ("IT","ES","FR-TRF","DE-THE","SI","DK-SE")])
    for col in ("2023/2024","2024/2025"):
        chart[col]=pd.to_numeric(chart[col],errors="coerce")
    st.markdown("**Incidenza degli sbilanciamenti · zone selezionate**")
    st.bar_chart(chart,x="zone",y=["2023/2024","2024/2025"],stack=False,horizontal=True,y_label="%",height=260)
    st.caption("Confronto descrittivo, non graduatoria di efficienza. Edizione 2025: estrazione da verificare visivamente.")
    st.markdown(f"[Report ACER 2026]({REPORT_2026}) · [Report ACER 2025]({REPORT_2025}) · [Analisi completa](/market)")


def _operations():
    st.warning("SIMULAZIONE · dati sintetici · nessun dato operativo Snam.")
    o,b,s=operational_case()
    kpi_grid([("Operations · scadenze aperte",len(o["overdue"]),"","Registro demo · al 18/11/2026",0,"rose" if o["overdue"] else ""),
              ("Balancing · |SAS| medio",b["mean_abs_sas"],"GWh",f'{b["observed"]}/{b["expected"]} giorni gas · nov 2026',1,""),
              ("Settlement · definitivi utilizzabili",s["eligible_pct"],"%",f'{s["eligible"]}/{s["expected"]} giorni gas · set 2026',1,"")])
    left,right=st.columns([1.4,1])
    with left,st.container(border=True):
        st.markdown("**Stime SAS di esempio**")
        chart=pd.DataFrame(b["records"])
        chart["day"]=pd.to_datetime(chart["day"])
        chart=chart.set_index("day")["sas_gwh"].asfreq("D").rename("SAS GWh")
        st.line_chart(chart,height=225,y_label="GWh")
        st.caption("Giorni gas conclusi · copertura parziale · nessuna soglia tecnica.")
    with right,st.container(border=True):
        st.markdown("**Controlli di esempio**")
        st.metric("Rettifiche economiche assolute",numero(s["revision_abs"],2)+" €")
        st.caption("Settembre 2026 · effetti lordi simulati, non fatture.")
        st.metric("Attività puntuali",numero(o["on_time_pct"],1)+"%")
        st.caption(f'{o["on_time"]}/{o["due"]} scadenze trascorse · novembre 2026')
    st.caption("Periodi distinti mostrati con finalità dimostrativa. Nessuna contaminazione dei registri importati.")
    st.markdown("[Bilanciamento](/balancing) · [Fatture e garanzie](/ledger)")


def _forecast():
    st.caption("Archivio storico JRC ENaGaD Italia 2015–2021 · nessuna previsione di oggi")
    if st.button("Esegui backtest storico",key="executive_run",type="primary",width="stretch"):
        try:
            with st.spinner("Confronto su date comuni…"):
                st.session_state[STUDY]=historical_study()
        except (OSError,ValueError):
            st.error("Archivio storico o campione non utilizzabile.")
    saved=st.session_state.get(STUDY)
    if not saved:
        st.info("Avvia il confronto tra benchmark settimanale e regressioni Ridge. Il risultato si basa esclusivamente sui dati inclusi.")
        return
    r=saved["result"]
    names={"weekly":"Naive settimanale","autoregressive":"Ridge autoregressivo","multivariate":"Ridge multivariato"}
    st.caption(f'{r["test_n"]} date comuni · riferimento {r["test_start"]} – {r["test_end"]} · D+1')
    kpi_grid([(names[m],r["scores"][m]["mae"],"GWh","MAE fuori campione",1,"") for m in MODELS])
    f=pd.DataFrame(r["records"]).rename(columns=names|{"actual":"Osservato"})
    st.line_chart(f,x="target",y=["Osservato",*names.values()],height=300,y_label="GWh/giorno gas")
    st.caption("Dati storici rivisti, ritardi ipotizzati, nessuna garanzia operativa ex ante. Non si sceglie automaticamente il modello.")
    with st.expander("Provenienza e metodo"):
        st.markdown(f"[Archivio JRC]({saved['url']})")
        st.text("SHA-256: "+saved["fingerprint"])
        st.caption("Ridge con regressori settoriali ritardati, nessun dato futuro osservato come feature. Scaling per finestra di training.")
    st.markdown("[Laboratorio previsionale](/market)")


def _pilot():
    st.markdown("**Disponibile nel prototipo**")
    st.markdown("Controlli di qualità e provenienza, benchmarking ACER, KPI, backtest e analisi documentale con riferimenti alle fonti.")
    st.markdown("**Per un pilot autorizzato**")
    st.dataframe([{"Priorità":"1 · Accesso","Verifica":"Dati e permessi, perimetro e sicurezza"},
                  {"Priorità":"2 · Validazione","Verifica":"Riconciliazione bilanci, rettifiche e scadenze su casi concordati"},
                  {"Priorità":"3 · Valore","Verifica":"Misurare accuratezza, copertura e tempo di revisione rispetto a una baseline"},
                  {"Priorità":"4 · Esercizio","Verifica":"Responsabilità, monitoraggio, backup e accettazione del team"}],
                 hide_index=True,width="stretch")
    st.caption("Obiettivi proposti, non SLA Snam né risparmi già misurati.")
    st.markdown("[Norme e documenti](/regulatory) · [Assistente AI](/operations) · [Checklist tecnica](https://github.com/Artisello/GasOps/blob/main/docs/PRODUCTION_READINESS.md)")


def panel():
    with st.container(key="executive_shell"):
        stage=st.radio("Percorso di presentazione",STAGES,horizontal=True,key="executive_stage")
        i=STAGES.index(stage)
        marks="".join('<span class="past"></span>' if k<=i else '<span></span>' for k in range(len(STAGES)))
        st.html(f'<div class="gas-exec-kicker">Executive demo · {i+1}/{len(STAGES)}</div>'
                f'<div class="gas-exec-heading" role="heading" aria-level="2">{escape(TITLES[i])}</div>'
                f'<div class="gas-exec-subtitle">{escape(DESCRIPTIONS[i])}</div>'
                f'<div class="gas-exec-step" aria-hidden="true">{marks}</div>')
        st.caption("Prototipo indipendente · sola lettura · percorso offline · 5 minuti")
        (_context,_operations,_forecast,_pilot)[i]()
        st.divider()
        a,b=st.columns(2)
        a.button("Indietro",on_click=_change,args=(-1,),disabled=i==0,key="executive_prev",width="stretch")
        b.button("Avanti",on_click=_change,args=(1,),disabled=i==len(STAGES)-1,type="primary",key="executive_next",width="stretch")
