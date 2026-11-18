"""Bayesian Snam forecast view; explicit experiments, no promotion."""
import pandas as pd
import streamlit as st
from .models import utc_now
from .data import ROME
from .snam_forecast import daily_vintages
from .snam_bayesian import groups,signature,evaluate,MODELS

STATE="snam_bayesian_v1"
LABELS={"official":"Snam","ridge":"Ridge esteso","bayesian_base":"Bayes Jarvis","bayesian_multi":"Bayes multi-fonte"}

def panel(annual,horizon):
    with st.expander("Bayesiano · multi-fonte",expanded=False):
        state=st.session_state;options=groups(state)
        st.caption("Jarvis (HDD, immesso, clienti diretti, altre reti, export) sempre inclusi; fonti esterne solo da vintage anteriori al cutoff.")
        keys=st.multiselect("Gruppi di variabili aggiuntivi",list(options),format_func=lambda k:options[k]["label"],max_selections=4,key="snam_bayes_groups")
        if not options:st.caption("Modello Jarvis disponibile; acquisisci storico Terna o programmi ENTSOG per estenderlo.")
        sig=(tuple(sorted((y,v["sha256"]) for y,v in annual.items())),horizon,signature(options,keys))
        if st.button("Valuta modello bayesiano",type="primary",key="snam_bayes_run"):
            state.pop(STATE,None)
            try:
                asof=utc_now().astimezone(ROME).replace(tzinfo=None)
                with st.spinner("Backtest bayesiano walk-forward…"):
                    v,_=daily_vintages(pd.concat([x["frame"] for x in annual.values()],ignore_index=True),asof)
                    r=evaluate(v,horizon,asof,options,keys)
                state[STATE]={"signature":sig,"result":r}
            except ValueError as e:st.caption(str(e))
        saved=state.get(STATE)
        if not saved or saved["signature"]!=sig:return
        r=saved["result"]
        models=MODELS if keys else MODELS[:-1]
        st.caption(f'{r["n"]}/90 giorni comuni · {r["start"]} – {r["end"]} · unità native Jarvis')
        for col,k in zip(st.columns(len(models)),models):
            col.metric(LABELS[k]+" · MAE",f'{r["scores"][k]["mae"]/1000:.2f}')
        chosen="bayesian_multi" if keys else "bayesian_base"
        s=r["scores"][chosen]
        baseline=r["scores"]["bayesian_base"]["mae"]
        if keys and baseline>0:st.caption(f"Variazione MAE rispetto a Bayes Jarvis: {100*(s['mae']/baseline-1):+.1f}% sullo stesso campione.")
        st.caption(f'Intervallo nominale 80% · copertura osservata {s["coverage_80"]:.1f}% · MAE in migliaia di unità.')
        frame=pd.DataFrame(r["records"])
        chart=frame.rename(columns=LABELS|{"actual":"Consuntivo G−1"})
        st.line_chart(chart,x="target",y=["Consuntivo G−1",*[LABELS[k] for k in models]],y_label="Unità native")
        p=r["candidate"]
        if p:
            st.markdown("**Ultima previsione disponibile nell’archivio**")
            st.caption(p["target"]+" · origine "+p["origin"])
            st.metric(LABELS[chosen],f'{p[chosen]/1000:.2f}')
            st.caption(f'Intervallo 80%: {p[chosen+"_low"]/1000:.2f}–{p[chosen+"_high"]/1000:.2f} · migliaia di unità native')
        with st.expander("Metriche, fonti ed esportazione"):
            st.dataframe([{"Modello":LABELS[k],**r["scores"][k]} for k in models],hide_index=True,width="stretch")
            st.caption("Intervalli condizionali, non includono incertezza delle covariate. Consuntivo G−1 provvisorio, import dichiarati, nessuna promozione automatica.")
            st.download_button("CSV backtest bayesiano",frame.assign(horizon=horizon,groups="; ".join(r["groups"])).to_csv(index=False),"igor-snam-bayesian.csv","text/csv",key="snam_bayes_csv")
