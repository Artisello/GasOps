"""Independent study lab: real historic archive, recent session data, no auto promotion."""
from datetime import timedelta
from hashlib import sha256
import pandas as pd
import streamlit as st

from .data import jrc_archive,ROME
from .models import Kind,utc_now
from .quality import inspect
from .predictive import evaluate,HORIZONS,MODELS,MIN_TRAIN,MIN_TEST
from .predictive_sources import session_features,historical_weather
from .public_data import SourceUnavailable
from .session import database

LABELS={"weekly":"Naive settimanale","autoregressive":"Ridge autoregressivo","multivariate":"Ridge multivariato","bayesian_base":"Bayes autoregressivo","bayesian_multi":"Bayes multivariato"}
STATE="predictive_study_v1"


def panel():
    st.subheader("Laboratorio previsionale")
    st.caption("Studio retrospettivo · giorno gas 06:00–06:00 · nessuna sostituzione del forecast principale")
    now=utc_now()
    active=st.session_state.get("live_public_bundles_v1",{}).get("daily") or st.session_state.get("active_bundle")
    recent=bool(active and active.origin.kind in (Kind.HISTORICAL,Kind.LIVE) and active.origin.grain=="daily" and
                not active.origin.archive and active.origin.name.startswith("ENTSOG"))
    source=st.selectbox("Serie di domanda",["Archivio JRC 2015–2021","ENTSOG SRG già caricato"],
                        index=1 if recent else 0,key="predictive_target")
    use_recent=source.startswith("ENTSOG")
    if use_recent and not recent:
        st.info("Carica prima la serie ENTSOG dalla vista Domanda e previsioni. Nessun fallback sintetico.")
        return
    bundle=active if use_recent else jrc_archive()
    frame=inspect(bundle,now).usable
    st.caption(f"{bundle.origin.name} · {bundle.origin.url or ''} · ultimo periodo {bundle.origin.latest_period or '—'}")
    if not use_recent:
        frame=frame.tail(730)
        st.caption("Ultimi 730 giorni dell'archivio storico: risultati non riferiti al mercato attuale.")
    available=session_features(st.session_state) if use_recent else {}
    options=list(available)
    # Suggest only sufficiently long historical series, never select by test error.
    eligible=[k for k in ("terna_residual_wind_solar","terna_Thermal","storage","entsog_Physical Flow","flow") if k in available and available[k].values.dropna().shape[0]>=MIN_TRAIN+28+7]
    selected=st.multiselect("Variabili aggiuntive già caricate",options,default=eligible[:2],format_func=lambda k:available[k].name,
                            max_selections=3,key="predictive_covariates")
    snapshots=tuple((k,sha256(available[k].values.to_csv().encode()).hexdigest(),available[k].provenance) for k in selected)
    def describe(c):
        valid=c.values.dropna()
        return {"Variabile":c.name,"Unità":c.unit,"Perimetro":c.scope,"Osservazioni":len(valid),
                "Da":str(valid.index.min().date()) if len(valid) else "—",
                "A":str(valid.index.max().date()) if len(valid) else "—","Fonte":c.source}
    if options:
        st.dataframe([describe(c) for c in available.values()],hide_index=True,width="stretch")
    else:
        st.caption("Nessuna variabile esterna compatibile caricata; modalità multivariata settoriale disponibile.")
    if use_recent:
        st.caption("AGSI+ Italia, ENTSOG interconnessioni e Terna si caricano nelle viste dedicate. Finestre brevi possono non bastare al backtest.")
    from .weather_source import enabled,refresh as refresh_weather,archive as weather_archive
    weather=st.checkbox("HDD Open-Meteo · demo non commerciale",value=bool(use_recent and enabled(st.session_state)),disabled=not enabled(st.session_state),key="predictive_weather_"+("recent" if use_recent else "archive"))
    weather=weather and enabled(st.session_state)
    horizon=st.selectbox("Orizzonte",HORIZONS,format_func=lambda h:f"{h} giorno" if h==1 else f"{h} giorni",
                         key="predictive_horizon")
    st.caption(f"Training minimo {MIN_TRAIN} giorni comuni per origine; verifica ultimi 28 giorni di riferimento, almeno {MIN_TEST} coppie. Ritardi assunti: gas 2 giorni, covariate 7 giorni. Non sono SLA né vintage storici verificati.")
    if st.button("Esegui confronto",type="primary",key="predictive_run"):
        st.session_state.pop(STATE,None)
        try:
            cov=[available[k] for k in selected]
            with st.spinner("Validazione temporale e confronto dei modelli…"):
                weather_note=None
                if weather:
                    try:
                        if use_recent:
                            refresh_weather(st.session_state,database(),now)
                        cov.append(historical_weather(database(),frame,now,snapshot=weather_archive(st.session_state,now) if use_recent else None))
                    except (ValueError,SourceUnavailable):
                        weather_note="HDD non disponibile: confronto esplicitamente senza meteo."
                last=frame["demand_gwh"].last_valid_index()
                if last is None:
                    raise ValueError("Domanda assente.")
                reference=last+pd.Timedelta(days=2)
                if use_recent:
                    local=now.astimezone(ROME)
                    active_day=local.date() if local.hour>=6 else local.date()-timedelta(days=1)
                    reference=min(reference,pd.Timestamp(active_day))
                result=evaluate(frame,cov,horizon,reference)
            st.session_state[STATE]={"result":result,"fingerprint":bundle.fingerprint,"source":source,
                "selected":snapshots,"weather":weather,"horizon":horizon,"cov":[describe(c)|{"Provenienza":c.provenance} for c in cov],
                "acquired":now.isoformat(),"weather_note":weather_note}
        except (ValueError,SourceUnavailable) as e:
            st.caption(str(e))
    saved=st.session_state.get(STATE)
    if not saved:
        return
    if (saved["source"],saved["fingerprint"],saved["selected"],saved["weather"],saved["horizon"])!=(source,bundle.fingerprint,snapshots,weather,horizon):
        st.info("Parametri cambiati: esegui un nuovo confronto.")
        return
    if saved.get("weather_note"):st.caption(saved["weather_note"])
    r=saved["result"]
    st.caption(f'{r["test_n"]}/28 origini confrontabili · {r["test_start"]} – {r["test_end"]} · calcolato {saved["acquired"]}')
    st.warning("Backtest con dati storici rivisti e ritardi ipotizzati: non certifica performance operativa ex ante. Nessuna promozione automatica del modello.")
    st.markdown("**Errore medio assoluto, GWh**")
    cols=st.columns(len(MODELS))
    for col,m in zip(cols,MODELS,strict=True):
        col.metric(LABELS[m],f'{r["scores"][m]["mae"]:.1f}')
    base=r["scores"]["autoregressive"]["mae"]
    bayes_base=r["scores"]["bayesian_base"]["mae"]
    if bayes_base>0:
        delta=(r["scores"]["bayesian_multi"]["mae"]/bayes_base-1)*100
        st.caption(f"Variazione MAE Bayes multivariato vs Bayes autoregressivo: {delta:+.1f}% sulle stesse date.")
    if base>0:
        change=(r["scores"]["multivariate"]["mae"]/base-1)*100
        st.caption(f"Variazione MAE multivariato rispetto al Ridge autoregressivo: {change:+.1f}%. Campione comune; nessuna garanzia futura.")
    st.caption(f"Copertura osservata Bayes multivariato (80% nominale): {r['scores']['bayesian_multi']['coverage_80']:.1f}% su {r['test_n']} origini.")
    backtest=pd.DataFrame(r["records"])
    st.line_chart(backtest.rename(columns=LABELS|{"actual":"Osservato"}),x="target",y=["Osservato",*LABELS.values()],y_label="GWh/giorno gas")
    forecast=r["forecast"]
    st.markdown("**Proiezione sperimentale**")
    if not forecast:
        st.info("Covariate o lag insufficienti alla data di riferimento: nessuna proiezione.")
    else:
        st.caption(f"Riferimento {forecast['origin']} · giorno gas target {forecast['target']} · non bollettino ufficiale")
        c=st.columns(len(MODELS))
        for col,m in zip(c,MODELS,strict=True):
            col.metric(LABELS[m],f"{forecast[m]:.1f} GWh")
        st.caption(f"Intervallo predittivo Bayes multivariato (80% nominale): {forecast['bayesian_multi_low']:.1f}–{forecast['bayesian_multi_high']:.1f} GWh; condizionato ai regressori.")
        if "empirical_low" in forecast:
            st.caption(f"Intervallo empirico descrittivo: {forecast['empirical_low']:.1f}–{forecast['empirical_high']:.1f} GWh; quantili degli errori osservati, copertura non calibrata.")
    with st.expander("Qualità, metodo e download"):
        st.dataframe(pd.DataFrame([{"Modello":LABELS[k],**v} for k,v in r["scores"].items()]),hide_index=True,width="stretch")
        if saved["cov"]:
            st.dataframe(saved["cov"],hide_index=True,width="stretch")
        st.dataframe(backtest,hide_index=True,width="stretch")
        st.download_button("Esporta backtest CSV",backtest.assign(source=bundle.origin.name,source_url=bundle.origin.url or "",
            horizon=r["horizon"],gas_lag=r["gas_lag"],external_lag=r["external_lag"],
            snapshot_sha256=bundle.fingerprint,features="; ".join(r["features"])).to_csv(index=False),
            "igor-predictive-backtest.csv","text/csv",key="predictive_csv")
        st.caption("Nessun valore futuro osservato usato come feature, nessun riempimento, scaling adattato per origine; le revisioni storiche non sono riproduzioni point-in-time. Nessun invio a LLM.")
