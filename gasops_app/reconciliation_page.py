"""Existing settlement and commercial views, no implicit demo or private persistence."""
import streamlit as st
from . import reconciliation as m
from .settlement_desk import csv_text
from .settlement_desk_page import STATE as BALANCE_STATE
from .bso_kpis import closed_gas_day
from .models import utc_now
from .data import ROME
from .visuals import kpi_grid,info

REPORT_STATE="settlement_reported_v1"
DOC_STATE="settlement_documents_v1"


def _upload(kind,state,fields,parser):
    st.download_button("Modello CSV",m.template(fields),"igor-"+kind+"-modello.csv","text/csv",key=state+"_template")
    with st.form(state+"_form"):
        raw=st.file_uploader("Estratto CSV normalizzato",type="csv",key=state+"_file")
        st.caption("Solo dati pubblici o sintetici · ID fittizi.")
        authorized=st.checkbox("Confermo di essere autorizzato a usare questo estratto",key=state+"_authorized")
        submit=st.form_submit_button("Importa e valida")
    if submit:
        if raw is None:
            st.warning("Seleziona un CSV.")
        elif not authorized:
            st.warning("Conferma l’autorizzazione d’uso dell’estratto.")
        else:
            try:
                st.session_state[state]={**parser(raw.getvalue()),"authorized":True,"origin":"user_upload",
                                         "retrieved_at":utc_now().isoformat()}
                st.success("Estratto acquisito · provenienza dichiarata.")
            except ValueError as exc:
                st.error(str(exc)+" Registro precedente conservato.")
    saved=st.session_state.get(state)
    if saved:
        st.caption("Sessione · SHA-256 "+saved["sha"][:12]+"…")
        if st.button("Rimuovi estratto",key=state+"_clear"):
            st.session_state.pop(state,None)
            st.rerun()
    return saved


def daily_panel(balances,user,year,month,balance_sha):
    st.subheader("Riconciliazione fisica ed economica")
    st.caption("Confronto indipendente · DS e flusso utente comunicati · IVA esclusa")
    now=utc_now()
    cutoff=closed_gas_day(now)
    with st.expander("Importa esiti definitivi comunicati"):
        st.caption("Una riga per partecipante, giorno gas e versione definitiva. DS in MWh e flusso in EUR con segno utente: negativo addebito, positivo credito. Riferimento fittizio. Schema I.G.O.R., non export nativo.")
        saved=_upload("settlement",REPORT_STATE,m.FIELDS,lambda raw:m.parse_report(raw,cutoff))
    if not saved:
        st.caption("Importa un secondo estratto per confrontare i bilanci calcolati. Nessuna quadratura presunta.")
        return
    results=m.reconcile_days(balances,saved["rows"],user,year,month,cutoff)
    if not results:
        st.caption("Nessun giorno gas concluso nel periodo.")
        return
    s=m.score(results)
    kpi_grid([("Giorni quadrati",s["matched"],"",f'Su {s["expected"]} giorni conclusi',0,""),
              ("Eccezioni",s["exceptions"],"",f'{s["unknown"]} non confrontabili',0,""),
              ("Differenze assolute",s["gross_difference"],"€",f'{s["compared"]} confronti omogenei',2,"")])
    if s["exceptions"]:
        st.warning("Verifica le eccezioni: una versione discordante non è una differenza quantificabile.")
    only=st.checkbox("Solo eccezioni",value=True,key="settlement_recon_only")
    shown=[r for r in results if not only or r["status"]!="QUADRA"]
    shown=sorted(shown,key=lambda r:(r["cash_delta"] is not None,-abs(r["cash_delta"] or 0),r["day"]))
    if shown:
        st.dataframe([{"Giorno gas":r["day"],"Stato":r["status"],"Versione bilancio":r["version"],"Versione comunicata":r["reported_version"],
                       "DS atteso (MWh)":r["ds_expected"],"DS comunicato (MWh)":r["ds_reported"],"Δ DS (MWh)":r["ds_delta"],
                       "Atteso (€)":r["cash_expected"],"Comunicato (€)":r["cash_reported"],"Δ €":r["cash_delta"],"Rif.":r["reference"],"Note":r["issues"]}
                      for r in shown],hide_index=True,width="stretch")
    else:
        st.caption("Nessuna eccezione nei confronti disponibili.")
    st.download_button("Esporta riconciliazione DS",csv_text([{"user":user,"balance_sha":balance_sha,"reported_sha":saved["sha"],
                        "energy_tolerance_mwh":m.ENERGY_TOL,"money_tolerance_eur":m.MONEY_TOL,**r} for r in results]),
                       "igor-settlement-quadratura.csv","text/csv",key="settlement_recon_export")
    info("Metodo","Confronto soltanto tra versioni definitive omogenee e giornate concluse. Differenze = dato comunicato − calcolato; tolleranze diagnostiche 0,001 MWh / 0,01 EUR. Non certificazione Snam. Importi mancanti o non confrontabili non valgono zero.")


def documents_panel():
    st.subheader("Controlla le fatture")
    st.caption("Partite mensili DS · imponibili ordinari · IVA esclusa")
    balances=st.session_state.get(BALANCE_STATE)
    if not balances:
        st.info("Per controllare le fatture, [importa prima i bilanci](/balancing).")
        return
    now=utc_now()
    with st.expander("Importa documenti DS"):
        st.caption("CSV con mese AAAA-MM, gruppo short/long, riferimento fittizio, imponibile positivo, data emissione. Solo documenti ordinari originali; escludi note di credito, rettifiche e altre componenti.")
        saved=_upload("fatture-ds",DOC_STATE,m.DOCUMENT_FIELDS,lambda raw:m.parse_documents(raw,now.astimezone(ROME).date()))
    if not saved:return
    rows=balances["rows"]
    users=sorted({r.user for r in rows}|{r.user for r in saved["rows"]})
    user=st.selectbox("Partecipante (ID fittizio)",users,key="doc_recon_user")
    months=sorted({(r.day.year,r.day.month) for r in rows if r.user==user}|{(r.year,r.month) for r in saved["rows"] if r.user==user},reverse=True)
    year,month=st.selectbox("Mese competenza",months,format_func=lambda p:f"{p[0]}-{p[1]:02d}",key="doc_recon_month")
    result=m.reconcile_documents(rows,saved["rows"],user,year,month,closed_gas_day(now))
    st.dataframe([{"Partita":"DS negativo" if r["group"]=="short" else "DS positivo","Atteso (€)":r["expected"],
                   "Documento (€)":r["observed"],"Δ (€)":r["delta"],"Esito":r["status"],"Riferimenti":r["references"]}
                  for r in result],hide_index=True,width="stretch")
    st.caption("Calcolo bloccato se manca un giorno definitivo valido. Documenti multipli da verificare, nessuna compensazione tra gruppi.")
    st.download_button("Esporta quadratura documenti",csv_text([{"user":user,"month":f"{year}-{month:02d}","balance_sha":balances["sha"],"document_sha":saved["sha"],
                          "tolerance_eur":m.MONEY_TOL,**r} for r in result]),"igor-quadratura-documenti.csv","text/csv",key="doc_recon_export")
