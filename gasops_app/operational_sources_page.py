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
from .visuals import BLUE, TEAL, info, local_time, mini_chart, plot, kpi_grid
from .supply_view import scope_label, finite, inventory_snapshot, chart_window
from .iip_view import MISSING, coverage, display_row, export_rows, filter_messages, options, project_messages


def configured_key():
    # Streamlit loads its secrets lazily; explicitly access them before falling
    # back to the environment. Never display the key or prompt visitors for it.
    try:
        return gie_key(st.secrets)
    except (FileNotFoundError,KeyError):
        return gie_key()


def operational_context():
    """Standalone view; only the selected platform is loaded."""
    st.title("Stoccaggi e forniture")
    st.caption("Quanto gas è stoccato, quanto entra in rete e quali avvisi sono pubblicati.")
    key=configured_key()
    selected=st.radio("Sezione",["AGSI+","ALSI","IIP","Jarvis"],horizontal=True,key="operational_platform",
                      label_visibility="collapsed",
                      format_func={"AGSI+":"Scorte","ALSI":"Gas liquefatto","IIP":"Avvisi di mercato","Jarvis":"Rete Snam"}.__getitem__)
    if not key and selected!="Jarvis":
        st.info("Accesso GIE non configurato. La sezione Rete Snam resta disponibile.")
    with st.popover("Info fonti",icon=":material/info:"):
        st.write("AGSI+: gas negli stoccaggi. ALSI: terminali di gas naturale liquefatto (GNL). IIP: avvisi pubblicati dagli operatori. Jarvis: dati della rete Snam importati manualmente.")
        st.caption("Chiave GIE configurata; verifica al caricamento." if key else "Imposta GASOPS_GIE_API_KEY nei Secrets di Streamlit e riavvia l’app.")
    if selected=="AGSI+":
        _inventory_panel(selected,load_agsi,key)
    elif selected=="ALSI":
        _inventory_panel(selected,load_alsi,key)
    elif selected=="IIP":
        _iip_panel(key)
    else:
        _jarvis_panel()


def _jarvis_panel():
    st.subheader("Stime della rete Snam")
    st.markdown("**Italia · rete Snam**")
    st.caption("Importazione manuale di dati pubblici. Nessun collegamento automatico.")
    st.link_button("Apri portale Snam Jarvis",JARVIS_SOURCE,icon=":material/open_in_new:")
    info("Come importare i dati","Scarica il modello CSV GasOps, compila con i dati pubblici autorizzati e caricalo qui. Il modello non è un export nativo Jarvis.","Usa GWh e date ISO 8601 con offset. Non inserire informazioni riservate o bilanci individuali. I file non vengono inviati a LLM o salvati.")
    with st.container(border=True,key="panel_jarvis_import"):
        st.download_button("1. Scarica modello CSV",jarvis_template(),"gasops-jarvis-template.csv","text/csv")
        file=st.file_uploader("2. Carica il CSV compilato",type=["csv"],key="jarvis_public_extract")
    if file is not None:
        try:
            result=parse_jarvis(file.getvalue())
            latest=result["latest"]
            row=latest.iloc[-1]
            st.caption(f"Giorno gas {row['gas_day']} · versione {local_time(row['published_at'])} · fonte dichiarata, non verificata indipendentemente")
            kpi_grid([("Prelievo atteso",finite(row["expected_withdrawal_gwh"]),"GWh","Consumo atteso",1,"teal"),
                      ("SAS pubblicato",finite(row["sas_gwh"]),"GWh","Sbilanciamento atteso di sistema",1,""),
                      ("Gas presente in rete",finite(row["expected_linepack_gwh"]),"GWh","Linepack atteso",1,"blue")])
            info("Info stime","Il SAS è il valore riportato dalla fonte e non è calcolato come semplice differenza domanda/offerta. Il linepack indica il gas presente nella rete.")
            with st.expander("Dati importati e versioni"):
                st.dataframe(latest,hide_index=True,width="stretch")
                st.dataframe(result["versions"],hide_index=True,width="stretch")
                st.text("SHA-256 · "+result["sha256"])
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
    is_storage=platform=="AGSI+"
    st.subheader("Scorte di gas" if is_storage else "Gas naturale liquefatto (GNL)")
    control,action=st.columns([2,1],vertical_alignment="bottom")
    with control:
        scope=st.selectbox("Area geografica",["IT","EU"],format_func=scope_label,key=platform+"_scope")
    _credit(platform)
    if not key:
        return
    with action:
        result=_load_once(platform+"_"+scope,"Aggiorna dati",loader,key,scope)
    if result is None:
        return
    if result["scope"]!=scope:
        st.error("La fonte ha restituito un’area diversa da quella selezionata.")
        return
    frame=result["frame"]
    recent,changes=inventory_snapshot(frame,platform)
    age=(utc_now().astimezone(ROME).date()-recent["gas_day"]).days
    state=st.session_state.get(platform+"_"+scope,{})
    if age>2 or age<0 or result["failed"] or state.get("error"):
        st.warning("Dato non recente o aggiornamento non riuscito: verifica la fonte.")
    status={"C":"Confermato","E":"Stimato","N":"Assente"}.get(recent["status"],recent["status"])
    st.markdown("**"+scope_label(scope)+"**")
    st.caption(f"Ultimo dato: {data_it(recent['gas_day'])} · {status} · acquisito {local_time(result['acquired'])}"+
               (" · cache" if result["cached"] else ""))
    if is_storage and frame["review"].any():
        st.warning("Alcuni valori di capacità/riempimento richiedono verifica.")
    def delta(field,unit):
        value=changes.get(field)
        return (numero(value,signed=True)+" "+unit+" rispetto a 7 giorni prima") if value is not None else "Confronto a 7 giorni non disponibile"
    if is_storage:
        fill=finite(recent["fill_pct"])
        capacity=finite(recent["capacity_twh"])
        with st.container(border=True,key="panel_storage_fill"):
            st.caption("Riempimento degli stoccaggi")
            st.markdown("### "+(numero(fill,1)+"%" if fill is not None else "Non disponibile"))
            if fill is not None and 0<=fill<=100:
                st.progress(fill/100)
            elif fill is not None:
                st.caption("Valore pubblicato fuori dall’intervallo 0–100%; barra non mostrata.")
            st.caption(delta("fill_pct","punti percentuali"))
            st.caption("Capacità dichiarata: "+(numero(capacity,1)+" TWh" if capacity is not None else "non disponibile")+
                       " · riempimento fisico, non disponibilità commerciale.")
        kpi_grid([
            ("Giacenza",finite(recent["stock_twh"]),"TWh",delta("stock_twh","TWh"),2,"teal"),
            ("Gas prelevato",finite(recent["withdrawal_gwh_d"]),"GWh/giorno","Uscita dagli stoccaggi",1,""),
            ("Gas immagazzinato",finite(recent["injection_gwh_d"]),"GWh/giorno","Ingresso negli stoccaggi",1,"blue"),
        ])
        labels={"fill_pct":("Riempimento","%"),"stock_twh":("Giacenza","TWh"),
                "withdrawal_gwh_d":("Gas prelevato","GWh/giorno"),"injection_gwh_d":("Gas immagazzinato","GWh/giorno")}
        preferred="fill_pct"
    else:
        # Keep liquid volume and energy separate; show only a published unit.
        stock_field="inventory_1000m3_lng" if finite(recent["inventory_1000m3_lng"]) is not None else "inventory_gwh"
        stock_unit="migliaia di m³ GNL" if stock_field=="inventory_1000m3_lng" else "GWh"
        kpi_grid([
            ("Gas immesso in rete",finite(recent["sendout_gwh_d"]),"GWh/giorno",delta("sendout_gwh_d","GWh/giorno"),1,"teal"),
            ("Gas liquefatto nei terminali",finite(recent[stock_field]),stock_unit,"Inventario pubblicato",2,""),
            ("Immissione / riferimento",finite(recent["sendout_reference_pct"]),"%","Rapporto sul riferimento dichiarato",1,"blue"),
        ])
        labels={"sendout_gwh_d":("Gas immesso in rete","GWh/giorno"),
                "inventory_1000m3_lng":("Inventario GNL","migliaia di m³ GNL"),
                "inventory_gwh":("Inventario GNL","GWh"),
                "sendout_reference_pct":("Immissione / riferimento","%")}
        preferred="sendout_gwh_d"
    with st.container(border=True,key="panel_supply_history"):
        st.subheader("Andamento nel tempo")
        available=[f for f in labels if frame[f].notna().any()]
        left,right=st.columns([2,1])
        with left:
            col=st.selectbox("Indicatore",available,index=available.index(preferred) if preferred in available else 0,
                             format_func=lambda f:labels[f][0],key=platform+"_"+scope+"_chart")
        with right:
            days=st.selectbox("Periodo",[30,90],index=1,format_func=lambda n:f"{n} giorni",key=platform+"_"+scope+"_period")
        chart=chart_window(frame,days)
        label,unit=labels[col]
        st.caption(scope_label(scope)+" · "+unit)
        plot(mini_chart(chart[col],label,"daily",unit,TEAL if is_storage else BLUE).update_layout(height=320),
             key=platform+"_"+scope+"_trend")
        st.caption("Fonte: "+GIE_CREDIT[platform]+" · giorni senza dati lasciati vuoti.")
    info("Info indicatori","Il riempimento è quello pubblicato dalla fonte, non una soglia di sicurezza. La giacenza misura energia stoccata.",
         "Per ALSI il rapporto di immissione è riferito al valore dichiarato dall’operatore; non è una stima della capacità commerciale.")
    with st.expander("Dati giornalieri e download"):
        headers={"gas_day":"Giorno gas","status":"Stato","stock_twh":"Giacenza (TWh)","capacity_twh":"Capacità (TWh)",
                 "fill_pct":"Riempimento (%)","withdrawal_gwh_d":"Erogazione (GWh/d)","injection_gwh_d":"Iniezione (GWh/d)",
                 "inventory_1000m3_lng":"Inventario (10³ m³ LNG)","inventory_gwh":"Inventario (GWh)",
                 "dtmi_1000m3_lng":"DTMI (10³ m³ LNG)","sendout_gwh_d":"Send-out (GWh/d)",
                 "dtrs_gwh_d":"DTRS (GWh/d)","sendout_reference_pct":"Send-out / riferimento (%)","review":"Da verificare","source":"Fonte"}
        st.dataframe(frame.assign(source=result["source"]).rename(columns=headers),hide_index=True,width="stretch")
        st.download_button("Scarica CSV con fonte",attributed_csv(result),
                           "gasops-gie-"+platform.lower().replace("+","")+".csv","text/csv",key=platform+"_csv")


def _iip_panel(key):
    st.subheader("Interruzioni e avvisi di mercato (UMM)")
    st.markdown("**Perimetro: internazionale · paesi dichiarati nei messaggi**")
    st.caption("Avvisi pubblicati · non una misura di capacità persa.")
    info("Info UMM","Informazioni e indisponibilità pubblicate dagli operatori. Il conteggio non indica eventi unici o capacità persa aggregata.")
    _credit("IIP")
    if not key:
        return
    actions=st.columns([1,1,2],vertical_alignment="bottom")
    with actions[0]:
        result=_load_once("gie_iip","Aggiorna avvisi",load_iip,key,primary=True)
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
        search=st.text_input("Cerca impianto, operatore o motivo",key="iip_search",
                             placeholder="Cerca nei campi disponibili")
        with st.expander("Filtri per paese, stato e tipo"):
            c1,c2,c3=st.columns(3)
            countries=c1.multiselect("Paese",options(rows,"country"),key="iip_country",placeholder="Tutti")
            statuses=c2.multiselect("Stato UMM",options(rows,"status"),key="iip_status",placeholder="Tutti")
            types=c3.multiselect("Tipo di evento",options(rows,"event_type"),key="iip_type",placeholder="Tutti")
        visible=filter_messages(rows,query=search,countries=countries,statuses=statuses,types=types)
        st.caption(f"{len(visible)} / {len(rows)} messaggi")
        if visible:
            st.dataframe([display_row(r) for r in visible],hide_index=True,width="stretch",
                         column_order=["Paese","Asset","Tipo evento","Stato UMM","Inizio evento","Fine evento","Capacità indisponibile"],
                         column_config={"Asset":st.column_config.TextColumn("Impianto",width="medium"),
                                        "Motivo":st.column_config.TextColumn(width="large")})
            info("Info tabella","Ordinamento per pubblicazione quando il fuso è noto. I campi non riconosciuti restano non indicati.","Capacità del singolo messaggio, senza aggregazione. Fonte: "+GIE_CREDIT["IIP"])
            st.download_button("Esporta CSV filtrato",export_rows(visible,result),"gasops-iip-messaggi.csv",
                               "text/csv",key="iip_csv",icon=":material/download:")
            by_index={r["record_index"]:r for r in visible}
            chosen=st.selectbox("Apri dettaglio del messaggio",list(by_index),
                format_func=lambda i:f'{i+1} · {by_index[i]["message_id"] or "ID non indicato"} · {by_index[i]["asset"] or MISSING}',
                key="iip_detail")
            row=by_index[chosen]
            with st.expander("Leggi il messaggio selezionato"):
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
    with st.expander("Messaggi originali (JSON)"):
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
