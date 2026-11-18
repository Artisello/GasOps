"""Matched sample challenger, acquisition time only."""
import pandas as pd
import streamlit as st
from .models import utc_now
from .data import ROME
from .entsog_vintages import STATE,points,digest,FORWARD
from .entsog_network import NAMES
from .snam_forecast import daily_vintages
from .snam_power_forecast import evaluate

RESULT="snam_entsog_result_v1"

def panel(annual,horizon):
    with st.expander("ENTSOG · nomine e rinomine nel forecasting"):
        state=st.session_state;batches=state.get(STATE,[])
        available=points([b for b in batches if b["complete"] and any(r["indicator"] in FORWARD and not r["assumed"] for r in b["rows"])])
        if not available:
            st.caption("Acquisisci programmi nella vista Interconnessioni gas.")
            return
        point=st.selectbox("Punto e direzione",available,key="snam_entsog_point")
        indicator=st.selectbox("Programma",FORWARD,format_func=NAMES.__getitem__,key="snam_entsog_indicator")
        sig=(tuple(sorted((y,v["sha256"]) for y,v in annual.items())),tuple(digest(b) for b in batches),horizon,point,indicator)
        st.caption("Solo acquisizioni entro cutoff 15:00; almeno 180 giorni training e 30 test; singolo punto.")
        if st.button("Confronta modelli con ENTSOG",key="snam_entsog_run"):
            state.pop(RESULT,None)
            try:
                asof=utc_now().astimezone(ROME).replace(tzinfo=None)
                v,_=daily_vintages(pd.concat([x["frame"] for x in annual.values()],ignore_index=True),asof)
                r=evaluate(v,batches,horizon,asof,network=(point,indicator))
                state[RESULT]={"signature":sig,"result":r}
            except ValueError as e:st.caption(str(e))
        saved=state.get(RESULT)
        if not saved or saved["signature"]!=sig:return
        r=saved["result"];a,b=st.columns(2)
        a.metric("MAE baseline",f'{r["scores"]["extended"]["mae"]/1000:.2f}')
        b.metric("MAE con ENTSOG",f'{r["scores"]["power"]["mae"]/1000:.2f}')
        st.caption(f'{r["n"]} giorni comuni · migliaia di unità native Jarvis · studio sperimentale.')
        f=pd.DataFrame(r["records"]).rename(columns={"actual":"Consuntivo G−1","extended":"Baseline","power":"Con ENTSOG"})
        st.line_chart(f,x="target",y=["Consuntivo G−1","Baseline","Con ENTSOG"],y_label="Unità native")
