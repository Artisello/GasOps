"""Compact additions in existing views; no extra navigation."""
from datetime import date,datetime,timedelta
from decimal import Decimal
from hashlib import sha256
import pandas as pd
import streamlit as st
from .models import utc_now
from .data import ROME
from .operating_rules import calendar,balance_checks,parse_balance,template,STATE,MAX_BYTES
from .visuals import local_time


def calendar_panel(now):
    with st.expander("Scadenze da Codice · calcolo"):
        st.caption("Edizioni di studio XCII / 2023-I. Calendario lavorativo esplicito; non sostituisce gli avvisi Snam.")
        a,b=st.columns(2)
        d=a.date_input("Giorno gas",value=now.date() if now.hour>=6 else now.date()-timedelta(days=1),key="rules_day")
        m=b.date_input("Mese di competenza",value=now.date().replace(day=1),key="rules_month")
        raw=st.text_input("Festività aggiuntive (YYYY-MM-DD, separate da virgole)",key="rules_holidays")
        try:
            holidays={date.fromisoformat(x.strip()) for x in raw.split(",") if x.strip()}
            if len(holidays)>100:raise ValueError()
        except ValueError:
            st.caption("Usa date ISO separate da virgola.")
            return
        rows=[]
        for label,due,ref in calendar(d,m,holidays):
            timed=isinstance(due,datetime)
            passed=now>due if timed else now.date()>due
            rows.append({"Adempimento":label,"Termine":local_time(due) if timed else due.strftime("%d/%m/%Y"),
                         "Stato data":"Trascorso" if passed else "Oggi" if (due.date() if timed else due)==now.date() else "Futuro",
                         "Riferimento":ref})
        st.dataframe(rows,hide_index=True,width="stretch")
        st.caption("Sabato e domenica esclusi nei termini lavorativi; festività solo se inserite. Stato data, non stato di esecuzione. Verificare edizione, eccezioni e calendario ufficiale.")


def network_panel():
    now=utc_now()
    with st.expander("Quadratura del bilancio di rete"):
        st.latex(r"I+S=P+C+PE+\Delta LPC+GNC")
        st.caption("CdR XCII · cap. 9 §3.1.1 · pp. 368–370. Solo aggregati SRG, stessa fase e giorno gas, GWh a PCS coerente.")
        st.download_button("Modello CSV vuoto",template(),"igor-bilancio-rete.csv","text/csv",key="network_balance_template")
        with st.form("network_balance_import"):
            f=st.file_uploader("Componenti del bilancio",type=["csv"],key="network_balance_file")
            ok=st.checkbox("Confermo dati pubblici autorizzati, perimetro e unità.")
            submitted=st.form_submit_button("Verifica bilancio")
        if submitted:
            if f is None or not ok:st.caption("Seleziona il CSV e conferma la provenienza.")
            else:
                try:
                    raw=f.getvalue()
                    st.session_state[STATE]={"rows":parse_balance(raw,now),"sha256":sha256(raw).hexdigest()}
                except (ValueError,TypeError):st.caption("CSV non valido o incompleto. Dati precedenti invariati.")
        saved=st.session_state.get(STATE)
        if not saved:return
        stage=st.selectbox("Fase",sorted({r["stage"] for r in saved["rows"]}),format_func=lambda x:"Definitivo" if x=="definitive" else "Provvisorio",key="network_balance_stage")
        rows=[r for r in saved["rows"] if r["stage"]==stage]
        tol=Decimal(str(st.number_input("Tolleranza di studio (GWh)",min_value=0.,max_value=1e6,value=.01,step=.01,key="network_balance_tolerance")))
        checks=balance_checks(rows,tol);compared=[x for x in checks if x["delta_GNC"] is not None]
        cols=st.columns(2 if compared else 1);cols[0].metric("Giorni calcolati",len(checks))
        if compared:cols[1].metric("Da verificare",sum(x["esito"]=="Da verificare" for x in compared))
        frame=pd.DataFrame(checks)
        chart=frame[["gas_day","GNC_calcolato"]].copy()
        chart["GNC_calcolato"]=chart["GNC_calcolato"].astype(float)
        if len(chart)>1:st.line_chart(chart,x="gas_day",y="GNC_calcolato",y_label="GWh")
        else:st.metric("GNC calcolato",str(checks[0]["GNC_calcolato"])+" GWh")
        st.dataframe(checks,hide_index=True,width="stretch")
        st.caption("GNC calcolato per differenza; verifica solo se GNC pubblicato è fornito. Nessuna equivalenza con SAS o DS. Dati di sessione, non inviati ad AI.")
        st.download_button("Esporta controlli CSV",frame.to_csv(index=False),"igor-quadrature.csv","text/csv",key="network_balance_export")
        with st.expander("Provenienza"):
            st.text("SHA-256 · "+saved["sha256"])
        if st.button("Rimuovi bilancio importato",key="network_balance_clear"):
            st.session_state.pop(STATE,None)
            st.rerun()
