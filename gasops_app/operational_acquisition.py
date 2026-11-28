"""Background acquisition of national gas-day evidence using the existing SQLite cache."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from itertools import groupby
import json
import sqlite3
from threading import Lock
from time import monotonic, sleep

from .entsog import FIELDS, load_range
from .freshness import timestamp
from .gas_calendar import closed_gas_day
from .italian_network import verified_bindings
from .italian_network_sources import load_catalog, load_facility, load_point
from .models import utc_now
from .italian_network_events import load_interruptions
from .operational_sources import load_agsi, load_alsi, load_iip
from .public_data import SourceUnavailable, SourceNoObservation, network_allowed

HISTORY_DAYS = 90
REVISION_DAYS = 7
TTL = {"srg": timedelta(hours=12), "agsi": timedelta(hours=24),
       "alsi": timedelta(hours=24), "network": timedelta(hours=12)}
NAMES = {"srg": "Prelievi SRG", "agsi": "GIE · AGSI+", "alsi": "GIE · ALSI", "network": "ENTSOG · rete"}
FAILURES = (ValueError, SourceUnavailable, OSError, sqlite3.Error)
JOURNAL = "operational-acquisition-v1"
RETRY = timedelta(minutes=15)
MANUAL_LIMIT = timedelta(minutes=1)


def journal(store):
    saved = store.cached(JOURNAL)
    return json.loads(saved[1]) if saved else {}


def _days(first, last):
    return (first + timedelta(days=i) for i in range((last-first).days+1))


def _windows(requested, size):
    for _, group in groupby(enumerate(requested), lambda pair: pair[1].toordinal()-pair[0]):
        days = [day for _, day in group]
        for stop in range(len(days), 0, -size):
            yield days[max(0,stop-size)], days[stop-1]


def plan(network, saved, now, *, api_key=None, first=None, last=None, force=False, sources=tuple(TTL)):
    """Prefer the newest gas days; refresh only the tail and unacquired dates."""
    closed = closed_gas_day(now)
    automatic = first is None and last is None
    last = min(last or closed, closed)
    first = first or last-timedelta(days=HISTORY_DAYS-1)
    if not 0 <= (last-first).days < HISTORY_DAYS:
        return ()
    cutoff = closed-timedelta(days=REVISION_DAYS-1)
    attempts = saved.get("attempts", {})
    work = []
    for source in sources:
        if source in ("agsi","alsi") and not api_key:
            continue
        targets = {b.point_direction:b for b in verified_bindings(network)} if source=="network" else {source:None}
        for key, binding in targets.items():
            history = attempts.get(key,{})
            needed = []
            for day in _days(first,last):
                status = history.get(day.isoformat())
                at = timestamp(status[0]) if status else None
                if at is None:
                    needed.append(day)
                    continue
                ok = status[1]
                observed = len(status)<3 or status[2]
                delay = (MANUAL_LIMIT if force else
                         RETRY if (not ok or not observed) and (not automatic or day>=cutoff) else
                         TTL[source] if day>=cutoff else timedelta(days=1) if not ok else timedelta.max)
                if now-at>=delay:
                    needed.append(day)
            if not needed:
                continue
            if automatic and source in ("srg","network"):
                groups = ([d for d in needed if d>=cutoff],[d for d in needed if d<cutoff])
            else:
                groups = (needed,)
            size = HISTORY_DAYS if source in ("agsi","alsi") else 28
            for group in groups:
                for a,b in _windows(group,size):
                    work.append((source,key,binding,a,b,force or any(d.isoformat() in history for d in _days(a,b))))
    return tuple(sorted(work,key=lambda item:(-item[4].toordinal(),list(TTL).index(item[0]),item[3])))


def _verified(binding, catalog):
    return sum(r["operatorKey"]==binding.operator_id and r["pointKey"]==binding.external_id
        and r["directionKey"]==binding.direction and r["pointLabel"]==binding.expected_label
        and r["hasData"] is True and r["isInvalid"] is False for r in catalog["rows"]) == 1


def _map_detail(store, network, detail, catalog, api_key, now):
    identifier, direction, first, last = detail
    output = {}
    for binding in verified_bindings(network,identifier):
        if binding.direction == direction and _verified(binding,catalog):
            try:
                output["interruptions"] = {binding.point_direction:load_interruptions(store,binding,first,last,refresh=True)}
            except FAILURES:
                pass
    if api_key:
        facilities = {}
        for binding in network.bindings_for(identifier):
            if binding.provider in ("AGSI+","ALSI") and binding.mapping_confidence=="confirmed":
                try:
                    facilities[(binding.provider,binding.external_id)] = load_facility(store,api_key,binding,first,last,refresh=True)
                except FAILURES:
                    continue
        if facilities:
            output["facilities"] = facilities
        try:
            output["gie_iip"] = {"result":load_iip(store,api_key,now=now),"attempted":now}
        except FAILURES:
            pass
    return output


def inventory_error_code(reason):
    # Store only bounded diagnostic codes, never raw provider content.
    reason=str(reason).casefold()
    if "http 429" in reason or "limite richieste" in reason:return "rate_limit"
    if any(v in reason for v in ("http 401","http 403","accesso gie negato")):return "access_denied"
    if "tempo di risposta" in reason or "timeout" in reason:return "timeout"
    if "connessione" in reason:return "connection"
    if "http " in reason:return "http_error"
    return "validation_or_unavailable"


def synchronize(store, network, work, now, *, api_key=None, clock=utc_now, pause=.4, detail=None):
    """No Streamlit state in the worker. Source loaders own validation and data persistence."""
    saved = journal(store)
    attempts = saved.setdefault("attempts", {})
    health = saved.setdefault("connections", {})
    catalog = None
    next_request = 0.
    throttled = set()
    for (source,first,last), batch in groupby(work,lambda task:(task[0],task[3],task[4])):
        family = "entsog" if source in ("network","srg") else "gie"
        if source=="network" and catalog is None and family not in throttled:
            try:
                catalog = load_catalog(store)
            except FAILURES as error:
                catalog = network.sources["opd"]
                if isinstance(error,SourceUnavailable) and "HTTP 429" in str(error):
                    throttled.add(family)
        good = count = 0
        partial = False
        reason_code = None
        no_observation = False
        for _,key,binding,_,_,refresh in batch:
            count += 1
            delay = next_request-monotonic()
            if delay>0:
                sleep(delay)
            next_request = monotonic()+pause
            observed = set()
            try:
                if family in throttled:
                    raise SourceUnavailable("Limite richieste · prossima finestra di aggiornamento")
                if binding is not None:
                    if not _verified(binding,catalog):
                        raise ValueError("Associazione ENTSOG non verificata")
                    result = load_point(store,binding,first,last,now=now,refresh=refresh)
                    ok = not result.failed
                    if any("HTTP 429" in warning for warning in result.warnings):
                        throttled.add(family)
                    observed = {row.gas_day for row in result.records
                                if row.indicator=="Physical Flow" and row.value is not None}
                elif source=="srg":
                    result = load_range(store,first,last,now=now,refresh=refresh)
                    ok = not result.failed
                    observed = {day for day,_ in result.values if all(
                        result.values.get((day,field)) is not None
                        for field in FIELDS)}
                else:
                    loader = load_agsi if source=="agsi" else load_alsi
                    result = loader(store,api_key,"IT",first=first,last=last,now=now,refresh=refresh)
                    ok = not result["failed"]
                    no_observation = bool(result.get("no_observation"))
                    if not ok:reason_code=inventory_error_code(result.get("refresh_error",""))
                    if "HTTP 429" in (result.get("refresh_error") or ""):
                        throttled.add(family)
                    column = "stock_twh" if source=="agsi" else "sendout_gwh_d"
                    observed = set() if no_observation else set(result["frame"].loc[result["frame"][column].notna(),"gas_day"])
            except SourceNoObservation:
                ok = True
                no_observation = True
            except FAILURES as error:
                if family=="gie":reason_code=inventory_error_code(error)
                ok = False
                if isinstance(error,SourceUnavailable) and "HTTP 429" in str(error):
                    throttled.add(family)
            good += ok
            partial |= ok and not all(day in observed for day in _days(first,last))
            at = clock().isoformat()
            prior = attempts.setdefault(key,{})
            prior.update((day.isoformat(),(at,ok,day in observed)) for day in _days(first,last))
            if len(prior)>180:
                attempts[key] = dict(sorted(prior.items(),key=lambda item:(item[1][0],item[0]))[-180:])
        if last.isoformat()>=health.get(source,{}).get("last",""):
            health[source] = {"first":str(first),"last":str(last),"at":at,"valid":good,"expected":count,"failed":good<count,"partial":partial}
            if family=="gie":
                health[source].update(reason_code=reason_code,no_observation=no_observation,
                    outcome="failed" if good<count else "no_observation" if no_observation else "partial" if partial else "acquired")
        store.cache(JOURNAL,at,json.dumps(saved,separators=(",",":")))
    if detail and not throttled:
        return _map_detail(store,network,detail,catalog or network.sources["opd"],api_key,now)


def failures(saved, day):
    """An older failed historical request must not mark today's data stale."""
    return {key for key,history in saved.get("attempts",{}).items()
            if day.isoformat() in history and not history[day.isoformat()][1]}


_LOCK = Lock()
_EXECUTOR = ThreadPoolExecutor(max_workers=2,thread_name_prefix="gasops-sources")
_RUNNING = {}


def schedule(store, network, now, *, api_key=None, first=None, last=None, force=False, sources=tuple(TTL), detail=None):
    if not network_allowed():
        return None
    key = store.path.resolve()
    with _LOCK:
        running = _RUNNING.get(key)
        if running is not None and not running.done():
            return running
        work = plan(network,journal(store),now,api_key=api_key,first=first,last=last,force=force,sources=sources)
        if not work:
            _RUNNING.pop(key,None)
            return None
        job = _EXECUTOR.submit(synchronize,store,network,work,now,api_key=api_key,detail=detail)
        _RUNNING[key] = job
        return job
