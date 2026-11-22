"""Cross-infrastructure reconciliation under the existing daily control desk."""
import streamlit as st
from . import reconciliation as m
from .models import utc_now
from .settlement_desk import csv_text
from .visuals import kpi_grid,info

STATE="interface_reconciliation_v1"


def panel():
    st.subheader("Riconciliazione infrastrutture")
    st.caption("G+1 · allocazioni per utente del trasporto · HS1 e punto di entrata Piombino · MWh")
    now=utc_now()
    with st.expander("Importa estratti di allocazione",expanded=STATE not in st.session_state):
        st.warning("Solo estratti pubblici autorizzati o sintetici con ID fittizi. Non caricare dati riservati sul prototipo pubblico.")
        st.download_button("Scarica modello CSV per entrambi gli estratti",m.template(m.INTERFACE_FIELDS),
                           "igor-allocazioni-interfacce.csv","text/csv",key="interface_template")
        st.caption("Schema I.G.O.R., non formato nativo: una riga per utente, giorno gas e interfaccia; HS1 o PIOMBINO. Stessi ID di trasporto e perimetro; energia in MWh, punto decimale.")
        with st.form("interface_import"):
            a,b=st.columns(2)
            with a:
                left=st.file_uploader("SRG · allocazioni G+1",type="csv",key="interface_srg")
                st.caption("HS1: erogazione in rete positiva, iniezione negativa. Piombino: allocazione al punto di entrata.")
            with b:
                right=st.file_uploader("HS1 / Piombino · allocazioni G+1",type="csv",key="interface_operator")
                st.caption("HS1: iniezione in stoccaggio positiva, erogazione negativa. Piombino: quantità comunicata a SRG per lo stesso utente.")
            st.caption("gas_day_convention: CET_FIXED (UTC+01) o EUROPE_ROME (ora locale); match_batch: stesso codice solo per versioni dichiarate allineate. reference: riferimento fittizio distinto per fonte. Max 2 MiB e 10.000 righe per file.")
            submit=st.form_submit_button("Confronta estratti",type="primary")
        if submit:
            if left is None or right is None:
                st.warning("Carica entrambi gli estratti; non dedurre l’uno dall’altro.")
            else:
                try:
                    transport=m.parse_interface(left.getvalue(),now)
                    operator=m.parse_interface(right.getvalue(),now)
                    if not transport["rows"] and not operator["rows"]:
                        raise ValueError("Entrambi gli estratti sono vuoti.")
                except ValueError as error:
                    st.error(str(error)+" · Dossier precedente conservato.")
                else:
                    st.session_state[STATE]={"transport":transport,"operator":operator,"synthetic":False}
        a,b=st.columns(2)
        if a.button("Prova demo sintetica",key="interface_demo"):
            st.session_state[STATE]=m.interface_demo(now)
        if STATE in st.session_state and b.button("Rimuovi dossier",key="interface_clear"):
            st.session_state.pop(STATE,None)
            st.rerun()
    saved=st.session_state.get(STATE)
    if saved is None:
        st.caption("Nessun dossier: importa i due estratti oppure prova la demo.")
        _method()
        return
    st.caption("Demo sintetica · nessun dato operativo" if saved["synthetic"] else
               "Estratti dichiarati dall’utente · fonte non verificata indipendentemente · solo sessione")
    results=m.reconcile_interfaces(saved["transport"]["rows"],saved["operator"]["rows"])
    a,b=st.columns(2)
    with a:
        point=st.selectbox("Interfaccia",["Tutte","HS1","PIOMBINO"],key="interface_point",
                          format_func=lambda p:"Piombino" if p=="PIOMBINO" else p)
    with b:
        user=st.selectbox("Utente (ID fittizio)",["Tutti",*sorted({r["user"] for r in results})],key="interface_user")
    selected=[r for r in results if (point=="Tutte" or r["interface"]==point) and (user=="Tutti" or r["user"]==user)]
    score=m.interface_score(selected)
    kpi_grid([("Coppie quadrate",score["matched"],"",f'{score["compared"]}/{score["received_keys"]} confrontabili',0,""),
              ("Differenze",score["differences"],"","Oltre tolleranza",0,"rose" if score["differences"] else ""),
              ("Non confrontabili",score["unknown"],"","Assenti o disallineate",0,""),
              ("Scostamento assoluto",score["absolute_difference_mwh"],"MWh","Solo coppie confrontabili",3,"")])
    st.caption("Copertura sulle chiavi ricevute, non sul totale atteso del mercato. Non è un bilancio di sistema né un importo di settlement.")
    only=st.checkbox("Solo eccezioni",value=True,key="interface_only")
    visible=[r for r in selected if not only or r["status"]!="QUADRA"]
    if visible:
        st.dataframe([{"Giorno gas":r["gas_day"],"Utente":r["user"],"Interfaccia":r["interface"],
                       "Esito":r["status"],"SRG (MWh)":r["transport_mwh"],
                       "Gestore (MWh)":r["operator_mwh"],"Atteso lato SRG (MWh)":r["expected_transport_mwh"],
                       "Δ SRG − atteso (MWh)":r["delta_mwh"],"Nota":r["reason"],
                       "Rif. SRG":r["transport_reference"],"Rif. gestore":r["operator_reference"]} for r in visible],
                      hide_index=True,width="stretch")
    else:
        st.caption("Nessuna eccezione nel filtro." if selected else "Nessuna coppia ricevuta nel filtro.")
    if selected:
        st.download_button("Esporta confronto completo del perimetro",csv_text([
            {"provenance":"SYNTHETIC" if saved["synthetic"] else "DECLARED_CSV",
             "transport_sha":saved["transport"]["sha"],"operator_sha":saved["operator"]["sha"],
             "tolerance_mwh":m.ENERGY_TOL,**r} for r in selected]),
            "igor-riconciliazione-infrastrutture.csv","text/csv",key="interface_export")
    _method()


def _method():
    info("Metodo e fonti",m.INTERFACE_REFERENCES["HS1"],m.INTERFACE_REFERENCES["PIOMBINO"],
         "HS1: confronta il termine allocato (ultima rinomina confermata), invertendo il segno tra stoccaggio e trasporto. Non usare la variazione della giacenza, i consumi o il flusso fisico totale.",
         "Piombino: usa le quantità comunicate a SRG dopo la ripartizione per utente del trasporto e gli eventuali scostamenti allocati al netto dei margini TIB. Esclusi PSV, flusso totale misurato e impresa di rigassificazione. Non ricalcola le regole di allocazione.",
         "Confronta solo stesso intervallo UTC, utente e interfaccia con versioni dichiarate allineate. Tolleranza diagnostica 0,001 MWh; vigenza e validità da verificare. Nessun invio AI o persistenza del dossier.")
