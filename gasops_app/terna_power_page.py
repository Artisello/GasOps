"""National electricity context, separate from gas forecasting and settlement."""
from datetime import timedelta
import pandas as pd
import streamlit as st
from .italiano import numero
from .visuals import TEAL, BLUE, kpi_grid, plot, info
from .terna_charts import comparison_bars, timeseries, day_label, acquisition_label

from .terna_power import (ANNUAL_URL,CATALOG,PORTAL,GEN_DOC,LOAD_DOC,TOKEN_DOC,
    annual_rows,credentials,latest_day,load_power,load_gas,paired,correlation)
from .models import utc_now
from .public_data import SourceUnavailable
from .session import database
from .entsog import SOURCE as ENTSOG_URL

STATE="terna_power_v1"
ATTEMPT="terna_power_attempt_v1"
LABELS={"Thermal":"Termoelettrico (tutti i combustibili)","Wind":"Eolico","Photovoltaic":"Fotovoltaico",
        "Hydro":"Idroelettrico","Geothermal":"Geotermico","load":"Fabbisogno",
        "load_forecast":"Fabbisogno previsto"}


def panel():
    st.subheader("Sistema elettrico · Terna")
    mode=st.radio("Analisi",["Statistiche annuali","Giorni gas","Previsioni elettriche","Capacità e industria"],horizontal=True,key="terna_mode",label_visibility="collapsed")
    if mode=="Previsioni elettriche":
        from .terna_forward_page import panel as forward_panel
        forward_panel()
    elif mode=="Capacità e industria":
        from .terna_context_page import panel as context_panel
        context_panel()
    elif mode=="Statistiche annuali":
        _annual()
    else:
        _daily()


ANNUAL_LABELS={
    "demand":"Fabbisogno elettrico","production_for_consumption":"Produzione destinata al consumo",
    "net_imports":"Importazioni nette","gross_generation":"Generazione lorda","net_generation":"Generazione netta",
    "gas_gross":"Generazione lorda da gas","gas_gross_yoy":"Variazione generazione da gas vs 2024",
    "gas_share_thermal":"Gas / generazione termoelettrica","wind_gross":"Eolico · generazione lorda",
    "hydro_gross":"Idroelettrico · generazione lorda","bioenergy_gross":"Bioenergie · generazione lorda",
    "solid_fuels_gross":"Combustibili solidi · generazione lorda","installed_gross":"Potenza lorda installata",
    "renewable_installed":"Potenza rinnovabile installata","pv_installed":"Fotovoltaico · potenza installata",
    "wind_installed":"Eolico · potenza installata","thermal_installed":"Termoelettrico · potenza installata",
}


def _annual():
    try:
        rows=annual_rows()
    except (OSError,ValueError):
        st.warning("Statistiche annuali non disponibili o non validabili.")
        return
    v={r["metric"]:r["value"] for r in rows}
    st.caption("Italia · Anno civile 2025 · Statistiche ufficiali Terna · valori arrotondati, non live")
    info("Fonte e metodologia","Sintesi statistica annuale, non dati in tempo reale. TWh = energia elettrica; GW = potenza installata. La generazione elettrica da gas non è il contenuto energetico del gas consumato.")
    kpi_grid([("Generazione lorda da gas",v["gas_gross"],"TWh",numero(v["gas_gross_yoy"],signed=True)+"% vs 2024",1,""),
              ("Gas nel termoelettrico",v["gas_share_thermal"],"%","Quota della produzione termoelettrica",1,""),
              ("Fabbisogno elettrico",v["demand"],"TWh","Anno 2025",1,"")])
    st.markdown("**Copertura del fabbisogno**")
    demand=v["demand"]
    if demand>0:
        prod=100*v["production_for_consumption"]/demand
        imp=100*v["net_imports"]/demand
        st.caption(f"Produzione destinata al consumo {numero(prod)}% · Importazioni nette {numero(imp)}%")
    plot(comparison_bars([("Produzione per il consumo",v["production_for_consumption"],TEAL),
                          ("Importazioni nette",v["net_imports"],BLUE)],"TWh"),"terna_annual_coverage")
    st.markdown("**Generazione lorda per fonte**")
    selected=[("Gas naturale",v["gas_gross"]),("Idroelettrico",v["hydro_gross"]),
              ("Eolico",v["wind_gross"]),("Bioenergie",v["bioenergy_gross"]),("Combustibili solidi",v["solid_fuels_gross"])]
    plot(comparison_bars([(name,value,TEAL if name=="Gas naturale" else BLUE) for name,value in selected],"TWh"),"terna_annual_generation")
    st.caption("Selezione delle fonti con valore esatto nella sintesi; fotovoltaico oltre 45 TWh. Non è il mix completo.")
    st.markdown("**Potenza installata**")
    kpi_grid([("Totale lordo",v["installed_gross"],"GW","Potenza nominale",1,""),
              ("Rinnovabili",v["renewable_installed"],"GW","Totale rinnovabili",1,""),
              ("Termoelettrico",v["thermal_installed"],"GW","Tutti i combustibili",1,"")])
    plot(comparison_bars([("Fotovoltaico",v["pv_installed"],BLUE),("Eolico",v["wind_installed"],TEAL)],"GW"),"terna_annual_capacity")
    st.caption("Fotovoltaico ed eolico sono sottoinsiemi delle rinnovabili; le categorie tecnologiche non costituiscono una somma del totale.")
    with st.expander("Dati e fonti"):
        st.dataframe(pd.DataFrame([{"Indicatore":ANNUAL_LABELS[r["metric"]],"Valore":numero(r["value"]),"Unità":r["unit"]} for r in rows]),hide_index=True,width="stretch")
        st.download_button("Scarica dati originali CSV",pd.DataFrame(rows).to_csv(index=False),"igor-terna-2025.csv","text/csv",key="terna_annual_export")
        st.markdown(f"[Statistiche ufficiali Terna]({ANNUAL_URL}) · [Portale dati]({PORTAL})")


def _daily():
    st.caption("Italia · generazione netta oraria e carico · aggregazione sperimentale 06:00–06:00")
    st.markdown(f"[Terna Actual Generation]({GEN_DOC}) · [Total Load]({LOAD_DOC}) · [Access token]({TOKEN_DOC})")
    from .terna_history_page import panel as history_panel
    try:
        client,secret=credentials(st.secrets)
    except (FileNotFoundError,KeyError):
        client,secret=credentials()
    if not client or not secret:
        st.info("API Terna non configurata. Le statistiche annuali restano consultabili senza credenziali.")
        with st.expander("Configura sul server"):
            st.markdown(f"[Registrazione Developer Portal]({CATALOG})")
            st.code('GASOPS_TERNA_CLIENT_ID = "..."\nGASOPS_TERNA_CLIENT_SECRET = "..."',language="toml")
            st.caption("Inserire soltanto nei Secrets Streamlit o in .env locale; mai in chat, GitHub o nei campi pubblici. Verifica condizioni e quote Terna.")
        history_panel()
        return
    now=utc_now()
    last=latest_day(now)
    with st.form("terna_request"):
        a,b=st.columns(2)
        first=a.date_input("Dal giorno gas",value=last-timedelta(days=13),max_value=last)
        end=b.date_input("Al giorno gas",value=last,max_value=last)
        st.caption("Timestamp Terna = inizio intervallo (ipotesi sperimentale da verificare).")
        archive=st.checkbox("Aggiungi allo storico di sessione",value=True)
        submit=st.form_submit_button("Carica dati",type="primary")
    if submit:
        if ATTEMPT in st.session_state and now-st.session_state[ATTEMPT]<timedelta(seconds=60):
            st.warning("Una richiesta ogni 60 secondi per sessione.")
        else:
            st.session_state[ATTEMPT]=now
            try:
                with st.spinner("Terna ed ENTSOG…"):
                    power=load_power(client,secret,first,end,now=now)
                    gas=None
                    try:
                        gas=load_gas(database(),first,end,now=now)
                    except (SourceUnavailable,ValueError):
                        pass
                st.session_state[STATE]={"power":power,"gas":gas}
                if archive:
                    from .terna_history import STATE as HISTORY,make_batch,merge
                    try:
                        st.session_state[HISTORY]=merge(st.session_state.get(HISTORY,[]),[make_batch(power,utc_now())])
                        st.success("Acquisizione aggiunta allo storico. Scarica il JSON per conservarla.")
                    except (ValueError,TypeError,KeyError):
                        st.warning("Dati visualizzati, ma storico non aggiornato: verificare copertura e limite.")
            except (SourceUnavailable,ValueError):
                st.caption("Aggiornamento Terna non disponibile. Ultimo risultato valido conservato, se presente.")
    history_panel()
    saved=st.session_state.get(STATE)
    if not saved:
        return
    power,gas=saved["power"],saved["gas"]
    st.caption(f"Periodo effettivo: {power['first']} – {power['last']} · acquisizione {power['acquired']}")
    if power["warning"]:
        st.warning(power["warning"])
    frame=pd.DataFrame(power["rows"])
    frame["gwh"]=pd.to_numeric(frame.gwh,errors="coerce")
    chart=frame.pivot(index="gas_day",columns="metric",values="gwh").rename(columns=LABELS)
    st.markdown("**Generazione elettrica per fonte**")
    visible=[LABELS[k] for k in ("Thermal","Wind","Photovoltaic","Hydro","Geothermal") if LABELS[k] in chart and chart[LABELS[k]].notna().any()]
    if visible:
        st.line_chart(chart[visible],y_label="GWh elettrici/giorno gas")
    load=[LABELS[k] for k in ("load","load_forecast") if LABELS[k] in chart and chart[LABELS[k]].notna().any()]
    if load:
        st.markdown("**Fabbisogno elettrico**")
        st.line_chart(chart[load],y_label="GWh elettrici/giorno gas")
    if all(LABELS[k] in chart for k in ("load","Wind","Photovoltaic")):
        proxy=(chart[LABELS["load"]]-chart[LABELS["Wind"]]-chart[LABELS["Photovoltaic"]]).dropna()
        if not proxy.empty:
            st.markdown("**Carico al netto di eolico e fotovoltaico**")
            st.line_chart(proxy.rename("Carico residuo parziale"),y_label="GWh elettrici/giorno gas")
            st.caption("Proxy consuntiva; non sottrae importazioni e altre fonti, non misura il consumo di gas.")
    st.caption("Intervalli mancanti o in conflitto escludono il totale del giorno per quella metrica. Thermal include più combustibili; non è solo gas. Idroelettrico non identificato come rinnovabile puro.")
    if gas is not None:
        st.markdown("**Relazione con i prelievi termoelettrici SRG**")
        st.markdown(f"[Fonte ENTSOG]({ENTSOG_URL}) · acquisizione {gas['acquired']}")
        if gas["cached"] or gas["failed"] or gas["metadata_warning"]:
            st.warning("Cache o metadati ENTSOG da verificare; copertura non certificata.")
        pairs=paired(power["rows"],gas["gas"])
        r=correlation(pairs)
        a,b=st.columns(2)
        a.metric("Giorni confrontabili",len(pairs))
        if r is not None:b.metric("Correlazione Pearson",f"{r:.2f}")
        if pairs:
            pair=pd.DataFrame(pairs)
            st.scatter_chart(pair,x="thermal_gwh",y="sr_gas_gwh",x_label="Terna · termoelettrico GWh elettrici",
                             y_label="ENTSOG · prelievi SRG GWh gas")
        st.caption("Minimo 7 coppie e variabilità non nulla. Correlazione descrittiva su finestra breve, non causalità né rendimento; perimetri diversi. Nessun dato assunto zero, nessun input al forecast.")
    with st.expander("Copertura oraria e download"):
        st.dataframe(frame,hide_index=True,width="stretch")
        st.download_button("CSV Terna con fonte",frame.assign(source="Terna",source_url=PORTAL,
            acquired_at=power["acquired"],time_convention="assumed interval start; Rome 06:00 gas day").to_csv(index=False),
            "igor-terna-giorni-gas.csv","text/csv")
        st.caption("Dati API solo in sessione; prelievi pubblici ENTSOG in cache SQLite. Nessuna chiamata schedulata o invio ai modelli AI.")
