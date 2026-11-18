"""One compact foldout in the existing monthly settlement desk."""
from decimal import Decimal as D
import pandas as pd
import streamlit as st

from .adjustments import STATE,REF,MAX_BYTES,template,merge,archive_csv,controls,coverage,monthly
from .settlement_desk import csv_text
from .models import utc_now
from .visuals import kpi_grid

def panel():
    state=st.session_state
    with st.expander("Sessioni di aggiustamento",expanded=STATE in state):
        st.caption("Esiti economici separati dal bilancio definitivo · importi IVA esclusa.")
        with st.popover("Formato e regole",icon=":material/info:"):
            st.write(REF)
            st.caption("CSV normalizzato I.G.O.R., non export nativo. Importa esiti già determinati, con ID fittizi e riferimenti alle due sessioni. DS/IO: segno positivo a favore dell'utente; altre componenti: costo positivo. IO e SCOST: primo giorno del mese; altre: giorno gas. Baseline annuale = balancing, pluriennale = adjustment. Importo pubblicato opzionale. Nessun dato riservato, nessun invio all'AI. Gli importi non sono fatture; convenzioni e applicabilità richiedono verifica.")
        st.download_button("Modello CSV",template(),"igor-aggiustamenti-modello.csv","text/csv",key="adj_template")
        with st.form("adj_import"):
            f=st.file_uploader("Esiti e baseline CSV",type=["csv"],key="adj_file")
            st.caption("Dati di sessione · ID fittizi; verifica segni e unità.")
            submit=st.form_submit_button("Aggiungi esiti")
        if submit:
            if f is None:st.caption("Seleziona un CSV.")
            elif f.size>MAX_BYTES:st.caption("File oltre 2 MiB.")
            else:
                try:state[STATE]=merge(state.get(STATE),f.getvalue(),utc_now().date())
                except ValueError as e:st.caption(str(e)+" Archivio precedente invariato.")
        saved=state.get(STATE)
        if not saved:
            st.caption("Importa esiti annuali o pluriennali per calcolare le differenze.")
            return
        rows=saved["rows"]
        a,b,c=st.columns(3)
        user=a.selectbox("UDISA (ID fittizio)",sorted({r.user for r in rows}),key="adj_user")
        session=b.selectbox("Sessione",sorted({r.session_year for r in rows if r.user==user},reverse=True),key="adj_session")
        year,month=c.selectbox("Competenza",sorted({(r.competence.year,r.competence.month) for r in rows if r.user==user and r.session_year==session},reverse=True),format_func=lambda x:f"{x[0]}-{x[1]:02d}",key="adj_competence")
        original=state.get("settlement_desk_csv_v1",{}).get("rows",())
        results=controls(rows,user,session,year,month,balances=original)
        r=monthly(results)
        st.caption(("Annuale" if session-year==1 else "Pluriennale")+" · subtotali delle sole partite importate; non importo da fatturare.")
        if not r:return
        kpi_grid([("Addebiti teorici",r["debit"],"€","Partite importate",2,""),
                  ("Crediti teorici",r["credit"],"€","Partite importate",2,""),
                  ("Da verificare",r["exceptions"],"","Controlli di studio",0,"rose" if r["exceptions"] else "")])
        filter_=st.radio("Mostra",["Da verificare","Tutte"],horizontal=True,key="adj_filter")
        shown=[x for x in results if x["issues"]] if filter_=="Da verificare" else results
        if shown:
            st.dataframe([{"Competenza":x["competence"],"Partita":x["component"],"Precedente €":x["previous_eur"],
               "Nuovo €":x["current_eur"],"Δ €":x["delta_eur"],"Controllo":x["issues"] or x["classification"]} for x in shown],hide_index=True,width="stretch")
        else:st.caption("Nessun rilievo nei controlli eseguiti; non certifica la completezza.")
        checks=coverage(results,year,month)
        with st.expander("Copertura, confronti e provenienza"):
            st.caption(f'{r["compared"]}/{r["rows"]} differenze confrontate con importi pubblicati dichiarati. Assenti ≠ zero; applicabilità delle componenti da confermare.')
            st.dataframe(checks,hide_index=True,width="stretch")
            st.caption("Tolleranza 0,01 € di studio. Baseline DS annuale confrontata con il definitivo importato se univoco; pluriennale confrontata con l’esito dell’anno precedente se importato e con riferimento coincidente. Nessuna ricostruzione delle allocazioni.")
            st.caption(f"{sum(x['baseline_difference_eur'] is not None for x in results)}/{len(results)} baseline confrontate.")
            st.text("SHA-256 archivio · "+saved["sha256"])
            for h in saved["hashes"]:st.caption("Estratto · "+h)
            st.download_button("Esporta controlli",csv_text(results),"igor-aggiustamenti-controlli.csv","text/csv",key="adj_export")
            st.download_button("Esporta archivio ripristinabile",archive_csv(saved),"igor-aggiustamenti-archivio.csv","text/csv",key="adj_archive")
            clear=st.checkbox("Ho esportato e confermo rimozione.",key="adj_confirm_clear")
            if st.button("Rimuovi archivio",disabled=not clear,key="adj_clear"):
                state.pop(STATE,None);st.rerun()
