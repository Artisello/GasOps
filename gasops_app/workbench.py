"""Bilanciamento, ricerca normativa e centro operativo AI."""

from datetime import datetime
from html import escape
import json
import logging
import sqlite3

import pandas as pd
from pydantic import ValidationError
import streamlit as st

from .agents import MarketContext
from .finance import CommercialInput, ScenarioCase, ScenarioInput, SettlementInput, scenario, settle, settle_commercial, settlement_sensitivity
from .italiano import ESITI, GRAVITA, MODALITA, numero
from .models import AGENT_LABELS, Agent, Kind, Run, utc_now
from .regulatory import SETTLEMENT_NOTE
from .reports import markdown
from .session import analysis_label, assumptions, database, fixture, launch, save_assumptions, source_filters
from .visuals import chip, evidence, header, heading, info, kind_tag, kpi, kpi_grid, local_time, rows, steps

LOG = logging.getLogger(__name__)

def _settlement_panel() -> None:
    state=assumptions()
    mode=st.radio("Tipo di calcolo",["Semplice","Completo"],horizontal=True,
                  key="balancing_mode",help="Completo: aggiunge stoccaggio e transazioni nette al PSV.")
    advanced=mode=="Completo"
    saved=st.session_state.get("commercial_settlement") if advanced else None
    inputs=(CommercialInput.model_validate(saved) if saved else CommercialInput(**state.settlement.model_dump())) if advanced else state.settlement
    st.caption("Partecipante ipotetico · volumi e prezzi inseriti dall’utente · importi prima delle imposte.")
    form,output=st.columns([1,1.2],gap="medium")
    with form,st.container(border=True,key="panel_settlement_input"):
        st.subheader("1. Inserisci i dati")
        with st.form("settlement_form_"+mode,border=False):
            unit=st.selectbox("Unità dei volumi",("kWh","MWh","GWh"),index=("kWh","MWh","GWh").index(inputs.unit))
            def field(label,value,help=None):
                return st.text_input(label,str(value) if value is not None else "",max_chars=25,help=help)
            st.caption("Volumi di gas")
            a,b=st.columns(2)
            with a:
                delivered=field("Immissioni",inputs.delivered,"Gas immesso in rete.")
            with b:
                withdrawn=field("Prelievi",inputs.withdrawn,"Gas prelevato dalla rete.")
            if advanced:
                a,b=st.columns(2)
                with a:
                    storage=field("Stoccaggio netto",inputs.storage_net,"Prelievo da stoccaggio positivo, iniezione negativa.")
                with b:
                    psv=field("Transazioni nette (PSV)",inputs.psv_net,"Acquisti positivi, vendite negative. Inserisci il termine netto completo.")
            st.caption("Prezzi di sbilanciamento (€/MWh)")
            a,b=st.columns(2)
            with a:
                buy=field("Prezzo di acquisto",inputs.buy_eur_mwh)
            with b:
                sell=field("Prezzo di vendita",inputs.sell_eur_mwh)
            submitted=st.form_submit_button("Calcola sbilanciamento",type="primary",width="stretch")
        invalid=False
        if submitted:
            try:
                values=dict(delivered=delivered,withdrawn=withdrawn,unit=unit,buy_eur_mwh=buy,sell_eur_mwh=sell)
                if advanced:
                    inputs=CommercialInput(**values,storage_net=storage,psv_net=psv)
                    st.session_state["commercial_settlement"]=inputs.model_dump(mode="json")
                else:
                    inputs=SettlementInput(**values)
                    save_assumptions(state.model_copy(update={"settlement":inputs}))
            except ValidationError as error:
                labels={"delivered":"immissioni","withdrawn":"prelievi","buy_eur_mwh":"prezzo di acquisto",
                        "sell_eur_mwh":"prezzo di vendita","storage_net":"stoccaggio","psv_net":"transazioni nette"}
                st.error("Controlla: "+", ".join(labels.get(e["loc"][0],"unità") for e in error.errors())+
                         ". Il risultato precedente resta visibile.")
                invalid=True
        if advanced:
            st.caption("Calcolo completo indipendente: il bollettino AI conserva le ipotesi del calcolo semplice.")
    with output,st.container(border=True,key="panel_settlement_output"):
        st.subheader("2. Risultato")
        if invalid:
            st.caption("Ultimo risultato valido, non i valori appena inseriti.")
        result=settle_commercial(inputs) if advanced else settle(inputs)
        ds=result.imbalance_mwh
        cash=result.cash_flow_eur
        position="Non disponibile" if ds is None else "Carenza di gas" if ds<0 else "Eccesso di gas" if ds>0 else "In equilibrio"
        money="Non disponibile" if cash is None else "Addebito" if cash<0 else "Credito" if cash>0 else "Nessun flusso"
        st.markdown("**"+position+"**")
        kpi_grid([
            ("Saldo energetico",ds,"MWh","Immissioni + saldi netti − prelievi" if advanced else "Immissioni − prelievi",2,""),
            ("Flusso economico",cash,"€",money,2,"rose" if cash is not None and cash<0 else "teal" if cash is not None and cash>0 else ""),
        ])
        if ds is not None:
            if ds==0:
                st.write("Le quantità di gas sono in equilibrio.")
            else:
                st.write("Per annullare lo sbilanciamento servirebbe un aggiustamento netto di "+
                         numero(abs(ds),2)+" MWh "+("in aumento." if ds<0 else "in diminuzione."))
        rows([("Operazione applicata",ESITI[result.side] if result.side else "Non disponibile"),
              ("Prezzo applicato",_readout(result.price_eur_mwh,"€/MWh"))])
        for issue in result.problems:
            st.warning(issue)
        if result.price_eur_mwh is not None and result.price_eur_mwh<0:
            st.warning("Prezzo negativo: carenza/eccesso e addebito/credito possono avere segni diversi. Verifica il caso prima di ogni uso operativo.")
        with st.expander("Quanto cambia il risultato se cambia il prezzo?"):
            sensitivity=settlement_sensitivity(result)
            if sensitivity:
                st.caption("Variazione ipotetica di ±10 €/MWh, con saldo energetico invariato.")
                st.dataframe([{"Prezzo (€/MWh)":float(p),"Flusso (€)":float(v)} for p,v in sensitivity],
                             hide_index=True,width="stretch",column_config={"Prezzo (€/MWh)":st.column_config.NumberColumn(format="%.2f"),
                                                                         "Flusso (€)":st.column_config.NumberColumn(format="%.2f")})
            else:
                st.caption("Servono uno sbilanciamento non nullo e il prezzo applicabile.")
        with st.expander("Formula, unità e riferimenti"):
            if advanced:
                st.latex(r"DS_k=I_k+S_k+T_k^N-P_k")
                st.caption("Edizione di studio: CdR XCII, cap. 9 §3.1.2. S e T sono saldi netti con segno.")
            else:
                st.latex(r"DS=I-P")
                st.caption("Esempio semplificato: stoccaggio e transazioni nette pari a zero.")
            st.write("Flusso economico = saldo in MWh × prezzo applicabile. Negativo: addebito; positivo: credito. Calcolo dimostrativo, non fattura ufficiale.")
            evidence([SETTLEMENT_NOTE])
        st.download_button("Scarica simulazione",json.dumps({"tipo":"SIMULAZIONE","modalita":mode,
                           "inputs":inputs.model_dump(mode="json"),"risultato":result.model_dump(mode="json")},ensure_ascii=False,indent=2),
                           "gasops-bilanciamento.json","application/json",key="balance_download",icon=":material/download:")


def _readout(number, unit: str) -> str:
    return "Non disponibile" if number is None else f"{numero(number, 2)} {unit}"


def _scenario_panel() -> None:
    state=assumptions()
    changes=state.stress
    selected=st.session_state.get("active_bundle")
    data=selected or fixture()
    facts=MarketContext(data,state.model,utc_now()).facts
    if not facts or facts.get("demand_gwh") is None or facts.get("supply_gwh") is None:
        data=fixture()
        facts=MarketContext(data,state.model,utc_now()).facts
        st.warning("La fonte selezionata non contiene domanda e offerta confrontabili. Scenario basato su dati di esempio.")
    saved_key=f"scenario_case_{data.fingerprint}"
    saved=st.session_state.get(saved_key)
    try:
        case=ScenarioCase.model_validate(saved or facts)
        scenario(case,ScenarioInput(demand_pct=0))
    except (ValueError,ArithmeticError):
        st.error("I valori di base non sono validi. Seleziona dati di esempio nella panoramica.")
        return
    if case.storage_gwh is None and changes.storage_pct:
        changes=changes.model_copy(update={"storage_pct":0})
        st.warning("Contributo stoccaggio non disponibile: la variazione stoccaggio è sospesa per questa simulazione.")
    grain="GWh/mese" if data.origin.grain=="monthly" else "GWh/giorno gas"
    st.markdown("**"+("Simulazione · dati fittizi" if data.origin.kind==Kind.SYNTHETIC else "Italia · bilancio nazionale mensile" if data.origin.grain=="monthly" else "Serie selezionata")+"**")
    st.caption(data.origin.name+" · "+facts.get("label","periodo non disponibile")+" · "+grain+
               (" · base modificata dall’utente" if saved else " · base di riferimento"))
    if data.origin.grain=="monthly":
        st.caption("Disponibilità contabile, non offerta fisica della rete.")
    st.caption("Scenario ipotetico, non previsione né sbilanciamento ufficiale del sistema.")
    form,output=st.columns([1,1.2],gap="medium")
    with form,st.container(border=True,key="panel_scenario_input"):
        st.subheader("1. Imposta lo scenario")
        with st.form(f"scenario_form_{data.fingerprint[:12]}",border=False):
            demand_pct=st.slider("Variazione della domanda (%)",-100.,300.,float(changes.demand_pct),1.)
            supply_pct=st.slider("Variazione dell’offerta escluso stoccaggio (%)",-100.,300.,float(changes.supply_pct),1.)
            with st.expander("Valori di base e altre ipotesi"):
                demand=st.number_input("Domanda di base (GWh)",min_value=0.0,value=float(case.demand_gwh),step=10.)
                supply=st.number_input("Offerta totale di base (GWh)",min_value=0.0,value=float(case.supply_gwh),step=10.)
                storage=st.number_input("Contributo dello stoccaggio (GWh)",min_value=0.0,value=float(case.storage_gwh) if case.storage_gwh is not None else None)
                storage_pct=st.number_input("Variazione stoccaggio (%)",-100.0,300.0,float(changes.storage_pct))
                price=st.number_input("Prezzo di riferimento (€/MWh)",value=float(case.price_eur_mwh) if case.price_eur_mwh is not None else None)
                price_delta=st.number_input("Variazione prezzo (€/MWh)",-1000.0,1000.0,float(changes.price_delta_eur_mwh))
            submitted=st.form_submit_button("Simula scenario",type="primary",width="stretch")
        if submitted:
            try:
                candidate=ScenarioCase(demand_gwh=demand,supply_gwh=supply,storage_gwh=storage,price_eur_mwh=price)
                updated=ScenarioInput(demand_pct=demand_pct,supply_pct=supply_pct,storage_pct=storage_pct,price_delta_eur_mwh=price_delta)
                scenario(candidate,updated)
                case,changes=candidate,updated
                st.session_state[saved_key]=case.model_dump(mode="json")
                save_assumptions(state.model_copy(update={"stress":changes}))
            except (ValueError,ArithmeticError) as error:
                st.error("Ipotesi non valide: "+str(error)+". Resta visibile lo scenario precedente.")
        info("Info scenario","Lo stoccaggio è già incluso nell’offerta totale. I cambiamenti si applicano separatamente alle altre fonti e allo stoccaggio.",
             "Il Centro operativo usa gli scostamenti salvati e la propria fonte di riferimento; la base personalizzata resta in questa pagina.")
    with output,st.container(border=True,key="panel_scenario_output"):
        st.subheader("2. Impatto dello scenario")
        base=scenario(case,ScenarioInput(demand_pct=0))
        stress=scenario(case,changes)
        balance_label="Carenza" if stress.imbalance_gwh<0 else "Eccesso" if stress.imbalance_gwh>0 else "Equilibrio"
        st.markdown("**"+balance_label+" nello scenario**")
        kpi_grid([
            ("Saldo semplificato",stress.imbalance_gwh,grain,"Offerta − domanda",1,""),
            ("Copertura della domanda",stress.coverage_pct,"%","Offerta / domanda",1,""),
        ])
        comparison=pd.DataFrame({"Domanda":[float(base.demand_gwh),float(stress.demand_gwh)],
                                 "Offerta":[float(base.supply_gwh),float(stress.supply_gwh)]},index=["Base","Scenario"])
        st.caption("Domanda e offerta · "+grain)
        st.bar_chart(comparison,stack=False)
        if stress.gap_value_eur is not None:
            kpi("Valore indicativo del saldo",stress.gap_value_eur,"€","Non è settlement né fattura",0)
        with st.expander("Confronto numerico"):
            st.dataframe([{"Indicatore":label,"Base":_readout(getattr(base,field),unit),
                           "Scenario":_readout(getattr(stress,field),unit)}
                for label,field,unit in (("Domanda","demand_gwh",grain),("Offerta","supply_gwh",grain),
                    ("Stoccaggio","storage_gwh",grain),("Copertura","coverage_pct","%"),
                    ("Saldo","imbalance_gwh",grain),("Prezzo","price_eur_mwh","€/MWh"),
                    ("Valore saldo","gap_value_eur","€"))],hide_index=True,width="stretch")
        if stress.gap_value_eur is not None and base.gap_value_eur is not None:
            st.caption("Variazione del valore del saldo: "+numero(stress.gap_value_eur-base.gap_value_eur,0,signed=True)+" €.")


def balancing() -> None:
    header("Bilanciamento", f'{kind_tag(Kind.SIMULATION)} <span>Calcoli illustrativi · nessuna operazione reale</span>')
    system, daily, participant, aggregate = st.tabs(["Stato sistema", "Controllo giornaliero", "Sbilanciamento del partecipante", "Scenario di mercato"])
    with system:
        from .operational_sources_page import _jarvis_panel
        _jarvis_panel(prefix="balancing")
    with daily:
        from .settlement_desk_page import panel
        panel()
    with participant:
        _settlement_panel()
    with aggregate:
        _scenario_panel()


def regulatory() -> None:
    from .document_page import document_page
    document_page()


def operations() -> None:
    from .assistant_page import assistant_page
    assistant_page()
