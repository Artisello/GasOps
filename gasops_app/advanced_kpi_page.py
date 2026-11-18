"""Live-first BSO overview. Explicit refresh only; no demo fallback."""
from datetime import date
import streamlit as st

from .data import ROME
from .models import utc_now
from .italiano import numero
from .advanced_kpis import (operations_scores,balancing_scores,archive_scores,participant_scores,
    network_scores,storage_scores,historical_scores,benchmark_scores,power_scores,export_csv,
    latest_power_scores,native_balance_scores)

HIGHLIGHTS=("baf_imbalance_share","baf_net_adjusted_neutrality","baf_tso_buy_share","terna_gas","mase_prod","lng")
RECENT=("srg_withdrawals","srg_power","srg_industry","national_demand","psv","lng","native_provisional","native_final","native_revision","stock","fill","terna_thermal_day","terna_load_day","flow","util","ren_gap","power_corr")
PRECISION={"baf_net_adjusted_neutrality":2,"mase_prod":2,"power_corr":2,"lng":2,"lng_spread":2,"overdue":0}


def _cards(metrics,limit=3):
    for start in range(0,len(metrics),limit):
        group=metrics[start:start+limit]
        cols=st.columns(len(group))
        for col,r in zip(cols,group):
            with col:
                st.metric(r.label,numero(r.value,PRECISION.get(r.code,1))+(f" {r.unit}" if r.unit else ""),help=r.definition)
                st.caption(f"{r.source} · {r.period} · {r.status}")


def panel():
    now=utc_now().astimezone(ROME)
    state=st.session_state
    st.caption("Italia · ultimi dati pubblicati e controlli BSO")
    from .live_sources_page import controls
    from .live_sources import market_scores
    controls("bso")
    context=network_scores(state.get("entsog_network_result_v1"),now)+storage_scores(state.get("AGSI+_IT"),now)+power_scores(state.get("terna_power_v1"))
    context+=market_scores(state,now)
    context+=latest_power_scores(state.get("terna_power_v1"),now)+native_balance_scores(state.get("jarvis_native_v1"),now)
    for getter in (lambda:historical_scores(state.get("acer_lng_result_v1"),now),benchmark_scores):
        try:
            context+=getter()
        except (OSError,ValueError,KeyError,StopIteration):
            with st.expander("Copertura archivio"):
                st.caption("Un archivio pubblico non è disponibile o validabile.")
    context_by={r.code:r for r in context}
    def current(r):
        try:
            period=date.fromisoformat(r.period if len(r.period)==10 else r.period+"-01")
        except ValueError:
            return False
        age=(now.date()-period).days
        return 0<=age<=(93 if len(r.period)==7 else 4) and not any(x in r.status.lower() for x in ("storico","verificare","sospeso","aggiornare"))
    recent=[context_by[k] for k in RECENT if k in context_by and context_by[k].value is not None and current(context_by[k])]
    dated=[context_by[k] for k in RECENT if k in context_by and context_by[k].value is not None and context_by[k] not in recent and k not in HIGHLIGHTS]
    if recent:
        st.markdown("**Ultimi dati caricati**")
        _cards(recent[:6])
        if len(recent)>6:
            with st.expander("Altri dati caricati"):
                _cards(recent[6:])
        st.caption("Periodi e perimetri distinti: non necessariamente dati di oggi.")
    else:
        st.caption("Aggiorna le fonti per visualizzare gli ultimi dati disponibili.")
    if dated:
        with st.expander("Ultimi dati validi · periodi precedenti o da verificare"):
            _cards(dated)
    public=[context_by[k] for k in HIGHLIGHTS if k in context_by and context_by[k].value is not None and context_by[k] not in recent]
    if public:
        with st.expander("Benchmark storici e statistiche annuali"):
            _cards(public)
            st.caption("Periodi espliciti · non dati odierni né KPI interni.")
    with st.expander("Come aggiornare i dati"):
        st.markdown("[Rete Snam · importazione nativa e stime Jarvis](/security-of-supply) · [Terna e ACER](/market)")
        st.caption("I dati acquisiti nelle viste dedicate o con Aggiorna fonti reali sono riutilizzati nella stessa sessione. Gli archivi storici restano consultabili senza credenziali.")
    st.divider()
    st.markdown("**Controlli operativi interni**")
    chosen=st.date_input("Mese delle attività e dei bilanci",value=now.date().replace(day=1),
                         min_value=date(2000,1,1),max_value=now.date(),key="advanced_kpi_month")
    year,month=chosen.year,chosen.month
    archive=state.get("jarvis_aggregate_archive_v1",{}).get("records",())
    series=sorted({(r.metric,r.unit) for r in archive if r.family=="balance" and (r.gas_day.year,r.gas_day.month)==(year,month)})
    saved=state.get("settlement_desk_csv_v1",{})
    rows=saved.get("rows")
    users=sorted({r.user for r in rows}) if rows else []
    metric,unit="withdrawals","GWh"
    user=None
    if series or users:
        with st.expander("Perimetro settlement"):
            if series:
                metric,unit=st.selectbox("Serie pubblica Jarvis",series,format_func=lambda x:f"{x[0]} · {x[1]}",key="advanced_balance_series")
            if users:
                user=st.selectbox("Partecipante (registro importato)",[None,*users],
                                  format_func=lambda x:x if x is not None else "Non selezionato",key="advanced_participant")
    ops=state.get("bso_tasks_v1")
    operational=(operations_scores(ops["tasks"] if ops else None,now,year,month)+
                 balancing_scores(state.get("jarvis_public_snapshot_v1"),now,year,month)+
                 archive_scores(archive,now,year,month,metric,unit)+participant_scores(rows,user,now,year,month))
    by={r.code:r for r in operational}
    primary=[by[k] for k in ("overdue","sas_mean","eligible") if by[k].value is not None]
    if primary:
        _cards(primary)
    missing=[area for area in ("Operations","Balancing","Settlement") if not any(r.area==area and r.value is not None for r in operational)]
    available=sum(r.value is not None for r in operational)
    st.caption(f"{available}/{len(operational)} KPI interni e controlli aggregati misurabili · KPI proposti, non SLA Snam.")
    if by["overdue"].value is not None and by["overdue"].value>0:
        st.warning("Attività oltre termine nel registro: verifica l'agenda in Scadenze.")
    if available<len(operational):
        st.info(("Registri da alimentare: "+", ".join(missing)+". " if missing else "")+
                "Importa i registri autorizzati nelle viste dedicate. Le assenze non valgono zero.")
    with st.expander("Dettaglio operativo · mese selezionato",expanded=bool(available)):
        st.dataframe([{"Area":r.area,"KPI":r.label,"Valore":r.value,"Unità":r.unit,"Periodo":r.period,
                       "Copertura":r.coverage,"Stato":r.status} for r in operational],hide_index=True,width="stretch")
        st.markdown("[Bilanci e stime Jarvis](/security-of-supply) · [Settlement](/balancing) · Scadenze nella vista Registro operativo.")
    with st.expander("Tutti gli indicatori pubblici e copertura"):
        st.dataframe([{"Area":r.area,"KPI":r.label,"Valore":r.value,"Unità":r.unit,"Periodo":r.period,
                       "Perimetro":r.scope,"Stato":r.status,"Copertura / fonte":r.coverage} for r in context],hide_index=True,width="stretch")
    with st.expander("Definizioni, provenienza e download"):
        all_rows=operational+context
        st.dataframe([{"KPI":r.label,"Definizione":r.definition,"Fonte":r.source,"URL":r.source_url,"Periodo":r.period,
                       "Perimetro":r.scope,"Stato":r.status,"Copertura":r.coverage} for r in all_rows],
                     hide_index=True,width="stretch",column_config={"URL":st.column_config.LinkColumn("Fonte web")})
        st.download_button("Esporta scorecard CSV",export_csv(all_rows),"igor-bso-scorecard.csv","text/csv",key="advanced_kpi_csv")
        st.caption("Indicatori aggregati; nessuna persistenza condivisa, richiesta automatica o invio a LLM.")
