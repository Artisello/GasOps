"""Monthly market operations controls embedded in the KPI overview."""
import streamlit as st
from . import market_efficiency as m
from .bso_kpis import closed_gas_day
from .visuals import kpi_grid,info
from .italiano import numero

STATE="market_efficiency_v1"


def panel(now,year,month):
    st.subheader("Market Operations · efficienza economica")
    st.caption("RdB · azioni di mercato · stesso perimetro e giorni gas conclusi")
    cutoff=closed_gas_day(now)
    with st.expander("Fonti e importazione azioni"):
        st.markdown("[GME · parametri prezzi di sbilanciamento]("+m.SOURCE+") · [ACER · benchmark bilanciamento]("+m.ACER+")")
        st.caption("Schema normalizzato I.G.O.R., non export nativo. Una riga per giorno/perimetro title, locational o storage; acquisti/vendite dal punto di vista RdB. Quantità MWh positive, controvalori EUR senza IVA né fee, con segno del prezzo. Complete = tutte le azioni del giorno nel perimetro, anche se zero. Partial = incompleto. Riferimento title facoltativo, coerente con giorno e prodotto.")
        st.download_button("Modello CSV",m.template(),"igor-market-actions.csv","text/csv",key="market_eff_template")
        with st.form("market_eff_upload"):
            f=st.file_uploader("Estratto giornaliero",type="csv",key="market_eff_file")
            consent=st.checkbox("Confermo fonte autorizzata, assenza di dati riservati e copertura dichiarata.")
            submit=st.form_submit_button("Importa e valida")
        if submit:
            if f is None or not consent:
                st.warning("Seleziona il file e conferma l’autorizzazione.")
            else:
                try:
                    st.session_state[STATE]=m.parse(f.getvalue(),cutoff)
                    st.success("Estratto acquisito; provenienza dichiarata.")
                except ValueError as e:
                    st.error(str(e)+" · ultimo estratto valido conservato.")
        if STATE in st.session_state and st.button("Rimuovi estratto",key="market_eff_clear"):
            st.session_state.pop(STATE,None)
            st.rerun()
    saved=st.session_state.get(STATE)
    if saved is None:
        st.caption("Importa volumi e controvalori delle azioni del RdB per misurare l’efficienza. Nessun dato effettivo acquisito.")
        return
    scopes=sorted({r.scope for r in saved["rows"] if (r.day.year,r.day.month)==(year,month)})
    if not scopes:
        st.caption("Nessun estratto nel mese selezionato.")
        return
    scope=st.selectbox("Perimetro azioni",scopes,format_func=m.SCOPES.__getitem__,key="market_eff_scope")
    s,rows=m.evaluate(saved["rows"],year,month,scope,cutoff)
    st.caption(f'{year}-{month:02d} · {s["complete_days"]}/{s["expected_days"]} giorni completi dichiarati · fonte importata non verificata')
    if not s["complete_period"]:
        st.warning(f'Copertura parziale: {s["partial_days"]} giorni incompleti, {s["missing_days"]} assenti. Totali sui soli giorni completi.')
    kpi_grid([("Volume azioni",s["gross_mwh"],"MWh","Acquisti + vendite",1,""),
              ("Costo netto azioni",s["net_cost_eur"],"€","Acquisti − vendite, non neutralità",2,""),
              ("Giorni con azioni",s["action_days"],"",f'Su {s["complete_days"]} giorni completi',0,"")])
    kpi_grid([("Prezzo medio acquisto",s["buy_vwap"],"€/MWh","Ponderato per volume",3,""),
              ("Prezzo medio vendita",s["sell_vwap"],"€/MWh","Ponderato per volume",3,""),
              ("Differenziale prezzi",s["spread"],"€/MWh","Acquisto − vendita; mix di giorni",3,"")])
    if scope=="title":
        st.caption(f'Benchmark: {s["comparable_days"]}/{s["action_days"]} giornate con azioni confrontabili.')
        kpi_grid([("Differenza vs riferimento",s["differential_eur"],"€","Solo giorni confrontabili; non risparmio realizzabile",2,""),
                  ("Differenza per MWh",s["differential_eur_mwh"],"€/MWh","Per volume lordo confrontabile",3,"")])
    if s["complete_days"]:
        import pandas as pd
        frame=pd.DataFrame(rows)
        for key in ("buy_mwh","sell_mwh"):
            frame[key]=[float(r[key]) if r["coverage"]=="complete" and r[key] is not None else None for r in rows]
        st.bar_chart(frame,x="gas_day",y=["buy_mwh","sell_mwh"],stack=False,y_label="MWh")
    with st.expander("Dettaglio e provenienza"):
        st.dataframe(rows,hide_index=True,width="stretch")
        st.caption("SHA-256 · "+saved["sha256"])
        st.download_button("Esporta controllo CSV",m.export(rows,saved["sha256"]),"igor-market-efficiency.csv","text/csv",key="market_eff_export")
    info("Metodo","Il differenziale rispetto al riferimento title è costo acquisti − ricavi vendite − (volume acquisti − volume vendite) × prezzo di riferimento dello stesso giorno. Il riferimento non è un prezzo marginale né un’alternativa eseguibile. Confronto solo su giorni completi e con azioni.",
         "Nessuna inferenza di neutralità, costo totale di bilanciamento, P2 o P3 regolatorio. Locational e storage restano separati. Nessun invio automatico, nessun dato riservato o AI.")
