"""Forecast of closing publication, in the existing Jarvis view."""
import streamlit as st
from .intraday import evaluate,METRICS
from .italiano import numero

LABELS={"sas_gwh":"SAS","expected_linepack_gwh":"Linepack atteso","expected_withdrawal_gwh":"Prelievo atteso"}

def panel(versions,day,now,prefix):
    with st.expander("Stima di chiusura · analisi storica"):
        available=[k for k in METRICS if versions.loc[versions.gas_day==day,k].notna().any()]
        if not available:return
        metric=st.selectbox("Indicatore",available,format_func=LABELS.__getitem__,key=prefix+"_closing_metric")
        result=evaluate(versions,day,metric,now)
        if result is None:
            st.caption("Stima non disponibile per questa versione: verifica aggiornamento e copertura.")
            return
        if "estimate" not in result:
            st.caption(f'{result["n"]}/{result["required"]} giorni storici confrontabili. Importa ulteriori pubblicazioni prima del calcolo.')
            return
        a,b=st.columns(2)
        a.metric("Ultima stima importata",numero(result["published"],1)+" GWh")
        b.metric("Stima di chiusura I.G.O.R.",numero(result["estimate"],1)+" GWh")
        st.caption(f'Intervallo empirico 80%: {numero(result["low"],1)} – {numero(result["high"],1)} GWh · {result["n"]} giorni · {result["first"]} – {result["last"]}')
        scores=result["scores"]
        if scores:
            a,b,c=st.columns(3)
            a.metric("MAE stima fonte",numero(scores["mae_raw"],1)+" GWh")
            b.metric("MAE correzione",numero(scores["mae_corrected"],1)+" GWh")
            c.metric("Copertura",numero(scores["coverage_80"],1)+"%")
            st.caption(f'{scores["n"]} giorni di verifica progressiva.')
        else:st.caption("Verifica progressiva non ancora disponibile: servono almeno 20 giorni dopo il minimo di training.")
        st.caption("Previsione sperimentale dell’ultima stima pubblicata prima delle 06:00, non consuntivo fisico. Non calibrata per uso operativo; non sostituisce Jarvis.")
        with st.popover("Metodo",icon=":material/info:"):
            st.write("Mediana delle revisioni storiche a pari tempo residuo alla fine del giorno gas. Intervallo dai quantili 10/90. Ultima pubblicazione storica entro 90 minuti dalla chiusura; nessun dato dello stesso giorno futuro. Fuso Europe/Rome con calcolo in UTC. CdR XCII, cap. 9 §1.1, p. 362.")
