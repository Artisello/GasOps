"""Synthetic gas-day/portfolio fixtures; no official position is fabricated."""
from dataclasses import replace
from datetime import date,datetime,timedelta,timezone
from decimal import Decimal as D
import json

import pandas as pd
import pytest

from gasops_app import balancing_cockpit as m,gas_data as g
from gasops_app.entsog_vintages import audit_rows
from gasops_app.gas_calendar import gas_day_bounds
from gasops_app.italian_network import Observation,load_network_assets
from gasops_app.italian_network_sources import Snapshot
from gasops_app.jarvis_archive import Record
from gasops_app.operations_ledger import sample_rows
from gasops_app.settlement_desk import archive_csv,merge_csv,daily_controls

NOW=datetime(2026,11,23,12,tzinfo=timezone.utc)
DAY=date(2026,11,20)


@pytest.fixture(scope="module")
def network():return load_network_assets()


def frame(network,day=DAY):
    b=next(b for b in network.bindings_for("INET_BP_65","ENTSOG") if b.direction=="entry")
    start,stop=gas_day_bounds(day)
    records=tuple(Observation(b.infrastructure_id,b.point_direction,name,D(str(value)),"GWh/d",start,stop,day,
        NOW-timedelta(hours=1),(NOW-timedelta(hours=2)).isoformat(),"Synthetic fixture","https://example.invalid",name,
        "valid","Confirmed") for name,value in zip(m.INDICATORS,(10,12,11,0)))
    return g.collect(network,(Snapshot(b.point_direction,records,day,day,NOW-timedelta(hours=1)),),{},NOW,first=day,last=day)


def target(network,data,day=DAY):
    return next(r for r in m.public_reconciliation(network,data,day) if r["point_direction"]==data.point_direction.iloc[0])


def portfolio(rows=None,**changes):
    data=merge_csv(None,archive_csv(rows or sample_rows()).encode(),acquired=NOW)
    return {m.BALANCE_STATE:{**data,"authorized":True,"origin":"user_upload",**changes}}


def record(metric,value="10",unit="GWh",**kw):
    return replace(Record("balance",DAY,NOW-timedelta(hours=2),"provisional","SRG",metric,unit,D(value),"Report public"),**kw)


def test_point_rates_and_missing_cells_are_not_an_individual_or_national_balance(network):
    data=frame(network)
    row=target(network,data)
    assert row["Physical Flow"]==0 and row["comparable"]
    assert (row["delta_renomination_nomination"],row["delta_allocation_renomination"],row["delta_physical_allocation"])==(D(2),D(-1),D(-11))
    missing=target(network,data.loc[data.indicator!="Allocation"])
    assert missing["Allocation"] is None and missing["delta_physical_allocation"] is None
    assert not missing["comparable"]
    state={g.MAP_STATE:{"snapshots":{}},"daily_desk_demo":True}
    assert m.system_position(state,DAY,NOW)["value"] is None
    assert m.portfolio_day(state,"DEMO-001",DAY,NOW)["value"] is None


def test_duplicates_directions_units_and_publication_phases_are_guarded(network):
    data=frame(network)
    assert target(network,pd.concat([data,data]))["Nomination"]==10
    different=data.copy();different.loc[different.indicator=="Nomination","value"]=D(20)
    assert target(network,pd.concat([data,different]))["Nomination"] is None
    wrong=data.copy();wrong.loc[wrong.indicator=="Allocation","direction"]="exit"
    assert target(network,wrong)["Allocation"] is None
    wrong=data.copy();wrong.loc[wrong.indicator=="Allocation","unit"]="MWh/d"
    assert target(network,wrong)["Allocation"] is None
    wrong=data.copy();wrong.loc[wrong.indicator=="Allocation","publication_status"]="Provisional"
    r=target(network,wrong)
    assert r["Allocation"]==11 and r["delta_allocation_renomination"]==-1 and r["comparable"]
    assert "provvisorio" in r["state"] and "non riconciliazione definitiva" in r["note"]


@pytest.mark.parametrize("day,hours",[(date(2026,3,28),23),(date(2026,10,24),25)])
def test_dst_compares_identical_instants_without_rescaling_a_daily_rate(network,day,hours):
    data=frame(network,day)
    row=target(network,data,day)
    assert row["comparable"] and (row["period_to"]-row["period_from"]).total_seconds()/3600==hours
    assert row["Nomination"]==10 and row["unit"]=="GWh/d"
    different=data.copy();different.loc[different.indicator=="Allocation","period_to"]=row["period_to"]+timedelta(hours=1)
    assert target(network,different,day)["Allocation"] is None


def test_unverified_binding_never_enters_reconciliation(network):
    data=frame(network)
    changed=replace(network,bindings=tuple(replace(b,mapping_confidence="unverified") if b.point_direction==data.point_direction.iloc[0] else b for b in network.bindings))
    assert data.point_direction.iloc[0] not in {r["point_direction"] for r in m.public_reconciliation(changed,data,DAY)}


def test_estimate_needs_same_aggregate_release_and_converts_energy_only():
    rows=(record("injections","10000","MWh"),record("withdrawals","9","GWh"))
    state={"jarvis_aggregate_archive_v1":{"records":rows}}
    pos=m.system_position(state,DAY,NOW)
    assert pos["value"]==1 and pos["label"]==m.ESTIMATED and not pos["official"]
    assert pos["evidence"][0]["retrieved_at"] is None
    for wrong in (replace(rows[1],report_ref="Other"),replace(rows[1],unit="Sm3"),
                  replace(rows[1],published_at=NOW-timedelta(hours=3)),replace(rows[1],stage="definitive")):
        state["jarvis_aggregate_archive_v1"]["records"]=(rows[0],wrong)
        assert m.system_position(state,DAY,NOW)["value"] is None
    state["jarvis_aggregate_archive_v1"]["records"]=(rows[0],rows[1],replace(rows[0],value=D(20)))
    assert m.system_position(state,DAY,NOW)["value"] is None


def test_declared_reported_balance_and_native_spreadsheet_cannot_certify_official_position():
    state={"jarvis_aggregate_archive_v1":{"records":(record("balance_reported","42"),),"official":True},
           "jarvis_native_v1":{"frame":pd.DataFrame([{"metric":"SAS","value":42,"unit":"MWh"}])}}
    result=m.system_position(state,DAY,NOW)
    assert result["value"] is None and result["status"]=="Non calcolabile" and not result["official"]
    assert m.workflow([])==[(k,"Non disponibile") for k in ("Nomination","Renomination","Allocation","Reconciliation","Settlement")]


def test_source_publication_audit_does_not_fabricate_revisions(network):
    data=frame(network).loc[lambda f:f.indicator=="Physical Flow"].copy()
    only=audit_rows(pd.concat([data,data]),DAY,NOW)
    assert len(only)==1 and only[0]["old_value"] is None and not only[0]["changed"]
    first=(NOW-timedelta(hours=4)).isoformat();last=(NOW-timedelta(hours=2)).isoformat()
    data["revisions"]=json.dumps([{"value":"5","observed_at":first,"source_id":"first"},
        {"value":"0","observed_at":last,"source_id":"second"}])
    rows=audit_rows(data,DAY,NOW)
    assert rows[1]["old_value"]==5 and rows[1]["new_value"]==0 and rows[1]["reason"]=="Revisione pubblicata"
    data["revisions"]=json.dumps([{"value":"5","observed_at":first},{"value":"0","observed_at":first}])
    assert all(r["old_value"] is None and r["quality_flag"]=="conflict" for r in audit_rows(data,DAY,NOW))


def test_portable_vintages_preserve_acquisition_without_invented_publication(network):
    data=frame(network).iloc[0:0]
    point=frame(network).point_direction.iloc[0]
    b={"point":point,"first":str(DAY),"last":str(DAY),"acquired":(NOW-timedelta(hours=4)).isoformat(),"complete":True,
       "rows":[{"day":str(DAY),"indicator":"Nomination","gwh":10.,"assumed":False}]}
    later={**b,"acquired":(NOW-timedelta(hours=2)).isoformat(),"rows":[{**b["rows"][0],"gwh":12.}]}
    rows=audit_rows(data,DAY,NOW,batches=[b,b,later])
    assert len(rows)==2 and all(r["publication_timestamp"] is None for r in rows)
    assert rows[1]["old_value"]==10 and rows[1]["reason"]=="Variazione tra acquisizioni"
    assert rows[1]["version"] and rows[1]["source_id"]==point


def test_authorization_and_shipper_scope_do_not_reuse_public_or_synthetic_defaults():
    for changes in ({"authorized":False},{"origin":"synthetic"},{"authorized":None}):
        state=portfolio(**changes)
        state["daily_desk_data_mode"]="Esempio guidato"
        assert m.authorized_portfolio(state) is None
        assert m.portfolio_day(state,"DEMO-001",date(2026,9,5),NOW)["value"] is None
    state=portfolio()
    assert m.portfolio_day(state,"OTHER",date(2026,9,5),NOW)["value"] is None
    day=date(2026,9,5)
    result=m.portfolio_day(state,"DEMO-001",day,NOW)
    expected=next(r for r in daily_controls(sample_rows(),"DEMO-001",2026,9,closed_day=date(2026,11,22)) if r["day"]==str(day))
    assert result["value"]==expected["ds_mwh"] and result["cash"]==expected["cash_eur"]
    assert result["reconciliation"] is None and len(result["evidence"])==2
    assert result["evidence"][0]["old_value"] is None
    assert all(r["publication_timestamp"] is None and r["point_direction"] is None for r in result["evidence"])
    assert all(s=="Non disponibile" for _,s in m.workflow([],result)[:4])


def test_import_acquisition_is_per_version_and_idempotent():
    rows=sample_rows()[:2]
    a=merge_csv(None,archive_csv(rows[:1]).encode(),acquired=NOW-timedelta(hours=2))
    b=merge_csv(a,archive_csv(rows).encode(),acquired=NOW)
    duplicate=merge_csv(b,archive_csv(rows).encode(),acquired=NOW+timedelta(hours=1))
    assert duplicate["version_provenance"]==b["version_provenance"]
    assert b["version_provenance"][m.version_key(rows[0])]["retrieved_at"]!=(b["version_provenance"][m.version_key(rows[1])]["retrieved_at"])
    assert duplicate["rows"]==rows


def test_jarvis_audit_reuses_actual_provisional_final_pair_only():
    a=record("withdrawals")
    state={"jarvis_aggregate_archive_v1":{"records":[a]}}
    assert m.jarvis_audit(state,DAY,NOW)[0]["old_value"] is None
    b=replace(a,stage="definitive",value=D(12),published_at=NOW-timedelta(hours=1),report_ref="Final")
    state["jarvis_aggregate_archive_v1"]["records"].append(b)
    rows=m.jarvis_audit(state,DAY,NOW)
    assert rows[-1]["old_value"]==10 and rows[-1]["new_value"]==12
    assert all(r["retrieved_at"] is None for r in rows)


def test_portfolio_partial_missing_duplicate_and_other_shipper_are_not_completed():
    day=sample_rows()[0].day
    rows=[sample_rows()[0],replace(sample_rows()[1],user="OTHER",withdrawn=D(1))]
    state=portfolio(rows)
    partial=m.portfolio_day(state,"DEMO-001",day,NOW)
    assert partial["value"] is not None and partial["cash"] is None
    assert m.workflow([],partial)[-1][1]=="Non disponibile"
    assert m.portfolio_day(state,"DEMO-001",day+timedelta(days=1),NOW)["value"] is None
    state[m.BALANCE_STATE]["rows"].append(rows[0])
    duplicate=m.portfolio_day(state,"DEMO-001",day,NOW)
    assert duplicate["value"] is None and duplicate["cash"] is None


def test_inventory_context_withholds_tied_conflicts_and_newer_empty_window():
    def result(value,at):
        return {"scope":"IT","acquired":at,"first":DAY,"last":DAY,
            "frame":pd.DataFrame([{"gas_day":DAY,"sendout_gwh_d":value,"status":"C"}])}
    a=result(10,NOW-timedelta(hours=1));b=result(20,a["acquired"])
    context={"inventory":[("ALSI",None,"IT",a,False),("ALSI",None,"IT",b,False)]}
    f=m.inventory_state(context,{},DAY)["ALSI_IT"]["result"]["frame"]
    assert len(f)==2 and f.sendout_gwh_d.nunique()==2
    empty={**b,"frame":b["frame"].iloc[:0],"acquired":NOW}
    context["inventory"].append(("ALSI",None,"IT",empty,False))
    assert m.inventory_state(context,{},DAY)["ALSI_IT"]["result"]["frame"].empty


def test_structural_direction_type_does_not_depend_on_day_coverage(network):
    rows=m.public_reconciliation(network,frame(network),DAY)
    expected={"INET_BP_65":"Solo ingresso","INET_BP_12":"Solo uscita",
              "INET_BP_78":"Bidirezionale","INET_BP_89":"Bidirezionale",
              "INET_BP_84":"Bidirezionale","INET_BP_35":"Bidirezionale"}
    for identifier,label in expected.items():
        matches=[r for r in rows if r["infrastructure_id"]==identifier]
        assert matches and {r["point_type"] for r in matches}=={label}
        if label=="Bidirezionale":
            assert {r["direction"] for r in matches}=={"entry","exit"}
            assert all(r["Physical Flow"] is None for r in matches)
    assert next(r for r in rows if r["infrastructure_id"]=="INET_BP_65")["Physical Flow"]==0
