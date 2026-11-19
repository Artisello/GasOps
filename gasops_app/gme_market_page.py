"""Lean market desk; no GME credentials, cache or external requests in Streamlit."""
from decimal import Decimal as D
from datetime import date,timedelta
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from . import gme_market as g
from .bso_kpis import closed_gas_day
from .models import utc_now
from .italiano import numero
from .visuals import kpi_grid,plot,info,_frame,TEAL,BLUE,AMBER

STATE="gme_private_market_v1"
LABELS={"prices":"Parametri di sbilanciamento","mgs":"MGS · stoccaggio","mpl":"MPL · locational"}
FIELDS={
 "MaxPurchaseSRGPrice":"Massimo acquisto SRG","MinSaleSRGPrice":"Minimo vendita SRG",
 "WeightedAveragePrice":"Prezzo medio remunerazione","MGASVolumes":"Volume MGAS",
 "Price":"Prezzo di remunerazione","Volumes":"Volume scambiato",
 "SRGPurchases":"Acquisti SRG","SRGSales":"Vendite SRG","Participants":"Operatori",
 "SRGVolumes":"Volume abbinato SRG"}
KEYS={"FlowDate":"Giorno di flusso","SessionDate":"Data sessione","GasDay":"Giorno gas",
      "StorageCompany":"Impresa stoccaggio","Type":"Tipo","OfferPoint":"Punto","Reason":"Motivazione"}


def panel():
    st.subheader("Mercato gas · GME")
    kind=st.radio("Analisi",list(LABELS),format_func=LABELS.__getitem__,horizontal=True,
                  key="gme_view",label_visibility="collapsed")
    cutoff=closed_gas_day(utc_now())
    private=g.private_enabled()
    if not private:
        st.caption("Modalità pubblica · solo esempi sintetici. Accesso ai dati GME riservato a installazioni autorizzate.")
    a,b=st.columns([2,1])
    with a:
        st.caption("Fonte di riferimento: "+g.SOURCE)
    if b.button("Mostra demo",key="gme_demo",width="stretch"):
        st.session_state.setdefault(STATE,{})[kind]=g.demo(kind,cutoff)
    if private:
        with st.expander("Importa estratto GME autorizzato"):
            st.warning("Solo installazione privata, diritti d’uso verificati. Non importare dati su un servizio condiviso.")
            f=st.file_uploader("JSON nativo o risposta API JSON",type="json",key="gme_json_"+kind)
            if st.button("Valida estratto",key="gme_import_"+kind):
                if f is None:st.caption("Seleziona un file.")
                else:
                    try:saved=g.parse(f.getvalue(),kind,cutoff)
                    except ValueError as e:st.error(str(e)+" · estratto precedente conservato.")
                    else:st.session_state.setdefault(STATE,{})[kind]=saved
    saved=st.session_state.get(STATE,{}).get(kind)
    if saved and not private and not saved["synthetic"]:
        st.session_state[STATE].pop(kind,None)
        saved=None
    if saved:
        st.caption("Demo sintetica · valori inventati" if saved["synthetic"] else
                   "Estratto dichiarato GME · non verificato indipendentemente · solo sessione")
        if st.button("Rimuovi estratto",key="gme_clear_"+kind):
            st.session_state[STATE].pop(kind,None)
            st.rerun()
        entries=list(saved["rows"])
        if kind=="prices":_prices(entries)
        else:_auctions(entries,kind)
        with st.expander("Dati e provenienza"):
            st.dataframe(pd.DataFrame(entries).rename(columns={**KEYS,**FIELDS}),hide_index=True,width="stretch")
            st.caption("SHA-256 · "+saved["sha"])
    else:st.info("Nessun estratto disponibile. Prova la demo oppure consulta gli esiti ufficiali.")
    with st.expander("Fonti e accesso"):
        st.markdown(f"[Portale API e condizioni]({g.TERMS}) · [Manuale tecnico]({g.MANUAL})")
        st.markdown("[Parametri sbilanciamento](https://www.mercatoelettrico.org/Home/Esiti/Gas/PrezzoSbilanciamento/Esiti/PrezzoSbilanciamento) · [MGS](https://www.mercatoelettrico.org/it-it/Home/Esiti/Gas/MGS/Esiti/MGS) · [MPL](https://gme.mercatoelettrico.org/it-it/Home/Esiti/Gas/MPL/Esiti)")
        st.caption("Licenza standard personale, informativa e privata; per uso commerciale o pubblicazione richiedere autorizzazione GME. Nessuna acquisizione automatica o trasmissione AI sul deployment pubblico.")


def _prices(rows):
    latest=rows[-1]
    kpi_grid([(FIELDS[k],latest[k],"€/MWh",latest["FlowDate"],3,"") for k in (
        "WeightedAveragePrice","MaxPurchaseSRGPrice","MinSaleSRGPrice")])
    st.caption("Volume MGAS: "+numero(latest["MGASVolumes"],1)+" · unità fonte da confermare. Non è automaticamente il volume STSP title regolatorio.")
    frame=pd.DataFrame(rows).set_index("FlowDate")
    idx=pd.date_range(frame.index[0],frame.index[-1],freq="D") if (date.fromisoformat(frame.index[-1])-date.fromisoformat(frame.index[0])).days<=3660 else None
    frame.index=pd.to_datetime(frame.index)
    if idx is not None:frame=frame.reindex(idx)
    fig=go.Figure()
    for k,c in zip(("WeightedAveragePrice","MaxPurchaseSRGPrice","MinSaleSRGPrice"),(TEAL,AMBER,BLUE)):
        vals=[float(v) if pd.notna(v) else None for v in frame[k]]
        if any(v is not None for v in vals):
            fig.add_trace(go.Scatter(x=frame.index,y=vals,name=FIELDS[k],mode="lines+markers",connectgaps=False,line={"color":c}))
    if fig.data:plot(_frame(fig,"daily","€/MWh",280),"gme_price_chart")
    st.caption("Serie pubblicate come parametri, non prezzi finali di sbilanciamento.")
    with st.expander("Calcola prezzi di sbilanciamento · scenario"):
        selected=st.selectbox("Giorno gas",[r["FlowDate"] for r in reversed(rows)],key="gme_calc_day")
        item=next(r for r in rows if r["FlowDate"]==selected)
        volume=st.number_input("Volume STSP title verificato (MWh)",min_value=0.,value=None,key="gme_title_vol")
        rate=st.number_input("Percentuale small adjustment pubblicata (%)",min_value=0.,max_value=10.,value=None,key="gme_sa_rate")
        st.caption("Inserire il volume e la percentuale di competenza. Solo regime ordinario dell’edizione CdR XCII §4.4.1; estremi SRG necessari. Sotto 2.000 MWh serve lo storico completo dei 30 prezzi medi precedenti.")
        if volume is not None and rate is not None:
            day=date.fromisoformat(selected)
            history={date.fromisoformat(r["FlowDate"]):r["WeightedAveragePrice"] for r in rows
                     if day-timedelta(days=30)<=date.fromisoformat(r["FlowDate"])<day and r["WeightedAveragePrice"] is not None}
            try:r=g.study_prices(item,D(str(volume)),D(str(rate)),history)
            except ValueError as e:st.warning(str(e))
            else:
                kpi_grid([("Prezzo acquisto",r["buy"],"€/MWh","Scenario",3,""),
                          ("Prezzo vendita",r["sell"],"€/MWh","Scenario",3,""),
                          ("Small adjustment",r["adjustment"],"€/MWh",r["method"],3,"")])


def _auctions(rows,kind):
    # No total/constituent or distinct products summed together.
    dims=("StorageCompany","Type") if kind=="mgs" else ("OfferPoint","Reason","Type")
    scopes=sorted({tuple(r[k] for k in dims) for r in rows})
    scope=st.selectbox("Perimetro",scopes,format_func=lambda x:" · ".join(x),key="gme_scope_"+kind)
    selected=[r for r in rows if tuple(r[k] for k in dims)==scope]
    date_key="FlowDate" if kind=="mgs" else "GasDay"
    selected.sort(key=lambda r:(r[date_key],r.get("SessionDate","")))
    row=selected[-1]
    keys=("Price","SRGPurchases","SRGSales") if kind=="mgs" else ("Price","Volumes","SRGVolumes")
    kpi_grid([(FIELDS[k],row[k],"€/MWh" if k=="Price" else "",row[date_key]+" · "+("unità fonte" if k!="Price" else "ultimo record"),3,"") for k in keys])
    st.caption("Volumi riportati senza conversione: unità da confermare sulla fonte. Nessuna somma di totali e componenti; nessun costo di neutralità inferito.")
    st.dataframe(pd.DataFrame(selected).rename(columns={**KEYS,**FIELDS}),hide_index=True,width="stretch")
