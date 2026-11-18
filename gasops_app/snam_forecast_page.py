"""Historical Jarvis forecasting: private session, explicit file import, no auto-promote."""
from datetime import datetime
import pandas as pd
import streamlit as st
from .data import ROME
from .models import utc_now
from .snam_forecast import read_annual,daily_vintages,evaluate,MAX_FILES,MODELS
from .jarvis_archive import SOURCE

STATE="snam_forecast_annual_v1"
RESULT="snam_forecast_result_v1"
LABELS={"weekly":"Naive settimanale","official":"Pubblicazione Snam","igor":"Snam + I.G.O.R.","extended":"I.G.O.R. esteso"}


def panel():
    st.subheader("Forecasting Snam Jarvis")
    st.caption("Riconsegnato · G, G+1, G+2 · confronto con consuntivo provvisorio G−1")
    saved=st.session_state.get(STATE,{})
    with st.expander("Archivi annuali originali",expanded=not saved):
        st.markdown(f"[Dati pubblici Jarvis]({SOURCE})")
        with st.form("snam_forecast_import"):
            file=st.file_uploader("DatiOperativi_AAAA-IT.xlsx o ZIP annuale",type=["xlsx","zip"])
            consent=st.checkbox("Confermo dati pubblici, autorizzati e non riservati.")
            submit=st.form_submit_button("Carica annualità")
        if submit:
            if file is None or not consent:
                st.warning("Seleziona un file e conferma l'autorizzazione.")
            else:
                try:
                    with st.spinner("Lettura delle quattro serie di pubblicazione…"):
                        item=read_annual(file.getvalue(),file.name)
                        existing=saved.get(item["year"])
                        if existing and existing["sha256"]!=item["sha256"]:
                            raise ValueError("Annualità diversa già presente")
                        if not existing and len(saved)>=MAX_FILES:
                            raise ValueError("Limite annualità")
                        saved={**saved,item["year"]:item}
                        st.session_state[STATE]=saved
                        st.session_state.pop(RESULT,None)
                    st.success("Annualità acquisita.")
                except (ValueError,TypeError,RuntimeError,OSError):
                    st.error("Formato non valido, annualità già presente con altro hash o limite raggiunto. Archivio invariato.")
        if saved:
            st.dataframe([{"Anno":y,"File":v["name"],"Righe entro le 15":len(v["frame"]),"Timestamp non leggibili":v["bad"],"SHA-256":v["sha256"]} for y,v in sorted(saved.items())],hide_index=True,width="stretch")
            if st.button("Rimuovi annualità caricate",key="snam_forecast_clear"):
                st.session_state.pop(STATE,None)
                st.session_state.pop(RESULT,None)
                st.rerun()
    if not saved:
        st.info("Carica le annualità 2023–2026 per eseguire il confronto. Nessuna serie sintetica.")
        return
    st.caption("Unità nativa: grafici ed errori visualizzati in migliaia di unità, senza assumere MWh per tutti gli anni. Orari locali dichiarati nel file; non disponibilità storica certificata.")
    h=st.selectbox("Orizzonte", [0,1,2],format_func=lambda x:"G" if x==0 else f"G+{x}",key="snam_horizon")
    extended=st.checkbox("Modello esteso e incertezza",key="snam_extended")
    models=(*MODELS,"extended") if extended else MODELS
    signatures=tuple((y,v["sha256"]) for y,v in sorted(saved.items()))
    if st.button("Esegui backtest",type="primary",key="snam_forecast_run"):
        st.session_state.pop(RESULT,None)
        try:
            asof=utc_now().astimezone(ROME).replace(tzinfo=None)
            with st.spinner("Confronto walk-forward, finestra comune…"):
                vintages,conflicts=daily_vintages(pd.concat([v["frame"] for v in saved.values()],ignore_index=True),asof)
                if extended:
                    from .snam_reliability import evaluate_extended
                    result=evaluate_extended(vintages,h,asof)
                else:
                    result=evaluate(vintages,h,asof)
            st.session_state[RESULT]={"h":h,"extended":extended,"hashes":signatures,"result":result,"conflicts":conflicts,"checked":asof.isoformat()}
        except ValueError as exc:
            st.error(str(exc))
    cached=st.session_state.get(RESULT)
    if not cached or cached["h"]!=h or cached.get("extended",False)!=extended or cached["hashes"]!=signatures:
        return
    r=cached["result"]
    st.caption(f'{r["n"]}/90 date nella finestra {r["start"]} – {r["end"]} · {cached["conflicts"]} origini/fogli ambigui esclusi · cutoff locale 15:00')
    cols=st.columns(len(models))
    for col,k in zip(cols,models,strict=True):
        col.metric(LABELS[k],f'{r["scores"][k]["mae"]/1000:.2f}',help="MAE in migliaia di unità native")
    baseline=r["scores"]["official"]["mae"]
    if baseline>0:
        change=100*(r["scores"]["igor"]["mae"]/baseline-1)
        st.caption(f"Variazione MAE rispetto alla previsione Snam: {change:+.2f}%. Nessuna sostituzione automatica.")
    if extended:
        st.caption("Modello esteso: clienti diretti, altre reti ed esportazioni; campione comune.")
        e=r["empirical"]
        if e["n"]:
            st.caption(f'Intervallo empirico nominale 90% · copertura osservata {e["coverage"]:.1f}% su {e["n"]} giorni · ampiezza media {e["mean_width"]/1000:.2f} migliaia di unità. Nessuna garanzia.')
    f=pd.DataFrame(r["records"])
    chart=f.rename(columns=LABELS|{"actual":"Consuntivo provvisorio"})
    for col in [*[LABELS[k] for k in models],"Consuntivo provvisorio"]:
        chart[col]=chart[col]/1000
    st.line_chart(chart,x="target",y=["Consuntivo provvisorio",*[LABELS[k] for k in models]],y_label="Migliaia di unità native")
    if r["candidate"]:
        item=r["candidate"]
        st.markdown("**Ultima proiezione disponibile nell'archivio**")
        st.caption(f"Giorno gas {item['target']} · pubblicazione {item['published']} · non necessariamente attuale")
        a,b=st.columns(2)
        a.metric("Previsione Snam",f'{item["official"]/1000:.2f}')
        b.metric("Correzione sperimentale",f'{item["igor"]/1000:.2f}')
        if extended:
            st.metric("I.G.O.R. esteso",f'{item["extended"]/1000:.2f}')
            if "low" in item:
                st.caption(f'Intervallo empirico nominale 90%: {item["low"]/1000:.2f} – {item["high"]/1000:.2f} · {item["cal_n"]} errori precedenti disponibili.')
    st.caption("Terna: dati elettrici nella vista dedicata; non inclusi senza storico e vintage comuni.")
    st.warning("Riferimento provvisorio, non bilancio definitivo. Dati storici eventualmente revisionati, unità annuali da confermare e nessuna attestazione di disponibilità ex ante.")
    with st.expander("Metriche, metodo ed esportazione"):
        st.dataframe([{"Modello":LABELS[k],**{m:v/1000 if m!="wape" and v is not None else v for m,v in score.items()}} for k,score in r["scores"].items()],hide_index=True,width="stretch")
        st.caption("MAE, RMSE e bias in migliaia di unità native; WAPE in %. Ridge sui residui Snam con previsione, immesso e HDD pubblicati nello stesso slot. Training ≥180 giorni, date comuni, etichette disponibili solo dopo cutoff G+1. Scaling su training.")
        st.download_button("Esporta risultati CSV",f.assign(horizon=h,unit="native",cutoff="15:00 local",source=SOURCE).to_csv(index=False),"igor-snam-backtest.csv","text/csv",key="snam_forecast_export")
