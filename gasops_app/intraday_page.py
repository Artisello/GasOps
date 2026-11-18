"""Forecast of closing publication, in the existing Jarvis view."""
import streamlit as st
from .intraday import evaluate,METRICS,decision_support,replay_times,gas_end,MIN_TEST
from .italiano import numero
from .data import ROME
from .visuals import kpi_grid,local_time
from datetime import datetime

LABELS={"sas_gwh":"SAS","expected_linepack_gwh":"Linepack atteso","expected_withdrawal_gwh":"Prelievo atteso"}

def panel(versions,day,now,prefix):
    with st.expander("Stima di chiusura · analisi storica"):
        available=[k for k in METRICS if (prefix!="balancing" or k!="sas_gwh") and versions.loc[versions.gas_day==day,k].notna().any()]
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


def decision_panel(versions,day,now,prefix):
    st.subheader("Chiusura giorno gas · SAS")
    st.caption("Previsione sperimentale dell’ultima stima pubblicata. Non del consuntivo fisico.")
    cutoff=None
    if gas_end(day)<=now:
        times=replay_times(versions,day,now)
        if not times:
            st.caption("Replay non disponibile: nessuna pubblicazione SAS oltre 90 minuti prima della chiusura.")
            return
        cutoff=st.selectbox("Replay storico · pubblicazione disponibile",times,
                            format_func=local_time,key=prefix+"_sas_replay_"+str(day))
        st.caption("Ricostruzione storica: usa solo le informazioni precedenti alla pubblicazione scelta.")
    r=decision_support(versions,day,now,as_of=cutoff)
    status=r["status"]
    c=r.get("candidate")
    scores=r.get("scores")
    picked=status=="candidate"
    detail={"missing":"Nessun SAS utilizzabile per questo orario.",
            "stale":"Pubblicazione oltre 3 ore fa: aggiornare prima di interpretare il modello.",
            "near_close":"Meno di 90 minuti alla chiusura: usa la pubblicazione più recente.",
            "insufficient":f"Storico omogeneo insufficiente: {r.get('n',0)}/{r.get('required',30)} giorni.",
            "unvalidated":"Verifica progressiva insufficiente: correzione solo esplorativa.",
            "benchmark":"La correzione non supera tutti i criteri di studio: mantieni il riferimento pubblicato.",
            "candidate":"Correzione sperimentale: ha superato i criteri storici di studio."}
    kpi_grid([("SAS pubblicato",r.get("published"),"GWh","Fonte dichiarata",1,""),
              ("Stima di chiusura",c["estimate"] if picked else None,"GWh","Modello di revisione" if picked else "Modello non selezionato",1,"blue"),
              ("Tempo alla chiusura",r["hours_to_close"],"h","Al momento del replay" if cutoff else "Giorno gas in corso",1,"")])
    if r.get("issued"):
        st.caption("Pubblicazione: "+local_time(datetime.fromisoformat(r["issued"]))+
                   " · fine giorno gas: "+local_time(datetime.fromisoformat(r["ends_at"])))
    if status in ("stale","near_close","missing"):
        st.warning(detail[status])
    else:
        st.caption(detail.get(status,"Stima non disponibile."))
    if picked:
        st.markdown("**Distribuzione empirica SAS alla chiusura**")
        p=r["distribution"]
        kpi_grid([("SAS negativo",100*p["negative"],"%","Segno della stima",1,""),
                  ("SAS nullo",100*p["zero"],"%","Segno della stima",1,""),
                  ("SAS positivo",100*p["positive"],"%","Segno della stima",1,"")])
        st.caption("Intervallo empirico 80%: "+numero(c["low"],1)+" – "+numero(c["high"],1)+
                   " GWh · "+str(r["n"])+" giorni comparabili. Non probabilità di deficit fisico.")
    if c:
        with st.expander("Validazione e modello candidato"):
            st.caption(f'Storico: {r["first"]} – {r["last"]} · {r["n"]} giorni a orizzonte confrontabile.')
            st.caption("Candidato: "+numero(c["estimate"],1)+" GWh · intervallo 80%: "+
                       numero(c["low"],1)+" – "+numero(c["high"],1)+" GWh.")
            if scores:
                st.dataframe([{"Indicatore":"MAE (GWh)","Pubblicato":scores["mae_raw"],"Corretto":scores["mae_corrected"]},
                              {"Indicatore":"Brier multiclasse (↓)","Pubblicato":scores["brier_raw"],"Corretto":scores["brier"]}],
                             hide_index=True,width="stretch")
                st.caption(f'{scores["n"]} verifiche progressive · copertura intervallo: '+numero(scores["coverage_80"],1)+"%.")
            else:
                st.caption(f"Servono almeno {MIN_TEST} verifiche progressive dopo i primi 30 giorni.")
            st.caption("Criteri sperimentali: miglioramento MAE ≥5%, copertura empirica ≥70%, Brier non peggiore del segno pubblicato. Non soglie operative Snam.")
    if c and picked:
        st.caption("Il segno è quello importato; nessuna indicazione di acquisto/vendita o automatismo di intervento.")
