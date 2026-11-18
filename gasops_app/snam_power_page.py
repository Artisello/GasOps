"""Separate optional comparable Terna experiment, independent of original forecasts."""
import pandas as pd
import streamlit as st
from .models import utc_now
from .data import ROME
from .terna_history import STATE,summary,batch_id
from .snam_forecast import daily_vintages
from .snam_power_forecast import evaluate,MODELS,LAG

RESULT="snam_power_result_v1"
LABELS={"weekly":"Naive","official":"Snam","extended":"I.G.O.R. senza Terna","power":"I.G.O.R. + Terna"}


def panel(annual,horizon):
    with st.expander("Confronto Power–Gas · Terna"):
        state=st.session_state
        from .terna_forward import STATE as FORWARD,digest
        use_forward=st.radio("Segnali Terna",["Consuntivi ritardati","Previsioni MSD1 (carico + eolico)"],horizontal=True,key="snam_power_signal")!="Consuntivi ritardati"
        batches=state.get(FORWARD,[]) if use_forward else state.get(STATE,[])
        st.caption("Confronto sulla stessa finestra e sullo stesso campione. Nessun consuntivo elettrico futuro.")
        if not batches:
            st.caption("Carica lo storico in Sistema elettrico Terna → "+("Previsioni elettriche" if use_forward else "Giorni gas")+". Servono almeno 180 giorni di training e 30 di test.")
            return
        if use_forward:
            st.caption(f"{len(batches)} acquisizioni · solo previsioni acquisite entro il cutoff originale 15:00.")
        else:st.dataframe(summary(batches),hide_index=True,width="stretch")
        mode=st.radio("Disponibilità elettrica",["Archivio acquisito prima del cutoff","Studio retrospettivo (dati rivisti)"],key="power_forecast_vintage",disabled=use_forward)
        strict=use_forward or mode.startswith("Archivio")
        load=st.checkbox("Includi fabbisogno elettrico osservato",value=True,key="power_forecast_load",disabled=use_forward)
        if use_forward:st.caption("Carico ed eolico del giorno target, solo versioni acquisite entro il cutoff; nessun backfill retroattivo.")
        else:st.caption(f"Ritardo fisso G−{LAG} rispetto al giorno di pubblicazione Snam. Il backfill non prova che il dato fosse disponibile allora.")
        signatures=(tuple(sorted((y,v["sha256"]) for y,v in annual.items())),tuple((digest if use_forward else batch_id)(b) for b in batches),horizon,strict,load)
        result_key=RESULT+"_forward" if use_forward else RESULT
        if st.button("Confronta modelli Power–Gas",type="primary",key="power_forecast_run"):
            state.pop(result_key,None)
            try:
                asof=utc_now().astimezone(ROME).replace(tzinfo=None)
                with st.spinner("Backtest su giorni comuni…"):
                    vintages,_=daily_vintages(pd.concat([v["frame"] for v in annual.values()],ignore_index=True),asof)
                    r=evaluate(vintages,batches,horizon,asof,strict=strict,load=load,forward=use_forward)
                state[result_key]={"signature":signatures,"result":r}
            except ValueError as e:st.caption(str(e))
        saved=state.get(result_key)
        if not saved or saved["signature"]!=signatures:return
        r=saved["result"]
        st.caption(f'{r["n"]}/90 giorni confrontabili · {r["start"]} – {r["end"]} · {r["overlap"]} giorni comuni totali')
        a,b=st.columns(2)
        a.metric("MAE senza Terna",f'{r["scores"]["extended"]["mae"]/1000:.2f}')
        baseline=r["scores"]["extended"]["mae"]
        b.metric("MAE con Terna",f'{r["scores"]["power"]["mae"]/1000:.2f}',
                 f'{100*(1-r["scores"]["power"]["mae"]/baseline):+.1f}% riduzione errore' if baseline else None,delta_color="off")
        st.caption("Migliaia di unità native Jarvis; miglioramento non garantito. Nessuna promozione automatica.")
        f=pd.DataFrame(r["records"])
        chart=f.rename(columns=LABELS|{"actual":"Consuntivo provvisorio"})
        for c in ["Consuntivo provvisorio",*LABELS.values()]:chart[c]/=1000
        st.line_chart(chart,x="target",y=["Consuntivo provvisorio",*LABELS.values()],y_label="Migliaia di unità native")
        st.dataframe([{"Modello":LABELS[k],**{m:v/1000 if m!="wape" and v is not None else v for m,v in r["scores"][k].items()}} for k in MODELS],hide_index=True,width="stretch")
        st.warning("Consuntivo G−1 provvisorio; unità native e versione Snam non certificate. Terna orari assunti inizio intervallo; Thermal include tutti i combustibili. Timestamp di importazione dichiarati, non autenticati. Nessun uso operativo automatico.")
        st.download_button("CSV confronto Power–Gas",f.assign(horizon=horizon,strict=strict,include_load=load,power_lag=0 if use_forward else LAG,signal="MSD1 forecast" if use_forward else "lagged observed").to_csv(index=False),"igor-power-gas-backtest.csv","text/csv",key="power_forecast_export")
