from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from gasops_app import assistant_evidence_cache as cache
from gasops_app import assistant_sources as src
from gasops_app.assistant_lookup import collect_context
from gasops_app.live_sources import STATUS
from gasops_app.mensile import ARERA_CACHE
from gasops_app.acer_market import CACHE_KEY
from gasops_app.store import Store

NOW=datetime(2026,11,28,12,tzinfo=timezone.utc)


def setup(tmp_path):
    store=Store(tmp_path/"evidence.sqlite3")
    store.cache(ARERA_CACHE,NOW.isoformat(),"raw price")
    store.cache(CACHE_KEY,NOW.isoformat(),"raw lng")
    calls=[]
    def collect(sources):
        calls.append(tuple(sources))
        return {key:{"source":key,"status":"available","acquired":NOW.isoformat(),
                     "period":"2026-10-01","value":42} for key in sources}
    return store,calls,collect


def run(store,state,collect,requested=(src.PRICE,),now=NOW,day=None):
    return cache.collect_cached(store,state,now,requested,day,collect,lambda:now)


def test_same_evidence_reused_and_return_isolated(tmp_path):
    store,calls,collect=setup(tmp_path)
    state={}
    result=run(store,state,collect)
    result[src.PRICE]["value"]=999
    second=run(store,state,collect,now=NOW+timedelta(seconds=10))
    assert second[src.PRICE]["value"]==42
    assert second[src.PRICE]["acquired"]==NOW.isoformat()
    second[src.PRICE]["value"]=0
    assert run(store,state,collect)[src.PRICE]["value"]==42
    assert calls==[(src.PRICE,)]
    run(store,{},collect)
    assert len(calls)==2


def test_same_timestamp_revision_invalidates_only_related_source(tmp_path):
    store,calls,collect=setup(tmp_path)
    state={}
    requested=(src.PRICE,src.ACER)
    run(store,state,collect,requested)
    store.cache(ARERA_CACHE,NOW.isoformat(),"raw revision")
    run(store,state,collect,requested)
    assert calls==[requested,(src.PRICE,)]
    run(store,state,collect,requested)
    assert len(calls)==2


def test_expiry_and_period_isolation(tmp_path):
    store,calls,collect=setup(tmp_path)
    state={}
    run(store,state,collect)
    run(store,state,collect,day=NOW.date()-timedelta(days=1))
    run(store,state,collect,now=NOW+cache.TTL)
    assert len(calls)==3
    assert cache.token(store,state,cache.groups((src.PRICE,),None)[0],NOW+timedelta(hours=12)) is None


def test_failed_manual_refresh_disables_reuse(tmp_path):
    store,calls,collect=setup(tmp_path)
    state={}
    run(store,state,collect)
    state[STATUS]={"sources":{"monthly":{"status":"Da aggiornare","at":NOW.isoformat()}}}
    run(store,state,collect)
    run(store,state,collect)
    assert len(calls)==3


def test_unavailable_partial_and_stale_are_not_cached(tmp_path):
    store,_,_=setup(tmp_path)
    for status in ("unavailable","partial","stale"):
        state={}
        def collect(sources):
            return {src.PRICE:{"status":status,"value":42,"acquired":NOW.isoformat()}}
        run(store,state,collect)
        assert not state.get(cache.STATE)
    state={}
    def mixed(sources):
        return {src.ACER:{"status":"available","acquired":NOW.isoformat(),
                         "values":{"eu":{"status":"available","value":1},
                                   "south":{"status":"stale","value":2}}}}
    run(store,state,mixed,(src.ACER,))
    assert not state.get(cache.STATE)


def test_revision_during_collection_not_cached(tmp_path):
    store,_,_=setup(tmp_path)
    state={}
    def collect(sources):
        store.cache(ARERA_CACHE,NOW.isoformat(),"changed")
        return {src.PRICE:{"status":"available","value":42,"acquired":NOW.isoformat()}}
    run(store,state,collect)
    assert not state.get(cache.STATE)


def test_context_wrapper_never_caches_credentialed_or_full_queries(tmp_path,monkeypatch):
    from gasops_app import assistant_lookup
    store,calls,collect=setup(tmp_path)
    def uncached(store,selected,context,now,state,*,requested,**kwargs):
        return collect(requested)
    monkeypatch.setattr(assistant_lookup,"_collect_context_uncached",uncached)
    state={}
    def request(sources,**kwargs):
        return collect_context(store,None,None,NOW,state,requested=sources,clock=lambda:NOW,**kwargs)
    request((src.PRICE,),question="Prezzo CMEM,m?")
    request((src.PRICE,),question="Riferimento ARERA?")
    assert len(calls)==1
    request(("AGSI+",),key="fixture",include_gie=True)
    request(("AGSI+",),key="fixture",include_gie=True)
    request((src.PRICE,),full=True)
    request((src.PRICE,),full=True)
    assert len(calls)==5


def test_cache_is_bounded():
    state={}
    for i in range(cache.MAX_ENTRIES+5):
        cache.remember(state,(i,),("token",),{"value":i},NOW)
    assert len(state[cache.STATE])==cache.MAX_ENTRIES
    assert (0,) not in state[cache.STATE]
