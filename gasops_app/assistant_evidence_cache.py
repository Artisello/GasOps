"""Short session-only reuse of validated public assistant evidence.

Raw SQLite cache remains authoritative. Never cache answers, credentials,
private uploads, GME, or a stale/failed/partial projection. Exact dependencies
are hashed from existing cache rows, not inferred from timestamps alone.
"""
from copy import deepcopy
from datetime import datetime, timedelta
from hashlib import sha256
import sqlite3

from .assistant_sources import ACER, DAILY, MONTHLY, PRICE
from .data import ROME
from .gas_calendar import closed_gas_day

STATE="assistant_evidence_cache_v1"
TTL=timedelta(seconds=90)
MAX_ENTRIES=16
MAX_RAW_BYTES=4_000_000


def groups(requested, day):
    from .mensile import ARERA_CACHE
    from .acer_market import CACHE_KEY
    from .entsog import RANGE_CACHE
    keys=set(requested)
    out=[]
    if MONTHLY in keys:
        sources=(MONTHLY,PRICE) if PRICE in keys else (MONTHLY,)
        out.append((sources,"monthly",(("eurostat-nrg_cb_gasm-IT-bilancio-TJ_GCV",8),(ARERA_CACHE,12))))
    elif PRICE in keys:
        out.append(((PRICE,),"monthly",((ARERA_CACHE,12),)))
    if ACER in keys:
        out.append(((ACER,),"acer",((CACHE_KEY,24),)))
    if DAILY in keys and day is not None:
        out.append(((DAILY,),"daily",((f"{RANGE_CACHE}{day-timedelta(days=13)}:{day}",12),)))
    return out


def _stamp(value):
    try:
        dt=datetime.fromisoformat(value) if isinstance(value,str) else value
        return dt if isinstance(dt,datetime) and dt.utcoffset() is not None else None
    except (ValueError,TypeError,OverflowError):
        return None


def token(store,state,group,now):
    """Read exact raw dependencies; do not extend their source TTL."""
    sources,refresh,dependencies=group
    if not getattr(store,"path",None) or not callable(getattr(store,"cached",None)):
        return None
    from .live_sources import STATUS
    attempt=state.get(STATUS,{}).get("sources",{}).get(refresh,{})
    # A recorded review/failure is not a validated refresh.
    if attempt.get("status") in ("Da aggiornare","Da verificare") or attempt.get("outcome") in ("failed","partial","no_observation","review"):
        return None
    result=[]
    try:
        for key,hours in dependencies:
            raw=store.cached(key)
            if raw is None:return None
            at=_stamp(raw[0])
            if at is None or not timedelta(0)<=now-at<timedelta(hours=hours):return None
            if not isinstance(raw[1],str) or len(raw[1])>MAX_RAW_BYTES:return None
            data=raw[1].encode("utf-8")
            if len(data)>MAX_RAW_BYTES:return None
            result.append((key,at.isoformat(),sha256(data).hexdigest()))
    except (OSError,ValueError,TypeError,sqlite3.Error):
        return None
    return (str(store.path),attempt.get("at"),attempt.get("status"),tuple(result))


def _valid(value):
    if isinstance(value,dict):
        if "status" in value and value["status"]!="available":return False
        if value.get("quality_review") or value.get("refresh_failed") or value.get("partial"):return False
        return all(_valid(v) for v in value.values())
    if isinstance(value,list):return all(_valid(v) for v in value)
    return True


def cacheable(public,sources,now,dependency_token):
    from .assistant_sources import useful_source
    stamps=[_stamp(row[1]) for row in dependency_token[-1]]
    for source in sources:
        item=public.get(source)
        if not isinstance(item,dict) or item.get("status")!="available" or not useful_source(item) or not _valid(item):
            return False
        at=_stamp(item.get("acquired"))
        expected=stamps[1] if source==PRICE and MONTHLY in sources else stamps[0]
        if at is None or at>now or at!=expected:return False
        if source==MONTHLY:
            price=item.get("price")
            if not isinstance(price,dict) or _stamp(price.get("acquired"))!=stamps[1]:
                return False
    return True


def identity(sources,day,now):
    # Latest lookups must not cross civil midnight or the gas-day boundary.
    return (sources,day.isoformat() if day else None,
            now.astimezone(ROME).date().isoformat(),closed_gas_day(now).isoformat())


def lookup(state,ident,revision,now):
    item=state.get(STATE,{}).get(ident)
    if item is None or revision is None:return None
    at,prior,public=item
    if not timedelta(0)<=now-at<TTL or prior!=revision:return None
    return deepcopy(public)


def remember(state,ident,revision,public,now):
    if revision is None:return
    entries={k:v for k,v in state.get(STATE,{}).items() if timedelta(0)<=now-v[0]<TTL}
    entries.pop(ident,None)
    entries[ident]=(now,revision,deepcopy(public))
    state[STATE]=dict(list(entries.items())[-MAX_ENTRIES:])


def collect_cached(store,state,now,requested,day,collect,clock):
    """Reuse independently invalidated source groups, never final answers.

    Skip writing a projection when raw dependencies change during acquisition:
    the next stable read can be cached without racing another writer.
    """
    eligible=groups(requested,day)
    if not eligible or not getattr(store,"path",None):
        return collect(requested)
    remaining=list(dict.fromkeys(requested))
    public={}
    misses=[]
    hits=[]
    for group in eligible:
        sources=group[0]
        ident=identity(sources,day,now)
        revision=token(store,state,group,now)
        found=lookup(state,ident,revision,now)
        if found is None:
            misses.append((group,ident,revision))
            continue
        hits.append((group,ident,revision))
        public.update(found)
        remaining=[key for key in remaining if key not in sources]
    if remaining:
        public.update(collect(tuple(remaining)))
    checked=clock()
    # Other sources may have taken long enough for an earlier hit to expire.
    # Recheck only when work took place, and fall back once if invalidated.
    if any(identity(group[0],day,checked)!=ident or
           lookup(state,ident,token(store,state,group,checked) if remaining else revision,checked) is None
           for group,ident,revision in hits):
        return collect(requested)
    for group,ident,before in misses:
        if before is None or identity(group[0],day,checked)!=ident:continue
        after=token(store,state,group,checked)
        if before!=after or not cacheable(public,group[0],checked,after):continue
        remember(state,ident,after,{key:public[key] for key in group[0]},checked)
    return {key:public[key] for key in requested if key in public}
