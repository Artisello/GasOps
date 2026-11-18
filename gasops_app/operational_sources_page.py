"""Optional panels; no background network work, no storage of uploaded files."""
from datetime import timedelta

import streamlit as st

from .data import ROME
from .italiano import numero
from .models import utc_now
from .operational_sources import (AGSI_SOURCE,GME_SOURCE,GME_TERMS,JARVIS_SOURCE,
                                  jarvis_template,load_agsi,parse_jarvis,load_alsi,load_iip,
                                  gie_key,attributed_csv,attributed_iip_json,GIE_CREDIT,GIE_LINKS,GIE_TERMS)
from .public_data import SourceUnavailable
from .session import database


def operational_context():
    with st.expander("Dati operativi e stoccaggi · facoltativo"):
        st.caption("Contesto separato dalle previsioni e dal settlement. Nessuna sostituzione automatica dei dati.")
        tabs=st.tabs(["Jarvis","AGSI+","ALSI","IIP"])
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
            _inventory_panel("AGSI+",load_agsi)
        with tabs[2]:
            _inventory_panel("ALSI",load_alsi)
        with tabs[3]:
            _iip_panel()


def _credit(platform):
    st.markdown("[Fonte: "+GIE_CREDIT[platform]+"]("+GIE_LINKS[platform]+") · [Condizioni d’uso]("+GIE_TERMS+")")


def _key(platform):
    _credit(platform)
    key=gie_key()
    if not key:
        st.info("Configura GASOPS_GIE_API_KEY nei Secrets di Streamlit o nell’ambiente locale. "
                "La stessa chiave copre le tre piattaforme se abilitata; GASOPS_AGSI_API_KEY resta compatibile.")
    return key


def _inventory_panel(platform,loader):
    key=_key(platform)
    if not key:
        return
    import pandas as pd
    scope=st.selectbox("Perimetro",["IT","EU"],format_func=lambda x:"Italia" if x=="IT" else "Unione europea",
                       key=platform+"_scope")
    state=platform+"_result"
    if st.button("Carica dati",key=platform+"_load"):
        st.session_state.pop(state,None)
        try:
            with st.spinner("Acquisizione "+GIE_CREDIT[platform]+"…"):
                st.session_state[state]=loader(database(),key,scope)
        except (SourceUnavailable,ValueError):
            st.warning("Fonte non disponibile o risposta non valida. Verifica la configurazione.")
    result=st.session_state.get(state)
    if result is None or result["scope"]!=scope:
        return
    frame=result["frame"]
    col="stock_twh" if platform=="AGSI+" else "sendout_gwh_d"
    valid=frame[frame[col].notna()]
    recent=(valid if not valid.empty else frame).iloc[-1]
    age=(utc_now().astimezone(ROME).date()-recent["gas_day"]).days
    st.caption(f"G {recent['gas_day']} · stato {recent['status']} · acquisito {result['acquired'].isoformat()}"+
               (" · cache" if result["cached"] else ""))
    if age>2 or result["failed"]:
        st.warning("Dato non recente o aggiornamento non riuscito: verificare la fonte.")
    if platform=="AGSI+" and frame["review"].any():
        st.warning("Alcuni valori di capacità/riempimento richiedono verifica.")
    def show(value,unit):
        return "—" if pd.isna(value) else numero(value,2)+" "+unit
    specs=([("Giacenza","stock_twh","TWh"),("Riempimento","fill_pct","%"),("Erogazione","withdrawal_gwh_d","GWh/d")]
           if platform=="AGSI+" else
           [("Inventario GNL","inventory_1000m3_lng","10³ m³ LNG"),
            ("Send-out","sendout_gwh_d","GWh/d"),
            ("Send-out / riferimento","sendout_reference_pct","%")])
    for box,(label,field,unit) in zip(st.columns(3),specs,strict=True):
        box.metric(label,show(recent[field],unit))
    chart=frame.set_index("gas_day")[[col]]
    chart=chart.reindex(pd.date_range(chart.index.min(),chart.index.max(),freq="D").date)
    chart_title=("Giacenza (TWh)" if platform=="AGSI+" else "Send-out (GWh/d)")+" · "+GIE_CREDIT[platform]
    st.line_chart(chart.rename(columns={col:chart_title}))
    _credit(platform)
    with st.expander("Dettaglio giornaliero"):
        st.dataframe(frame.assign(source=result["source"]),hide_index=True,width="stretch")
        st.download_button("Esporta CSV con fonte",attributed_csv(result),
                           "gasops-gie-"+platform.lower().replace("+","")+".csv","text/csv",key=platform+"_csv")
    st.caption("C = confermato, E = stimato, N = assente, se indicato. Non equivale a disponibilità commerciale. "
               "Per ALSI il rapporto send-out/riferimento usa la capacità dichiarata, non quella effettivamente disponibile.")


def _iip_panel():
    key=_key("IIP")
    st.caption("Messaggi attivi richiesti per oggi e i prossimi sette giorni, prima pagina (max 100). "
               "Non è una mappa completa delle indisponibilità né una stima di capacità persa.")
    if not key:
        return
    if st.button("Carica messaggi UMM",key="iip_load"):
        st.session_state.pop("iip_result",None)
        try:
            with st.spinner("Acquisizione GIE IIP…"):
                st.session_state["iip_result"]=load_iip(database(),key)
        except (SourceUnavailable,ValueError):
            st.warning("GIE IIP non disponibile oppure risposta non valida.")
    result=st.session_state.get("iip_result")
    if result is None:
        return
    st.caption("Acquisito "+result["acquired"].isoformat()+(" · cache" if result["cached"] else ""))
    if result["failed"] or utc_now()-result["acquired"]>timedelta(hours=2):
        st.warning("Messaggi non aggiornati: verifica il portale IIP.")
    if result["partial"]:
        st.warning("Risultati parziali: prima pagina di "+str(result["pages"])+". Consulta il portale per l’elenco completo.")
    st.metric("Messaggi restituiti",len(result["messages"]))
    _credit("IIP")
    if not result["messages"]:
        st.caption("Nessun messaggio restituito per la richiesta; non dimostra assenza di indisponibilità.")
    else:
        with st.expander("Messaggi originali GIE IIP"):
            st.json(result["messages"],expanded=False)
    st.download_button("Esporta JSON con fonte",attributed_iip_json(result),
                       "gasops-gie-iip.json","application/json",key="iip_json")


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
