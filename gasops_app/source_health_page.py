"""Compact quality overview of loaded data, no new API calls."""
import pandas as pd
import streamlit as st
from .models import utc_now
from .source_health import session_health,compare_srg
from .freshness import label as freshness_label
from .operational_sources import attributed_csv
from .visuals import kpi_grid,info

def _csv(rows):
    return attributed_csv({"frame":pd.DataFrame(rows)},per_row_source=True)

def render_rows(rows,*,key="source_health",filterable=True,kpis=True,download=True):
    good=sum(r["status"]=="Copertura verificata" for r in rows)
    absent=sum(r["status"].startswith("Non disponibile") or r["status"]=="Disattivato" for r in rows)
    review=len(rows)-good-absent
    if kpis:kpi_grid([("Copertura verificata",good,"","Serie / misure, non provider",0,""),
              ("Da verificare",review,"","Cache, lacune, metadati",0,""),
              ("Non disponibili",absent,"","Incluse misure disattivate",0,"")])
    view=st.radio("Serie mostrate",["Tutte","Da verificare","Non disponibili","Verificate"],
                  horizontal=True,key=key+"_filter",label_visibility="collapsed") if filterable else "Tutte"
    def group(r):
        if r["status"]=="Copertura verificata":return "Verificate"
        if r["status"].startswith("Non disponibile") or r["status"]=="Disattivato":return "Non disponibili"
        return "Da verificare"
    visible=[r for r in rows if view=="Tutte" or group(r)==view]
    if filterable:st.caption(f"{len(visible)}/{len(rows)} serie · stato riferito ai controlli della sessione")
    if visible:
        enriched=any("state" in r for r in visible)
        st.dataframe([{"Serie":r["source"],"Qualità":r["status"],"Ultimo periodo valido":r["latest"],
                       "Stato del dato":freshness_label(r),
                       "Copertura":f'{r["valid"]}/{r["expected"]}' if r["expected"] else "—",
                       "Perimetro":r["scope"],"Tipo":r["kind"],"Acquisizione dato":r["acquired"],
                       "Ultimo tentativo":r["attempt"],**({"Stato fonte":r.get("state"),
                        "Età copia più vecchia · h":r.get("cache_age_hours"),"Pubblicazione dato":r.get("published_at"),
                        "Anomalie timestamp":r.get("timestamp_issues"),
                        "Errore aggiornamento":r.get("refresh_error"),"Righe con revisioni":r.get("revision_rows"),
                        "Base copertura":r.get("coverage_basis")} if enriched else {})} for r in visible],hide_index=True,width="stretch",
                     column_config={"Serie":st.column_config.TextColumn(width="medium"),
                                    "Qualità":st.column_config.TextColumn(width="medium")})
    else:st.caption("Nessuna serie per questo filtro.")
    if rows and download:
        st.download_button("Esporta controllo qualità completo",_csv(rows),"igor-qualita-fonti.csv","text/csv",key=key+"_export",help="Include tutte le serie, indipendentemente dal filtro.")


def panel():
    now=utc_now()
    st.subheader("Qualità e affidabilità dei dati")
    st.caption("Controllo della sessione · distinto dal report del monitor automatico")
    try:
        from .italian_network_page import assets,bundled_interruptions
        from .gas_data import collect
        from .session import database
        network,_,snapshots=assets()
        frame=collect(network,snapshots,st.session_state,now,store=database(),interruptions=(bundled_interruptions(),))
        rows=session_health(st.session_state,now,gas_rows=frame)
    except (OSError,ValueError,KeyError):
        rows=session_health(st.session_state,now)
        st.caption("Dati della mappa non disponibili per il controllo.")
    render_rows(rows)
    with st.expander("Coerenza tra acquisizioni · ENTSOG"):
        st.caption("Stesso aggregato termoelettrico SRG, stesso giorno gas: serie mercato vs contesto Terna. Non confronto gas/elettricità e non fonte indipendente.")
        try:paired=compare_srg(st.session_state,now)
        except (ValueError,KeyError,TypeError,AttributeError,ArithmeticError):paired=[]
        if paired:
            bad=sum(r["status"]=="Discordante" for r in paired)
            st.caption(f"{len(paired)} giorni confrontabili · {bad} discordanti")
            if bad:st.warning("Verifica revisioni, date di acquisizione e metadati. Nessuna correzione automatica.")
            if any(r["review"] for r in paired):st.warning("Almeno una fonte usa cache dopo errore o segnala metadati da verificare.")
            st.dataframe(paired,hide_index=True,width="stretch")
            st.download_button("Esporta confronti",_csv(paired),"igor-entsog-coerenza.csv","text/csv",key="source_health_pairs")
        else:st.caption("Nessuna coppia confrontabile. Carica ENTSOG e il contesto gas di Terna dalle viste esistenti.")
    info("Metodo e soglie","Finestre diagnostiche: 14 giorni per le serie giornaliere, 6 mesi per le mensili; ACER ultime 14 righe ricevute. Soglie indicano una revisione, non SLA di pubblicazione. Le previsioni meteo non sono osservazioni.",
         "Stato di acquisizione, periodo del dato, copertura e provenienza sono distinti. Copertura verificata si riferisce soltanto alla finestra e ai controlli applicati, non autenticità o certificazione.")
