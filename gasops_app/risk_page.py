"""Read-only one-period Monte Carlo workbench; all scenarios illustrative."""
import json

import plotly.graph_objects as go
import streamlit as st

from .agents import MarketContext
from .italiano import numero
from .models import Kind, utc_now
from .risk import RiskSettings, forecast_uncertainty
from .risk_view import PRESETS, Stress, compare_stress, gap_distribution, cost_distribution
from .session import assumptions, fixture, save_assumptions
from .visuals import BLUE, ROSE, TEAL, info, kpi_grid, plot


def _graph(title,unit):
    fig=go.Figure()
    fig.update_layout(template="plotly_dark",height=295,margin=dict(l=8,r=8,t=12,b=12),
                      paper_bgcolor="rgba(0,0,0,0)",plot_bgcolor="rgba(0,0,0,0)",
                      xaxis_title=title,yaxis_title="% delle simulazioni",bargap=.08,
                      legend=dict(orientation="h",y=1.12),separators=",.",
                      xaxis=dict(showgrid=False),yaxis=dict(gridcolor="#26384d",rangemode="tozero"))
    return fig


def _results(result,base,r,unit):
    st.subheader("Risultati della simulazione")
    st.caption(r["scenario"]+" · "+numero(r["settings"]["simulations"],0)+" simulazioni · "+r["analysis_period"])
    p=r["probability_deficit"]
    kpi_grid([
        ("Probabilità di carenza",100*p,"%","Quota delle simulazioni con offerta < domanda",1,""),
        ("Carenza media",r["expected_deficit_gwh"],unit,"Media su tutti gli scenari, inclusi gli zeri",1,""),
        ("Costo lordo medio",r["expected_gross_cost_eur"],"€","Stima ipotetica, non settlement",0,""),
    ])
    if r["conditional_deficit_gwh"] is not None:
        st.caption("Carenza media quando presente: "+numero(r["conditional_deficit_gwh"])+" "+unit+".")
    else:
        st.caption("Nessuna carenza nel campione; non significa rischio reale pari a zero.")
    for label,key in (("domanda","clipped_demand_fraction"),("offerta","clipped_supply_fraction")):
        if r[key]>=.01:
            st.warning("Il modello ha troncato a zero "+numero(100*r[key])+"% dei valori simulati di "+label+". Rivedi le ipotesi di volatilità.")
    if any(r["stress"].values()):
        with st.container(border=True,key="panel_risk_comparison"):
            st.subheader("Confronto con la base")
            delta=100*(p-base["probability_deficit"])
            info("Confronto","Stessi shock casuali e seed; cambiano soltanto i valori centrali e le volatilità relative che ne dipendono.")
            kpi_grid([("Probabilità nella base",100*base["probability_deficit"],"%","Prima dello stress",1,""),
                      ("Probabilità nello scenario",100*p,"%","Dopo lo stress",1,""),
                      ("Variazione",delta,"punti %","Scenario − base",1,"")])
            st.dataframe([{"Indicatore":label,"Base":base[key],"Scenario":r[key]}
                          for label,key in (("Carenza media (GWh)","expected_deficit_gwh"),
                                            ("Costo lordo medio (€)","expected_gross_cost_eur"))],
                         hide_index=True,width="stretch")
    view=st.radio("Risultati",["Carenza di gas","Impatto economico","Ipotesi e metodo"],
                  horizontal=True,label_visibility="collapsed",key="risk_result_view")
    if view!="Ipotesi e metodo":
        level=st.radio("Livello di analisi",["95","99"],format_func=lambda v:v+"%",horizontal=True,
                       index=1 if st.session_state.get("risk_saved_confidence")=="99" else 0,key="risk_confidence")
        st.session_state["risk_saved_confidence"]=level
    if view=="Carenza di gas":
        tail=r["deficit_tail_gwh"][level]
        kpi_grid([("Carenza al percentile "+level,tail["var"],unit,"Soglia empirica (VaR)",1,""),
                  ("Media dei casi peggiori",tail["cvar"],unit,"CVaR · coda "+str(100-int(level))+"%",1,"")])
        h=gap_distribution(result.gap)
        with st.container(border=True,key="panel_risk_gap"):
            st.subheader("Distribuzione del saldo")
            st.caption("Saldo negativo = carenza. Saldo positivo o nullo = domanda coperta.")
            fig=_graph("Offerta − domanda ("+unit+")",unit)
            for mask,name,color in ((h["negative"],"Carenza",ROSE),(~h["negative"],"Saldo ≥ 0",TEAL)):
                fig.add_bar(x=h["center"][mask],y=h["pct"][mask],width=h["width"][mask],
                            name=name,marker_color=color,marker_pattern_shape="/" if name=="Carenza" else "",
                            hovertemplate="%{y:.2f}% delle simulazioni<extra>%{fullData.name}</extra>")
            fig.add_vline(x=0,line_dash="dash",line_color="#a3b4c9")
            plot(fig,"risk_gap_distribution")
        lo,hi=r["probability_deficit_mc_interval95"]
        st.caption("Intervallo Monte Carlo 95%: "+numero(100*lo,2)+"–"+numero(100*hi,2)+"% · solo errore di campionamento.")
        info("Info percentili","Il VaR è il percentile empirico della carenza; il CVaR è la media della coda peggiore, anche con valori uguali. Non è una riserva fisicamente disponibile né un requisito normativo.")
    elif view=="Impatto economico":
        if result.loss is None:
            st.info("Rischio economico non calcolato. Attiva il prezzo nelle ipotesi e ripeti la simulazione.")
        else:
            tail=r["gross_cost_tail_eur"][level]
            kpi_grid([("Costo al percentile "+level,tail["var"],"€","VaR · soglia empirica",0,""),
                      ("Costo medio dei casi peggiori",tail["cvar"],"€","CVaR · coda "+str(100-int(level))+"%",0,"")])
            h=cost_distribution(result.loss)
            st.caption(numero(h["zero_pct"],1)+"% delle simulazioni ha costo lordo nullo.")
            if len(h["pct"]):
                fig=_graph("Costo lordo positivo (€)","€")
                fig.add_bar(x=h["center"],y=h["pct"],width=h["width"],marker_color=BLUE,
                            name="Costi positivi",hovertemplate="%{y:.2f}% delle simulazioni<extra></extra>")
                fig.add_vline(x=tail["var"],line_dash="dash",line_color="#f2be72")
                fig.add_vline(x=tail["cvar"],line_dash="dot",line_color=ROSE)
                fig.update_layout(showlegend=False)
                plot(fig,"risk_cost_distribution")
                st.caption("Tratteggio: VaR. Puntini: CVaR. Frequenze sul totale, zeri esclusi dal grafico.")
            info("Info costo","Costo lordo ipotetico = carenza × 1.000 × max(prezzo, 0). Non è una perdita contabile o un corrispettivo di sbilanciamento.")
    else:
        st.caption("Fonte: "+r["source"]+" · "+r["source_kind"]+" · "+r["analysis_period"])
        st.dataframe([{"Variabile":label,**r[key]} for label,key in
                      (("Domanda","demand_gwh"),("Offerta","supply_gwh"),("Saldo","gap_gwh"),("Carenza","deficit_gwh"))],
                     hide_index=True,width="stretch")
        st.caption("P05, P50 e P95 · "+unit)
        st.write(r["limitations"])
        st.caption("Deviazione standard domanda: "+numero(r["inputs"]["demand_sd_gwh"])+" "+unit+" · "+r["inputs"]["demand_sd_source"])
        st.caption("Correlazioni gaussiane ipotetiche; correlazione latente offerta/prezzo implicita = "+numero(r["inputs"]["supply_price_latent_correlation"],2)+".")
        st.caption("Gli shock sui valori centrali non modificano una deviazione standard storica assoluta. Le volatilità relative si applicano ai nuovi valori.")
        with st.expander("Parametri e risultati completi"):
            st.json({"scenario":r,"base":base},expanded=False)
    st.download_button("Scarica simulazione JSON",json.dumps({"scenario":r,"base":base},ensure_ascii=False,indent=2,allow_nan=False),
                       "igor-risk.json","application/json",key="risk_export")


def risk_page(*, auto_demo=False):
    st.title("Simulazione rischi")
    from .gme_market import api_configured as gme_configured
    if gme_configured():
        from .workspace import picker
        if picker("Analisi del rischio", ("Simula uno scenario", "Rischio prezzo IGI"),
                  key="risk_workspace") == "Rischio prezzo IGI":
            from .gme_market_page import risk
            risk()
            return
    st.caption("Scenario ipotetico · non rischio ufficiale")
    state=assumptions()
    data=st.session_state.get("active_bundle") or fixture()
    origin=data.origin
    context=MarketContext(data,state.model,utc_now())
    facts=context.facts
    unit="GWh/mese" if origin.grain=="monthly" else "GWh/giorno gas"
    scope=("Simulazione · dati fittizi" if origin.kind==Kind.SYNTHETIC else
           "Italia · archivio storico" if origin.archive else
           "Italia · bilancio nazionale mensile" if origin.grain=="monthly" else
           "Italia · rete SRG, perimetro parziale")
    st.markdown("**"+scope+"**")
    st.caption(origin.name+" · "+facts.get("label","Periodo non disponibile")+" · "+unit)
    if origin.grain=="monthly":
        st.caption("Disponibilità contabile mensile, non capacità fisica della rete.")
    if origin.refresh_failed:
        st.warning("Aggiornamento della fonte non riuscito; verifica il periodo di riferimento.")
    use_forecast=st.checkbox("Parti dalla prossima previsione della domanda",key="risk_forecast")
    forecast_period=forecast_model=None
    sd=None
    sd_source="Ipotesi relativa dell’operatore"
    demand_base=facts.get("demand_gwh")
    if use_forecast:
        with st.spinner("Calcolo previsione…"):
            projection=context.projection
        if not projection.points:
            st.warning("Previsione non disponibile. Disattiva l’opzione.")
            return
        point=projection.points[0]
        forecast_period,forecast_model=point.period,projection.model
        demand_base=point.estimate
        sd,count=forecast_uncertainty(projection)
        st.caption("Previsione: "+forecast_period+" · "+forecast_model+" · offerta e prezzo restano ipotesi.")
        if sd is not None:
            sd_source=f"Deviazione standard di {count} errori storici a un passo ({forecast_model}); bias non corretto"
        else:
            st.warning("Meno di 20 errori validi: usa la volatilità ipotetica.")
    if demand_base is None:
        st.warning("Domanda assente: inserisci un valore ipotetico.")
    supply_base=facts.get("supply_gwh")
    if supply_base is None:
        st.warning("Offerta non disponibile nella fonte: il valore proposto è ipotetico.")
        supply_base=demand_base if demand_base is not None else 2400.
    p=facts.get("price_eur_mwh")
    settings=state.risk
    preset=st.selectbox("Scenario",[*PRESETS,"Personalizzato"],key="risk_preset",
                        help="Lo scenario modifica i valori centrali; il modello resta probabilistico.")
    stress=PRESETS.get(preset,Stress())
    if preset!="Personalizzato":
        st.caption("Domanda "+numero(stress.demand_pct,0,signed=True)+"% · offerta "+numero(stress.supply_pct,0,signed=True)+"% · prezzo "+numero(stress.price_delta,0,signed=True)+" €/MWh (se attivo).")
    form_key=f"risk_form_v2_{data.fingerprint[:14]}_{use_forecast}_{state.model}"
    with st.container(border=True,key="panel_risk_inputs"):
        st.subheader("Imposta le ipotesi")
        with st.form(form_key,border=False):
            a,b,c=st.columns(3)
            with a:
                demand=st.number_input("Domanda di base ("+unit+")",0.,1e12,float(demand_base or 0.),disabled=use_forecast)
            with b:
                supply=st.number_input("Offerta di base ipotetica ("+unit+")",0.,1e12,float(supply_base))
            with c:
                price=st.number_input("Prezzo ipotetico (€/MWh)",-1e6,1e6,float(p if p is not None else 42.))
                price_enabled=st.checkbox("Includi rischio economico",value=p is not None)
            if preset=="Personalizzato":
                a,b,c=st.columns(3)
                dp=a.number_input("Shock domanda (%)",-100.,300.,10.)
                sp=b.number_input("Shock offerta (%)",-100.,300.,-10.)
                pp=c.number_input("Shock prezzo (€/MWh)",-1000.,1000.,10.)
            with st.expander("Volatilità, correlazioni e parametri avanzati"):
                a,b=st.columns(2)
                with a:
                    dv=st.number_input("Volatilità domanda (%)",0.,100.,float(settings.demand_cv*100),disabled=sd is not None)
                    if sd is not None:
                        st.caption("Deviazione storica: "+numero(sd)+" "+unit)
                    sv=st.number_input("Volatilità offerta (%)",0.,100.,float(settings.supply_cv*100))
                    pv=st.number_input("Deviazione standard prezzo (€/MWh)",0.,1000.,float(settings.price_sd))
                with b:
                    rho_ds=st.slider("Correlazione domanda/offerta",-1.,1.,float(settings.rho_ds),.05)
                    rho_dp=st.slider("Correlazione domanda/prezzo",-1.,1.,float(settings.rho_dp),.05)
                    n=st.select_slider("Simulazioni",options=[1000,10000,25000,50000,100000],
                                       value=settings.simulations if settings.simulations in [1000,10000,25000,50000,100000] else 10000)
                    seed=st.number_input("Seed",0,2**32-1,settings.seed)
            submitted=st.form_submit_button("Esegui simulazione",type="primary",width="stretch")
    fingerprint={"source_fingerprint":data.fingerprint,"forecast_period":forecast_period,
                 "forecast_model":forecast_model,"scenario":preset}
    if submitted or (auto_demo and "risk_workspace_v2" not in st.session_state):
        try:
            if preset=="Personalizzato":
                stress=Stress(demand_pct=dp,supply_pct=sp,price_delta=pp)
            chosen=RiskSettings(simulations=n,seed=seed,demand_cv=dv/100,supply_cv=sv/100,
                                price_sd=pv,rho_ds=rho_ds,rho_dp=rho_dp)
            result,base=compare_stress(float(demand_base) if use_forecast else demand,supply,
                                        price if price_enabled else None,chosen,stress,
                                        demand_sd=sd,demand_sd_source=sd_source)
            base_summary=base.copy()
            result.summary.update({**fingerprint,"source":origin.name,"source_kind":origin.kind.value,
                                   "grain":origin.grain,"source_period":facts.get("period"),
                                   "analysis_period":forecast_period or facts.get("period") or "Periodo ipotetico",
                                   "stress":stress.model_dump(mode="json"),"executed_at":utc_now().isoformat()})
            st.session_state["risk_workspace_v2"]={"result":result,"base":base_summary}
            save_assumptions(state.model_copy(update={"risk":chosen}))
        except (ValueError,ArithmeticError) as error:
            st.session_state.pop("risk_workspace_v2",None)
            st.error("Simulazione non eseguita: "+str(error))
    saved=st.session_state.get("risk_workspace_v2")
    if not saved:
        st.caption("Il risultato apparirà qui dopo il calcolo.")
        return
    result=saved["result"]
    r=result.summary
    if any(r.get(k)!=v for k,v in fingerprint.items()):
        st.warning("Fonte, previsione o scenario cambiati. Esegui una nuova simulazione.")
        return
    st.caption("Ultimo calcolo · aggiornamento manuale")
    if r["inputs"]["price_eur_mwh"] is None and r["stress"]["price_delta"]:
        st.caption("Shock prezzo non applicato: rischio economico disattivato.")
    _results(result,saved["base"],r,unit)
