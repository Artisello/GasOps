"""Optional panels; no background network work, no storage of uploaded files."""
from datetime import timedelta
import json

import streamlit as st

from .data import ROME
from .italiano import numero, data_it
from .models import utc_now
from .operational_sources import (AGSI_SOURCE,GME_SOURCE,GME_TERMS,JARVIS_SOURCE,
                                  jarvis_template,load_agsi,parse_jarvis,load_alsi,load_iip,
                                  gie_key,attributed_csv,attributed_iip_json,GIE_CREDIT,GIE_LINKS,GIE_TERMS)
from .public_data import SourceUnavailable
from .session import database
from .visuals import info, local_time
from .iip_view import MISSING, coverage, display_row, export_rows, filter_messages, options, project_messages


def configured_key():
    # Streamlit loads its secrets lazily; explicitly access them before falling
    # back to the environment. Never display the key or prompt visitors for it.
    try:
        return gie_key(st.secrets)
    except (FileNotFoundError,KeyError):
        return gie_key()


def operational_context():
    """Standalone view: no demand source filters or forecast computation."""
    st.title("Stoccaggi e forniture")
    key=configured_key()
    if not key:
        st.info("Fonti GIE non configurate. Jarvis resta disponibile; consulta la configurazione qui sotto.")
    with st.popover("Accesso API",icon=":material/info:"):
        st.caption("Chiave GIE configurata; verifica al caricamento." if key else "Imposta GASOPS_GIE_API_KEY nei Secrets di Streamlit e riavvia l’app.")
    selected=st.radio("Fonte operativa",["AGSI+","ALSI","IIP","Jarvis"],horizontal=True,key="operational_platform",
                      format_func={"AGSI+":"AGSI+ · Stoccaggi","ALSI":"ALSI · GNL","IIP":"IIP · Indisponibilità","Jarvis":"Jarvis · Rete"}.__getitem__)
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
    st.caption("Importazione manuale · solo dati pubblici, non riservati.")
    info("Info importazione","Prelievo atteso, SAS e linepack atteso. Il modello CSV GasOps non è un export nativo Jarvis.","Riporta i valori pubblici autorizzati in GWh, con pubblicazione ISO 8601 e offset. Non caricare report riservati o bilanci di singoli utenti. I file non vengono inviati a LLM o salvati.")
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
            info("Info SAS","Stime dichiarate dall’operatore. Il SAS viene riportato, non derivato dalla differenza offerta-domanda.")
        except ValueError as error:
            st.warning(str(error))


def _credit(platform):
    st.markdown("[Fonte: "+GIE_CREDIT[platform]+"]("+GIE_LINKS[platform]+") · [Condizioni d’uso]("+GIE_TERMS+")")


def _load_once(state,button,loader,key,*args,primary=False):
    """One automatic load for each selection in this session. Explicit retry only."""
    clicked=st.button(button,key=state+"_load",type="primary" if primary else "secondary",
                      icon=":material/refresh:")
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
    st.subheader("Stoccaggi di gas" if platform=="AGSI+" else "Rigassificazione GNL")
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
    status={"C":"Confermato","E":"Stimato","N":"Assente"}.get(recent["status"],recent["status"])
    st.caption(f"Giorno gas: {data_it(recent['gas_day'])} · {status} · acquisizione {local_time(result['acquired'])}"+
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
    available=[field for field in labels if field in frame and frame[field].notna().any()]
    if platform=="AGSI+":
        labels.update({"fill_pct":"Riempimento (%)","withdrawal_gwh_d":"Erogazione (GWh/d)","injection_gwh_d":"Iniezione (GWh/d)"})
        available=[field for field in labels if field in frame and frame[field].notna().any()]
    col=st.selectbox("Indicatore del grafico",available,index=available.index(col),format_func=labels.__getitem__,key=platform+"_"+scope+"_chart")
    chart=frame.set_index("gas_day")[[col]]
    chart=chart.reindex(pd.date_range(chart.index.min(),chart.index.max(),freq="D").date)
    st.line_chart(chart.rename(columns={col:labels[col]+" · "+GIE_CREDIT[platform]}))
    with st.expander("Dettaglio giornaliero"):
        headers={"gas_day":"Giorno gas","status":"Stato","stock_twh":"Giacenza (TWh)","capacity_twh":"Capacità (TWh)",
                 "fill_pct":"Riempimento (%)","withdrawal_gwh_d":"Erogazione (GWh/d)","injection_gwh_d":"Iniezione (GWh/d)",
                 "inventory_1000m3_lng":"Inventario (10³ m³ LNG)","inventory_gwh":"Inventario (GWh)",
                 "dtmi_1000m3_lng":"DTMI (10³ m³ LNG)","sendout_gwh_d":"Send-out (GWh/d)",
                 "dtrs_gwh_d":"DTRS (GWh/d)","sendout_reference_pct":"Send-out / riferimento (%)","review":"Da verificare","source":"Fonte"}
        st.dataframe(frame.assign(source=result["source"]).rename(columns=headers),hide_index=True,width="stretch")
        st.download_button("Esporta CSV con fonte",attributed_csv(result),
                           "gasops-gie-"+platform.lower().replace("+","")+".csv","text/csv",key=platform+"_csv")
    info("Info indicatori","C = confermato, E = stimato, N = assente. Non equivale a disponibilità commerciale.","Per ALSI il rapporto send-out/riferimento usa la capacità dichiarata.")


def _iip_panel(key):
    st.subheader("Messaggi urgenti di mercato (UMM)")
    st.caption("Messaggi UMM · non misura della capacità persa.")
    info("Info UMM","Informazioni e indisponibilità pubblicate dagli operatori. Il conteggio non indica eventi unici o capacità persa aggregata.")
    _credit("IIP")
    if not key:
        st.info("Per consultare i messaggi serve una chiave GIE abilitata.")
        return
    actions=st.columns([1,1,2],vertical_alignment="bottom")
    with actions[0]:
        result=_load_once("gie_iip","Aggiorna UMM",load_iip,key,primary=True)
    if result is None:
        st.caption("Consulta il portale GIE IIP in caso di errore.")
        return
    with actions[1]:
        st.download_button("Esporta JSON",attributed_iip_json(result),
                           "gasops-gie-iip.json","application/json",key="iip_json",icon=":material/download:")
    total=result.get("reported_total")
    state=coverage(result)
    period=(result["request_from"]+" – "+result["request_to"]
            if result.get("request_from") and result.get("request_to") else "Non indicato")
    with actions[2]:
        if result["cached"]:
            st.caption("Da cache")
    if result["failed"] or utc_now()-result["acquired"]>timedelta(hours=2) or st.session_state.get("gie_iip",{}).get("error"):
        st.warning("Aggiornamento non riuscito o dati non recenti. Consulta il portale IIP.")
    if state=="Parziale":
        st.warning(f"Prima pagina di {result['pages']}. Non tutti i risultati sono stati acquisiti.")
    elif state=="Non verificata":
        st.warning("Copertura della richiesta non verificata. Consulta il portale per l’elenco completo.")
    cards=st.columns(4)
    for col,label,value,detail in zip(cards,
            ("Messaggi ricevuti","Copertura richiesta","Periodo richiesto","Ultima acquisizione"),
            (f'{len(result["messages"])} / {total}' if total is not None else str(len(result["messages"])),
             state,period,local_time(result["acquired"])),
            ("Record API, non eventi distinti","Rispetto al totale dichiarato","Filtro trasmesso all’API","Europe/Rome"),strict=True):
        with col,st.container(border=True):
            st.caption(label)
            st.markdown("**"+value+"**")
    rows=project_messages(result["messages"])
    if not rows:
        st.info("Nessun messaggio restituito per questa richiesta. Non dimostra assenza di indisponibilità.")
    else:
        st.subheader("Messaggi ricevuti")
        search=st.text_input("Cerca per asset, operatore, ID o motivo",key="iip_search",
                             placeholder="Cerca nei campi disponibili")
        c1,c2,c3=st.columns(3)
        countries=c1.multiselect("Paese",options(rows,"country"),key="iip_country",placeholder="Tutti")
        statuses=c2.multiselect("Stato UMM",options(rows,"status"),key="iip_status",placeholder="Tutti")
        types=c3.multiselect("Tipo di evento",options(rows,"event_type"),key="iip_type",placeholder="Tutti")
        visible=filter_messages(rows,query=search,countries=countries,statuses=statuses,types=types)
        st.caption(f"{len(visible)} / {len(rows)} messaggi")
        if visible:
            st.dataframe([display_row(r) for r in visible],hide_index=True,width="stretch",
                         column_config={"Asset":st.column_config.TextColumn(width="medium"),
                                        "Motivo":st.column_config.TextColumn(width="large")})
            info("Info tabella","Ordinamento per pubblicazione quando il fuso è noto. I campi non riconosciuti restano non indicati.","Capacità del singolo messaggio, senza aggregazione. Fonte: "+GIE_CREDIT["IIP"])
            st.download_button("Esporta CSV filtrato",export_rows(visible,result),"gasops-iip-messaggi.csv",
                               "text/csv",key="iip_csv",icon=":material/download:")
            by_index={r["record_index"]:r for r in visible}
            chosen=st.selectbox("Apri dettaglio del messaggio",list(by_index),
                format_func=lambda i:f'{i+1} · {by_index[i]["message_id"] or "ID non indicato"} · {by_index[i]["asset"] or MISSING}',
                key="iip_detail")
            row=by_index[chosen]
            with st.expander("Dettaglio UMM"):
                st.markdown("**Messaggio selezionato**")
                a,b=st.columns(2)
                with a:
                    for label,field in (("Asset","asset"),("Operatore","operator"),("Paese","country"),
                                        ("Stato UMM","status"),("Tipo evento","event_type"),("Direzione","direction")):
                        st.caption(label)
                        st.text(row.get(field) or MISSING)
                with b:
                    for label,field in (("Pubblicato","published_label"),("Inizio","start_label"),("Fine","stop_label"),
                                        ("Capacità indisponibile","impact"),("Motivo","reason"),("Note","remarks")):
                        st.caption(label)
                        st.text(row.get(field) or MISSING)
                st.caption("Dati originali e possibili intervalli di capacità multipli")
                st.json(result["messages"][chosen],expanded=False)
                st.caption("Fonte: "+GIE_CREDIT["IIP"])
        else:
            st.info("Nessun risultato corrisponde ai filtri. Modifica la ricerca.")
    diagnostic=result.get("pagination_diagnostic")
    if diagnostic is not None:
        with st.expander("Diagnostica paginazione IIP"):
            st.caption(f"Ricevuti: {len(result['messages'])} · Totale dichiarato: "
                       f"{total if total is not None else 'non indicato'} · Pagine: "
                       f"{result['pages'] if result['pages'] is not None else 'non indicate'} · {state}")
            diagnostic_text=json.dumps(diagnostic,ensure_ascii=False,indent=2)
            st.code(diagnostic_text,language="json")
            st.download_button("Scarica diagnostica JSON",diagnostic_text,"gasops-iip-diagnostica.json",
                               "application/json",key="iip_pagination_diagnostic")
    with st.expander("Tutti i messaggi originali GIE IIP"):
        st.json(result["messages"],expanded=False)


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
