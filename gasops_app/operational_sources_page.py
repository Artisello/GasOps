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


def configured_key():
    # Streamlit loads its secrets lazily; explicitly access them before falling
    # back to the environment. Never display the key or prompt visitors for it.
    try:
        return gie_key(st.secrets)
    except (FileNotFoundError,KeyError):
        return gie_key()


def operational_context():
    """Standalone view: no demand source filters or forecast computation."""
    st.title("Security of supply")
    st.caption("Stoccaggi, rigassificazione e messaggi di mercato · dati pubblici separati dalle simulazioni.")
    key=configured_key()
    if key:
        st.caption("Chiave GIE configurata · la connessione viene verificata al caricamento.")
    else:
        st.warning("Chiave GIE non configurata. Inserisci GASOPS_GIE_API_KEY nei Secrets di Streamlit e riavvia l’app.")
    selected=st.radio("Fonte operativa",["AGSI+","ALSI","IIP","Jarvis"],horizontal=True,key="operational_platform")
    if selected=="AGSI+":
        _inventory_panel(selected,load_agsi,key)
    elif selected=="ALSI":
        _inventory_panel(selected,load_alsi,key)
    elif selected=="IIP":
        _iip_panel(key)
    else:
        _jarvis_panel()


def _jarvis_panel():
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


def _credit(platform):
    st.markdown("[Fonte: "+GIE_CREDIT[platform]+"]("+GIE_LINKS[platform]+") · [Condizioni d’uso]("+GIE_TERMS+")")


def _load_once(state,button,loader,key,*args):
    """One automatic load for each selection in this session. Explicit retry only."""
    clicked=st.button(button,key=state+"_load")
    previous=st.session_state.get(state)
    if previous is None or clicked:
        now=utc_now()
        if previous is not None and now-previous["attempted"]<timedelta(seconds=60):
            st.info("Attendi 60 secondi tra richieste manuali alla stessa fonte.")
        else:
            try:
                with st.spinner("Verifica connessione e caricamento dati…"):
                    result=loader(database(),key,*args,refresh=clicked)
                st.session_state[state]={"attempted":now,"result":result}
            except (SourceUnavailable,ValueError) as exc:
                # SourceUnavailable and SourceSchemaError expose controlled
                # reasons; other ValueErrors may include raw publisher values.
                reason=str(exc) if isinstance(exc,SourceUnavailable) else "Parametri o formato non validi."
                saved=previous.get("result") if previous else None
                st.session_state[state]={"attempted":now,"error":reason,"result":saved}
    snapshot=st.session_state.get(state,{})
    if snapshot.get("error"):
        st.error(snapshot["error"])
        st.caption("Verifica il portale ufficiale e l’abilitazione della chiave. Nessun dato di esempio sostitutivo.")
    return snapshot.get("result")


def _inventory_panel(platform,loader,key):
    import pandas as pd
    _credit(platform)
    scope=st.selectbox("Perimetro",["IT","EU"],format_func=lambda x:"Italia" if x=="IT" else "Unione europea",
                       key=platform+"_scope")
    if not key:
        st.info("Per attivare questa fonte serve una chiave GIE gratuita con accesso abilitato.")
        return
    result=_load_once(platform+"_"+scope,"Aggiorna "+platform,loader,key,scope)
    if result is None:
        return
    frame=result["frame"]
    col="stock_twh" if platform=="AGSI+" else "sendout_gwh_d"
    if platform=="ALSI" and not frame[col].notna().any():
        col="inventory_1000m3_lng" if frame["inventory_1000m3_lng"].notna().any() else "inventory_gwh"
    valid=frame[frame[col].notna()]
    recent=valid.iloc[-1]
    age=(utc_now().astimezone(ROME).date()-recent["gas_day"]).days
    state=st.session_state.get(platform+"_"+scope,{})
    if age>2 or result["failed"] or state.get("error"):
        st.warning("Dato non recente o aggiornamento non riuscito: verificare la fonte.")
    else:
        st.success("Dati GIE acquisiti"+(" dalla cache verificata." if result["cached"] else "."))
    st.caption(f"G {recent['gas_day']} · stato {recent['status']} · acquisito {result['acquired'].isoformat()}"+
               (" · cache" if result["cached"] else ""))
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
    labels={"stock_twh":"Giacenza (TWh)","sendout_gwh_d":"Send-out (GWh/d)",
            "inventory_1000m3_lng":"Inventario (10³ m³ LNG)","inventory_gwh":"Inventario (GWh)"}
    chart=frame.set_index("gas_day")[[col]]
    chart=chart.reindex(pd.date_range(chart.index.min(),chart.index.max(),freq="D").date)
    st.line_chart(chart.rename(columns={col:labels[col]+" · "+GIE_CREDIT[platform]}))
    _credit(platform)
    with st.expander("Dettaglio giornaliero"):
        st.dataframe(frame.assign(source=result["source"]),hide_index=True,width="stretch")
        st.download_button("Esporta CSV con fonte",attributed_csv(result),
                           "gasops-gie-"+platform.lower().replace("+","")+".csv","text/csv",key=platform+"_csv")
    st.caption("C = confermato, E = stimato, N = assente. Non equivale a disponibilità commerciale. "
               "Per ALSI il rapporto send-out/riferimento usa la capacità dichiarata.")


def _iip_panel(key):
    _credit("IIP")
    st.caption("Messaggi attivi richiesti per oggi e i prossimi sette giorni, prima pagina (max 100). "
               "Non è una mappa completa delle indisponibilità né una stima di capacità persa.")
    if not key:
        return
    result=_load_once("gie_iip","Aggiorna messaggi UMM",load_iip,key)
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
