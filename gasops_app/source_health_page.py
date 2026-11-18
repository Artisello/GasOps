"""Compact quality overview of loaded data, no new API calls."""
import csv,io
import streamlit as st
from .models import utc_now
from .source_health import session_health,compare_srg
from .visuals import kpi_grid,info

def _csv(rows):
    f=io.StringIO();w=csv.DictWriter(f,fieldnames=list(rows[0]),lineterminator="\n")
    w.writeheader();w.writerows(rows);return f.getvalue()

def panel():
    now=utc_now()
    st.subheader("Qualità e affidabilità dei dati")
    st.caption("Controllo della sessione · distinto dal report del monitor automatico")
    rows=session_health(st.session_state,now)
    good=sum(r["status"]=="Copertura verificata" for r in rows)
    absent=sum(r["status"].startswith("Non disponibile") or r["status"]=="Disattivato" for r in rows)
    review=len(rows)-good-absent
    kpi_grid([("Copertura verificata",good,"","Serie / misure, non provider",0,""),
              ("Da verificare",review,"","Cache, lacune, metadati",0,""),
              ("Non disponibili",absent,"","Incluse misure disattivate",0,"")])
    st.dataframe([{"Serie":r["source"],"Perimetro":r["scope"],"Tipo":r["kind"],"Stato":r["status"],
                   "Ultimo periodo":r["latest"],"Copertura":f'{r["valid"]}/{r["expected"]}' if r["expected"] else "—",
                   "Acquisito":r["acquired"],"Ultimo tentativo":r["attempt"]} for r in rows],hide_index=True,width="stretch")
    st.download_button("Esporta controllo qualità",_csv(rows),"igor-qualita-fonti.csv","text/csv",key="source_health_export")
    with st.expander("Coerenza tra acquisizioni · ENTSOG"):
        st.caption("Stesso aggregato termoelettrico SRG, stesso giorno gas: serie mercato vs contesto Terna. Non confronto gas/elettricità e non fonte indipendente.")
        try:paired=compare_srg(st.session_state,now)
        except (ValueError,KeyError,TypeError,AttributeError,ArithmeticError):paired=[]
        if paired:
            bad=sum(r["status"]=="Discordante" for r in paired)
            st.caption(f"{len(paired)} giorni confrontabili · {bad} discordanti")
            if bad:st.warning("Verifica revisioni, date di acquisizione e metadati. Nessuna correzione automatica.")
            if any(r["review"] for r in paired):st.warning("Almeno una fonte usa cache dopo errore o segnala metadati da verificare.")
            st.dataframe(paired,hide_index=True,width="stretch")
            st.download_button("Esporta confronti",_csv(paired),"igor-entsog-coerenza.csv","text/csv",key="source_health_pairs")
        else:st.caption("Nessuna coppia confrontabile. Carica ENTSOG e il contesto gas di Terna dalle viste esistenti.")
    info("Metodo e soglie","Finestre diagnostiche: 14 giorni per le serie giornaliere, 6 mesi per le mensili; ACER ultime 14 righe ricevute. Soglie indicano una revisione, non SLA di pubblicazione. Le previsioni meteo non sono osservazioni.",
         "Stato di acquisizione, periodo del dato, copertura e provenienza sono distinti. Copertura verificata si riferisce soltanto alla finestra e ai controlli applicati, non autenticità o certificazione.")
