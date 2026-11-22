"""Synthetic API fixtures only; no live requests or credentials in CI."""
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import json

import pytest
import requests

from gasops_app import italian_network_sources as src
from gasops_app.italian_network import applicable, load_network_assets
from gasops_app.italian_network_events import parse_interruptions, relevant_events, iip_events
from gasops_app.public_data import SourceUnavailable
from gasops_app.store import Store

DAY=date(2026,11,20)
NOW=datetime(2026,11,22,2,tzinfo=timezone.utc)


@pytest.fixture
def binding():
    return next(b for b in load_network_assets().bindings_for("INET_BP_65","ENTSOG") if b.direction == "entry")


def row(binding,**kw):
    return {"operatorKey":binding.operator_id,"pointKey":binding.external_id,"directionKey":binding.direction,
        "indicator":"Physical Flow","unit":"kWh/d","periodType":"day","value":2_000_000,"id":"synthetic-only",
        "periodFrom":"2026-11-20T06:00:00+01:00","periodTo":"2026-11-21T06:00:00+01:00",**kw}


@pytest.mark.parametrize("value,expected", [(0,Decimal(0)),(-1_000_000,Decimal(-1)),(None,None),("",None),("2500000",Decimal("2.5"))])
def test_kwh_to_gwh_missing_zero_signs_and_status(binding,value,expected):
    obs=src.parse_observations([row(binding,value=value,flowStatus="Provisional")],binding,DAY,DAY,NOW)[0]
    assert obs.value == expected and obs.unit == "GWh/d"
    assert obs.publication_status == "Provisional"
    assert obs.retrieved_at == NOW and obs.source_id == "synthetic-only"


@pytest.mark.parametrize("patch",[{"unit":"m3/d"},{"periodType":"hour"},{"pointKey":"ITP-00040"},
    {"value":True},{"value":"NaN"},{"value":"Infinity"},{"periodFrom":"2026-11-20T06:00:00"},
    {"periodTo":"2026-11-19T06:00:00+01:00"},{"indicator":"invented indicator"}])
def test_bad_identity_unit_date_or_measurement_rejected(binding,patch):
    with pytest.raises(ValueError):
        src.parse_observations([row(binding,**patch)],binding,DAY,DAY,NOW)


@pytest.mark.parametrize("day,start,end,hours",[
    (date(2026,3,28),"2026-03-28T06:00:00+01:00","2026-03-29T06:00:00+02:00",23),
    (date(2026,10,24),"2026-10-24T06:00:00+02:00","2026-10-25T06:00:00+01:00",25)])
def test_italian_gas_day_dst_is_not_forced_to_24_hours(binding,day,start,end,hours):
    obs=src.parse_observations([row(binding,periodFrom=start,periodTo=end)],binding,day,day,NOW)[0]
    assert obs.gas_day == day and (obs.period_to-obs.period_from).total_seconds() == hours*3600
    assert obs.source_period_from == start and obs.source_period_to == end and obs.source_unit == "kWh/d"
    assert applicable([obs],binding.point_direction,day,"Physical Flow") == 2


def test_revisions_last_na_wins_ties_conflict_and_missing_publication_cannot_resolve(binding):
    old=row(binding,value=2_000_000,lastUpdateDateTime="2026-11-21T10:00:00Z")
    new=row(binding,value=None,lastUpdateDateTime="2026-11-21T11:00:00Z")
    obs=src.parse_observations([old,new,old],binding,DAY,DAY,NOW)[0]
    assert obs.value is None and obs.quality_status == "N/A" and len(obs.revisions) == 2
    conflict=src.parse_observations([old,dict(old,value=3_000_000)],binding,DAY,DAY,NOW)[0]
    assert conflict.value is None and conflict.quality_status == "conflict"
    missing=src.parse_observations([old,row(binding,value=3_000_000)],binding,DAY,DAY,NOW)[0]
    assert missing.quality_status == "conflict"


def test_catalog_deduplicates_semantic_rows_and_withholds_conflicts():
    n=load_network_assets()
    item=dict(next(r for r in n.sources["opd"]["rows"] if r["pointKey"] == "ITP-00136"))
    def parse(rows,total=None):
        return src.parse_catalog(json.dumps({"operatorPointDirections":rows,"meta":{
            "count":len(rows),"total":len(rows) if total is None else total}}),NOW)
    assert len(parse([item,dict(item,dataSet=99)])["rows"]) == 1
    result=parse([item,dict(item,pointLabel="Different identity")])
    assert not result["rows"] and result["conflicts"]
    for rows,total in (([dict(item,tSOCountry="FR")],1),([item],2)):
        with pytest.raises(ValueError):
            parse(rows,total)


def test_loader_pagination_merges_revisions_across_pages_and_preserves_timezone(monkeypatch,binding):
    calls=[]
    def fake(store,**kw):
        calls.append(kw)
        offset=kw["params"]["offset"]
        rows=[row(binding,id=f"synthetic-{i}",lastUpdateDateTime="2026-11-21T10:00:00Z") for i in range(200)] if not offset else [
            row(binding,value=3_000_000,id="synthetic-new",lastUpdateDateTime="2026-11-21T11:00:00Z")]
        return kw["parse"](json.dumps({"operationalData":rows,"meta":{"offset":offset,"count":len(rows),"total":201}}),NOW)
    monkeypatch.setattr(src,"retrieve",fake)
    result=src.load_point(None,binding,DAY,DAY,now=NOW)
    assert len(calls) == 2 and result.records[0].value == 3 and len(result.records[0].revisions) == 201
    assert not result.partial
    assert calls[0]["params"]["timeZone"] == "CET" and "timezone" not in calls[0]["params"]
    assert calls[0]["attempts"] == 1 and calls[0]["max_bytes"] == 2_000_000
    with pytest.raises(ValueError):
        src.load_point(None,binding,NOW.date(),NOW.date(),now=NOW)


def test_partial_next_page_keeps_valid_first_page(monkeypatch,binding):
    calls=[]
    def fake(store,**kw):
        calls.append(kw)
        if len(calls) > 1:
            raise SourceUnavailable("Synthetic upstream failure")
        rows=[row(binding,id=f"synthetic-{i}") for i in range(200)]
        return kw["parse"](json.dumps({"operationalData":rows,"meta":{"count":200,"total":220,"offset":0}}),NOW)
    monkeypatch.setattr(src,"retrieve",fake)
    result=src.load_point(None,binding,DAY,DAY,now=NOW)
    assert result.partial and result.records[0].value == 2 and len(calls) == 2
    assert "Pagina successiva non disponibile" in result.warnings


def test_loader_stops_at_three_pages_and_flags_inconsistent_short_page(monkeypatch,binding):
    calls=[]
    def fake(store,**kw):
        calls.append(kw)
        rows=[row(binding,id=f"synthetic-{i}") for i in range(200)]
        return kw["parse"](json.dumps({"operationalData":rows,"meta":{
            "count":200,"total":999,"offset":kw["params"]["offset"]}}),NOW)
    monkeypatch.setattr(src,"retrieve",fake)
    assert src.load_point(None,binding,DAY,DAY,now=NOW).partial and len(calls) == 3
    def short(store,**kw):
        return kw["parse"](json.dumps({"operationalData":[row(binding)],"meta":{"count":1,"total":2}}),NOW)
    monkeypatch.setattr(src,"retrieve",short)
    assert src.load_point(None,binding,DAY,DAY,now=NOW).partial


def test_shared_sqlite_ttl_and_failed_refresh_keep_original_acquisition(monkeypatch,tmp_path,binding):
    from gasops_app import public_data
    payload=json.dumps({"operationalData":[row(binding)],"meta":{"count":1,"total":1}}).encode()
    calls=[]
    class Response:
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def raise_for_status(self):pass
        def iter_content(self,chunk_size):yield payload
    def get(*a,**kw):
        calls.append(kw)
        return Response()
    monkeypatch.setattr(public_data.requests,"get",get)
    monkeypatch.setattr(public_data,"utc_now",lambda:NOW)
    store=Store(tmp_path/"test.sqlite3")
    original=src.load_point(store,binding,DAY,DAY,now=NOW)
    cached=src.load_point(store,binding,DAY,DAY,now=NOW)
    assert len(calls) == 1 and cached.cached and cached.acquired == original.acquired
    def fail(*a,**kw):raise requests.Timeout()
    monkeypatch.setattr(public_data.requests,"get",fail)
    monkeypatch.setattr(public_data,"utc_now",lambda:NOW+timedelta(hours=13))
    fallback=src.load_point(store,binding,DAY,DAY,refresh=True,now=NOW+timedelta(hours=13))
    assert fallback.failed and fallback.cached and fallback.acquired == NOW
    assert fallback.records[0].value == 2


def test_facility_loader_uses_exact_company_and_facility_not_country_scope(monkeypatch):
    binding=next(b for b in load_network_assets().bindings if b.provider == "ALSI")
    seen=[]
    def fake(store,**kw):
        seen.append(kw)
        return {"synthetic":"fixture"}
    monkeypatch.setattr(src,"retrieve",fake)
    src.load_facility(None,"synthetic-key",binding,DAY,DAY,refresh=True)
    call=seen[0]
    assert call["params"]["company"] == binding.operator_id and call["params"]["facility"] == binding.external_id
    assert call["params"]["country"] == "IT" and call["refresh"]
    assert "synthetic-key" not in str(call["params"]) and "synthetic-key" not in call["key"]
    assert call["headers"]["x-key"] == "synthetic-key"
    with pytest.raises(ValueError):src.load_facility(None,"synthetic-key",replace(binding,external_id="IT"),DAY,DAY)


def test_interruptions_keep_zero_publications_but_do_not_turn_them_into_outages(binding):
    def event(value,identifier):
        return row(binding,value=value,id=identifier,interruptionType="Planned",capacityType="Firm",
                   lastUpdateDateTime="2026-11-21T10:00:00Z")
    rows=[event(0,"zero"),event(1_000_000,"positive"),event(None,"unknown")]
    result=parse_interruptions(json.dumps({"interruptions":rows,"meta":{"count":3,"total":3}}),NOW,binding,DAY,DAY)
    active=relevant_events(result["records"],DAY,DAY)
    assert len(result["records"]) == 3 and not result["partial"]
    assert len(active) == 1 and active[0]["source_id"] == "positive" and active[0]["value"] == 1
    with pytest.raises(ValueError):
        parse_interruptions(json.dumps({"interruptions":[event(-1,"negative")]}),NOW,binding,DAY,DAY)


def test_iip_exact_facility_matching_cancellation_and_virtual_groups_are_not_geocoded():
    network=load_network_assets()
    binding=next(b for b in network.bindings if b.provider == "ALSI")
    def umm(code,identifier,**kw):
        return {"messageId":identifier,"publicationDateTime":"2026-11-19T10:00:00Z",
            "assetCode":code,"eventStatus":"Active","countryCode":"IT",
            "eventStart":"2026-11-20T00:00:00Z","eventStop":"2026-11-22T00:00:00Z",**kw}
    result={"messages":[umm(binding.external_id,"a"),umm("21Z000000000274I","group"),
        umm(binding.operator_id,"company"),umm("missing","name",assetName="Panigaglia"),
        umm(binding.external_id,"cancel"),umm(binding.external_id,"cancel",eventStatus="Cancelled",
            publicationDateTime="2026-11-19T11:00:00Z")],"source_url":"https://iip.gie.eu/","acquired":NOW}
    events,unresolved=iip_events(network,result,DAY,DAY)
    assert len(events) == 1 and events[0]["infrastructure_id"] == binding.infrastructure_id
    assert unresolved == 3
    events,_=iip_events(network,result,DAY-timedelta(days=15),DAY-timedelta(days=10))
    assert not events
