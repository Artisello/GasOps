"""Bounded, read-only projection of existing gas observations. No provider I/O.

No new observation model or cache: map Snapshot/Observation, the ENTSOG desk
and parsed GIE frames remain authoritative. The returned frame drives every view.
"""
from dataclasses import replace
from datetime import date, datetime, timedelta
from decimal import Decimal
import json

import pandas as pd

from .data import ROME
from .entsog_network import INDICATORS, NAMES, parse_network, combine_results, as_snapshot
from .gas_calendar import closed_gas_day, gas_day_bounds
from .italian_network import merge_observations, validated_observations, verified_bindings, applicable_observations
from .italian_network_sources import (Snapshot, parse_point_page, coalesce_records,
                                     parse_agsi, parse_alsi)
from .italian_network_events import parse_interruptions
from .source_health import finite, stamp

MAX_DAYS=92
MAX_ROWS=10000
MAX_EXPORT_ROWS=5000
MAX_CACHE_BYTES=8_000_000
MAX_CACHE_ENTRIES=96
LABELS={**NAMES,"Storage inventory":"Giacenza stoccaggi","LNG send-out":"Send-out GNL",
        "Interruptions":"Capacità interrotta pubblicata"}
GIE_INDICATORS={
    "AGSI+":(("stock_twh","Storage inventory","TWh","Giacenza stoccaggi"),
        ("capacity_twh","Storage working capacity","TWh","Capacità di stoccaggio"),
        ("fill_pct","Storage filling","%","Riempimento pubblicato"),
        ("injection_gwh_d","Storage injection","GWh/d","Iniezioni stoccaggi"),
        ("withdrawal_gwh_d","Storage withdrawal","GWh/d","Erogazioni stoccaggi"),
        ("injection_capacity_gwh_d","Storage injection capacity","GWh/d","Capacità di iniezione"),
        ("withdrawal_capacity_gwh_d","Storage withdrawal capacity","GWh/d","Capacità di erogazione")),
    "ALSI":(("sendout_gwh_d","LNG send-out","GWh/d","Send-out GNL"),
        ("inventory_gwh","LNG energy inventory","GWh","Giacenza GNL · energia"),
        ("inventory_1000m3_lng","LNG liquid inventory","10³ m³ LNG","Giacenza GNL · volume liquido"),
        ("dtmi_1000m3_lng","LNG maximum inventory","10³ m³ LNG","Giacenza massima dichiarata GNL"),
        ("dtrs_gwh_d","LNG reference send-out","GWh/d","Send-out di riferimento dichiarato"))}
LABELS.update({indicator:label for specs in GIE_INDICATORS.values() for _,indicator,_,label in specs})
MAP_STATE="italian_network_data_v1"
DESK_STATE="entsog_network_result_v1"
FIELDS=("provider","infrastructure_id","point_direction","indicator","value","unit","gas_day",
    "period_from","period_to","observed_at","retrieved_at","source_id","source_url","quality_status",
    "publication_status","cached","failed","partial","source","source_unit","source_period_from",
    "source_period_to","revisions","revision_count","entity_key","entity_label","direction","scope",
    "time_basis","usable","query_first","query_last","note","value_d1","delta_d1",
    "d1_gas_day","d1_source_id","d1_observed_at","d1_retrieved_at")


def _stamp(value):
    try:return stamp(value) if value is not None and not pd.isna(value) else None
    except (TypeError,ValueError):return None


def _day(value):
    if isinstance(value,datetime):return value.date()
    if isinstance(value,date):return value
    try:return date.fromisoformat(str(value))
    except ValueError:return None


def _json(value):
    def encode(v):
        if isinstance(v,(date,datetime)):return v.isoformat()
        if isinstance(v,Decimal):return str(v)
        raise TypeError("Metadato non serializzabile")
    return json.dumps(value,ensure_ascii=False,default=encode,sort_keys=True)


def _window(first,last,now):
    last=last or now.astimezone(ROME).date()
    first=first or last-timedelta(days=MAX_DAYS-1)
    if not isinstance(first,date) or not isinstance(last,date) or not 0<=(last-first).days<MAX_DAYS:
        raise ValueError("Seleziona da 1 a 92 giorni")
    return first,last


def cached_sources(store,network,now,first,last):
    """Read only known cache keys, with existing parsers and an 8 MB budget."""
    snapshots, inventories, interruptions, notices=[],[],[],[]
    if store is None:return snapshots,inventories,interruptions,notices
    bindings={b.point_direction:b for b in verified_bindings(network)}
    pages, desks={},{}
    budget=0
    prefixes=("italian-map-ops-v1:","entsog-network-v1:","italian-map-interruptions-v1:","italian-map-gie-v1:",
              "agsi-public-v2-","alsi-public-v2-")
    entries=[]
    for prefix in prefixes:entries.extend(store.cached_entries(prefix,limit=MAX_CACHE_ENTRIES))
    if len(entries)>MAX_CACHE_ENTRIES:
        notices.append(f"Lettura limitata alle {MAX_CACHE_ENTRIES} estrazioni più recenti; lo storico completo resta nelle viste originali.")
    for key,at,size in sorted(entries,key=lambda r:r[1],reverse=True)[:MAX_CACHE_ENTRIES]:
        acquired=_stamp(at)
        if acquired is None or acquired>now:continue
        if size>2_000_000 or budget+size>MAX_CACHE_BYTES:
            notices.append("Cache oltre il limite di lettura: sono disponibili altre estrazioni nelle viste della fonte.")
            continue
        parts=key.split(":")
        try:
            if parts[0] in ("italian-map-ops-v1","entsog-network-v1","italian-map-interruptions-v1"):
                a,z=date.fromisoformat(parts[2]),date.fromisoformat(parts[3])
                if z<first or a>last:continue
            elif parts[0]=="italian-map-gie-v1":
                a,z=date.fromisoformat(parts[4]),date.fromisoformat(parts[5])
                if z<first or a>last:continue
            cached=store.cached(key)
            if cached is None:continue
            budget+=size
            text=cached[1]
            if parts[0]=="italian-map-ops-v1":
                b=bindings.get(parts[1])
                if b is None:continue
                offset=int(parts[4])
                if offset not in (0,200,400):continue
                page=parse_point_page(text,b,a,z,acquired,offset=offset,cached=True)
                pages.setdefault((b.point_direction,a,z),{})[offset]=page
            elif parts[0]=="entsog-network-v1":
                names=INDICATORS[:4] if parts[4:]==["flows"] else INDICATORS[4:] if parts[4:]==["capacity"] else INDICATORS
                result=parse_network(json.loads(text),parts[1],a,z,acquired,cached=True,requested=names)
                desks.setdefault((result.point,a,z),[]).append((names,result))
            elif parts[0]=="italian-map-interruptions-v1":
                if parts[1] in bindings:
                    interruptions.append(parse_interruptions(text,acquired,bindings[parts[1]],a,z,cached=True))
            elif parts[0]=="italian-map-gie-v1":
                matches=[b for b in network.bindings if b.mapping_confidence=="confirmed" and
                    (b.provider,b.operator_id,b.external_id)==tuple(parts[1:4])]
                if len(matches)!=1:continue
                b=matches[0]
                parser=parse_agsi if b.provider=="AGSI+" else parse_alsi
                result=parser(text,acquired,scope=b.external_id,cached=True)
                inventories.append((b.provider,b.infrastructure_id,b.external_id,{**result,"first":a,"last":z},False))
            elif key.startswith(("agsi-public-v2-","alsi-public-v2-")):
                storage=key.startswith("agsi-")
                scope=key.rsplit("-",1)[1]
                if scope not in ("IT","EU","DE"):continue
                result=(parse_agsi if storage else parse_alsi)(text,acquired,scope=scope,cached=True)
                inventories.append(("AGSI+" if storage else "ALSI",None,scope,result,False))
        except (ValueError,TypeError,KeyError,IndexError):
            notices.append("Un’estrazione in cache non ha superato la validazione ed è stata esclusa.")
    for (point,a,z),group in pages.items():
        counts=sum(p["count"] for p in group.values())
        total={p["total"] for p in group.values()}
        complete=(0 in group and sorted(group)==list(range(0,max(group)+1,200))
                  and group[max(group)]["count"]<200 and total=={counts})
        records=coalesce_records([r for p in group.values() for r in p["records"]])
        snapshots.append(Snapshot(point,tuple(records),a,z,min(p["acquired"] for p in group.values()),True,False,not complete))
    for group in desks.values():
        result=group[0][1] if len(group)==1 else combine_results(group)
        snapshots.append(as_snapshot(result,network))
    return snapshots,inventories,interruptions,list(dict.fromkeys(notices))


def _base(**values):
    return {**dict.fromkeys(FIELDS),"cached":None,"failed":False,"partial":False,
            "usable":False,"revision_count":0,"revisions":"[]",**values}


def _daily_interval(start,stop):
    if not start or not stop:return None
    day=start.astimezone(ROME).date()
    return day if gas_day_bounds(day)==(start,stop) else None


def _inventory_rows(items,network,now,first,last):
    output=[]
    lookup={i.id:i for i in network.infrastructure}
    for provider,identifier,scope,result,failed in sorted(items,key=lambda i:_stamp(i[3].get("acquired")) or datetime.min.replace(tzinfo=now.tzinfo)):
        acquired=_stamp(result.get("acquired"))
        frame=result.get("frame")
        if acquired is None or acquired>now or not isinstance(frame,pd.DataFrame) or result.get("scope")!=scope:continue
        specs=[spec for spec in GIE_INDICATORS.get(provider,()) if spec[0] in frame]
        if not specs or "gas_day" not in frame:continue
        entity=provider+":"+str(identifier or scope)
        label=lookup[identifier].name if identifier else {"IT":"Italia","EU":"Unione europea","DE":"Germania"}.get(scope,scope)+" · aggregato GIE"
        a=_day(result.get("first")) or min((_day(d) for d in frame.gas_day if _day(d)),default=first)
        z=_day(result.get("last")) or max((_day(d) for d in frame.gas_day if _day(d)),default=last)
        output=[r for r in output if not (r["entity_key"]==entity and r["retrieved_at"]<acquired and a<=r["gas_day"]<=z)]
        for _,r in frame.iterrows():
            day=_day(r.gas_day)
            if day is None or not first<=day<=last:continue
            for field,indicator,unit,_ in specs:
                value=Decimal(str(r[field])) if finite(r[field]) and r.get("status")!="N" else None
                review=bool(r.get("review",False))
                output.append(_base(provider=provider,infrastructure_id=identifier,entity_key=entity,entity_label=label,
                    scope=scope,indicator=indicator,value=value,unit=unit,gas_day=day,retrieved_at=acquired,
                    source_id=scope,source=result.get("source"),source_url=result.get("source_url"),
                    quality_status="review" if review else "valid" if value is not None else "N/A",
                    publication_status=r.get("status") or "Non indicato",cached=result.get("cached"),
                    failed=bool(failed or result.get("failed")),partial=bool(result.get("partial")),
                    time_basis="publisher_day",usable=value is not None,query_first=a,query_last=z,
                    note="Giorno pubblicato dalla fonte; orari e data di pubblicazione non forniti."))
    return output


def source_context(network,bundled,state,now,*,store=None,first=None,last=None,interruptions=()):
    """Load existing evidence once for readers sharing the same bounded window."""
    first,last=_window(first,last,now)
    saved=state.get(MAP_STATE,{})
    cached,inventory,events,notices=cached_sources(store,network,now,first,last)
    snapshots=[*bundled,*cached,*saved.get("snapshots",{}).values()]
    desk=state.get(DESK_STATE)
    if desk is not None:
        try:snapshots.append(as_snapshot(desk,network))
        except (ValueError,TypeError,KeyError):notices.append("Estrazione ENTSOG della sessione non valida: esclusa.")
    snapshots=[s for s in snapshots if s.acquired<=now and s.first<=last and s.last>=first]
    for provider in ("AGSI+","ALSI"):
        for scope in ("IT","EU","DE"):
            source=state.get(provider+"_"+scope,{})
            if source.get("result"):inventory.append((provider,None,scope,source["result"],bool(source.get("error"))))
    for (provider,eic),result in saved.get("facilities",{}).items():
        bindings=[b for b in network.bindings if b.provider==provider and b.external_id==eic and b.mapping_confidence=="confirmed"]
        if len(bindings)==1:
            inventory.append((provider,bindings[0].infrastructure_id,eic,result,provider+":"+eic in saved.get("failures",())))
    return {"snapshots":snapshots,"inventory":inventory,"interruptions":[*interruptions,*events,*saved.get("interruptions",{}).values()],
            "notices":notices,"first":first,"last":last}


def collect(network,bundled,state,now,*,store=None,first=None,last=None,interruptions=(),context=None):
    """Return one validated frame, bounded to the requested 92-day window."""
    first,last=_window(first,last,now)
    saved=state.get(MAP_STATE,{})
    loaded=context if context is not None else source_context(network,bundled,state,now,store=store,
        first=first,last=last,interruptions=interruptions)
    if loaded["first"]>first or loaded["last"]<last:raise ValueError("Contesto fuori periodo")
    snapshots,inventory=loaded["snapshots"],loaded["inventory"]
    notices=list(loaded["notices"])
    desk=state.get(DESK_STATE)
    binding_by_point={b.point_direction:b for b in verified_bindings(network)}
    lookup={i.id:i for i in network.infrastructure}
    flags={}
    for s in snapshots:
        for o in s.records:
            flags[id(o)]=(s,s in bundled)
    merged=merge_observations(snapshots)
    # A tied response can produce withheld cells with the same source locator.
    for o in merged:
        if id(o) not in flags:
            s=next(s for s in reversed(snapshots) if s.point_direction==o.point_direction
                and o.period_from<gas_day_bounds(s.last)[1] and o.period_to>gas_day_bounds(s.first)[0])
            flags[id(o)]=(s,s in bundled)
    verified=set(id(o) for o in validated_observations(network,merged,now))
    rows=[]
    for o in merged:
        s,packaged=flags[id(o)]
        b=binding_by_point.get(o.point_direction)
        if b and id(o) not in verified or not b and o.infrastructure_id:continue
        if o.quality_status=="missing":continue
        if o.period_from>=gas_day_bounds(last)[1] or o.period_to<=gas_day_bounds(first)[0]:continue
        published=_stamp(o.observed_at)
        if o.retrieved_at>now or published and published>now:continue
        if o.indicator=="Physical Flow" and o.period_to>now:continue
        unit_ok=o.unit=="GWh/d"
        value=o.value if unit_ok and finite(o.value) else None
        usable=value is not None and o.quality_status not in ("conflict","N/A","unaligned")
        quality=o.quality_status if unit_ok else "invalid_unit"
        if usable and o.gas_day is not None and o.indicator in INDICATORS:
            comparable=applicable_observations(merged,o.point_direction,o.gas_day,o.indicator)
            if o not in comparable:
                usable=False
                quality="incompatible_interval"
        direction=b.direction if b else "exit" if o.point_direction.endswith("exit") else "entry"
        item=lookup.get(o.infrastructure_id)
        label=(item.name if item else (desk.labels[0][1] if desk and desk.point==o.point_direction and len(desk.labels)==1 else o.point_direction))
        rows.append(_base(provider="ENTSOG",infrastructure_id=o.infrastructure_id or None,point_direction=o.point_direction,
            entity_key=o.point_direction,entity_label=label+" · "+("Ingresso" if direction=="entry" else "Uscita"),
            direction=direction,indicator=o.indicator,value=value,unit=o.unit,gas_day=o.gas_day,
            period_from=o.period_from,period_to=o.period_to,observed_at=published,retrieved_at=o.retrieved_at,
            source_id=o.source_id,source=o.source,source_url=o.source_url,quality_status=quality,
            publication_status=o.publication_status,cached=bool(packaged or s.cached),
            failed=bool(s.failed or o.point_direction in saved.get("failures",())),partial=s.partial,
            source_unit=o.source_unit,source_period_from=o.source_period_from,source_period_to=o.source_period_to,
            revisions=_json(o.revisions),revision_count=len(o.revisions),
            time_basis="gas_day" if o.gas_day is not None and o.quality_status!="unaligned" else "source_interval",
            usable=usable,query_first=s.first,query_last=s.last,
            note="ID fonte: chiave punto; l’estrazione legacy non conserva gli ID originali." if o.source_id==o.point_direction else ""))
    # Parsed GIE frames: aggregate scopes remain distinct from single facilities.
    rows.extend(_inventory_rows(inventory,network,now,first,last))
    for result in loaded["interruptions"]:
        b=binding_by_point.get(result.get("point_direction"))
        if b is None or not _stamp(result.get("acquired")) or result["acquired"]>now:continue
        for r in result["records"]:
            published=_stamp(r.get("observed_at"))
            if (r.get("mapping_confidence")!="confirmed" or r["infrastructure_id"]!=b.infrastructure_id
                    or r["period_from"]>=gas_day_bounds(last)[1] or r["period_to"]<=gas_day_bounds(first)[0]
                    or r["retrieved_at"]>now or published and published>now):continue
            value=r["value"] if r.get("unit")=="GWh/d" and finite(r["value"]) else None
            day=_daily_interval(r["period_from"],r["period_to"])
            rows.append(_base(provider="ENTSOG",infrastructure_id=b.infrastructure_id,point_direction=b.point_direction,
                entity_key=b.point_direction,entity_label=lookup[b.infrastructure_id].name+" · "+("Ingresso" if b.direction=="entry" else "Uscita"),
                direction=b.direction,indicator="Interruptions",value=value,unit=r["unit"],gas_day=day,
                period_from=r["period_from"],period_to=r["period_to"],observed_at=published,retrieved_at=r["retrieved_at"],
                source_id=r["source_id"],source=r["source"],source_url=r["source_url"],source_unit=r.get("source_unit"),
                source_period_from=r.get("source_period_from"),source_period_to=r.get("source_period_to"),
                quality_status=r["quality_status"],publication_status=r["status"],cached=result.get("cached"),
                failed=bool(result.get("failed") or "interruptions:"+b.point_direction in saved.get("failures",())),
                partial=result.get("partial",False),time_basis="gas_day" if day else "source_interval",usable=value is not None,
                query_first=result["first"],query_last=result["last"],note="Zero pubblicato ≠ evento attivo; nessuna somma degli eventi."))
    frame=validated_frame(rows)
    if len(frame)>MAX_ROWS:raise ValueError("Troppi dati per la vista: riduci la finestra")
    frame.attrs["notices"]=list(dict.fromkeys(notices))
    return frame


def validated_frame(rows):
    """One row per series/period; identical copies collapse, tied conflicts do not."""
    groups={}
    keys=("provider","entity_key","indicator","unit","gas_day","period_from","period_to")
    for r in rows:
        groups.setdefault(tuple(r.get(k) for k in keys),[]).append(r)
    output=[]
    for copies in groups.values():
        at=max(r["retrieved_at"] for r in copies)
        newest=[r for r in copies if r["retrieved_at"]==at]
        chosen=dict(newest[-1])
        values={r["value"] for r in newest}
        if len(values)>1:
            chosen.update(value=None,usable=False,quality_status="conflict")
        versions=[]
        for r in copies:
            for version in json.loads(r.get("revisions") or "[]"):
                if version not in versions:versions.append(version)
        if len(values)>1:
            versions.extend({k:r.get(k) for k in ("value","observed_at","retrieved_at","source_id")} for r in newest)
        chosen.update(revisions=_json(versions),revision_count=max(len(versions),max(r.get("revision_count",0) for r in copies)))
        output.append(chosen)
    daily={}
    for r in output:
        if r["gas_day"] is not None and r["usable"]:
            daily.setdefault((r["provider"],r["entity_key"],r["indicator"],r["unit"],r["time_basis"],r["gas_day"]),[]).append(r)
    for r in output:
        if r["gas_day"] is None or not r["usable"]:continue
        candidates=daily.get((r["provider"],r["entity_key"],r["indicator"],r["unit"],r["time_basis"],r["gas_day"]-timedelta(days=1)),[])
        if len(candidates)==1:
            old=candidates[0]
            r.update(value_d1=old["value"],delta_d1=r["value"]-old["value"],d1_gas_day=old["gas_day"],
                d1_source_id=old["source_id"],d1_observed_at=old["observed_at"],d1_retrieved_at=old["retrieved_at"])
    frame=pd.DataFrame(output,columns=FIELDS).astype(object)
    return frame.where(pd.notna(frame),None)


def select(frame,provider,entities,indicator,unit,time_basis,first,last):
    _window(first,last,None)
    selected=frame.loc[(frame.provider==provider)&frame.entity_key.isin(entities)&(frame.indicator==indicator)
        &(frame.unit==unit)&(frame.time_basis==time_basis)].copy()
    if selected.empty:return selected.reset_index(drop=True)
    start,stop=gas_day_bounds(first)[0],gas_day_bounds(last)[1]
    return selected.loc[selected.apply(lambda r:first<=r.gas_day<=last if r.gas_day is not None
        else r.period_from is not None and r.period_from<stop and r.period_to>start,axis=1)].reset_index(drop=True)


def series_frame(frame,first,last):
    """A chart projection of exactly these rows, with explicit null calendar slots."""
    if frame.empty:return pd.DataFrame()
    if frame.unit.nunique()!=1 or frame.time_basis.nunique()!=1 or frame.time_basis.iloc[0]=="source_interval":
        raise ValueError("Unità o intervalli non confrontabili in una serie giornaliera")
    index=pd.date_range(first,last,freq="D")
    result=pd.DataFrame(index=index)
    for entity,rows in frame.groupby("entity_key",sort=False):
        values={}
        for day,group in rows.groupby("gas_day"):
            valid=group.loc[group.usable]
            values[pd.Timestamp(day)]=float(valid.iloc[0].value) if len(valid)==1 else None
        label=rows.entity_label.iloc[0]
        result[label]=pd.Series(values,dtype=float).reindex(index)
    return result
