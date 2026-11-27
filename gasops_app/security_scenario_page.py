"""Italian availability Stress Test in the existing scenario route. Local evidence only."""
from collections import Counter
from datetime import timedelta
from decimal import Decimal
import json

import pandas as pd
import streamlit as st

from .finance import SecurityStress, scenario, stress_configuration
from .gas_calendar import gas_day_bounds, closed_gas_day
from .gas_data import source_context
from .balancing_cockpit import inventory_state
from .balancing_charts import security_comparison
from .italian_network import security_entries, security_scenario_case, point_direction_labels
from .direction_ui import arrow_text
from .italian_network_page import assets, render_map, SELECTED, _open_full
from .italian_network_map import display_name, legend_symbol
from .models import utc_now
from .session import database
from .system_status import build_status
from .italiano import numero, data_it
from .visuals import plot

LABELS={"lng":"Send-out GNL","storage":"Prelievo storage","production":"Produzione nazionale",
        "demand":"Domanda domestica · perimetro dichiarato","exports":"Esportazioni","injection":"Iniezione storage"}


def _choice(mapping):
    identifier=mapping[st.session_state["sos_entry"]]
    st.session_state[SELECTED]=identifier
    st.session_state["sos_seen_map"]=identifier


def _read(value):
    return "Non calcolabile" if value is None else numero(value,1)+" GWh/d"


def panel():
    now=utc_now()
    network,boundary,bundled=assets()
    entries=security_entries(network)
    lookup={i.id:i for i in network.infrastructure}
    mapping={b.point_direction:b.infrastructure_id for b in entries}
    direction_types=point_direction_labels(network)
    labels={b.point_direction:display_name(lookup[b.infrastructure_id].name)+" · "+arrow_text(direction_types[b.point_direction]) for b in entries}
    st.markdown("**Stress Test · disponibilità e domanda del sistema italiano**")
    source,calendar=st.columns([2,1])
    mode=source.radio("Input del modello",["Dati pubblici","Demo esplicita"],horizontal=True,key="sos_mode")
    demo=mode=="Demo esplicita"
    prefix="sos_demo" if demo else "sos_public"
    closed=closed_gas_day(now)
    default=max((o.gas_day for s in bundled for o in s.records if o.indicator=="Physical Flow"
        and o.gas_day and o.gas_day<=closed and o.value is not None),default=closed)
    day=calendar.date_input("Giorno gas",value=default,min_value=closed-timedelta(days=91),
        max_value=closed+timedelta(days=1),format="DD/MM/YYYY",key=prefix+"_day")
    start,stop=gas_day_bounds(day)
    st.caption(data_it(day)+f" · 06:00–06:00 Europe/Rome · {int((stop-start).total_seconds()/3600)} ore · "+
               ("DEMO · quantità sintetiche dichiarate come ASSUMPTION" if demo else "Copie pubbliche già disponibili · nessun aggiornamento automatico"))
    basis="OBSERVED"
    point_layout=st
    if not demo:
        point_layout,basis_layout=st.columns([2,1])
        basis=basis_layout.radio("Base della domanda",["OBSERVED","FORECAST"],horizontal=True,key="sos_demand_basis",
            help="FORECAST usa solo una previsione SRG compatibile già calcolata; non genera una nuova previsione.")
        context=source_context(network,bundled,st.session_state,now,store=database(),first=day,last=day)
        state=inventory_state(context,st.session_state,day)
        status=build_status(network,context["snapshots"],state,now,gas_day=day)
        case=security_scenario_case(network,context["snapshots"],status,now,demand_basis=basis)
    else:
        case=security_scenario_case(network,(),None,now,day=day,demo=True)
    seen=st.session_state.get(SELECTED)
    if seen!=st.session_state.get("sos_seen_map"):
        selected=next((key for key,identifier in mapping.items() if identifier==seen),None)
        if selected:st.session_state["sos_entry"]=selected
        st.session_state["sos_seen_map"]=seen
    if st.session_state.get("sos_entry") not in mapping:st.session_state["sos_entry"]=next(iter(mapping))
    point=point_layout.selectbox("Ingresso verificato · selezione disponibile anche sulla mappa",list(mapping),
        format_func=labels.get,key="sos_entry",on_change=_choice,args=(mapping,))
    controls,results=st.columns([1,1.8],gap="medium")
    scope=prefix+"_"+day.isoformat()+"_"+basis
    missing=scenario(case,SecurityStress(demand_pct=0))["missing"]
    with controls,st.container(border=True):
        st.markdown("**ASSUMPTION · controlli dello stress**")
        preset=st.radio("Demand shock",["+5%","+10%","+20%","Personalizzato"],index=1,horizontal=True,key=scope+"_preset")
        with st.form(scope+"_form",border=False):
            demand=st.number_input("Aumento domanda (%)",0.,300.,10.,key=scope+"_demand") if preset=="Personalizzato" else float(preset.strip("+%"))
            cold=st.number_input("Freddo ipotetico · scarto sotto la base (°C)",0.,30.,0.,step=1.,key=scope+"_cold")
            sensitivity=st.number_input("Sensibilità assunta (% domanda / °C)",0.,10.,2.,step=.5,key=scope+"_sensitivity")
            st.caption("Il freddo è un’ipotesi: il suo effetto si compone moltiplicativamente con il demand shock.")
            outage=st.checkbox("Perdita ipotetica dell’ingresso",key=scope+"_outage")
            capacity=st.slider("Riduzione capacità tecnica ingresso (%)",0,100,0,key=scope+"_capacity")
            lng=st.slider("Riduzione LNG send-out (%)",0,100,0,key=scope+"_lng")
            limit=st.number_input("Limite prelievo storage (GWh/d)",min_value=0.,max_value=1e9,value=None,key=scope+"_storage")
            overrides={}
            with st.expander("Input mancanti · ipotesi facoltative"):
                st.caption("Nessun valore è precompilato. Un valore inserito resta ASSUMPTION, anche quando è zero.")
                for key in missing:
                    value=st.number_input(LABELS.get(key,labels.get(key,key))+" (GWh/d)",
                        min_value=0.,max_value=1e9,value=None,key=scope+"_input_"+key)
                    if value is not None:overrides[key]=Decimal(str(value))
                if not missing:st.caption("Le componenti del perimetro dichiarato sono disponibili.")
            st.form_submit_button("Calcola Stress Test",type="primary",width="stretch")
        try:
            changes=SecurityStress(demand_pct=demand,cold_deviation_c=cold,cold_sensitivity_pct_c=sensitivity,
                entry_key=point,entry_outage=outage,capacity_reduction_pct=capacity,lng_reduction_pct=lng,
                storage_withdrawal_limit=limit,input_assumptions=overrides)
            result=scenario(case,changes)
        except ValueError as exc:
            st.error("Ipotesi non valide: "+str(exc))
            return
    with results,st.container(key="sos_results"):
        st.html('<style>.st-key-sos_results [data-testid="stMetricValue"]{font-size:1.4rem;line-height:1.35}'
                '.st-key-sos_results [data-testid="stMetric"]{min-height:90px}</style>')
        st.caption("MODEL OUTPUT · "+result["status"])
        a,b=st.columns(2)
        for column,name,key in ((a,"BASELINE","baseline"),(b,"STRESS SCENARIO","stress")):
            with column,st.container(border=True):
                st.markdown("**"+name+"**")
                for label,field in (("Offerta","supply"),("Fabbisogno","demand"),("Surplus / deficit teorico","balance")):
                    delta=result["stress"][field]-result["baseline"][field] if key=="stress" and all(result[k][field] is not None for k in ("baseline","stress")) else None
                    st.metric(label,_read(result[key][field]),None if delta is None or delta==0 else numero(delta,1,signed=True)+" GWh/d",delta_color="off")
        counts=Counter(result["input_classes"].values())
        coverage=result["coverage"]
        st.caption(f"Copertura modello: {coverage['valid']}/{coverage['expected']} componenti · "+
            " · ".join(f"{k}: {counts[k]}" for k in ("OBSERVED","FORECAST","ASSUMPTION","MODEL OUTPUT")))
        st.caption("Copertura delle componenti richieste, non quota del gas nazionale. Un totale assente non è zero.")
        plot(security_comparison(result),key="sos_comparison")
        st.caption("Barre assenti = misura non calcolabile. Domanda domestica, esportazioni e iniezione formano il fabbisogno; non sono sommati aggregati alternativi.")
        st.markdown("**Effetto sull’ingresso scelto:** "+_read(result["point_flow_loss"]))
        if result["missing"] or result["unresolved_assumptions"]:
            st.caption("Componenti mancanti: "+" · ".join(LABELS.get(k,labels.get(k,k)) for k in [*result["missing"],*result["unresolved_assumptions"]]))
        with st.expander("Differenze e contributi noti",expanded=False):
            st.dataframe([{"Indicatore":label,"Baseline":result["baseline"][key],"Stress Scenario":result["stress"][key],
                "Δ":result["stress"][key]-result["baseline"][key] if all(result[k][key] is not None for k in ("baseline","stress")) else None}
                for label,key in (("Offerta nota · parziale se incompleta","known_supply"),("Fabbisogno noto · parziale se incompleto","known_demand"),
                    ("Storage richiesto prima del limite","storage_requirement"),("Ulteriore storage richiesto","additional_storage_requirement"),
                    ("Margine tecnico C−F · teorico","technical_headroom"))],hide_index=True,width="stretch")
            st.caption("GWh/d · il margine tecnico è derivato per lo stesso punto e periodo. Non è capacità disponibile pubblicata né garanzia di erogabilità.")
            st.caption("Capacità disponibile in input: "+_read(result["available_capacity_input"])+" · classificazione nella provenienza.")
        config=stress_configuration(case,changes)
        st.download_button("Scarica configurazione JSON",json.dumps(config,ensure_ascii=False,sort_keys=True,indent=2,default=str),
            "igor-stress-test-"+day.isoformat()+".json","application/json",key="sos_json",width="stretch")
    map_column,details=st.columns([1,1.6],gap="medium")
    identifier=mapping[point]
    with map_column:
        st.markdown("**Ingresso dello Stress Test**")
        stressed_ids=(identifier,) if outage or capacity else ()
        render_map(network,boundary,tuple(i for i in network.infrastructure if i.id in mapping.values()),identifier,
            mode="scenario",observations=(),day=day,scenario_ids=stressed_ids)
        if stressed_ids:
            st.markdown('<img width="20" src="'+legend_symbol("assumption")+'"> ASSUMPTION · indisponibilità o capacità ridotta ipotetica',unsafe_allow_html=True)
        st.caption(result["topology"]+". Nessuna congestione attribuita ad altri gasdotti.")
        st.caption("Geografie storiche indicative · SciGRID_gas / DLR-VE · CC BY 4.0 · confini Natural Earth, pubblico dominio.")
        st.button("Apri scheda infrastruttura",on_click=_open_full,args=(identifier,day,day,"entry"),key="sos_open_map",width="stretch")
    with details:
        st.markdown("**Ipotesi e perimetro**")
        st.write("Domanda domestica × (1 + "+numero(changes.demand_pct,1)+"%) × (1 + "+numero(changes.cold_deviation_c,1)+
                 " °C × "+numero(changes.cold_sensitivity_pct_c,1)+"%/°C).")
        st.write("Perdita ingresso: "+("sì" if outage else "no")+" · capacità −"+str(capacity)+"% · LNG −"+str(lng)+"% · limite storage: "+
                 (_read(changes.storage_withdrawal_limit) if limit is not None else "non imposto"))
        st.caption("Il taglio capacità limita il flusso soltanto se supera il nuovo tetto. La perdita del punto prevale sul taglio, senza doppia sottrazione.")
        st.caption("Esportazioni e iniezioni restano fisse. Nessun redispatch automatico; la giacenza non è convertita in capacità di prelievo. Risposta del linepack esclusa.")
        st.caption("Modello di disponibilità sul perimetro dichiarato, non bilancio ufficiale o digital twin idraulico. Non stima pressione, percorso dei flussi o probabilità dell’evento.")
        with st.expander("Input · fonte, periodo e qualità",expanded=True):
            rows=[{"Componente":LABELS.get(i.key,labels.get(i.key,i.key)),"Classe":i.classification,"Valore":i.value,
                "Unità":i.unit,"Fonte":i.source_id,"Periodo da":i.period_from,"Periodo a":i.period_to,
                "Pubblicato":i.observed_at,"Acquisito":i.retrieved_at,"Qualità":i.quality,"Copertura completa":i.complete,
                "Risposta fonte parziale":i.response_partial,
                "Perimetro":i.scope,"Derivazione":i.derivation} for i in case.inputs]
            rows.extend({"Componente":LABELS.get(k,labels.get(k,k)),"Classe":"ASSUMPTION","Valore":v,"Unità":"GWh/d",
                "Fonte":"Ipotesi esplicita dell’utente","Periodo da":start,"Periodo a":stop} for k,v in overrides.items())
            if rows:st.dataframe(pd.DataFrame(rows),hide_index=True,width="stretch")
            else:st.caption("Nessun input valido disponibile.")
            if not demo:
                for note in context["notices"]:st.caption(note)
