"""Session-only daily balancing and settlement desk."""
from datetime import date

import pandas as pd
import streamlit as st

from .settlement_desk import MAX_BYTES, archive_csv, csv_text, daily_controls, merge_csv, monthly_summary, template
from .gas_calendar import closed_gas_day
from .models import utc_now
from .operations_ledger import sample_rows
from .italiano import data_it, numero
from .visuals import kpi_grid, info, plot
from .workspace import guide, picker

STATE="settlement_desk_csv_v1"
SECTION="daily_desk_section"
QUEUE="daily_desk_queue"
JARVIS="https://jarvis.snam.it/public-data?lang=it"
GME="https://gme.mercatoelettrico.org/it-it/Home/Esiti/Gas/PrezzoSbilanciamento/Esiti/PrezzoSbilanciamento"


def _import_balances():
    notice=None
    with st.expander("Importa bilanci",expanded=STATE not in st.session_state):
        st.markdown(f"[Snam · Jarvis: bilanci e dati operativi]({JARVIS}) · [GME · parametri dei prezzi di sbilanciamento]({GME})")
        st.caption("Riferimenti alle fonti, non download automatici. Il CSV è uno schema I.G.O.R., non un formato Jarvis/GME: normalizza soltanto dati per i quali hai diritto d’uso. Prezzi forniti dall’utente, non stimati dal prezzo PSV.")
        st.download_button("Scarica modello CSV sintetico",template(),"igor-modello-bilanci.csv","text/csv",key="desk_template")
        from .bso_reference import template_guide
        template_guide()
        st.warning("Non caricare dati aziendali riservati o identificativi reali sul prototipo pubblico.")
        with st.form("desk_upload"):
            f=st.file_uploader("CSV bilanci e versioni",type=["csv"],help="Ogni import aggiunge versioni al registro. Anni 2000–2100, UTF-8, virgola come separatore, decimali con punto, fino a 2 MiB.")
            authorized=st.checkbox("Confermo di essere autorizzato a usare tutti i dati del registro",key="desk_authorized_import",
                help="La conferma comprende il nuovo CSV e le versioni già importate nel registro della sessione.")
            submitted=st.form_submit_button("Importa e controlla",type="primary",width="stretch")
        if submitted:
            if f is None:
                st.warning("Seleziona un CSV.")
            elif not authorized:
                st.warning("Conferma l’autorizzazione d’uso prima di importare il portafoglio.")
            elif f.size>MAX_BYTES:
                st.warning("CSV superiore a 2 MiB.")
            else:
                try:
                    raw=f.getvalue()
                    merged=merge_csv(st.session_state.get(STATE),raw,acquired=utc_now())
                    st.session_state[STATE]={**merged,"name":f.name,"authorized":True,"origin":"user_upload"}
                    notice=("success",f"Registro aggiornato: {merged['added']} nuove versioni, "
                            f"{merged['unchanged']} già presenti.")
                except ValueError as exc:
                    notice=("error",str(exc)+" Il dataset precedente resta invariato.")
        if STATE in st.session_state and st.button("Rimuovi CSV dalla sessione",key="desk_clear"):
            st.session_state.pop(STATE,None)
            st.rerun()
    if notice:
        getattr(st,notice[0])(notice[1])


def _open_day(day):
    st.session_state["daily_desk_day"] = day
    st.session_state[SECTION] = "Giornata"


def _select_queue_day(days):
    selection = st.session_state[QUEUE]["selection"]["rows"]
    if selection and 0 <= selection[0] < len(days):
        _open_day(days[selection[0]])


def panel(*, source_controls=None):
    if source_controls is None:
        st.subheader("Bilanci mensili")
    mode=(source_controls or st).radio("Dati da utilizzare",["Dati importati","Esempio guidato"],horizontal=True,
                  index=1 if st.session_state.get("daily_desk_demo") else 0,key="daily_desk_data_mode",
                  help="Carica il tuo registro CSV o consulta un caso con dati di esempio.")
    example=mode=="Esempio guidato"
    if not example:
        _import_balances()
    uploaded=None if example else st.session_state.get(STATE)
    if not example and not uploaded:
        st.info("Scarica il modello e importa i bilanci del mese con i prezzi di sbilanciamento.")
        guide("settlement")
        return
    rows=sample_rows() if example else uploaded["rows"]
    st.caption("Esempio guidato · dati sintetici · settembre 2026 · IVA esclusa" if example else
               "CSV utente · fonte non verificata · sessione corrente · IVA esclusa")
    users=sorted({r.user for r in rows})
    participant,period,settings=st.columns([2,2,1],vertical_alignment="bottom")
    user=participant.selectbox("Partecipante (ID fittizio)",users,key="daily_desk_user")
    months=sorted({(r.day.year,r.day.month) for r in rows if r.user==user},reverse=True)
    year,month=period.selectbox("Mese di competenza",months,
                              format_func=lambda x:data_it(date(x[0],x[1],1),day=False),key="daily_desk_month")
    with settings, st.popover("Tipo di rettifica",width="stretch"):
        comparison=st.radio("Confronto delle rettifiche",["Ultime due versioni","Provvisorio → definitivo"],
                            horizontal=True,key="daily_desk_comparison")
    cutoff=closed_gas_day(utc_now())
    daily=daily_controls(rows,user,year,month,closed_day=cutoff)
    summary=monthly_summary(daily)
    coverage=f"{summary['eligible']}/{summary['closed']} giorni conclusi utilizzabili."
    if summary["exceptions"]:
        st.warning(f"{summary['exceptions']} giornate da verificare. I subtotali coprono le sole giornate utilizzabili.")
    if summary["pending"]:
        st.caption(f"{summary['pending']} giorni del mese ancora aperti o futuri · ultimo giorno gas concluso {cutoff:%d/%m/%Y}.")
    prefix="version_" if comparison=="Ultime due versioni" else ""
    revisions=[row for row in daily if row[prefix+"delta_cash_eur"] is not None]
    revision_abs=sum((abs(row[prefix+"delta_cash_eur"]) for row in revisions),start=0) if revisions else None
    cards=[("Giornate da verificare",summary["exceptions"],"",coverage,0,"rose" if summary["exceptions"] else ""),
              ("Addebiti utente",summary["debits"],"€","Solo giorni utilizzabili",2,""),
              ("Crediti utente",summary["credits"],"€","Solo giorni utilizzabili",2,""),
              ("Impatto assoluto rettifiche",revision_abs,"€",str(len(revisions))+" coppie valorizzabili",2,"")]
    kpi_grid([c for c in cards if c[1] is not None])
    # The selected day and queue filter belong to the desk, even when their
    # widgets are temporarily absent while another section is open.
    for key in ("daily_desk_day","daily_desk_filter"):
        if key in st.session_state:
            st.session_state[key]=st.session_state[key]
    sections=["Giornate","Giornata","Grafici"]
    if uploaded:sections.append("Riconciliazione")
    if st.session_state.get(SECTION) not in (None,*sections):
        st.session_state.pop(SECTION)
    section=picker("Consulta il mese",sections,key=SECTION,labels={
        "Giornata":"Dettaglio giorno","Riconciliazione":"Confronta con esiti"})
    if section=="Grafici":
        _charts(daily,prefix)
    elif section=="Giornata":
        _day_detail(daily,rows,user,prefix,imported=not example)
    elif section=="Riconciliazione":
        from .reconciliation_page import daily_panel
        daily_panel(rows,user,year,month,uploaded["sha"])
    else:
        _queue(daily,summary,prefix,example)
        _downloads(daily,rows,user,year,month,cutoff,uploaded)
    st.caption("Importi indicativi da verificare, IVA esclusa · positivo = credito, negativo = addebito.")
    if uploaded:
        hashes=uploaded.get("hashes",(uploaded["sha"],))
        info("Provenienza del registro",f"{len(rows)} versioni · SHA-256 del registro: "+uploaded["sha"]+
             "\nSHA-256 degli estratti:\n"+"\n".join(hashes))
    guide("settlement")
    info("Metodo e limiti","DS = immissioni + stoccaggio netto + transazioni nette PSV − prelievi. "
         "Arrotondamento dimostrativo per giorno a centesimi. Il confronto può usare le ultime due versioni, "
         "incluse rettifiche definitivo → definitivo, oppure l’ultimo provvisorio e il definitivo. "
         "L’effetto quantità usa i prezzi della versione di partenza per il segno del saldo finale, "
         "l’effetto prezzo è il residuo. Un prezzo controfattuale mancante impedisce la scomposizione. "
         "Gli importi includono solo giornate concluse senza eccezioni. I CSV aggiungono versioni al registro "
         "della sessione e i conflitti bloccano l’intera importazione. Esporta il registro per conservarlo. "
         "Edizioni di studio, senza certificazione di fatture o regole di accettazione Snam.")


def _charts(daily,prefix):
    from .balancing_charts import daily_bars
    a,b=st.columns(2)
    with a:
        st.caption("Sbilanciamenti (MWh)")
        frame=pd.DataFrame({"Giorno":pd.to_datetime([r["day"] for r in daily]),
                            "DS":[float(r["ds_mwh"]) if r["ds_mwh"] is not None and r["closed"] else None for r in daily]})
        if frame.DS.notna().any():
            plot(daily_bars(frame,["DS"],"MWh").update_layout(height=235),"balancing_daily_ds")
        else:st.caption("Nessun saldo valorizzabile.")
    with b:
        st.caption("Rettifiche: quantità e prezzo (€)")
        bridge=pd.DataFrame({"Giorno":pd.to_datetime([r["day"] for r in daily]),
                            "Quantità":[float(r[prefix+"quantity_effect_eur"]) if r[prefix+"quantity_effect_eur"] is not None else None for r in daily],
                            "Prezzo":[float(r[prefix+"price_effect_eur"]) if r[prefix+"price_effect_eur"] is not None else None for r in daily]})
        if bridge[["Quantità","Prezzo"]].notna().any().any():
            plot(daily_bars(bridge,["Quantità","Prezzo"],"€").update_layout(height=235),"balancing_daily_revision")
        else:
            st.info("Nessuna coppia con scomposizione valorizzabile.")


def _revision(row,prefix):
    return row[prefix+"delta_cash_eur"] not in (None,0) or row[prefix+"delta_ds_mwh"] not in (None,0)


def _queue(daily,summary,prefix,example):
    changed=any(_revision(row,prefix) for row in daily)
    default_filter=1 if summary["exceptions"] else 2 if changed else 0
    mode=st.radio("Mostra giornate",["Tutte","Eccezioni","Rettifiche"],horizontal=True,index=default_filter,
                  key="daily_desk_filter",format_func=lambda value:"Da verificare" if value=="Eccezioni" else value)
    shown=[r for r in daily if mode=="Tutte" or (mode=="Eccezioni" and r["closed"] and r["issues"]) or
           (mode=="Rettifiche" and _revision(r,prefix))]
    if example:
        revised=next((r for r in daily if _revision(r,prefix)),None)
        if revised:
            st.button("Apri rettifica del "+data_it(date.fromisoformat(revised["day"])),
                      key="daily_desk_example_day",icon=":material/arrow_forward:",
                      on_click=_open_day,args=(revised["day"],))
    def display(r):
        stage={"missing":"Assente","pending":"Non concluso","invalid":"Da verificare",
               "provisional":"Provvisorio","definitive":"Definitivo"}
        return {"Giorno gas":date.fromisoformat(r["day"]),"Controlli":" · ".join(r["issues"]) or "Utilizzabile",
                "Fase":stage[r["stage"]],"Importo (€)":r["cash_eur"],"Rettifica (€)":r[prefix+"delta_cash_eur"],
                "Sbilanciamento (MWh)":r["ds_mwh"],"Versione":r["version"]}
    if shown:
        st.caption("Seleziona una riga per aprire la giornata.")
        days=[r["day"] for r in shown]
        st.dataframe([display(r) for r in shown],hide_index=True,width="stretch",key=QUEUE,
                     on_select=lambda:_select_queue_day(days),selection_mode="single-row",
                     column_config={"Giorno gas":st.column_config.DateColumn(format="DD/MM/YYYY")})
    else:
        st.caption("Nessuna giornata corrispondente al filtro.")


def _day_detail(daily,rows,user,prefix,*,imported=False):
    options=[row["day"] for row in daily]
    if st.session_state.get("daily_desk_day") not in options:
        st.session_state.pop("daily_desk_day",None)
    first_issue=next((r["day"] for r in daily if r["closed"] and r["issues"]),None)
    first_revision=next((r["day"] for r in daily if _revision(r,prefix)),None)
    focus=first_issue or first_revision or options[0]
    selected=st.selectbox("Giorno gas",options,index=options.index(focus),
                          format_func=lambda value:data_it(date.fromisoformat(value)),key="daily_desk_day")
    detail=daily[options.index(selected)]
    if detail["issues"]:
        st.info(" · ".join(detail["issues"]))
    kpi_grid([
        ("Rettifica",detail[prefix+"delta_cash_eur"],"€","Differenza tra le versioni selezionate",2,"blue"),
        ("Effetto quantità",detail[prefix+"quantity_effect_eur"],"€","Variazione attribuita ai volumi",2,""),
        ("Effetto prezzo",detail[prefix+"price_effect_eur"],"€","Variazione attribuita al prezzo",2,""),
    ])
    versions=sorted((row for row in rows if row.user==user and row.day.isoformat()==selected),key=lambda row:row.version)
    st.caption(f"{len(versions)} versioni · {detail['elapsed_hours']} ore · {detail['start_utc']} → {detail['end_utc']}")
    if versions:
        st.dataframe([{"Versione":row.version,"Fase":"Definitivo" if row.stage=="definitive" else "Provvisorio",
                           "Immissioni (MWh)":str(row.injected),"Stoccaggio netto (MWh)":str(row.storage_net),
                           "PSV netto (MWh)":str(row.psv_net),"Prelievi (MWh)":str(row.withdrawn),
                           "Acquisto (€/MWh)":str(row.buy) if row.buy is not None else "—",
                           "Vendita (€/MWh)":str(row.sell) if row.sell is not None else "—",
                           "DS (MWh)":str(row.imbalance),"Flusso (€)":str(row.cash) if row.cash is not None else "—"}
                      for row in versions],hide_index=True,width="stretch")
        if imported and detail["closed"] and versions[-1].stage == "definitive":
            from .gme_market import session_authorized as gme_authorized
            if gme_authorized():
                from .gme_market_page import settlement
                settlement(versions[-1])
    else:
        st.caption("Nessuna versione acquisita per questa giornata.")


def _downloads(daily,rows,user,year,month,cutoff,uploaded):
    export=[{"user":user,"period":f"{year}-{month:02d}","source":"CSV_NON_VERIFICATO" if uploaded else "SYNTHETIC",
             "closed_through":cutoff.isoformat(),"ledger_sha256":uploaded["sha"] if uploaded else "",
             "source_sha256":" ".join(uploaded.get("hashes",(uploaded["sha"],))) if uploaded else "",
             **r,"issues":"; ".join(r["issues"])} for r in daily]
    control_download,register_download=st.columns(2)
    control_download.download_button("Esporta controllo giornaliero CSV",csv_text(export),"igor-controllo-giornaliero.csv",
                       "text/csv",key="daily_desk_export",on_click="ignore")
    register_download.download_button("Scarica registro completo",archive_csv(rows),"igor-registro-bilanci.csv",
                           "text/csv",key="desk_archive_export",on_click="ignore")
