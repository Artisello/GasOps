"""Read-only management overview; data from the current session or attributed archives."""
from datetime import date
import pandas as pd
import streamlit as st

from .data import ROME
from .models import utc_now
from .italiano import numero
from .advanced_kpis import (operations_scores,balancing_scores,archive_scores,participant_scores,
                            network_scores,storage_scores,historical_scores,benchmark_scores,power_scores,export_csv)


def panel():
    now=utc_now().astimezone(ROME)
    st.caption("Cabina di controllo · dati pubblici e registri importati · nessuna simulazione")
    st.markdown("**Priorità operative**")
    state=st.session_state
    chosen=st.date_input("Mese delle attività e dei bilanci",value=now.date().replace(day=1),
                         min_value=date(2000,1,1),max_value=now.date(),key="advanced_kpi_month")
    year,month=chosen.year,chosen.month
    archive=state.get("jarvis_aggregate_archive_v1",{}).get("records",())
    series=sorted({(r.metric,r.unit) for r in archive if r.family=="balance" and (r.gas_day.year,r.gas_day.month)==(year,month)})
    with st.expander("Perimetro settlement",expanded=False):
        metric,unit=st.selectbox("Serie pubblica Jarvis",series or [("withdrawals","GWh")],
                                 format_func=lambda x:f"{x[0]} · {x[1]}",key="advanced_balance_series")
        saved=state.get("settlement_desk_csv_v1",{})
        rows=saved.get("rows")
        users=sorted({r.user for r in rows}) if rows else []
        user=st.selectbox("Partecipante (registro importato)",[None,*users],
                          format_func=lambda x:x if x is not None else "Non selezionato",key="advanced_participant")
        st.caption("Nessun aggregato economico tra partecipanti. Il selettore non entra nel CSV.")
    ops=state.get("bso_tasks_v1")
    operational=(operations_scores(ops["tasks"] if ops else None,now,year,month)+
                 balancing_scores(state.get("jarvis_public_snapshot_v1"),now,year,month)+
                 archive_scores(archive,now,year,month,metric,unit)+
                 participant_scores(rows,user,now,year,month))
    primary=("overdue","sas_mean","eligible")
    by={r.code:r for r in operational}
    cards=st.columns(3)
    for col,key in zip(cards,primary,strict=True):
        r=by[key]
        with col,st.container(border=True):
            st.caption(r.area)
            precision=0 if key=="overdue" else 1
            st.metric(r.label,("—" if r.value is None else numero(r.value,precision)+(f" {r.unit}" if r.unit else "")))
            st.caption(r.coverage+" · "+r.status)
    st.caption("KPI proposti, non SLA o indicatori ufficiali interni Snam. Nessuna soglia o punteggio composito inventato.")
    if by["overdue"].value is not None and by["overdue"].value>0:
        st.warning("Attività oltre termine nel registro: verifica l'agenda in Scadenze.")
    if any(by[k].value is None for k in primary):
        st.info("Alcuni KPI non sono misurabili: importa i registri autorizzati nelle viste dedicate. Le assenze non valgono zero.")
    st.markdown("**Dettaglio operativo · mese selezionato**")
    st.dataframe([{"Area":r.area,"KPI":r.label,"Valore":r.value,"Unità":r.unit,"Periodo":r.period,
                   "Copertura":r.coverage,"Stato":r.status} for r in operational],hide_index=True,width="stretch")
    st.markdown("[Bilanci e stime Jarvis](/security-of-supply) · [Settlement](/balancing) · Scadenze nella vista Registro operativo.")
    st.divider()
    st.subheader("Contesto esterno")
    context=network_scores(state.get("entsog_network_result_v1"),now)+storage_scores(state.get("AGSI+_IT"),now)+power_scores(state.get("terna_power_v1"))
    try:
        context+=historical_scores(state.get("acer_lng_result_v1"),now)+benchmark_scores()
    except (OSError,ValueError,KeyError,StopIteration):
        st.warning("Uno o più archivi storici non sono disponibili o validi.")
    st.caption("Ultima osservazione per fonte · periodo indipendente dal filtro mensile · non performance del team.")
    st.dataframe([{"Area":r.area,"KPI":r.label,"Valore":r.value,"Unità":r.unit,"Periodo":r.period,
                   "Perimetro":r.scope,"Stato":r.status,"Copertura / fonte":r.coverage} for r in context],hide_index=True,width="stretch")
    st.markdown("[Aggiorna fonti rete e stoccaggi](/security-of-supply) · [Aggiorna ACER e Terna](/market)")
    with st.expander("Definizioni, provenienza e download"):
        all_rows=operational+context
        st.dataframe([{"KPI":r.label,"Definizione":r.definition,"Fonte":r.source,
                       "URL":r.source_url,"Periodo":r.period,"Perimetro":r.scope,
                       "Stato":r.status,"Copertura":r.coverage} for r in all_rows],
                     hide_index=True,width="stretch",column_config={"URL":st.column_config.LinkColumn("Fonte web")})
        st.download_button("Esporta scorecard CSV",export_csv(all_rows),"igor-bso-scorecard.csv","text/csv",key="advanced_kpi_csv")
        st.caption("Solo indicatori aggregati della sessione e delle fonti storiche incluse. Nessuna nuova richiesta di rete, persistenza condivisa o invio a LLM da questa vista.")
