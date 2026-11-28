"""Unified Explorer checks. Generated observations below are synthetic fixtures."""
import csv
from dataclasses import replace
from datetime import date,datetime,timedelta,timezone
from decimal import Decimal as D
from io import StringIO
import json

import pandas as pd
import pytest
import requests

from gasops_app import gas_data as g
from gasops_app.gas_calendar import gas_day_bounds
from gasops_app.italian_network import Observation,load_network_assets
from gasops_app.italian_network_sources import Snapshot
from gasops_app.operational_sources import attributed_csv,parse_agsi,parse_alsi
from gasops_app.source_health import observation_health,session_health
from gasops_app.store import Store

NOW=datetime(2026,11,23,12,tzinfo=timezone.utc)
DAY=date(2026,11,22)


@pytest.fixture
def network():return load_network_assets()


def obs(network,day=DAY,value="10",indicator="Physical Flow",**changes):
    b=next(b for b in network.bindings_for("INET_BP_65","ENTSOG") if b.direction=="entry")
    start,end=gas_day_bounds(day)
    return replace(Observation(b.infrastructure_id,b.point_direction,indicator,D(value) if value is not None else None,"GWh/d",start,end,
        day,NOW-timedelta(hours=1),(NOW-timedelta(hours=2)).isoformat(),"Synthetic source",
        "https://example.invalid/fixture","fixture-id","valid","Confirmed"),**changes)


def dataset(network,rows,**snapshot_flags):
    s=Snapshot(rows[0].point_direction,tuple(rows),min(o.gas_day or DAY for o in rows),
        max(o.gas_day or DAY for o in rows),max(o.retrieved_at for o in rows),**snapshot_flags)
    return g.collect(network,(),{g.MAP_STATE:{"snapshots":{"fixture":s}}},NOW)


def test_dataset_csv_table_and_chart_keep_values_zero_units_and_provenance(network):
    frame=dataset(network,[obs(network,DAY-timedelta(days=1),"2"),obs(network,value="0")])
    selected=g.select(frame,"ENTSOG",[frame.entity_key.iloc[0]],"Physical Flow","GWh/d","gas_day",DAY,DAY)
    assert len(selected)==1 and selected.value.iloc[0]==0 and selected.delta_d1.iloc[0]==-2
    assert selected.value_d1.iloc[0]==2 and selected.d1_gas_day.iloc[0]==DAY-timedelta(days=1)
    series=g.series_frame(selected,DAY,DAY)
    exported=list(csv.DictReader(StringIO(attributed_csv({"frame":selected},per_row_source=True))))
    assert D(exported[0]["value"])==selected.value.iloc[0]==series.iloc[0,0]
    assert D(exported[0]["delta_d1"])==-2
    assert exported[0]["observed_at"]!=exported[0]["retrieved_at"]
    assert set(g.FIELDS)<=set(exported[0])
    assert exported[0]["unit"]=="GWh/d" and exported[0]["point_direction"].endswith("entry")
    assert exported[0]["period_from"]==gas_day_bounds(DAY)[0].isoformat()


@pytest.mark.parametrize("day,hours",[(date(2026,3,28),23),(date(2026,10,24),25)])
def test_dst_keeps_original_gas_day_interval_in_csv(network,day,hours):
    frame=dataset(network,[obs(network,day)])
    # Ask explicitly for the historical window rather than the default last 92 days.
    s=Snapshot(obs(network,day).point_direction,(obs(network,day),),day,day,NOW-timedelta(hours=1))
    frame=g.collect(network,(s,),{},NOW,first=day,last=day)
    r=frame.iloc[0]
    assert (r.period_to-r.period_from).total_seconds()/3600==hours
    assert r.gas_day==day and r.usable


def test_holes_and_na_are_not_filled_or_compared_to_last_available_day(network):
    rows=[obs(network,DAY-timedelta(days=2),"3"),obs(network,value="5")]
    frame=dataset(network,rows)
    series=g.series_frame(frame,DAY-timedelta(days=2),DAY)
    assert pd.isna(series.iloc[1,0]) and frame.iloc[-1].delta_d1 is None
    missing=obs(network,value=None,quality_status="N/A")
    updated=dataset(network,[rows[0],missing])
    assert updated.iloc[-1].value is None and updated.iloc[-1].delta_d1 is None


def test_newer_empty_response_clears_older_observations(network):
    old=obs(network)
    a=Snapshot(old.point_direction,(old,),DAY,DAY,NOW-timedelta(hours=2))
    b=replace(a,records=(),acquired=NOW-timedelta(minutes=30))
    frame=g.collect(network,(a,),{g.MAP_STATE:{"snapshots":{"new":b}}},NOW)
    assert frame.empty


def test_duplicates_collapse_and_tied_acquisitions_preserve_conflict_evidence(network):
    o=obs(network)
    same=dataset(network,[o,o])
    assert len(same)==1
    a=Snapshot(o.point_direction,(o,),DAY,DAY,o.retrieved_at)
    b=replace(a,records=(replace(o,value=D(20)),))
    tied=g.collect(network,(),{g.MAP_STATE:{"snapshots":{"a":a,"b":b}}},NOW)
    assert len(tied)==1 and tied.value.iloc[0] is None and not tied.usable.iloc[0]
    assert tied.quality_status.iloc[0]=="conflict" and tied.revision_count.iloc[0]>=2
    assert len(json.loads(tied.revisions.iloc[0]))>=2


def test_source_revisions_remain_distinct_from_acquisition(network):
    versions=({"value":"9","observed_at":"2026-11-23T07:00:00Z"},
              {"value":"10","observed_at":"2026-11-23T08:00:00Z"})
    frame=dataset(network,[obs(network,revisions=versions)])
    assert frame.revision_count.iloc[0]==2 and json.loads(frame.revisions.iloc[0])[0]["value"]=="9"
    assert frame.observed_at.iloc[0]!=frame.retrieved_at.iloc[0]


@pytest.mark.parametrize("change",[{"retrieved_at":NOW+timedelta(hours=1)},
    {"observed_at":(NOW+timedelta(hours=1)).isoformat()},{"mapping_confidence":"candidate"}])
def test_future_and_unverified_evidence_is_not_available(network,change):
    assert dataset(network,[obs(network,**change)]).empty


def test_units_and_temporal_bases_cannot_be_overlaid(network):
    frame=dataset(network,[obs(network),obs(network,indicator="Firm Technical",gas_day=None,
        period_from=gas_day_bounds(DAY)[0]+timedelta(hours=1))])
    with pytest.raises(ValueError,match="confrontabili"):g.series_frame(frame,DAY,DAY)
    invalid=dataset(network,[obs(network,unit="m³/d")])
    assert not invalid.usable.iloc[0] and invalid.value.iloc[0] is None


def test_capacity_with_conflicting_overlapping_interval_is_not_charted(network):
    capacity=obs(network,indicator="Firm Technical",value="20")
    partial=replace(capacity,value=D(15),gas_day=None,period_from=capacity.period_from+timedelta(hours=4))
    frame=dataset(network,[capacity,partial])
    daily=frame.loc[frame.time_basis=="gas_day"]
    assert not daily.usable.any() and daily.quality_status.iloc[0]=="incompatible_interval"


def test_gie_aggregates_and_sites_keep_native_units_without_invented_publication(network):
    agsi=parse_agsi(json.dumps({"last_page":1,"data":[{"code":"IT","gasDayStart":str(DAY),"status":"C",
        "gasInStorage":"90","workingGasVolume":"100","full":"90","injection":"8","withdrawal":"7"}]}),NOW,scope="IT")
    b=next(b for b in network.bindings if b.provider=="ALSI")
    alsi=parse_alsi(json.dumps({"last_page":1,"data":[{"code":b.external_id,"gasDayStart":str(DAY),"status":"C",
        "inventory":{"lng":"20","gwh":"130"},"sendOut":"40","dtrs":"100","dtmi":"50"}]}),NOW,scope=b.external_id)
    state={"AGSI+_IT":{"result":agsi},g.MAP_STATE:{"facilities":{("ALSI",b.external_id):alsi}}}
    frame=g.collect(network,(),state,NOW)
    inventory=frame.loc[frame.provider=="AGSI+"].iloc[0]
    lng=frame.loc[frame.provider=="ALSI"].iloc[0]
    assert inventory.value==90 and inventory.unit=="TWh" and inventory.infrastructure_id is None
    assert lng.value==40 and lng.unit=="GWh/d" and lng.infrastructure_id==b.infrastructure_id
    assert frame.observed_at.isna().all() and frame.period_from.isna().all() and frame.period_to.isna().all()


@pytest.mark.parametrize("cached,failed,partial,age,day,expected",[
    (False,False,False,1,DAY,"Live"),(True,False,False,1,DAY,"Cached"),
    (False,False,False,1,DAY-timedelta(days=1),"Historical"),(False,False,True,1,DAY,"Partial"),
    (True,False,False,13,DAY,"Stale"),(False,True,False,1,DAY,"Stale")])
def test_shared_health_definitions(network,cached,failed,partial,age,day,expected):
    frame=dataset(network,[obs(network,day=day,retrieved_at=NOW-timedelta(hours=age))],cached=cached,failed=failed,partial=partial)
    health=observation_health(frame,day,day,NOW)
    assert health["state"]=={"Live":"Current","Stale":"Failed refresh" if failed else "Stale"}.get(expected,expected)
    assert health["valid"]==1 and health["expected"]==1
    assert health["acquired"]==(NOW-timedelta(hours=age)).isoformat()
    assert health["published_at"]!=(NOW-timedelta(hours=age)).isoformat()
    if failed:assert health["refresh_error"]


def test_health_monitor_extends_map_without_duplicate_gie_italy_diagnostics(network):
    frame=dataset(network,[obs(network)])
    health=session_health({},NOW,gas_rows=frame)
    assert len(health)==11 and health[-1]["source"].startswith("ENTSOG · Mazara")


def test_cache_metadata_lookup_is_bounded_and_prefix_is_literal(tmp_path):
    store=Store(tmp_path/"cache.sqlite3")
    for key in ("gas_1","gas%2","gas_3","other"):
        store.cache(key,NOW.isoformat(),"example")
    assert {r[0] for r in store.cached_entries("gas_",limit=1)}<={"gas_1","gas_3"}
    assert len(store.cached_entries("gas_",limit=1))==1
    with pytest.raises(ValueError):store.cached_entries("gas",limit=101)


def test_cached_map_page_is_parsed_offline_with_original_acquisition(network,tmp_path,monkeypatch):
    def forbidden(*a,**kw):raise AssertionError("Explorer cannot fetch")
    monkeypatch.setattr(requests,"get",forbidden)
    store=Store(tmp_path/"cache.sqlite3")
    b=next(b for b in network.bindings_for("INET_BP_65","ENTSOG") if b.direction=="entry")
    start,stop=gas_day_bounds(DAY)
    raw={"operationalData":[{"id":"cached-fixture","operatorKey":b.operator_id,"pointKey":b.external_id,
        "directionKey":"entry","indicator":"Physical Flow","periodType":"day","unit":"kWh/d","value":"2000000",
        "periodFrom":start.isoformat(),"periodTo":stop.isoformat(),"flowStatus":"Confirmed"}],
        "meta":{"count":1,"total":1,"offset":0}}
    acquired=NOW-timedelta(hours=2)
    store.cache(f"italian-map-ops-v1:{b.point_direction}:{DAY}:{DAY}:0",acquired.isoformat(),json.dumps(raw))
    frame=g.collect(network,(),{},NOW,store=store)
    assert len(frame)==1 and frame.value.iloc[0]==2 and frame.cached.iloc[0]
    assert frame.retrieved_at.iloc[0]==acquired and frame.observed_at.iloc[0] is None


def test_csv_preserves_decimal_values_and_escapes_formula_metadata(network):
    frame=dataset(network,[obs(network,value="-1.23456789",publication_status="=1+1")])
    csv_data=attributed_csv({"frame":frame},per_row_source=True)
    r=next(csv.DictReader(StringIO(csv_data)))
    assert D(r["value"])==D("-1.23456789") and r["publication_status"]=="'=1+1"
    with pytest.raises(ValueError,match="grande"):attributed_csv({"frame":frame},per_row_source=True,max_rows=0)
    with pytest.raises(ValueError,match="grande"):attributed_csv({"frame":frame},per_row_source=True,max_bytes=1)


def test_selection_limits_are_explicit(network):
    frame=dataset(network,[obs(network)])
    assert g.select(frame,"ALSI",[],"LNG send-out","GWh/d","publisher_day",DAY,DAY).empty
    with pytest.raises(ValueError,match="92"):g.select(frame,"ENTSOG",[],"Physical Flow","GWh/d","gas_day",DAY-timedelta(days=92),DAY)


def test_latest_gie_window_does_not_fill_holes_from_an_older_copy(network):
    def inventory(days,acquired):
        return {"scope":"IT","frame":pd.DataFrame([{"gas_day":d,"stock_twh":90.,"status":"C"} for d in days]),
            "acquired":acquired,"source":"Synthetic GIE","source_url":"https://example.invalid/gie",
            "cached":True,"failed":False,"first":DAY-timedelta(days=2),"last":DAY}
    old=inventory([DAY-timedelta(days=2),DAY-timedelta(days=1),DAY],NOW-timedelta(hours=2))
    new=inventory([DAY-timedelta(days=2),DAY],NOW-timedelta(hours=1))
    rows=g._inventory_rows([("AGSI+",None,"IT",old,False),("AGSI+",None,"IT",new,False)],network,NOW,DAY-timedelta(days=2),DAY)
    frame=g.validated_frame(rows)
    series=g.series_frame(frame,DAY-timedelta(days=2),DAY)
    assert len(frame)==2 and pd.isna(series.iloc[1,0])
    assert frame.iloc[-1].delta_d1 is None


def test_legacy_desk_reuses_snapshot_model_and_keeps_original_ids_and_row_acquisitions(network):
    from gasops_app import entsog_network as en
    b=next(b for b in network.bindings_for("INET_BP_65","ENTSOG") if b.direction=="entry")
    start,stop=gas_day_bounds(DAY)
    def part(indicator,acquired):
        raw={"operationalData":[{"id":"original-"+indicator,"operatorKey":b.operator_id,"pointKey":b.external_id,
            "directionKey":"entry","indicator":indicator,"periodType":"day","unit":"kWh/d","value":"2000000",
            "periodFrom":start.isoformat(),"periodTo":stop.isoformat(),"flowStatus":"Confirmed",
            "lastUpdateDateTime":(NOW-timedelta(hours=3)).isoformat()}],"meta":{"count":1,"total":1}}
        names=en.INDICATORS[:4] if indicator=="Physical Flow" else en.INDICATORS[4:]
        return names,en.parse_network(raw,b.point_direction,DAY,DAY,acquired,requested=names)
    flow=part("Physical Flow",NOW-timedelta(hours=1))
    cap=part("Firm Technical",NOW-timedelta(hours=2))
    result=en.combine_results((flow,cap))
    frame=g.collect(network,(),{g.DESK_STATE:result},NOW)
    r=frame.loc[frame.indicator=="Physical Flow"].iloc[0]
    assert r.source_id=="original-Physical Flow" and r.retrieved_at==NOW-timedelta(hours=1)
    assert r.observed_at==NOW-timedelta(hours=3) and r.revision_count==1
    assert "original-Physical Flow" in en.export_csv(result)


def test_health_latest_observation_has_its_own_timestamps(network):
    older=DAY-timedelta(days=1)
    old_at=NOW-timedelta(hours=20)
    new_at=NOW-timedelta(hours=1)
    new_pub=NOW-timedelta(hours=2)
    frame=dataset(network,[
        obs(network,older,retrieved_at=old_at,observed_at=(old_at-timedelta(hours=1)).isoformat()),
        obs(network,DAY,retrieved_at=new_at,observed_at=new_pub.isoformat()),
    ])
    h=observation_health(frame,older,DAY,NOW)
    assert h["valid"]==h["expected"]==2
    assert h["retrieved_at"]==h["acquired"]==new_at.isoformat()
    assert h["observed_at"]==h["published_at"]==new_pub.isoformat()
    assert h["cache_age"]==3600
    assert h["oldest_acquired"]==old_at.isoformat()
    assert h["cache_age_hours"]==20
    assert not h["stale"]
    assert h["timestamp_issues"]==0
    start,stop=gas_day_bounds(DAY)
    assert h["observation_period"]=={"from":start.isoformat(),"to":stop.isoformat()}
    assert h["coverage_period"]["from"]==gas_day_bounds(older)[0].isoformat()


def test_health_does_not_date_latest_period_with_newer_historical_download(network):
    older=DAY-timedelta(days=1)
    latest_at=NOW-timedelta(hours=4)
    latest_pub=NOW-timedelta(hours=5)
    frame=dataset(network,[
        obs(network,older,retrieved_at=NOW,observed_at=(NOW-timedelta(hours=1)).isoformat()),
        obs(network,DAY,retrieved_at=latest_at,observed_at=latest_pub.isoformat()),
    ])
    h=observation_health(frame,older,DAY,NOW)
    assert h["latest"]==DAY.isoformat()
    assert h["retrieved_at"]==latest_at.isoformat()
    assert h["published_at"]==latest_pub.isoformat()
    assert h["newest_acquired"]==NOW.isoformat()


def test_health_d1_age_is_separate_from_selected_observation(network):
    older=DAY-timedelta(days=1)
    old_at=NOW-timedelta(hours=20)
    frame=dataset(network,[
        obs(network,older,retrieved_at=old_at,observed_at=(old_at-timedelta(hours=1)).isoformat()),
        obs(network),
    ])
    selected=g.select(frame,"ENTSOG",[frame.entity_key.iloc[0]],"Physical Flow","GWh/d","gas_day",DAY,DAY)
    h=observation_health(selected,DAY,DAY,NOW)
    assert h["valid"]==h["expected"]==1
    assert h["oldest_acquired"]==old_at.isoformat()
    assert h["cache_age_hours"]==20
    assert not h["stale"]


def test_health_inconsistent_publication_is_explicit_not_relabelled(network):
    frame=dataset(network,[obs(network)])
    frame.loc[:,"observed_at"]=(NOW-timedelta(minutes=1)).isoformat()
    h=observation_health(frame,DAY,DAY,NOW)
    assert h["timestamp_issues"]==1
    assert h["observed_at"] is None and h["published_at"] is None
    assert h["retrieved_at"]==(NOW-timedelta(hours=1)).isoformat()
    assert h["partial"] and h["data_status"]=="Partial"
    assert h["valid"]==1
    assert frame.observed_at.iloc[0]==(NOW-timedelta(minutes=1)).isoformat()
