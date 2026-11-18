"""Optional panels; no background network work, no storage of uploaded files."""
import os
from datetime import timedelta

import streamlit as st

from .data import ROME
from .italiano import numero
from .models import utc_now
from .operational_sources import (AGSI_SOURCE,GME_SOURCE,GME_TERMS,JARVIS_SOURCE,
                                  jarvis_template,load_agsi,parse_jarvis)
from .public_data import SourceUnavailable
from .session import database


def operational_context():
    with st.expander("Dati operativi e stoccaggi · facoltativo"):
        st.caption("Contesto separato dalle previsioni e dal settlement. Nessuna sostituzione automatica dei dati.")
        tabs=st.tabs(["Jarvis","AGSI+"])
        with tabs[0]:
            st.markdown("[Apri i dati pubblici Snam Jarvis]("+JARVIS_SOURCE+")")
            st.write("Importa una selezione delle stime pubbliche del giorno-gas G: prelievo atteso, SAS e linepack atteso.")
            st.caption("Il modello CSV GasOps non è un export nativo Jarvis. Riporta manualmente i valori pubblici "
                       "autorizzati, convertiti in GWh, con data di pubblicazione ISO 8601 e offset. "
                       "Non caricare report riservati o bilanci di singoli utenti. Non vengono inviati a LLM o salvati.")
            st.download_button("Scarica modello CSV",jarvis_template(),"gasops-jarvis-template.csv","text/csv")
            file=st.file_uploader("CSV normalizzato",type=["csv"],key="jarvis_public_extract")
            if file is not None:
                try:
                    result=parse_jarvis(file.getvalue())
                    latest=result["latest"]
                    row=latest.iloc[-1]
                    st.caption(f"Fonte dichiarata dall’operatore: Snam Jarvis · G {row['gas_day']} · "
                               f"pubblicazione {row['published_at'].isoformat()} · non verificata indipendentemente")
                    a,b,c=st.columns(3)
                    def display(value):
                        import pandas as pd
                        return "—" if pd.isna(value) else numero(value)+" GWh"
                    a.metric("Prelievo atteso",display(row["expected_withdrawal_gwh"]))
                    b.metric("SAS pubblicato",display(row["sas_gwh"]))
                    c.metric("Linepack atteso",display(row["expected_linepack_gwh"]))
                    st.dataframe(latest,hide_index=True,width="stretch")
                    with st.expander("Versioni e provenienza"):
                        st.dataframe(result["versions"],hide_index=True,width="stretch")
                        st.text("SHA-256 · "+result["sha256"])
                    st.caption("Le stime restano stime. Il SAS viene riportato, non derivato dalla differenza offerta-domanda.")
                except ValueError as error:
                    st.warning(str(error))
        with tabs[1]:
            st.markdown("[GIE AGSI+ — stoccaggi]("+AGSI_SOURCE+")")
            st.caption("API gratuita con registrazione. Configura GASOPS_AGSI_API_KEY nell’ambiente locale o nei "
                       "segreti del deployment; non inserire chiavi nel codice o in chat.")
            key=os.environ.get("GASOPS_AGSI_API_KEY","").strip()
            if not key:
                st.info("API non configurata. I dati pubblici sono consultabili sul portale; le altre funzioni restano disponibili.")
                return
            scope=st.selectbox("Perimetro",["IT","EU"],format_func=lambda x:"Italia" if x=="IT" else "Unione europea",
                               key="agsi_scope")
            if st.button("Carica stoccaggi",key="agsi_load"):
                st.session_state.pop("agsi_result",None)
                try:
                    with st.spinner("Acquisizione dati GIE AGSI+…"):
                        st.session_state["agsi_result"]=load_agsi(database(),key,scope)
                except (SourceUnavailable,ValueError):
                    st.warning("GIE AGSI+ non disponibile oppure risposta non valida. Verifica la configurazione.")
            result=st.session_state.get("agsi_result")
            if result is None or result["scope"]!=scope:
                return
            frame=result["frame"]
            recent=frame[frame["stock_twh"].notna()].iloc[-1]
            age=(utc_now().astimezone(ROME).date()-recent["gas_day"]).days
            st.caption(f"GIE AGSI+ · G {recent['gas_day']} · stato {recent['status']} · "
                       f"acquisito {result['acquired'].isoformat()}"+(" · cache" if result["cached"] else ""))
            if age>2 or result["failed"]:
                st.warning("Dato non recente o aggiornamento non riuscito: non utilizzare come informazione corrente.")
            if frame["review"].any():
                st.warning("Alcuni valori di capacità/riempimento richiedono verifica.")
            import pandas as pd
            a,b,c=st.columns(3)
            def show(value,unit):
                return "—" if pd.isna(value) else numero(value,2)+" "+unit
            a.metric("Giacenza",show(recent["stock_twh"],"TWh"))
            b.metric("Riempimento",show(recent["fill_pct"],"%"))
            c.metric("Erogazione",show(recent["withdrawal_gwh_d"],"GWh/d"))
            chart=frame.set_index("gas_day")[["stock_twh"]]
            chart=chart.reindex(pd.date_range(chart.index.min(),chart.index.max(),freq="D").date)
            st.line_chart(chart.rename(columns={"stock_twh":"Giacenza (TWh)"}))
            with st.expander("Dettaglio giornaliero"):
                st.dataframe(frame,hide_index=True,width="stretch")
            st.caption("Fonte: GIE AGSI+. C = confermato, E = stimato, N = assente. "
                       "Giacenza a fine giorno-gas; erogazione e iniezione durante il giorno-gas. "
                       "Non equivale alla disponibilità fisica o commerciale per il giorno successivo.")


def gme_reference():
    with st.expander("GME · fonte dei parametri di mercato"):
        st.markdown("[Esiti funzionali ai prezzi di sbilanciamento]("+GME_SOURCE+") · "
                    "[Condizioni di utilizzo]("+GME_TERMS+")")
        st.caption("Il servizio API richiede abilitazione personale e limita l’uso dei dati. "
                   "Nessuna estrazione, importazione o analisi automatizzata GME è attiva. "
                   "Il calcolatore sottostante usa valori ipotetici, non prezzi GME effettivi.")
        st.write("Campi da verificare presso la fonte: prezzo medio ponderato, massimo acquisto SRG, "
                 "minimo vendita SRG. Il volume MGAS pubblicato non va equiparato automaticamente "
                 "al volume STSP title richiesto per la soglia dei 2.000 MWh.")
