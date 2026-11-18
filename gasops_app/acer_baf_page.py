"""Cross-year ACER comparison with explicit source coverage."""
import pandas as pd
import streamlit as st

from .acer_baf_2026 import all_baf_rows, zone_changes, SELECTED, PDF_SHA256
from .acer_market import REPORT_2025, REPORT_2026, BALANCING

LABELS={"imbalance_share":"Volumi di sbilanciamento / mercato fisico",
        "net_adjusted_neutrality":"Neutralità netta rettificata / volume",
        "tso_buy_share":"Quota acquisti TSO",
        "tso_action_days_share":"Giorni con azioni di bilanciamento TSO",
        "tso_action_volume_share":"Volume azioni TSO / mercato fisico"}


def panel():
    st.caption("Report ACER ottobre 2026 · anni gas, non anni civili · dati pubblicati arrotondati.")
    try:
        rows=all_baf_rows()
    except (OSError,ValueError):
        st.error("Archivio benchmark ACER non valido.")
        return
    it={r["metric"]:r["value"] for r in rows if r["zone"]=="IT" and r["gas_year"]=="2024/2025"}
    old={r["metric"]:r["value"] for r in rows if r["zone"]=="IT" and r["gas_year"]=="2023/2024"}
    c=st.columns(3)
    for col,metric,fmt,label in zip(c,("imbalance_share","net_adjusted_neutrality","tso_buy_share"),
         (".1f",".2f",".0f"),("Sbilanciamenti / volume","Neutralità rettificata","Acquisti TSO"),strict=True):
        unit=" €/MWh" if metric=="net_adjusted_neutrality" else "%"
        d=it[metric]-old[metric]
        delta=f"{d:+{fmt}}"+(" €/MWh" if unit==" €/MWh" else " pp")
        col.metric("Italia · "+label,f"{it[metric]:{fmt}}"+unit,delta,delta_color="off")
    st.caption("2024/2025 rispetto a 2023/2024. Sbilanciamenti e neutralità: precedente edizione non verificata visivamente. Quota acquisti: entrambi gli anni esplicitamente riportati a p. 16 del PDF 2026.")
    mode=st.radio("Vista",["Confronto zone","Trend europeo"],horizontal=True,key="acer_baf_view")
    frame=pd.DataFrame(rows)
    if mode=="Confronto zone":
        metric=st.selectbox("Indicatore",["imbalance_share","net_adjusted_neutrality","tso_buy_share"],
                            format_func=LABELS.__getitem__,key="acer_baf_metric_2026")
        compare=pd.DataFrame(zone_changes(rows,metric))
        for k in ("2023/2024","2024/2025","delta"):
            compare[k]=pd.to_numeric(compare[k],errors="coerce")
        compare=compare.sort_values("2024/2025",ascending=False,na_position="last")
        unit=compare.unit.iloc[0]
        st.bar_chart(compare,x="zone",y=["2023/2024","2024/2025"],horizontal=True,stack=False,y_label=unit)
        st.caption("Unità della variazione: punti percentuali per quote; €/MWh per neutralità. Zona assente in un'edizione = non disponibile, non zero.")
        st.dataframe(compare,hide_index=True,width="stretch")
        st.caption("Quote acquisti: sole zone con valori numerici espliciti a p. 16; non tutte le zone del grafico. La quota vendite è il complemento al 100%.")
        visible=frame[(frame.zone!=SELECTED)&(frame.metric==metric)]
    else:
        metric=st.selectbox("Indicatore",["tso_action_days_share","tso_action_volume_share","imbalance_share"],
                            format_func=LABELS.__getitem__,key="acer_baf_eu_metric")
        visible=frame[(frame.zone==SELECTED)&(frame.metric==metric)].sort_values("gas_year")
        chart=visible.assign(value=visible.value.astype(float))
        st.line_chart(chart,x="gas_year",y="value",y_label="%")
        st.caption("Zone selezionate comparabili nel report 2026, non intera UE. Austria, Bulgaria, Germania, Finlandia, Francia, IGB e Portogallo escluse per dati non comparabili lungo il periodo.")
        st.dataframe(chart[["gas_year","value","unit","page"]],hide_index=True,width="stretch")
    st.caption("La neutralità positiva indica un surplus da attribuire agli utenti; quella negativa un costo da recuperare. Non profitto TSO. La struttura regolatoria, la liquidità, la topologia e le risorse flessibili condizionano i confronti.")
    with st.expander("Fonti, dati e metodologia"):
        st.markdown(f"[Report 2026, pp. 9–11, 15–16, 19]({REPORT_2026}) · [Report 2025, pp. 16 e 19]({REPORT_2025}) · [Dashboard ACER]({BALANCING})")
        st.caption("83 osservazioni trascritte dalle etichette e dal testo del PDF 2026 fornito. Zero è arrotondato, non assenza. Il grafico scatter di p. 13 non riporta valori puntuali leggibili; nessuna stima. Conteggi delle categorie p. 16 incoerenti (22 dichiarate, 8+8+7=23), non importati.")
        st.text("SHA-256 PDF 2026: "+PDF_SHA256)
        st.download_button("Scarica dati selezionati con fonte",visible.to_csv(index=False),"igor-acer-baf-selection.csv","text/csv",key="acer_baf_2026_selection")
        st.download_button("Scarica intero archivio BAF",frame.to_csv(index=False),"igor-acer-baf-all.csv","text/csv",key="acer_baf_2026_all")
