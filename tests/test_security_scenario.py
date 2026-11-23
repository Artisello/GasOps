"""Deterministic availability arithmetic, never a hydraulic/topological simulation."""
from datetime import date,datetime,timedelta,timezone
from decimal import Decimal as D,localcontext
from types import SimpleNamespace
from dataclasses import replace
import json

import pytest

from gasops_app.finance import (SecurityScenarioCase,SecurityStress,StressDatum,
    scenario,stress_configuration,ScenarioCase,ScenarioInput)
from gasops_app.gas_calendar import gas_day_bounds
from gasops_app.italian_network import load_network_assets,security_entries,security_scenario_case,Observation
from gasops_app.system_status import Measure,Coverage,BalanceComponent

DAY=date(2026,11,20)
NOW=datetime(2026,11,23,12,tzinfo=timezone.utc)
POINT="IT-TSO-0001ITP-00093entry"


def case(day=DAY):
    start,stop=gas_day_bounds(day)
    values={POINT:100,"lng":20,"storage":10,"production":5,"demand":120,"exports":5,"injection":0,
            "technical:"+POINT:200,"available:"+POINT:12}
    return SecurityScenarioCase(gas_day=day,reference_time=NOW,entry_keys=(POINT,),inputs=tuple(
        StressDatum(key=k,value=v,source_id="test:"+k,period_from=start,period_to=stop,
            retrieved_at=NOW-timedelta(hours=1),observed_at=NOW-timedelta(hours=2)) for k,v in values.items()))


def changed(source,key,**changes):
    return source.model_copy(update={"inputs":tuple(i.model_copy(update=changes) if i.key==key else i for i in source.inputs)})


def test_combined_stress_conserves_components_without_double_counting():
    result=scenario(case(),SecurityStress(demand_pct=10,cold_deviation_c=5,cold_sensitivity_pct_c=2,
        entry_key=POINT,capacity_reduction_pct=60,lng_reduction_pct=25,storage_withdrawal_limit=4))
    a,b=result["baseline"],result["stress"]
    assert a["supply"]==135 and a["demand"]==125 and a["balance"]==10
    assert result["demand_factor"]==D("1.21") and b["domestic_demand"]==D("145.20")
    assert b["supply"]==104 and b["demand"]==D("150.20") and b["balance"]==D("-46.20")
    assert b["storage_requirement"]==D("50.20") and b["additional_storage_requirement"]==D("46.20")
    assert result["point_flow_loss"]==20 and b["technical_headroom"]==0
    assert a["technical_headroom"]==100 and result["available_capacity_input"]==12
    for kind in ("baseline","stress"):
        values=result["components"][kind]
        assert result[kind]["supply"]==sum(values[k] for k in (POINT,"lng","storage","production"))
        assert result[kind]["balance"]==result[kind]["supply"]-result[kind]["demand"]
    assert result["topology"]=="Impatto topologico non determinabile"


def test_outage_dominates_capacity_and_does_not_remove_other_sources():
    a=scenario(case(),SecurityStress(demand_pct=0,entry_key=POINT,entry_outage=True,capacity_reduction_pct=100))
    assert a["point_flow_loss"]==100 and a["stress"]["supply"]==35 and a["stress"]["entry_flow"]==0
    assert a["components"]["stress"]["lng"]==20 and a["stress"]["technical_headroom"]==0
    b=scenario(case(),SecurityStress(demand_pct=0,entry_key=POINT,capacity_reduction_pct=25))
    assert b["point_flow_loss"]==0 and b["stress"]["technical_headroom"]==50


def test_missing_critical_inputs_never_become_fixtures_or_zeros():
    source=changed(case(),"demand",value=None)
    r=scenario(source,SecurityStress())
    assert r["status"]=="Parziale" and r["baseline"]["supply"]==135
    assert r["baseline"]["demand"] is None and r["stress"]["balance"] is None
    assert r["missing"]==["demand"] and r["baseline"]["known_demand"]==5
    assumed=scenario(source,SecurityStress(demand_pct=0,input_assumptions={"demand":120}))
    assert assumed["baseline"]["balance"]==10 and assumed["input_classes"]["demand"]=="ASSUMPTION"
    empty=scenario(case().model_copy(update={"inputs":()}),SecurityStress())
    assert empty["status"]=="Non calcolabile" and empty["baseline"]["known_supply"] is None
    cap_missing=changed(case(),"technical:"+POINT,value=None)
    r=scenario(cap_missing,SecurityStress(entry_key=POINT,capacity_reduction_pct=10))
    assert r["baseline"]["supply"]==135 and r["stress"]["supply"] is None
    assert r["unresolved_assumptions"]==["technical:"+POINT]
    outage=scenario(cap_missing,SecurityStress(entry_key=POINT,entry_outage=True))
    assert outage["stress"]["supply"]==35 and not outage["unresolved_assumptions"]


@pytest.mark.parametrize("changes",[{"unit":"MWh"},{"complete":False},{"quality":"conflict"},
    {"period_to":gas_day_bounds(DAY)[1]-timedelta(hours=1)}, {"retrieved_at":NOW+timedelta(hours=1)}])
def test_incompatible_or_partial_inputs_are_withheld(changes):
    result=scenario(changed(case(),POINT,**changes),SecurityStress())
    assert POINT in result["missing"] and result["baseline"]["supply"] is None


def test_duplicates_and_foreign_identifiers_cannot_add_supply():
    source=case()
    duplicated=SecurityScenarioCase.model_validate({**source.model_dump(),"inputs":(*source.inputs,source.inputs[0])})
    assert len(duplicated.inputs)==len(source.inputs) and scenario(duplicated,SecurityStress())==scenario(source,SecurityStress())
    with pytest.raises(ValueError,match="conflitto"):
        SecurityScenarioCase.model_validate({**source.model_dump(),"inputs":(*source.inputs,source.inputs[0].model_copy(update={"value":D(99)}))})
    with pytest.raises(ValueError):scenario(source,SecurityStress(entry_key="unverified",entry_outage=True))
    with pytest.raises(ValueError):scenario(source,SecurityStress(input_assumptions={"national_total":1000}))


def test_nonnegative_bounds_zero_and_stale_evidence():
    for kwargs in ({"demand_pct":-1},{"lng_reduction_pct":101},{"storage_withdrawal_limit":-1},
                   {"capacity_reduction_pct":"NaN"},{"demand_pct":300,"cold_deviation_c":10}):
        with pytest.raises(ValueError):SecurityStress(**kwargs)
    with pytest.raises(ValueError):StressDatum.model_validate({**case().inputs[0].model_dump(),"value":-1})
    r=scenario(case(),SecurityStress(demand_pct=0,lng_reduction_pct=100,storage_withdrawal_limit=0,entry_key=POINT,entry_outage=True))
    assert r["stress"]["supply"]==5 and r["stress"]["storage_withdrawal"]==0
    source=case()
    for k in ("demand","exports","injection"):source=changed(source,k,value=D(0))
    assert scenario(source,SecurityStress())["baseline"]["demand_coverage_pct"] is None
    assert scenario(changed(case(),POINT,quality="stale"),SecurityStress())["baseline"]["supply"]==135


@pytest.mark.parametrize("day,hours",[(date(2026,3,28),23),(date(2026,10,24),25),(DAY,24)])
def test_dst_preserves_gas_day_rates_and_reproducibility(day,hours):
    source=case(day);changes=SecurityStress(entry_key=POINT,capacity_reduction_pct=60,demand_pct=20)
    assert (gas_day_bounds(day)[1]-gas_day_bounds(day)[0]).total_seconds()==3600*hours
    assert scenario(source,changes)["baseline"]["supply"]==135
    first=stress_configuration(source,changes)
    restored=json.loads(json.dumps(first,default=str,sort_keys=True))
    with localcontext() as ctx:
        ctx.prec=8
        second=stress_configuration(SecurityScenarioCase.model_validate(restored["inputs"]),SecurityStress.model_validate(restored["assumptions"]))
    assert json.dumps(first,default=str,sort_keys=True)==json.dumps(second,default=str,sort_keys=True)


def test_export_has_public_references_and_explicit_classification_only():
    source=changed(case(),POINT,source_url="https://person:password@transparency.entsog.eu/data?api_key=SECRET#token")
    config=stress_configuration(source,SecurityStress())
    raw=json.dumps(config,default=str)
    assert "password" not in raw and "SECRET" not in raw and "api_key" not in raw
    assert config["schema_version"]==1 and config["model_version"] and config["gas_day"]==str(DAY)
    assert config["model_output"]["classification"]=="MODEL OUTPUT"
    assert "source_references" in config and "calculation_parameters" in config
    with pytest.raises(ValueError):SecurityScenarioCase.model_validate({**case().model_dump(),"credentials":"SECRET"})


def test_adapter_reuses_verified_assets_and_one_lng_alternative():
    network=load_network_assets()
    m=lambda value,code:Measure(D(value),"GWh/d",DAY,code,"Public source",retrieved_at=NOW-timedelta(hours=1),
        coverage=Coverage(1,1),status="observed",scope="declared scope")
    components=tuple(BalanceComponent(k,k,"supply",m(v,"GIE:ALSI:IT" if k=="lng" else "public:"+k))
        for k,v in (("withdrawal","10"),("production","5"),("exports","0"),("injection","0")))
    status=SimpleNamespace(gas_day=DAY,components=components,lng_sendout=m("20","GIE:ALSI:IT"),
        demand_actual=m("120","ENTSOG:SRG:sectors"),demand_forecast=replace(m("130","IGOR:forecast"),status="estimated"))
    public=security_scenario_case(network,(),status,NOW)
    assert len(public.entry_keys)==6 and len([i for i in public.inputs if i.key=="lng"])==1
    assert next(i for i in public.inputs if i.key=="lng").value==20
    assert next(i for i in public.inputs if i.key=="demand").classification=="MODEL OUTPUT"
    forecast=security_scenario_case(network,(),status,NOW,demand_basis="FORECAST")
    assert next(i for i in forecast.inputs if i.key=="demand").classification=="FORECAST"
    demo=security_scenario_case(network,(),None,NOW,day=DAY,demo=True)
    assert demo.mode=="DEMO" and all(i.classification=="ASSUMPTION" for i in demo.inputs)
    with pytest.raises(ValueError):SecurityScenarioCase.model_validate({**demo.model_dump(),"mode":"PUBLIC"})
    unverified=replace(network,bindings=tuple(replace(b,mapping_confidence="candidate") for b in network.bindings))
    assert not security_entries(unverified)
    assert scenario(ScenarioCase(demand_gwh=100,supply_gwh=90,storage_gwh=10),ScenarioInput(demand_pct=10)).imbalance_gwh==-20


def test_partial_response_keeps_valid_point_flow_and_new_holes_replace_old_values():
    network=load_network_assets();binding=security_entries(network)[0]
    start,stop=gas_day_bounds(DAY)
    missing=Measure(None,"GWh/d",DAY,"public:missing","Public source")
    status=SimpleNamespace(gas_day=DAY,components=tuple(BalanceComponent(k,k,"supply",missing)
        for k in ("withdrawal","production","exports","injection")),lng_sendout=missing,demand_actual=missing,demand_forecast=missing)
    o=Observation(binding.infrastructure_id,binding.point_direction,"Physical Flow",D(30),"GWh/d",start,stop,DAY,
        NOW-timedelta(hours=2),(NOW-timedelta(hours=3)).isoformat(),"ENTSOG","https://transparency.entsog.eu/",
        "published-flow-123","valid","Provisional")
    first=SimpleNamespace(point_direction=binding.point_direction,records=(o,),acquired=o.retrieved_at,first=DAY,last=DAY,partial=True)
    source=security_scenario_case(network,(first,),status,NOW)
    datum=next(i for i in source.inputs if i.key==binding.point_direction)
    assert datum.complete and datum.response_partial and datum.source_id=="published-flow-123"
    assert scenario(source,SecurityStress())["components"]["baseline"][binding.point_direction]==30
    second=SimpleNamespace(**{**vars(first),"acquired":NOW-timedelta(hours=1),"records":(
        replace(o,value=None,quality_status="N/A",retrieved_at=NOW-timedelta(hours=1)),)})
    new=security_scenario_case(network,(first,second),status,NOW)
    assert binding.point_direction in scenario(new,SecurityStress())["missing"]


def test_future_actual_cannot_be_promoted_but_dated_forecast_is_distinct():
    source=case(date(2026,11,24))
    r=scenario(source,SecurityStress())
    assert r["baseline"]["supply"] is None and r["baseline"]["demand"] is None
    forecast=source.model_copy(update={"inputs":tuple(i.model_copy(update={"classification":"FORECAST"}) for i in source.inputs)})
    assert scenario(forecast,SecurityStress())["baseline"]["supply"]==135
