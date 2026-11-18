"""Isolated challenger, same-sample baseline; no auto-promotion."""
import pandas as pd
import streamlit as st
from .models import utc_now
from .data import ROME
from .terna_context import STATE,scopes,digest
from .snam_forecast import daily_vintages
from .snam_power_forecast import evaluate

RESULT="snam_context_result_v1"

def panel(annual,horizon):
    with st.expander("Terna · capacità, industria e scambi nel forecasting"):
        state=st.session_state
        batches=state.get(STATE,[])
        kinds=[k for k in ("capacity","industry","exchange") if scopes(batches,k)]
        if not kinds:
            st.caption("Acquisisci dati nella vista Terna → Capacità e industria.")
            return
        kind=st.selectbox("Segnale esterno",kinds,format_func=lambda k:{"capacity":"Capacità prevista","industry":"IMCEI del mese precedente disponibile","exchange":"Scambi programmati"}[k],key="snam_context_kind")
        scope=st.selectbox("Perimetro",scopes(batches,kind),format_func=lambda s:" · ".join(s),key="snam_context_scope")
        signature=(tuple(sorted((y,v["sha256"]) for y,v in annual.items())),tuple(digest(b) for b in batches),horizon,kind,scope)
        st.caption("Solo versioni acquisite prima del cutoff 15:00; almeno 180 giorni di training e 30 di test. L’IMCEI usa mesi conclusi e disponibili, non il dato del mese target.")
        if st.button("Valuta contributo del segnale",key="snam_context_run"):
            state.pop(RESULT,None)
            try:
                asof=utc_now().astimezone(ROME).replace(tzinfo=None)
                v,_=daily_vintages(pd.concat([x["frame"] for x in annual.values()],ignore_index=True),asof)
                r=evaluate(v,batches,horizon,asof,context=(kind,scope))
                state[RESULT]={"signature":signature,"result":r}
            except ValueError as e:st.caption(str(e))
        saved=state.get(RESULT)
        if not saved or saved["signature"]!=signature:return
        r=saved["result"]
        a,b=st.columns(2)
        a.metric("MAE baseline",f'{r["scores"]["extended"]["mae"]/1000:.2f}')
        b.metric("MAE con segnale",f'{r["scores"]["power"]["mae"]/1000:.2f}')
        st.caption(f'{r["n"]} giorni comuni · migliaia di unità native Jarvis · nessuna promozione automatica.')
        f=pd.DataFrame(r["records"]).rename(columns={"actual":"Consuntivo G−1","extended":"Baseline","power":"Con segnale"})
        st.line_chart(f,x="target",y=["Consuntivo G−1","Baseline","Con segnale"],y_label="Unità native Jarvis")
        st.download_button("CSV confronto",f.to_csv(index=False),"igor-terna-context-backtest.csv","text/csv",key="snam_context_csv")
