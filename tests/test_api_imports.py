"""Synthetic provider responses; no credentials or network in these checks."""
from dataclasses import replace
from datetime import date,datetime,timedelta,timezone
from decimal import Decimal
import json

import pandas as pd
import pytest
import requests

from gasops_app import operational_sources as gie, gas_data as data
from gasops_app import italian_network_refresh as net, live_sources as live, terna_power as terna
from gasops_app.gas_calendar import gas_day_bounds
from gasops_app.italian_network import load_network_assets,verified_bindings,Observation
from gasops_app.italian_network_sources import Snapshot
from gasops_app.store import Store

NOW=datetime(2026,11,23,12,tzinfo=timezone.utc)
DAY=date(2026,11,22)


def iip_page(page,total=5,*,repeat=False,**meta):
    start=(page-1)*2
    return json.dumps({"data":[{"messageId":str(0 if repeat else n),"revision":n}
        for n in range(start,min(start+2,total))],
        "meta":{"current_page":page,"last_page":(total+1)//2,"per_page":2,"total":total,**meta}})


def test_iip_follows_verified_pages_and_exports_complete_records(monkeypatch):
    calls=[]
    def retrieve(store,**kw):
        page=kw["params"]["page"]
        calls.append(page)
        return kw["parse"](iip_page(page),NOW)
    monkeypatch.setattr(gie,"retrieve",retrieve)
    result=gie.load_iip(None,"synthetic-key",now=NOW,refresh=True)
    assert calls==[1,2,3] and len(result["messages"])==5
    assert result["pagination_complete"] and not result["partial"] and result["pages_loaded"]==3
    exported=json.loads(gie.attributed_iip_json(result))
    assert exported["messages"]==result["messages"] and exported["pagination_complete"]
    assert exported["pagination_diagnostic"]["returned_records"]==5
    assert "synthetic-key" not in json.dumps(exported)


@pytest.mark.parametrize("problem",["failure","drift","wrong_page","repeated_records","cached_failure"])
def test_iip_partial_acquisition_retains_valid_records_and_flags_the_gap(monkeypatch,problem):
    calls=[]
    def retrieve(store,**kw):
        page=kw["params"]["page"]
        calls.append(page)
        if page==2 and problem=="failure":raise gie.SourceUnavailable("Synthetic outage")
        if page==2 and problem=="drift":return kw["parse"](iip_page(page,total=6),NOW)
        if page==2 and problem=="wrong_page":return kw["parse"](iip_page(1),NOW)
        if page==2 and problem=="repeated_records":return kw["parse"](iip_page(1).replace('"current_page": 1','"current_page": 2'),NOW)
        return kw["parse"](iip_page(page),NOW-timedelta(hours=3) if page==2 else NOW,
            cached=page==2,failed=page==2 and problem=="cached_failure")
    monkeypatch.setattr(gie,"retrieve",retrieve)
    result=gie.load_iip(None,"synthetic-key",now=NOW,refresh=True)
    assert result["partial"] and not result["pagination_complete"]
    assert result["messages"][0]["messageId"]=="0" and calls[:2]==[1,2]
    if problem in ("failure","wrong_page","cached_failure"):assert result["failed"]
    if problem=="cached_failure":assert result["cached"] and result["acquired"]==NOW-timedelta(hours=3)


def test_iip_limits_pages_and_does_not_guess_unknown_pagination(monkeypatch):
    calls=[]
    def retrieve(store,**kw):
        page=kw["params"]["page"]
        calls.append(page)
        return kw["parse"](iip_page(page,total=20),NOW)
    monkeypatch.setattr(gie,"retrieve",retrieve)
    result=gie.load_iip(None,"synthetic-key",now=NOW)
    assert calls==[1,2,3,4,5] and result["limit_reached"] and result["partial"]
    calls.clear()
    def unknown(store,**kw):
        calls.append(1)
        return kw["parse"](json.dumps({"data":[{"messageId":"x"}]}),NOW)
    monkeypatch.setattr(gie,"retrieve",unknown)
    assert gie.load_iip(None,"synthetic-key",now=NOW)["partial"] and calls==[1]


def test_iip_keeps_different_source_revisions_of_the_same_identifier(monkeypatch):
    monkeypatch.setattr(gie,"retrieve",lambda store,**kw:kw["parse"](iip_page(kw["params"]["page"],repeat=True),NOW))
    result=gie.load_iip(None,"synthetic-key",now=NOW)
    assert len(result["messages"])==5 and {r["messageId"] for r in result["messages"]}=={"0"}
    assert result["pagination_complete"]


def point_snapshot(binding,first,last,**kwargs):
    start,stop=gas_day_bounds(last)
    observation=Observation(binding.infrastructure_id,binding.point_direction,"Physical Flow",Decimal(0),"GWh/d",
        start,stop,last,NOW,NOW.isoformat(),"Synthetic ENTSOG","https://example.invalid/fixture","fixture","valid","Confirmed")
    return Snapshot(binding.point_direction,(observation,),first,last,NOW)


def test_network_batch_uses_existing_bindings_and_preserves_other_points_on_failure(monkeypatch):
    network=load_network_assets()
    bindings=verified_bindings(network)
    rejected,failed=bindings[:2]
    catalog={**network.sources["opd"],"failed":False,"acquired":NOW,"rows":[r for r in network.sources["opd"]["rows"]
        if r["pointKey"]!=rejected.external_id]}
    monkeypatch.setattr(net,"load_catalog",lambda *a,**k:catalog)
    calls=[]
    def point(store,binding,first,last,**kw):
        calls.append(binding.point_direction)
        if binding==failed:raise ValueError("Synthetic provider failure")
        return point_snapshot(binding,first,last)
    monkeypatch.setattr(net,"load_point",point)
    monkeypatch.setattr(net,"load_interruptions",lambda *a,**k:{"failed":False,"records":()})
    prior=point_snapshot(failed,DAY-timedelta(days=6),DAY)
    state={net.STATE:{"snapshots":{(failed.point_direction,prior.first,prior.last):prior}}}
    net.refresh_network_batch(state,None,network,prior.first,DAY,NOW)
    saved=state[net.STATE]
    assert rejected.point_direction not in calls and len(calls)>1
    assert rejected.point_direction in saved["failures"] and failed.point_direction in saved["failures"]
    assert prior in saved["snapshots"].values() and saved["summary"]["partial"]
    frame=data.collect(network,(),state,NOW)
    assert frame.usable.any() and (frame.value.dropna()==0).all()
    assert not frame.infrastructure_id.isna().any()
    before=len(calls)
    net.refresh_network_batch(state,None,network,prior.first,DAY,NOW+timedelta(seconds=1))
    assert len(calls)==before


def test_network_budget_keeps_pending_points_and_prioritizes_them_next_time(monkeypatch):
    network=load_network_assets()
    ticks=[0]
    calls=[]
    monkeypatch.setattr(net,"monotonic",lambda:ticks[0])
    monkeypatch.setattr(net,"load_catalog",lambda *a,**k:{**network.sources["opd"],"failed":False,"acquired":NOW})
    def point(store,binding,first,last,**kw):
        calls.append(binding.point_direction)
        ticks[0]+=100
        return point_snapshot(binding,first,last)
    monkeypatch.setattr(net,"load_point",point)
    monkeypatch.setattr(net,"load_interruptions",lambda *a,**k:{"failed":False,"records":()})
    state={}
    net.refresh_network_batch(state,None,network,DAY,DAY,NOW)
    pending=state[net.STATE]["pending"]
    assert pending and calls[0] not in pending
    net.refresh_network_batch(state,None,network,DAY,DAY,NOW+timedelta(minutes=2))
    assert calls[1] in pending and state[net.STATE]["summary"]["partial"]


def test_gie_metrics_are_available_to_chart_table_and_csv_without_unit_conversion():
    network=load_network_assets()
    storage={"code":"IT","gasDayStart":str(DAY),"status":"C","gasInStorage":"90","workingGasVolume":"100",
        "full":"90","injection":"0","withdrawal":"7","injectionCapacity":"12","withdrawalCapacity":"18"}
    gas={"code":"IT","gasDayStart":str(DAY),"status":"C","inventory":{"lng":"20","gwh":"130"},
        "dtmi":"50","sendOut":"40","dtrs":"100"}
    a=gie.parse_agsi(json.dumps({"last_page":1,"data":[storage]}),NOW,scope="IT")
    b=gie.parse_alsi(json.dumps({"last_page":1,"data":[gas]}),NOW,scope="IT")
    frame=data.collect(network,(),{"AGSI+_IT":{"result":a},"ALSI_IT":{"result":b}},NOW)
    assert len(frame)==12 and not frame.duplicated(["provider","entity_key","indicator","unit","gas_day"]).any()
    for indicator,value,unit in (("Storage injection",0,"GWh/d"),("Storage withdrawal capacity",18,"GWh/d"),
            ("LNG energy inventory",130,"GWh"),("LNG liquid inventory",20,"10³ m³ LNG")):
        row=frame.loc[frame.indicator==indicator].iloc[0]
        assert row.value==value and row.unit==unit and row.observed_at is None
        selected=data.select(frame,row.provider,[row.entity_key],indicator,unit,"publisher_day",DAY,DAY)
        assert data.series_frame(selected,DAY,DAY).iloc[0,0]==value
        assert indicator in gie.attributed_csv({"frame":selected},per_row_source=True)


def test_terna_token_reuse_is_scoped_expires_and_isolates_credentials(monkeypatch):
    calls=[]
    clock=[0]
    def request(*args,**kw):
        calls.append(kw["data"]["client_id"])
        return {"access_token":"synthetic-"+str(len(calls)),"expires_in":300}
    monkeypatch.setattr(terna,"_json_request",request)
    monkeypatch.setattr(terna,"monotonic",lambda:clock[0])
    with terna.token_batch():
        first=terna.get_token("a","synthetic-secret")
        assert terna.get_token("a","synthetic-secret")==first and len(calls)==1
        assert terna.get_token("b","synthetic-secret")!=first
        clock[0]=286
        assert terna.get_token("a","synthetic-secret")!=first
    assert terna._TOKEN_BATCH.get() is None
    with pytest.raises(ValueError),terna.token_batch():
        terna.get_token("a","synthetic-secret")
        raise ValueError("Synthetic cancellation")
    assert terna._TOKEN_BATCH.get() is None and len(calls)==4


@pytest.mark.parametrize("status",[401,403,404,429])
def test_rejected_requests_do_not_retry_or_replace_last_valid_cache(monkeypatch,tmp_path,status):
    from gasops_app import public_data
    store=Store(tmp_path/"cache.sqlite3")
    original=json.dumps({"value":42})
    store.cache("fixture",NOW.isoformat(),original)
    calls=[]
    def get(*a,**kw):
        calls.append(1)
        response=requests.Response()
        response.status_code=status
        raise requests.HTTPError(response=response)
    monkeypatch.setattr(requests,"get",get)
    def parse(text,at,**flags):return {**json.loads(text),**flags,"acquired":at}
    result=public_data.retrieve(store,key="fixture",name="Synthetic provider",url="https://example.invalid/fixture",
        parse=parse,ttl=timedelta(0),refresh=True,attempts=3)
    assert len(calls)==1 and result["value"]==42 and result["cached"] and result["failed"]
    assert store.cached("fixture")[1]==original


def test_european_scope_failure_does_not_block_italy_or_other_providers(monkeypatch):
    calls=[]
    def storage(store,key,scope,**kw):
        calls.append(scope)
        if scope=="EU":raise ValueError("Synthetic outage")
        return {"scope":"IT","frame":pd.DataFrame({"stock_twh":[0]}),"failed":False}
    monkeypatch.setattr(live,"load_agsi",storage)
    previous={"frame":pd.DataFrame({"stock_twh":[10]})}
    state={"AGSI+_EU":{"result":previous}}
    progress=[]
    assert live.refresh(state,None,NOW,["agsi"],gie="synthetic-key",gie_scopes=("IT","EU"),clock=lambda:NOW,
        progress=lambda *event:progress.append(event))
    assert calls==["IT","EU"] and state["AGSI+_EU"]["result"] is previous
    assert state["AGSI+_IT"]["result"]["frame"].iloc[0,0]==0
    assert state[live.STATUS]["sources"]["agsi"]["status"]=="Da verificare"
    assert progress[-1][0]==progress[-1][1]


def test_connection_selection_only_acquires_on_click_and_passes_scope(monkeypatch):
    from streamlit.testing.v1 import AppTest
    from gasops_app import connections_page as page
    configuration={"available":["monthly","daily","network"],"gie":None,"terna":None,"ai":None,"documents":None}
    monkeypatch.setattr(page,"access",lambda:configuration)
    monkeypatch.setattr(page.session,"database",lambda:None)
    calls=[]
    def refresh(*args,**kwargs):calls.append(kwargs);return True
    monkeypatch.setattr(page,"refresh_all",refresh)
    app=AppTest.from_string("from gasops_app.connections_page import page\npage()",default_timeout=20).run()
    assert not app.exception and not calls
    app.multiselect(key="connections_sources").set_value([]).run()
    assert app.button(key="connections_refresh").disabled and not calls
    app.multiselect(key="connections_sources").set_value(["network"]).run()
    app.selectbox(key="connections_network_days").set_value(30).run()
    assert not calls
    app.button(key="connections_refresh").click().run()
    assert not app.exception and len(calls)==1
    assert calls[0]["selected"]==["network"] and calls[0]["network_days"]==30 and calls[0]["gie_scopes"]==("IT",)


def test_invalid_or_empty_source_selection_never_consumes_a_refresh(monkeypatch):
    from gasops_app import connections_page as page
    config={"available":["daily"],"gie":None,"terna":None,"ai":None,"documents":None}
    monkeypatch.setattr(page,"refresh",lambda *a,**k:pytest.fail("Unexpected acquisition"))
    state={}
    assert not page.refresh_all(state,None,config,NOW,selected=[])
    with pytest.raises(ValueError):page.refresh_all(state,None,config,NOW,selected=["not-configured"])
    assert live.STATUS not in state


def test_parallel_monthly_sources_preserve_offline_policy_in_both_workers(monkeypatch,tmp_path):
    from threading import Barrier
    from gasops_app import mensile,public_data
    from gasops_app.data import synthetic
    barrier=Barrier(2)
    store=Store(tmp_path/"empty.sqlite3")
    fixture=synthetic()
    def forbidden(*a,**k):pytest.fail("The offline policy escaped into an acquisition worker")
    monkeypatch.setattr(requests,"get",forbidden)
    def read(provider):
        barrier.wait(timeout=3)
        try:
            public_data.retrieve(store,key=provider,name=provider,url="https://example.invalid/fixture",
                parse=lambda *a,**k:None,ttl=timedelta(hours=1))
        except public_data.SourceUnavailable:
            if provider=="balance":return fixture
            raise
        pytest.fail("The empty cache cannot contain observations")
    monkeypatch.setattr(mensile.eurostat,"load",lambda *a,**k:read("balance"))
    monkeypatch.setattr(mensile,"load_arera",lambda *a,**k:read("price"))
    with public_data.cached_only():
        result,warning=mensile.load_monthly(store)
    assert result is fixture and warning


def test_pending_gie_facilities_are_imported_without_repeating_country_or_iip_calls(monkeypatch):
    network=load_network_assets()
    binding=next(b for b in network.bindings if b.provider=="ALSI" and b.mapping_confidence=="confirmed")
    state={net.STATE:{"pending":(binding.provider+":"+binding.external_id,)}}
    monkeypatch.setattr(net,"load_catalog",lambda *a,**k:{**network.sources["opd"],"failed":False,"acquired":NOW})
    def forbidden(*a,**k):pytest.fail("Pending facilities must not repeat the other acquisitions")
    monkeypatch.setattr(net,"load_point",forbidden)
    monkeypatch.setattr(net,"load_agsi",forbidden)
    monkeypatch.setattr(net,"load_iip",forbidden)
    calls=[]
    def facility(store,key,b,first,last,**kw):
        calls.append((b.provider,b.external_id))
        return {"failed":False,"acquired":NOW,"scope":b.external_id,
            "frame":pd.DataFrame({"gas_day":[DAY],"sendout_gwh_d":[4]})}
    monkeypatch.setattr(net,"load_facility",facility)
    net.refresh_network_batch(state,None,network,DAY,DAY,NOW,api_key="synthetic-key")
    assert calls==[(binding.provider,binding.external_id)] and not state[net.STATE]["pending"]
    assert state[net.STATE]["summary"]["facilities"]==1


def test_cached_response_is_validated_without_claiming_current_reachability():
    from gasops_app.connections_page import provider_rows
    config={"available":["network"],"gie":None,"terna":None,"ai":None,"documents":None}
    state={live.STATUS:{"sources":{"network":{"status":"Acquisito","at":NOW.isoformat(),
        "reachable":None,"validated":True,"records":42}}}}
    row=next(r for r in provider_rows(state,config,NOW) if r["Fonte"]=="ENTSOG · rete italiana")
    assert row["Raggiungibile"] is None and row["Risposta validata"] is True
    assert row["Record disponibili"]==42


def test_other_provider_failures_do_not_mislabel_a_valid_network_batch(monkeypatch):
    network=load_network_assets()
    monkeypatch.setattr(net,"load_catalog",lambda *a,**k:{**network.sources["opd"],"failed":False,"acquired":NOW})
    monkeypatch.setattr(net,"load_point",lambda store,b,first,last,**kw:point_snapshot(b,first,last))
    monkeypatch.setattr(net,"load_interruptions",lambda *a,**kw:{"failed":False,"records":()})
    state={net.STATE:{"failures":{"context:gie_iip":NOW}}}
    net.refresh_network_batch(state,None,network,DAY,DAY,NOW)
    assert not state[net.STATE]["summary"]["partial"]
    assert "context:gie_iip" in state[net.STATE]["failures"]


def test_terna_unauthorized_response_invalidates_token_reuse(monkeypatch):
    from contextlib import contextmanager
    native=terna._json_request
    issued=[]
    def token_request(*args,**kw):
        issued.append(1)
        return {"access_token":"synthetic-"+str(len(issued)),"expires_in":300}
    monkeypatch.setattr(terna,"_json_request",token_request)
    @contextmanager
    def unauthorized(*a,**kw):
        from types import SimpleNamespace
        yield SimpleNamespace(status_code=401)
    monkeypatch.setattr(terna.requests,"request",unauthorized)
    with terna.token_batch():
        first=terna.get_token("id","synthetic-secret")
        with pytest.raises(terna.SourceUnavailable):native("GET",terna.GEN,headers={"Authorization":"Bearer "+first})
        assert terna.get_token("id","synthetic-secret")!=first
