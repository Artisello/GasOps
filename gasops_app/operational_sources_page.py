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
from .iip_view import MISSING, coverage, display_row, export_rows, filter_messages, options, project_messages, visible_columns


def configured_key():
    # Streamlit loads its secrets lazily; explicitly access them before falling
    # back to the environment. Never display the key or prompt visitors for it.
    try:
        return gie_key(st.secrets)
    except (FileNotFoundError,KeyError):
        return gie_key()


def operational_context():
    """Standalone view; only the selected platform is loaded."""
    title=st.empty()
    key=configured_key()
    selected=st.radio("Sezione",["AGSI+","ALSI","IIP","Jarvis","MASE","ENTSOG","MAP","EXPLORER"],horizontal=True,key="operational_platform",
                      label_visibility="collapsed",
                      format_func={"AGSI+":"Scorte","ALSI":"Gas liquefatto","IIP":"Avvisi di mercato","Jarvis":"Rete Snam","MASE":"Produzione","ENTSOG":"Interconnessioni","MAP":"Mappa della rete","EXPLORER":"Esplora dati"}.__getitem__)
    title.title("Gas Data Explorer" if selected=="EXPLORER" else "Rete gas italiana" if selected=="MAP" else "Stoccaggi e forniture")
    if selected=="EXPLORER":
        from .gas_data_page import panel
        panel()
        return
    if selected=="MAP":
        from .italian_network_page import panel
        panel()
        return
    if not key and selected in ("AGSI+","ALSI","IIP"):
        st.info("Accesso GIE non configurato. I controlli HS1 e la sezione Rete Snam restano disponibili.")
    with st.popover("Fonti",icon=":material/info:"):
        st.write("AGSI+: gas negli stoccaggi. ALSI: terminali di gas naturale liquefatto (GNL). IIP: avvisi pubblicati dagli operatori. Jarvis: dati della rete Snam importati manualmente.")
        st.caption("Chiave GIE configurata; verifica al caricamento." if key else "Imposta GASOPS_GIE_API_KEY nei Secrets di Streamlit e riavvia l’app.")
    if selected=="AGSI+":
        mode=st.radio("Vista scorte",["Giacenze pubbliche","Bilanciamento HS1"],horizontal=True,
                      key="storage_view",label_visibility="collapsed")
        if mode=="Bilanciamento HS1":
            from .storage_balancing_page import panel
            panel()
        else:
            _inventory_panel(selected,load_agsi,key)
    elif selected=="ALSI":
        _inventory_panel(selected,load_alsi,key)
    elif selected=="IIP":
        _iip_panel(key)
    elif selected=="ENTSOG":
        from .entsog_network_page import panel
        panel()
    elif selected=="MASE":
        from .mase_page import panel
        panel()
    else:
        from .jarvis_archive_page import panel as archive_panel
        mode=st.radio("Vista rete Snam",["Stime infragiornaliere","Archivio pubblicazioni","Importazione nativa"],horizontal=True,key="jarvis_view")
        if mode=="Stime infragiornaliere":
            _jarvis_panel()
        elif mode=="Importazione nativa":
            from .jarvis_native_page import panel as native_panel
            native_panel()
        else:
            archive_panel()


def _jarvis_panel(prefix="supply"):
    import pandas as pd
    state="jarvis_public_snapshot_v1"
    st.subheader("Stato del sistema gas")
    st.caption("Italia · rete Snam · stime di sistema importate")
    st.link_button("Apri portale Snam Jarvis",JARVIS_SOURCE,icon=":material/open_in_new:")
    with st.expander("Importa dati pubblici Jarvis",expanded=state not in st.session_state):
        info("Come importare i dati","Scarica il modello CSV I.G.O.R., compila con i dati pubblici autorizzati e caricalo qui. Il modello non è un export nativo Jarvis.","Usa GWh e date ISO 8601 con offset. Non inserire informazioni riservate o bilanci individuali. I file non vengono inviati a LLM o salvati su disco.")
        st.download_button("1. Scarica modello CSV",jarvis_template(),"igor-jarvis-template.csv","text/csv",key=prefix+"_jarvis_template")
        with st.form(prefix+"_jarvis_import"):
            file=st.file_uploader("2. Carica il CSV compilato",type=["csv"],key=prefix+"_jarvis_public_extract")
            st.caption("CSV pubblico · solo sessione, senza dati riservati.")
            submitted=st.form_submit_button("Importa stime")
        if submitted:
            if file is None:
                st.warning("Seleziona un CSV.")
            elif file.size>1_000_000:
                st.warning("CSV superiore a 1 MB.")
            else:
                try:
                    from .intraday import merge_snapshot
                    st.session_state[state]=merge_snapshot(st.session_state.get(state),file.getvalue(),utc_now())
                    st.success("Stime aggiunte allo storico della sessione.")
                except (ValueError,TypeError,OverflowError) as error:
                    st.caption("Importazione non valida, conflitto o limite archivio. Le stime precedenti restano disponibili.")
        if state in st.session_state:
            from .intraday import archive_csv
            saved=st.session_state[state]
            st.caption(f"{len(saved['versions'])}/2000 versioni · esporta prima di rimuovere.")
            st.download_button("Esporta archivio CSV",archive_csv(saved["versions"]),"igor-jarvis-storico.csv","text/csv",key=prefix+"_jarvis_history")
        if state in st.session_state and st.button("Rimuovi stime dalla sessione",key=prefix+"_jarvis_clear"):
            st.session_state.pop(state,None)
            st.rerun()
    result=st.session_state.get(state)
    if result is None:
        st.info("Importa le pubblicazioni autorizzate per osservare SAS, linepack e prelievi attesi. Nessun dato ipotetico sostitutivo.")
        from .linepack_page import physical_panel
        physical_panel(utc_now(),prefix)
        return
    versions=result["versions"]
    days=sorted(versions["gas_day"].unique(),reverse=True)
    selected=st.selectbox("Giorno gas",days,format_func=data_it,key=prefix+"_jarvis_day")
    history=versions.loc[versions["gas_day"]==selected].sort_values("published_at")
    row=history.iloc[-1]
    now=utc_now().astimezone(ROME)
    gas_day=now.date() if now.hour>=6 else now.date()-timedelta(days=1)
    st.caption(f"Giorno gas {data_it(selected)} · versione {local_time(row['published_at'])} · fonte dichiarata, non verificata indipendentemente")
    if selected!=gas_day:
        st.caption("Consultazione storica.")
    elif utc_now()-row["published_at"]>timedelta(hours=3):
        st.warning("Ultima pubblicazione importata oltre 3 ore fa. Verifica il portale; soglia informativa I.G.O.R..")
    fields=(("Prelievo atteso","expected_withdrawal_gwh","Consumo atteso"),
            ("SAS pubblicato","sas_gwh","Sbilanciamento atteso di sistema"),
            ("Gas presente in rete","expected_linepack_gwh","Linepack atteso"))
    previous=history.iloc[-2] if len(history)>1 else None
    cards=[]
    for label,field,detail in fields:
        value=finite(row[field])
        prior=finite(previous[field]) if previous is not None else None
        change=" · Δ "+numero(value-prior,1,signed=True)+" GWh dalla versione precedente" if value is not None and prior is not None else ""
        cards.append((label,value,"GWh",detail+change,1,""))
    kpi_grid([c for c in cards if c[1] is not None])
    if prefix=="balancing":
        from .intraday_page import decision_panel
        decision_panel(versions,selected,now,prefix)
    st.caption("Evoluzione infragiornaliera (GWh)")
    frame=history.copy()
    frame["Pubblicazione"]=pd.to_datetime(frame["published_at"],utc=True).dt.tz_convert(ROME)
    for label,field,_ in fields:
        frame[label]=pd.to_numeric(frame[field],errors="coerce")
    chart_fields=[label for label,_,_ in fields if frame[label].notna().any()]
    if len(frame)>1 and chart_fields:
        sas_fields=[label for label in chart_fields if label=="SAS pubblicato"]
        other_fields=[label for label in chart_fields if label=="Prelievo atteso"]
        if sas_fields:
            st.line_chart(frame,x="Pubblicazione",y=sas_fields)
        if other_fields:
            st.line_chart(frame,x="Pubblicazione",y=other_fields)
    else:
        st.caption("Servono almeno due pubblicazioni per mostrare l'evoluzione infragiornaliera.")
    from .linepack_page import panel as linepack_panel, physical_panel
    linepack_panel(versions,selected,utc_now(),prefix)
    physical_panel(utc_now(),prefix)
    info("Info stime","Il SAS è il valore riportato dalla fonte, non una differenza domanda/offerta calcolata da I.G.O.R. e non il DS del partecipante. Il linepack indica il gas presente nella rete. Il segno del SAS è mantenuto come pubblicato.","Dati importati nella sessione, nessun aggiornamento automatico. Verifica perimetro, convenzioni e orari della fonte.")
    from .intraday_page import panel as closing_panel
    closing_panel(versions,selected,utc_now(),prefix)
    with st.expander("Dati importati e versioni"):
        st.dataframe(history,hide_index=True,width="stretch")
        st.text("SHA-256 · "+result["sha256"])
        for h in result.get("hashes",()):st.caption("Estratto · "+h)


def _credit(platform):
    st.markdown("[Fonte: "+GIE_CREDIT[platform]+"]("+GIE_LINKS[platform]+") · [Condizioni d’uso]("+GIE_TERMS+")")


def _load_once(state,button,loader,key,*args,primary=False):
    """Rendering is local; an explicit action authorizes each acquisition."""
    clicked=st.button(button,key=state+"_load",type="primary" if primary else "secondary",
                      icon=":material/refresh:")
    previous=st.session_state.get(state)
    if clicked:
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
    if not snapshot:
        st.caption("Premi " + button + " per consultare la fonte.")
    if snapshot.get("error"):
        st.caption("Aggiornamento non disponibile · ultimo dato valido conservato, se presente.")
        with st.expander("Dettagli connessione"):
            st.text(snapshot["error"])
            st.caption("Verifica il portale ufficiale e l’abilitazione della chiave.")
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
    try:
        recent,changes=inventory_snapshot(frame,platform)
    except ValueError:
        st.warning("Nessuna osservazione utilizzabile per questa fonte e area. Aggiorna i dati.")
        return
    age=(utc_now().astimezone(ROME).date()-recent["gas_day"]).days
    state=st.session_state.get(platform+"_"+scope,{})
    if age>2 or age<0 or result["failed"] or state.get("error"):
        st.caption("Ultima pubblicazione disponibile · aggiornamento da verificare.")
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
        if fill is not None:
          with st.container(border=True,key="panel_storage_fill"):
            st.caption("Riempimento degli stoccaggi")
            st.markdown("### "+(numero(fill,1)+"%" if fill is not None else "Non disponibile"))
            if fill is not None and 0<=fill<=100:
                st.progress(fill/100)
            elif fill is not None:
                st.caption("Valore pubblicato fuori dall’intervallo 0–100%; barra non mostrata.")
            st.caption(delta("fill_pct","punti percentuali"))
            if capacity is not None:st.caption("Capacità dichiarata: "+numero(capacity,1)+" TWh · riempimento fisico, non disponibilità commerciale.")
        cards=[
            ("Giacenza",finite(recent["stock_twh"]),"TWh",delta("stock_twh","TWh"),2,"teal"),
            ("Gas prelevato",finite(recent["withdrawal_gwh_d"]),"GWh/giorno","Uscita dagli stoccaggi",1,""),
            ("Gas immagazzinato",finite(recent["injection_gwh_d"]),"GWh/giorno","Ingresso negli stoccaggi",1,"blue"),
        ]
        kpi_grid([r for r in cards if r[1] is not None])
        labels={"fill_pct":("Riempimento","%"),"stock_twh":("Giacenza","TWh"),
                "withdrawal_gwh_d":("Gas prelevato","GWh/giorno"),"injection_gwh_d":("Gas immagazzinato","GWh/giorno")}
        preferred="fill_pct"
    else:
        # Keep liquid volume and energy separate; show only a published unit.
        stock_field="inventory_1000m3_lng" if finite(recent["inventory_1000m3_lng"]) is not None else "inventory_gwh"
        stock_unit="migliaia di m³ GNL" if stock_field=="inventory_1000m3_lng" else "GWh"
        cards=[
            ("Gas immesso in rete",finite(recent["sendout_gwh_d"]),"GWh/giorno",delta("sendout_gwh_d","GWh/giorno"),1,"teal"),
            ("Gas liquefatto nei terminali",finite(recent[stock_field]),stock_unit,"Inventario pubblicato",2,""),
            ("Immissione / riferimento",finite(recent["sendout_reference_pct"]),"%","Rapporto sul riferimento dichiarato",1,"blue"),
        ]
        kpi_grid([r for r in cards if r[1] is not None])
        labels={"sendout_gwh_d":("Gas immesso in rete","GWh/giorno"),
                "inventory_1000m3_lng":("Inventario GNL","migliaia di m³ GNL"),
                "inventory_gwh":("Inventario GNL","GWh"),
                "sendout_reference_pct":("Immissione / riferimento","%")}
        preferred="sendout_gwh_d"
    with st.container(border=True,key="panel_supply_history"):
        st.subheader("Andamento nel tempo")
        available=[f for f in labels if frame[f].notna().any()]
        if not available:
            st.caption("Nessuna serie numerica validata; consulta la fonte.")
            return
        left,right=st.columns([2,1])
        with left:
            col=st.selectbox("Indicatore",available,index=available.index(preferred) if preferred in available else 0,
                             format_func=lambda f:labels[f][0],key=platform+"_"+scope+"_chart")
        with right:
            days=st.selectbox("Periodo",[30,90],index=1,format_func=lambda n:f"{n} giorni",key=platform+"_"+scope+"_period")
        chart=chart_window(frame,days)
        label,unit=labels[col]
        st.caption(scope_label(scope)+" · "+unit)
        if chart[col].notna().any():
            plot(mini_chart(chart[col],label,"daily",unit,TEAL if is_storage else BLUE).update_layout(height=320),
                 key=platform+"_"+scope+"_trend")
        else:
            st.info("Nessun dato per questo indicatore nel periodo selezionato.")
        st.caption("Fonte: "+GIE_CREDIT[platform])
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
    st.subheader("Avvisi di mercato · UMM")
    st.caption("GIE IIP · record attivi · nessun filtro geografico alla fonte")
    info("UMM","Avvisi pubblicati dagli operatori. Record ricevuti ≠ eventi distinti o capacità persa aggregata.")
    if not key:
        return
    actions=st.columns([1,1,2],vertical_alignment="bottom")
    with actions[0]:
        result=_load_once("gie_iip","Aggiorna avvisi",load_iip,key,primary=True)
    if result is None:
        _credit("IIP")
        st.caption("Consulta il portale GIE IIP in caso di errore.")
        return
    with actions[1]:
        st.download_button("Esporta JSON",attributed_iip_json(result),
                           "igor-gie-iip.json","application/json",key="iip_json",icon=":material/download:")
    total=result.get("reported_total")
    state=coverage(result)
    period=(result["request_from"]+" – "+result["request_to"]
            if result.get("request_from") and result.get("request_to") else "Non indicato")
    with actions[2]:
        if result["cached"]:
            st.caption("Da cache")
    if result["failed"] or utc_now()-result["acquired"]>timedelta(hours=2) or st.session_state.get("gie_iip",{}).get("error"):
        reason=result.get("refresh_error") or st.session_state.get("gie_iip",{}).get("error")
        st.warning("Ultima acquisizione non recente o aggiornamento non riuscito."+((" "+str(reason)) if reason else "")+" Consulta il portale IIP.")
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
    st.caption("Copertura della richiesta API, non completezza di tutti gli avvisi sul mercato.")
    rows=project_messages(result["messages"])
    if not rows:
        st.info("Nessun messaggio restituito per questa richiesta. Non dimostra assenza di indisponibilità.")
    else:
        st.subheader("Messaggi ricevuti")
        search=st.text_input("Cerca impianto, operatore o motivo",key="iip_search",
                             placeholder="Cerca nei campi disponibili")
        countries=statuses=types=()
        available=[(label,field,key) for label,field,key in (("Paese","country","iip_country"),("Stato","status","iip_status"),("Tipo","event_type","iip_type")) if len(options(rows,field))>1]
        if available:
            with st.expander("Filtri disponibili"):
                chosen_filters={field:st.multiselect(label,options(rows,field),key=key,placeholder="Tutti") for label,field,key in available}
                countries=chosen_filters.get("country",())
                statuses=chosen_filters.get("status",())
                types=chosen_filters.get("event_type",())
        visible=filter_messages(rows,query=search,countries=countries,statuses=statuses,types=types)
        st.caption(f"{len(visible)} / {len(rows)} messaggi")
        if visible:
            st.dataframe([display_row(r) for r in visible],hide_index=True,width="stretch",
                         column_order=visible_columns(visible),
                         column_config={"Asset":st.column_config.TextColumn("Impianto",width="medium"),
                                        "Motivo":st.column_config.TextColumn(width="large")})
            info("Info tabella","Ordinamento per pubblicazione quando il fuso è noto. I campi non riconosciuti restano non indicati.","Capacità del singolo messaggio, senza aggregazione. Fonte: "+GIE_CREDIT["IIP"])
            st.download_button("Esporta CSV filtrato",export_rows(visible,result),"igor-iip-messaggi.csv",
                               "text/csv",key="iip_csv",icon=":material/download:")
            by_index={r["record_index"]:r for r in visible}
            chosen=st.selectbox("Apri dettaglio del messaggio",list(by_index),
                format_func=lambda i:f'{by_index[i]["asset"] or "Impianto non indicato"} · {by_index[i]["message_id"] or ("record "+str(i+1))}',
                key="iip_detail")
            row=by_index[chosen]
            with st.container(border=True):
                st.markdown("**Messaggio selezionato**")
                a,b=st.columns(2)
                with a:
                    for label,field in (("Asset","asset"),("Operatore","operator"),("Paese","country"),
                                        ("Stato UMM","status"),("Tipo evento","event_type"),("Direzione","direction")):
                        value=row.get(field)
                        if value and value not in (MISSING,"Consulta dettaglio"):
                            st.caption(label)
                            st.text(value)
                with b:
                    for label,field in (("Pubblicato","published_label"),("Inizio","start_label"),("Fine","stop_label"),
                                        ("Capacità indisponibile","impact"),("Motivo","reason"),("Note","remarks")):
                        value=row.get(field)
                        if value and value not in (MISSING,"Consulta dettaglio"):
                            st.caption(label)
                            st.text(value)
                missing=[label for label,field in (("paese","country"),("inizio","start"),("fine","stop"),("tipo evento","event_type"),("capacità","unavailable")) if not row.get(field) or (field=="unavailable" and row["impact"]=="Consulta dettaglio")]
                if missing:st.caption("Campi non disponibili o non riconosciuti: "+", ".join(missing)+".")
                with st.expander("Messaggio originale e intervalli di capacità"):
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
            st.download_button("Scarica diagnostica JSON",diagnostic_text,"igor-iip-diagnostica.json",
                               "application/json",key="iip_pagination_diagnostic")
    with st.expander("Fonte e messaggi originali"):
        _credit("IIP")
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
