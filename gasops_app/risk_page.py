"""Public, read-only probabilistic scenario laboratory."""
import json

import plotly.express as px
import streamlit as st

from .agents import MarketContext
from .italiano import numero
from .models import utc_now
from .risk import RiskSettings, forecast_uncertainty, simulate
from .session import assumptions, fixture, save_assumptions
from .visuals import info


def risk_page():
    st.title("Rischio probabilistico")
    st.caption("Simulazione Monte Carlo · rischio ipotetico, non ufficiale né settlement.")
    info("Info simulazione","Stima probabilità di deficit e perdita economica potenziale, VaR e CVaR.","Le probabilità sono condizionate alle ipotesi; non rappresentano il rischio ufficiale del sistema gas.")
    state = assumptions()
    data = st.session_state.get("active_bundle") or fixture()
    context = MarketContext(data, state.model, utc_now())
    facts = context.facts
    grain = "giorno-gas" if data.origin.grain == "daily" else "mese"
    st.caption(f"Fonte di riferimento: {data.origin.name} · {facts.get('label', 'non disponibile')} · GWh/{grain}.")
    use_forecast = st.checkbox("Usa la prossima previsione della domanda", key="risk_forecast")
    sd = None
    sd_source = "Ipotesi relativa dell’operatore"
    demand_base = facts.get("demand_gwh")
    if use_forecast:
        with st.spinner("Calcolo della previsione e degli errori storici…"):
            projection = context.projection
        if not projection.points:
            st.warning("Previsione non disponibile; disattiva l’opzione o seleziona un’altra fonte.")
            return
        demand_base = projection.points[0].estimate
        sd, count = forecast_uncertainty(projection)
        st.caption(f"Modello {projection.model} · periodo {projection.points[0].period}. L’offerta e il prezzo restano ipotesi, non previsioni.")
        if sd is not None:
            sd_source = f"Deviazione standard di {count} errori storici a un passo ({projection.model}); bias non corretto"
            st.caption(f"{sd_source}: {numero(sd)} GWh.")
        else:
            st.warning("Meno di 20 errori validi: usa una volatilità illustrativa.")
    if demand_base is None:
        st.warning("Domanda mancante: inserisci una quantità ipotetica.")
    supply_base = facts.get("supply_gwh")
    if supply_base is None:
        st.warning("Offerta mancante: il valore precompilato è una mera ipotesi, non un dato osservato.")
        supply_base = demand_base if demand_base is not None else 2400.
    if data.origin.grain == "monthly":
        st.caption("La disponibilità contabile mensile non equivale a capacità fisicamente disponibile.")
    p = facts.get("price_eur_mwh")
    s = state.risk
    st.subheader("1. Imposta lo scenario")
    with st.form("risk_assumptions"):
        a,b,c = st.columns(3)
        with a:
            demand = st.number_input("Domanda centrale (GWh)", min_value=0., max_value=1e12,
                                     value=float(demand_base or 0.), disabled=use_forecast,
                                     key=f"risk_demand_{data.fingerprint[:10]}_{use_forecast}_{state.model}")
            dv = st.number_input("Volatilità domanda (%)", 0.,100.,float(s.demand_cv*100), disabled=sd is not None)
            rho_ds = st.slider("Correlazione shock domanda/offerta", -1.,1.,float(s.rho_ds),.05)
        with b:
            supply = st.number_input("Offerta ipotetica (GWh)", min_value=0.,max_value=1e12,value=float(supply_base))
            sv = st.number_input("Volatilità offerta (%)",0.,100.,float(s.supply_cv*100))
            rho_dp = st.slider("Correlazione shock domanda/prezzo", -1.,1.,float(s.rho_dp),.05)
        with c:
            price_enabled = st.checkbox("Calcola anche rischio economico", value=p is not None)
            price = st.number_input("Prezzo ipotetico (€/MWh)", -1e6,1e6,float(p if p is not None else 42.))
            pv = st.number_input("Deviazione standard prezzo",0.,1000.,float(s.price_sd))
            n = st.select_slider("Simulazioni", options=[1000,10000,25000,50000,100000],
                                 value=s.simulations if s.simulations in [1000,10000,25000,50000,100000] else 10000)
            seed = st.number_input("Seed",0,2**32-1,s.seed)
        submitted = st.form_submit_button("Esegui Monte Carlo", type="primary")
    if submitted:
        settings = RiskSettings(simulations=n, seed=seed, demand_cv=dv/100, supply_cv=sv/100,
                                price_sd=pv, rho_ds=rho_ds, rho_dp=rho_dp)
        simulation = simulate(float(demand_base) if use_forecast else demand, supply,
                              price if price_enabled else None, settings, demand_sd=sd,
                              demand_sd_source=sd_source)
        simulation.summary.update({"source": data.origin.name, "source_kind": data.origin.kind.value,
                                   "grain": data.origin.grain, "source_period": facts.get("period"),
                                   "forecast_period": projection.points[0].period if use_forecast else None,
                                   "forecast_model": projection.model if use_forecast else None,
                                   "source_fingerprint": data.fingerprint})
        st.session_state["risk_simulation"] = simulation
        save_assumptions(state.model_copy(update={"risk":settings}))
    result = st.session_state.get("risk_simulation")
    if result is None:
        st.caption("Imposta le ipotesi e avvia la simulazione.")
        return
    r = result.summary
    if (r["source_fingerprint"] != data.fingerprint or bool(r["forecast_period"]) != use_forecast
            or (use_forecast and r["forecast_model"] != projection.model)):
        st.warning("Le ipotesi ora visualizzate sono cambiate. Esegui una nuova simulazione.")
        return
    st.subheader("2. Risultati dell’ultima simulazione")
    a,b,c = st.columns(3)
    a.metric("Probabilità di deficit", f"{numero(100*r['probability_deficit'],2)}%")
    b.metric("Deficit medio", f"{numero(r['expected_deficit_gwh'])} GWh")
    c.metric("Margine P05", f"{numero(r['gap_gwh']['p05'])} GWh")
    st.caption(f"Intervallo Monte Carlo 95% (solo errore di campionamento): "
               f"{numero(100*r['probability_deficit_mc_interval95'][0],2)}% – "
               f"{numero(100*r['probability_deficit_mc_interval95'][1],2)}%.")
    fig = px.histogram(x=result.gap, nbins=60, labels={"x":"Offerta − domanda (GWh)"})
    fig.add_vline(x=0, line_dash="dash", line_color="#d66b72")
    st.plotly_chart(fig, width="stretch")
    st.dataframe([{"Variabile": label, **r[key]} for label,key in
                  [("Domanda","demand_gwh"),("Offerta","supply_gwh"),("Margine","gap_gwh"),("Deficit","deficit_gwh")]], hide_index=True)
    st.subheader("3. Perdite nei casi peggiori (VaR e CVaR)")
    metrics = []
    for level in ("95","99"):
        energy = r["deficit_tail_gwh"][level]
        cost = r["gross_cost_tail_eur"][level] if r["gross_cost_tail_eur"] is not None else None
        metrics.append({"Confidenza":level+"%", "VaR deficit (GWh)":energy["var"],
                        "CVaR deficit (GWh)":energy["cvar"],
                        "VaR costo (EUR)":None if cost is None else cost["var"],
                        "CVaR costo (EUR)":None if cost is None else cost["cvar"],
                        "Massa scenari in coda":energy["tail_sample_mass"]})
    st.dataframe(metrics, hide_index=True)
    if result.loss is not None:
        st.metric("Costo lordo medio ipotetico", f"€ {numero(r['expected_gross_cost_eur'],2)}")
        fig = px.histogram(x=result.loss, nbins=60, labels={"x":"Costo lordo ipotetico (EUR)"})
        for label, dash in (("var","dash"),("cvar","dot")):
            fig.add_vline(x=r["gross_cost_tail_eur"]["95"][label], line_dash=dash,
                          annotation_text=label.upper()+" 95%")
        st.plotly_chart(fig, width="stretch")
    else:
        st.caption("Rischio monetario non calcolato: prezzo non fornito.")
    info("Info VaR e CVaR","CVaR = media della massa di coda peggiore, anche in presenza di perdite uguali. "+r["loss_definition"],"Le correlazioni sono ipotesi sui fattori gaussiani; offerta e prezzo non sono calibrati. Con molte simulazioni a zero il VaR può essere nullo e il CVaR positivo.","Il Centro operativo usa le ipotesi di volatilità salvate qui, ma applica il proprio scenario aggregato della fonte selezionata.")
    st.download_button("Esporta simulazione JSON",json.dumps(r,ensure_ascii=False,indent=2),
                       "gasops-risk.json","application/json")
