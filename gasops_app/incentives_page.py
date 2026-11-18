"""Compact 6PI scorecard within the existing BSO overview."""
from datetime import timedelta
import streamlit as st
from . import incentives as model
from .data import ROME
from .italiano import numero
from .visuals import kpi_grid,info

STATE="bso_6pi_v1"


def panel(now):
    st.subheader("Performance e incentivi · 6PI")
    st.caption("RdB · Italia · 2025–2028 · calcolo di studio, non rendicontazione ufficiale")
    with st.expander("Indicatori ARERA e importazione",expanded=False):
        st.markdown("[Delibera 482/2024/R/gas]("+model.SOURCE+") · [Parametri 6PI]("+model.ANNEX+") · [TIB art. 9]("+model.TIB+")")
        mode=st.radio("Dati",["Importati","Demo"],horizontal=True,key="incentive_mode")
        demo=mode=="Demo"
        if demo:
            rows=model.demo_rows()
            st.caption("Dati sintetici · nessun risultato Snam.")
        else:
            st.caption("Solo indicatori aggregati pubblici o autorizzati. Non inserire dati riservati o quotazioni non redistribuibili.")
            st.download_button("Modello CSV",model.template(),"igor-6pi-template.csv","text/csv",key="incentive_template")
            raw=st.file_uploader("Carica indicatori giornalieri (CSV)",type="csv",key="incentive_upload")
            if raw is not None and st.button("Valida importazione",key="incentive_import"):
                try:
                    local=now.astimezone(ROME)
                    cutoff=local.date()-timedelta(days=1 if local.hour>=6 else 2)
                    st.session_state[STATE]=model.parse_csv(raw.getvalue(),cutoff)
                    st.success("Importazione validata per formato; provenienza dichiarata.")
                except ValueError as e:
                    st.error(str(e)+" · ultimo registro valido conservato.")
            saved=st.session_state.get(STATE)
            if not saved:
                st.info("Importa p1–p6 giornalieri per vedere risultati e copertura. Nessun dato effettivo disponibile.")
                return
            rows,digest=saved
            st.caption("Registro di sessione · SHA-256 "+digest[:12]+"…")
        years=sorted({r.day.year for r in rows},reverse=True)
        year=st.selectbox("Anno solare",years,key="incentive_year_"+mode)
        chosen=tuple(r for r in rows if r.day.year==year)
        summaries=model.coverage(chosen)
        ia=model.annual_amount(chosen,year)
        from datetime import date
        expected=(date(year+1,1,1)-date(year,1,1)).days
        complete=sum(all(v is not None for v in r.incentives) and r.h is not None for r in chosen)
        kpi_grid([("Giorni importati",len(chosen),"",f"Su {expected} giorni dell’anno",0,""),
                  ("Giorni calcolabili",complete,"","Tutti i 6 indicatori e h",0,""),
                  ("IA annuale (studio)",ia,"€","Richiede anno intero e dati dichiarati definitivi",2,"")])
        st.dataframe([{"Indicatore":f"p{s['k']} · "+model.LABELS[s["k"]-1],
                       "Giorni":s["count"],"I grezzo (€)":float(s["raw"]) if s["raw"] is not None else None,
                       "Giorni con I negativo":s["negative"]} for s in summaries],
                     hide_index=True,width="stretch")
        st.caption("Somme giornaliere grezze sulle sole osservazioni importate; non IA né premio maturato. I2 in tabella prima della correzione h.")
        if any(r.incentives[1] is not None and r.h is None for r in chosen):
            st.warning("Correzione I2 incompleta: servono quotazioni EEX high/low o stato non quotato esplicito.")
        with st.expander("Dettaglio per giorno gas"):
            st.dataframe([{"Giorno gas":r.day,"Fase":r.phase,**{f"p{k} ({model.UNITS[k-1]})":float(v) if v is not None else None for k,v in enumerate(r.p,1)},
                           **{f"I{k} (€)":float(v) if v is not None else None for k,v in enumerate(r.incentives,1)},
                           "h":float(r.h) if r.h is not None else None} for r in chosen],hide_index=True,width="stretch")
        st.download_button("Esporta calcoli CSV",model.export_rows(chosen),"igor-6pi-"+str(year)+".csv","text/csv",key="incentive_export")
        info("Metodo","p1/p2 in punti percentuali (es. 4,5% nel CSV = 4.5); p3–p5 GWh; p6 Mmc. Importare gli indicatori del RdB, non sostituire con proxy.",
             "Due calendari stagionali, funzioni a tratti, h su spread EEX, sharing I1 oltre 3 milioni, floor annuo −5 milioni, limite sul gruppo I4+I5 e su I6 fino al 2026.",
             "Nessun valore assente trasformato in zero. Ricalcolo da p dichiarati, non da dati elementari. Nessuna verifica della pubblicazione o delle edizioni successive.")
