"""Linepack in the existing Jarvis desk, no new requests or AI."""
from datetime import timedelta
from decimal import Decimal as D
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from . import linepack as m
from .italiano import numero
from .data import ROME
from .visuals import kpi_grid,plot,local_time,info,TEAL,BLUE,AMBER,MUTED
from .operating_rules import STATE as BALANCE_STATE


def panel(versions,day,now,prefix):
    st.markdown("**Linepack atteso · revisioni**")
    st.caption("Stime successive importate per lo stesso giorno gas. Non sono misure dell’invaso.")
    r=m.revisions(versions,day,now)
    latest=r["latest"]
    last=r["last_valid"]
    if not latest or last is None:
        st.caption("Nessuna stima di linepack disponibile nel giorno selezionato.")
        return
    detail=local_time(latest["published_at"])
    if r["historical"]:detail+=" · storico"
    elif r["age_hours"]>3:detail+=" · non recente"
    kpi_grid([("Linepack atteso",latest["expected_gwh"],"GWh",detail,1,"blue"),
              ("Revisione ultima versione",latest["revision_gwh"],"GWh","Rispetto alla versione immediatamente precedente",1,""),
              ("Ore con stima",r["covered_hours"],"/ "+str(r["complete_hours"]),"Ore concluse nel solo estratto",0,"")])
    if latest["expected_gwh"] is None:
        st.warning("Ultima versione senza linepack. Ultimo valore disponibile: "+numero(last["expected_gwh"],1)+" GWh · "+local_time(last["published_at"])+". Non sostituisce l’ultima versione.")
    elif not r["historical"] and r["age_hours"]>3:
        st.warning("Pubblicazione non recente (oltre 3 ore, criterio informativo I.G.O.R.).")
    rows=r["rows"]
    times=[x["published_at"].astimezone(ROME).isoformat() for x in rows]
    fig=go.Figure(go.Scatter(x=[x["published_at"] for x in rows],y=[x["expected_gwh"] for x in rows],
        mode="lines+markers",name="Linepack atteso",connectgaps=False,line={"color":BLUE,"width":2.5},
        marker={"size":6},customdata=times,hovertemplate="%{customdata}<br>%{y:,.1f} GWh<extra></extra>"))
    fig.update_layout(template="plotly_dark",height=245,separators=",.",paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",margin={"l":10,"r":12,"t":12,"b":35},showlegend=False,
        font={"color":MUTED},xaxis={"title":"Pubblicazione (UTC; ora locale nel dettaglio)","nticks":6,"automargin":True},
        yaxis={"title":"GWh","nticks":5,"automargin":True,"gridcolor":"rgba(153,180,214,.12)"})
    plot(fig,prefix+"_linepack_revisions")
    largest=r["largest_revision"]
    if largest:
        st.caption("Revisione maggiore in valore assoluto: "+numero(largest["revision_gwh"],1,signed=True)+" GWh · "+local_time(largest["published_at"])+
                   " · escursione delle stime: "+numero(r["range_gwh"],1)+" GWh.")
    st.caption("Ore senza stima nell’estratto: "+str(r["complete_hours"]-r["covered_hours"])+". Non certifica ritardi della fonte. Nessuna soglia di sicurezza o azione automatica.")
    with st.expander("Versioni e variazioni del linepack"):
        frame=pd.DataFrame([{"Pubblicazione":local_time(x["published_at"]),"Stima GWh":x["expected_gwh"],
                             "Revisione GWh":x["revision_gwh"],"Ore dalla versione precedente":x["gap_hours"]} for x in rows])
        st.dataframe(frame,hide_index=True,width="stretch")
        st.download_button("Esporta revisioni",pd.DataFrame(rows).to_csv(index=False),"igor-linepack-revisioni.csv","text/csv",key=prefix+"_linepack_export")
    info("Come interpretare","Una revisione è una modifica della stima pubblicata, non gas immesso/prelevato. SAS e linepack sono grandezze distinte.",
         "Il modello di chiusura già disponibile usa revisioni storiche; non è una misura di fine giornata. Ore conteggiate in UTC per distinguere le ore ripetute al cambio d’ora.")


def physical_panel(now,prefix):
    with st.expander("ΔLPC · variazione giornaliera dell’invaso"):
        st.caption("Controllo separato dalle stime Jarvis · "+m.REF)
        yesterday=(now.astimezone(ROME)-timedelta(hours=6)).date()-timedelta(days=1)
        day=st.date_input("Giorno gas concluso",value=yesterday,max_value=yesterday,key=prefix+"_lpc_day")
        a,b=st.columns(2)
        opening=a.number_input("Energia in rete alle 06:00 G · GWh",min_value=0.,max_value=1e9,value=None,key=prefix+"_lpc_open")
        closing=b.number_input("Energia in rete alle 06:00 G+1 · GWh",min_value=0.,max_value=1e9,value=None,key=prefix+"_lpc_close")
        st.caption("Inserisci soltanto valori indipendenti, pubblici autorizzati o sintetici dello stesso perimetro SRG e PCS. Non usare valori di linepack atteso.")
        saved=st.session_state.get(BALANCE_STATE,{})
        options=m.balance_candidates(saved.get("rows",()),day)
        source=st.selectbox("Confronto con ΔLPC indipendente",["Nessuno","Valore manuale",*sorted(options)],
            format_func=lambda x:{"provisional":"Bilancio rete importato · provvisorio","definitive":"Bilancio rete importato · definitivo"}.get(x,x),key=prefix+"_lpc_source")
        reported=None
        if source=="Valore manuale":
            v=st.number_input("ΔLPC riportato · GWh",min_value=-1e9,max_value=1e9,value=None,key=prefix+"_lpc_reported")
            if v is not None:reported=D(str(v))
        elif source in options:
            reported=options[source]
            st.caption("ΔLPC importato: "+numero(reported,3,signed=True)+" GWh")
        tolerance=st.number_input("Tolleranza diagnostica · GWh",min_value=0.,max_value=1e6,value=.01,step=.01,key=prefix+"_lpc_tol")
        if opening is None or closing is None:
            st.caption("Inserisci entrambe le energie ai confini del giorno gas.")
            return
        if source!="Nessuno" and reported is None:
            st.caption("Completa il valore di confronto.")
            return
        if reported is not None and not st.checkbox("Confermo stesso giorno, perimetro, PCS e fase dei dati",key=prefix+"_lpc_confirm_"+str(day)+"_"+source):
            st.caption("Conferma l’omogeneità per confrontare il dato.")
            return
        r=m.physical_delta(day,now,D(str(opening)),D(str(closing)),reported,tolerance=D(str(tolerance)))
        kpi_grid([("ΔLPC ricostruito",r["delta"],"GWh","Fine − inizio",3,""),
                  ("ΔLPC riportato",r["reported"],"GWh","Dato indipendente",3,""),
                  ("Differenza",r["difference"],"GWh",r["status"],3,"rose" if r["status"]=="Da verificare" else "")])
        if r["status"]=="Da verificare":st.warning("Scostamento oltre tolleranza: verifica la fonte, non una dichiarazione di squilibrio.")
        st.caption("Il codice determina ΔLPC da misure di pressione, volume geometrico e PCS. Questo controllo non ricostruisce le telemisure e non certifica il bilancio definitivo.")
