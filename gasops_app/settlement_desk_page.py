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
from .balancing_charts import daily_bars

STATE="settlement_desk_csv_v1"
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


def panel():
    from .workspace import guide
    st.subheader("Bilanci e rettifiche")
    mode=st.radio("Dati da utilizzare",["Dati importati","Esempio guidato"],horizontal=True,
                  index=1 if st.session_state.get("daily_desk_demo") else 0,key="daily_desk_data_mode")
    guide("settlement")
    example=mode=="Esempio guidato"
    if not example:
        _import_balances()
    uploaded=None if example else st.session_state.get(STATE)
    if not example and not uploaded:
        st.info("Per iniziare, scarica il modello e importa i bilanci del mese con i prezzi di sbilanciamento. "
                "Puoi anche scegliere Esempio guidato per provare il flusso completo.")
        return
    rows=sample_rows() if example else uploaded["rows"]
    st.caption("Esempio guidato · dati sintetici · settembre 2026 · IVA esclusa" if example else
               "CSV utente · fonte non verificata · sessione corrente · IVA esclusa")
    if uploaded:
        st.caption(f"{len(rows)} versioni conservate nel registro della sessione.")
        hashes=uploaded.get("hashes",(uploaded["sha"],))
        info("Provenienza del registro","SHA-256 del registro: "+uploaded["sha"]+
             "\nSHA-256 degli estratti acquisiti:\n"+"\n".join(hashes))
    users=sorted({r.user for r in rows})
    participant,period=st.columns(2)
    user=participant.selectbox("Partecipante (ID fittizio)",users,key="daily_desk_user")
    months=sorted({(r.day.year,r.day.month) for r in rows if r.user==user},reverse=True)
    year,month=period.selectbox("Mese di competenza",months,
                              format_func=lambda x:data_it(date(x[0],x[1],1),day=False),key="daily_desk_month")
    cutoff=closed_gas_day(utc_now())
    daily=daily_controls(rows,user,year,month,closed_day=cutoff)
    summary=monthly_summary(daily)
    st.caption(f"Ultimo giorno gas concluso: {cutoff:%d/%m/%Y} · dalle 06:00 locali alle 06:00 successive.")
    if summary["pending"]:
        st.info(f"{summary['pending']} giorni gas del mese devono ancora concludersi. Gli importi sono esclusi dai subtotali.")
    if summary["exceptions"]:
        st.warning(f"{summary['exceptions']} giornate da verificare. Apri Eccezioni per individuare dati mancanti o incoerenti. "
                   f"Importi parziali: {summary['eligible']}/{summary['expected']} giorni utilizzabili.")
    elif summary["complete"]:
        st.success(f"{summary['eligible']}/{summary['expected']} giorni utilizzabili. Nessuna eccezione nei controlli eseguiti.")
    else:
        st.caption("Mese ancora aperto. I subtotali riguardano soltanto le giornate concluse e utilizzabili.")
    comparison=st.radio("Confronto delle rettifiche",["Ultime due versioni","Provvisorio → definitivo"],
                        horizontal=True,key="daily_desk_comparison")
    prefix="version_" if comparison=="Ultime due versioni" else ""
    revisions=[row for row in daily if row[prefix+"delta_cash_eur"] is not None]
    revision_abs=sum((abs(row[prefix+"delta_cash_eur"]) for row in revisions),start=0) if revisions else None
    cards=[("Addebiti utente",summary["debits"],"€","Solo giorni utilizzabili",2,""),
              ("Crediti utente",summary["credits"],"€","Solo giorni utilizzabili",2,""),
              ("Giorni con eccezioni",summary["exceptions"],"","Da verificare",0,""),
              ("Impatto assoluto rettifiche",revision_abs,"€",str(len(revisions))+" coppie valorizzabili",2,"")]
    kpi_grid([c for c in cards if c[1] is not None])
    st.caption("Importo positivo: credito. Importo negativo: addebito. Gli importi sono simulazioni da validare, non fatture.")
    if example:
        revised=next((row for row in daily if row[prefix+"delta_cash_eur"] not in (None,0)),None)
        if revised:
            st.info("Caso da esplorare: "+data_it(date.fromisoformat(revised["day"]))+
                    ". La rettifica cambia l’importo di "+numero(revised[prefix+"delta_cash_eur"],2,signed=True)+
                    " €. Apri il dettaglio della giornata per vedere quali quantità e prezzi sono cambiati.")
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
    changed=any(row[prefix+"delta_cash_eur"] not in (None,0) or row[prefix+"delta_ds_mwh"] not in (None,0) for row in daily)
    default_filter=1 if summary["exceptions"] else 2 if changed else 0
    mode=st.radio("Mostra giornate",["Tutte","Eccezioni","Rettifiche"],horizontal=True,index=default_filter,key="daily_desk_filter")
    shown=[r for r in daily if mode=="Tutte" or (mode=="Eccezioni" and r["closed"] and r["issues"]) or
           (mode=="Rettifiche" and (r[prefix+"delta_ds_mwh"] not in (None,0) or r[prefix+"delta_cash_eur"] not in (None,0)))]
    def display(r):
        return {"Giorno gas":r["day"],"Fase":{"missing":"Assente","pending":"Non concluso", "invalid":"Da verificare",
                "provisional":"Provvisorio","definitive":"Definitivo"}[r["stage"]],"Versione":r["version"],
                "Sbilanciamento (MWh)":r["ds_mwh"],"Importo (€)":r["cash_eur"],
                "Rettifica (€)":r[prefix+"delta_cash_eur"],"Controlli":"; ".join(r["issues"]) or "Utilizzabile"}
    if shown:
        st.dataframe([display(r) for r in shown],hide_index=True,width="stretch")
    else:
        st.caption("Nessuna giornata corrispondente al filtro.")
    with st.expander("Esamina una giornata e tutte le sue versioni"):
        options=[row["day"] for row in daily]
        focus=next((row["day"] for row in shown),options[0])
        selected=st.selectbox("Giorno gas",options,index=options.index(focus),
                              format_func=lambda value:data_it(date.fromisoformat(value)),key="daily_desk_day")
        detail=next(row for row in daily if row["day"]==selected)
        st.caption(f"Durata effettiva {detail['elapsed_hours']} ore · {detail['start_utc']} → {detail['end_utc']}")
        st.caption("Rettifica · quantità: "+numero(detail[prefix+"quantity_effect_eur"],2)+
                   " € · prezzo: "+numero(detail[prefix+"price_effect_eur"],2)+" €")
        versions=sorted((row for row in rows if row.user==user and row.day.isoformat()==selected),key=lambda row:row.version)
        if versions:
            st.dataframe([{"Versione":row.version,"Fase":"Definitivo" if row.stage=="definitive" else "Provvisorio",
                           "Immissioni (MWh)":str(row.injected),"Stoccaggio netto (MWh)":str(row.storage_net),
                           "PSV netto (MWh)":str(row.psv_net),"Prelievi (MWh)":str(row.withdrawn),
                           "Acquisto (€/MWh)":str(row.buy) if row.buy is not None else "—",
                           "Vendita (€/MWh)":str(row.sell) if row.sell is not None else "—",
                           "DS (MWh)":str(row.imbalance),"Flusso (€)":str(row.cash) if row.cash is not None else "—"}
                          for row in versions],hide_index=True,width="stretch")
        else:
            st.caption("Nessuna versione acquisita per questa giornata.")
    export=[{"user":user,"period":f"{year}-{month:02d}","source":"CSV_NON_VERIFICATO" if uploaded else "SYNTHETIC",
             "closed_through":cutoff.isoformat(),"ledger_sha256":uploaded["sha"] if uploaded else "",
             "source_sha256":" ".join(uploaded.get("hashes",(uploaded["sha"],))) if uploaded else "",
             **r,"issues":"; ".join(r["issues"])} for r in daily]
    control_download,register_download=st.columns(2)
    control_download.download_button("Esporta controllo giornaliero CSV",csv_text(export),"igor-controllo-giornaliero.csv",
                       "text/csv",key="daily_desk_export")
    register_download.download_button("Scarica registro completo",archive_csv(rows),"igor-registro-bilanci.csv",
                           "text/csv",key="desk_archive_export")
    if uploaded:
        from .reconciliation_page import daily_panel
        daily_panel(rows,user,year,month,uploaded["sha"])
    info("Metodo e limiti","DS = immissioni + stoccaggio netto + transazioni nette PSV − prelievi. "
         "Arrotondamento dimostrativo per giorno a centesimi. Il confronto può usare le ultime due versioni, "
         "incluse rettifiche definitivo → definitivo, oppure l’ultimo provvisorio e il definitivo. "
         "L’effetto quantità usa i prezzi della versione di partenza per il segno del saldo finale, "
         "l’effetto prezzo è il residuo. Un prezzo controfattuale mancante impedisce la scomposizione. "
         "Gli importi includono solo giornate concluse senza eccezioni. I CSV aggiungono versioni al registro "
         "della sessione e i conflitti bloccano l’intera importazione. Esporta il registro per conservarlo. "
         "Edizioni di studio, senza certificazione di fatture o regole di accettazione Snam.")
