"""Analytical reconstruction within the existing credit risk view."""
import json
import streamlit as st
from . import credit_snapshot as m
from .credit_risk import additional_guarantee_90
from .models import utc_now
from .data import ROME
from .visuals import kpi_grid
from .italiano import numero

STATE="credit_analytical_snapshot_v1"


def panel():
    st.subheader("Ricostruzione analitica EPSu / MEPSu")
    st.caption("Codice di Rete XCII · modello di studio su snapshot omogeneo")
    now=utc_now().astimezone(ROME).date()
    with st.expander("Importa snapshot analitico"):
        st.caption("Solo dati sintetici o aggregati autorizzati, senza identificativi reali. JSON normalizzato I.G.O.R., non estratto nativo Snam.")
        st.download_button("Esempio JSON sintetico",m.export(m.example()),"igor-credit-esempio.json","application/json",key="credit_snapshot_template")
        with st.form("credit_snapshot_form"):
            f=st.file_uploader("Snapshot JSON",type="json",key="credit_snapshot_upload")
            consent=st.checkbox("Confermo origine autorizzata, assenza di dati riservati e copertura dichiarata.")
            submit=st.form_submit_button("Valida e ricostruisci")
        if submit:
            if f is None or not consent:
                st.warning("Seleziona il file e conferma l’autorizzazione.")
            else:
                try:
                    st.session_state[STATE]=m.load(f.getvalue(),now)
                    st.success("Snapshot acquisito; provenienza e copertura dichiarate.")
                except ValueError as e:
                    st.error(str(e)+" · ultimo snapshot conservato.")
        if STATE in st.session_state and st.button("Rimuovi snapshot",key="credit_snapshot_clear"):
            st.session_state.pop(STATE,None)
            st.rerun()
    saved=st.session_state.get(STATE)
    if not saved:
        st.caption("Nessun dato importato. La simulazione manuale resta separata.")
        return
    p=saved["position"]
    st.caption("ID fittizio "+saved["user"]+" · snapshot "+saved["as_of"]+" · fonte non certificata")
    if saved["as_of"]!=now.isoformat():
        st.warning("Snapshot storico: non rappresenta l’esposizione corrente.")
    kpi_grid([("EPSu ricostruito",p["eps"],"€","Pfat + Pdet + Patt",2,""),
              ("MEPSu",p["meps"],"€","G riconosciuta − C",2,""),
              ("Utilizzo",p["ratio"],"%",p["status"],1,"rose" if p["status"]=="LIMITE" else ""),
              ("Margine residuo",p["headroom"],"€","MEPSu − EPSu",2,"")])
    if p["status"]!="OK":
        st.warning("Esito di studio: "+p["status"]+". Nessuna decisione ufficiale.")
    st.caption(f'Orizzonte {saved["horizon"]} giorni · Pr '+numero(saved["pr_eur_mwh"],3)+
               f' €/MWh · {saved["price_days"]} prezzi giornalieri · G aggiuntiva teorica a ≤90%: '+
               numero(additional_guarantee_90(p),2)+" €")
    st.dataframe([{"Componente":k,"Valore (€)":float(p[k])} for k in ("pfat","pdet","patt","g","c")],hide_index=True,width="stretch")
    with st.expander("Dettaglio Patt · quantità e PSV"):
        st.dataframe(saved["patt_rows"],hide_index=True,width="stretch")
        st.caption("PSV netto vendita positivo, acquisto negativo. Valori oltre orizzonte solo per transazioni già registrate; zero immissioni. Valorizzazione al prezzo stimato, aggregazione con segno; mapping e trattamento operativo da validare.")
    with st.expander("Partite contabili e provenienza"):
        st.dataframe(saved["obligations"],hide_index=True,width="stretch")
        st.text("SHA-256 · "+saved["sha256"])
        st.caption("Copertura, contabilizzazione, prezzi applicabili, validità delle garanzie e regolarità del semestre dichiarati dall’operatore. Il sistema non verifica l’autenticità o la completezza reale.")
    st.download_button("Esporta ricostruzione JSON",m.export(saved),"igor-credit-ricostruito.json","application/json",key="credit_snapshot_export")
