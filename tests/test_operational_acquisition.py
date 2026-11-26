from datetime import date, datetime, timedelta, timezone
import json
from threading import Event

import pytest
import requests

from gasops_app import operational_acquisition as ops, public_data
from gasops_app.balancing_cockpit import inventory_state
from gasops_app.entsog import QUERY_POINTS, combine, load, parse_month
from gasops_app.gas_calendar import closed_gas_day, gas_day_bounds
from gasops_app.gas_data import source_context
from gasops_app.italian_network import load_network_assets, verified_bindings
from gasops_app.italian_network_page import _status_state
from gasops_app.operational_sources import load_agsi
from gasops_app.store import Store
from gasops_app.system_status import build_status

NOW = datetime(2026,11,26,10,tzinfo=timezone.utc)
DAY = closed_gas_day(NOW)


class Response:
    status_code=200
    def __init__(self, data):
        self.data = data
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass
    def raise_for_status(self):
        pass
    def iter_content(self, **_):
        yield json.dumps(self.data).encode()


def flow(point, day, value, at):
    first,last=gas_day_bounds(day)
    direction="entry" if point.endswith("entry") else "exit"
    return {"operatorKey":point[:11],"pointKey":point[11:-len(direction)],"directionKey":direction,
            "indicator":"Physical Flow","periodType":"day","unit":"kWh/d","periodFrom":first.isoformat(),
            "periodTo":last.isoformat(),"value":value,"lastUpdateDateTime":at.isoformat(),"flowStatus":"Confirmed"}


@pytest.fixture
def provider(monkeypatch,tmp_path):
    network=load_network_assets()
    store=Store(tmp_path/"state.sqlite3")
    run={"now":NOW,"requests":[],"value":1_000_000,"error":False,"fail_day":None}
    monkeypatch.setattr(public_data,"utc_now",lambda:run["now"])

    def get(url,params,**kw):
        run["requests"].append((url,params))
        if run["error"]:
            raise requests.Timeout()
        if "operatorpointdirections" in url:
            rows=network.sources["opd"]["rows"]
            return Response({"operatorPointDirections":rows,"meta":{"count":len(rows),"total":len(rows)}})
        first,last=map(date.fromisoformat,(params["from"],params["to"]))
        days=[first+timedelta(days=i) for i in range((last-first).days+1)]
        if "operationaldatas" in url:
            points=params["pointDirection"].split(",")
            rows=[flow(p,d,run["value"],run["now"]-timedelta(minutes=1)) for p in points for d in days
                  if run["fail_day"]!=d or p in QUERY_POINTS]
            return Response({"operationalData":rows,"meta":{"count":len(rows),"total":len(rows),"offset":0}})
        assert kw["headers"]["x-key"]=="fixture"
        rows=[{"code":"IT","gasDayStart":d.isoformat(),"status":"C","gasInStorage":30,"withdrawal":10,
               "injection":8,"workingGasVolume":60,"full":50,"inventory":{"gwh":15,"lng":5},
               "sendOut":7,"dtmi":20,"dtrs":10} for d in days if d!=run.get("inventory_gap")]
        return Response({"last_page":1,"data":rows})

    monkeypatch.setattr(public_data.requests,"get",get)
    return network,store,run


def acquire(network,store,run,**kwargs):
    now=run["now"]
    work=ops.plan(network,ops.journal(store),now,api_key="fixture",**kwargs)
    ops.synchronize(store,network,work,now,api_key="fixture",clock=lambda:now,pause=0)
    return work


def observed(network,store,now,day):
    flags=ops.journal(store)
    state={"operational_acquisition":flags}
    context=source_context(network,(),state,now,store=store,first=day,last=day)
    return build_status(network,context["snapshots"],_status_state(context,state,now,day),now,gas_day=day)


def test_cold_backfills_90_days_and_reopens_persistent_sources(provider):
    network,store,run=provider
    batch=acquire(network,store,run)
    counts=ops.journal(store)["attempts"]
    assert set(counts)=={"srg","agsi","alsi",*(p.point_direction for p in verified_bindings(network))}
    assert all(len(attempts)==90 for attempts in counts.values())
    assert all((last-first).days<28 for p,_,_,first,last,_ in batch if p in ("srg","network"))
    persistent=Store(store.path)
    for day in (DAY,DAY-timedelta(days=89)):
        status=observed(network,persistent,NOW,day)
        assert status.entry_flow_observed.coverage.valid==6 and status.entry_flow_observed.value==6
        assert status.storage_level.value==30 and status.lng_sendout.value==7
        assert status.demand_actual.value==3
        assert all(c.measure.gas_day==day for c in status.components)
    assert not acquire(network,persistent,run)


def test_published_stock_keeps_its_own_day_and_srg_cache_feeds_daily_models(provider):
    network,store,run=provider
    run["inventory_gap"]=DAY
    acquire(network,store,run)
    state = {"operational_acquisition":ops.journal(store)}
    context = source_context(network,(),state,NOW,store=store,first=DAY-timedelta(days=1),last=DAY)
    status = build_status(network,context["snapshots"],_status_state(context,state,NOW,DAY),NOW,gas_day=DAY)
    assert status.storage_level.gas_day==DAY-timedelta(days=1)
    assert status.storage_level.value==30
    assert status.demand_actual.value==3
    assert next(c.measure for c in status.components if c.id=="withdrawal").value is None
    # Forecasting and report sources can open the same cache with networking off.
    requests_before = len(run["requests"])
    with public_data.cached_only():
        bundle,_ = load(store,now=NOW)
        inventory = load_agsi(store,"fixture","IT",now=NOW)
    assert len(inventory["frame"])==89 and not inventory["failed"]
    assert bundle.origin.latest_period==DAY.isoformat() and len(bundle.rows)>=90
    assert len(run["requests"])==requests_before


def test_incremental_tail_keeps_history_and_reconciles_revisions(provider):
    network,store,run=provider
    acquire(network,store,run)
    run.update(now=NOW+timedelta(days=1),value=2_000_000,requests=[])
    batch=acquire(network,store,run)
    closed=closed_gas_day(run["now"])
    assert batch and all(closed-timedelta(days=6)<=a<=b<=closed for _,_,_,a,b,_ in batch)
    assert observed(network,store,run["now"],closed).entry_flow_observed.value==12
    assert observed(network,store,run["now"],DAY).entry_flow_observed.value==12
    assert observed(network,store,run["now"],DAY-timedelta(days=20)).entry_flow_observed.value==6


def test_missing_selected_day_and_dst_use_exact_gas_period(provider):
    network,store,run=provider
    day=date(2025,10,25)
    work=acquire(network,store,run,first=day,last=day)
    assert len(work)==19 and all(first==last==day for _,_,_,first,last,_ in work)
    report=observed(network,store,NOW,day)
    assert report.hours==25 and report.entry_flow_observed.value==6 and report.lng_sendout.value==7
    assert observed(network,store,NOW,day+timedelta(days=1)).entry_flow_observed.value is None


def test_failed_refresh_preserves_last_valid_acquisition_and_rate_limits_retry(provider):
    network,store,run=provider
    acquire(network,store,run,first=DAY,last=DAY)
    run.update(now=NOW+timedelta(minutes=2),error=True)
    acquire(network,store,run,first=DAY,last=DAY,force=True)
    report=observed(network,Store(store.path),run["now"],DAY)
    assert report.entry_flow_observed.value==6 and report.entry_flow_observed.freshness=="stale"
    assert report.entry_flow_observed.retrieved_at==NOW
    assert report.demand_actual.value==3 and report.demand_actual.freshness=="stale"
    assert report.storage_level.value==30 and report.storage_level.freshness=="stale"
    assert not acquire(network,store,run,first=DAY,last=DAY,force=True)


def test_latest_day_prefers_broad_actual_coverage(provider):
    network,store,run=provider
    prior=DAY-timedelta(days=1)
    run["fail_day"]=DAY
    acquire(network,store,run,first=prior,last=DAY)
    context=source_context(network,(),{},NOW,store=store,first=prior,last=DAY)
    result=build_status(network,context["snapshots"],inventory_state(context,{},None),NOW)
    assert result.latest_observed_gas_day==DAY and result.gas_day==prior
    # A specific day with no physical publications is still eligible for retry.
    batch=ops.plan(network,ops.journal(store),NOW+timedelta(minutes=16),first=DAY,last=DAY)
    assert len(batch)==16 and all(task[0]=="network" for task in batch)


def test_only_newest_dated_sector_edition_counts():
    earlier=NOW-timedelta(hours=2)
    later=NOW-timedelta(hours=1)
    rows=[flow(point,DAY,1_000_000,earlier) for point in QUERY_POINTS]
    rows.append(flow(QUERY_POINTS[0],DAY,2_000_000,later))
    payload={"operationalData":rows}
    parsed=parse_month(payload,DAY,DAY,NOW)
    assert parsed.values[DAY,"distribution_gwh"]==2
    late_fetch = parse_month({"operationalData":rows[:-1]},DAY,DAY,NOW+timedelta(hours=1))
    bundle = combine([parsed,late_fetch],DAY,DAY)
    assert bundle.rows.iloc[0]["distribution_gwh"]==2


def test_entsog_quota_rejection_defers_other_requests_in_the_batch(provider,monkeypatch):
    network,store,run=provider
    errors = []
    def capped(*args,**kwargs):
        errors.append(True)
        raise ops.SourceUnavailable("ENTSOG: HTTP 429.")
    monkeypatch.setattr(ops,"load_range",capped)
    monkeypatch.setattr(ops,"load_catalog",lambda *a,**kw:pytest.fail("Quota already reached"))
    acquire(network,store,run,first=DAY,last=DAY)
    assert len(errors)==1 and len(run["requests"])==2  # GIE is a separate provider.
    assert ops.journal(store)["connections"]["network"]["failed"]
    assert not acquire(network,store,run,first=DAY,last=DAY)


def test_concurrent_sessions_share_one_work_item(monkeypatch,tmp_path):
    store=Store(tmp_path/"shared.sqlite3")
    network=load_network_assets()
    start,finish=Event(),Event()
    calls=[]
    def worker(*_,**__):
        calls.append(1)
        start.set()
        finish.wait(3)
    monkeypatch.setattr(ops,"network_allowed",lambda:True)
    monkeypatch.setattr(ops,"synchronize",worker)
    job=ops.schedule(store,network,NOW,sources=("srg",))
    try:
        assert start.wait(2)
        second=ops.schedule(Store(store.path),network,NOW,sources=("srg",))
        assert second is job and calls==[1]
    finally:
        finish.set()
        job.result(timeout=4)
