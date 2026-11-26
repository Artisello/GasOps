"""Targeted source acquisition for conversational lookups and briefings."""
from hashlib import sha256
import json

from .assistant_sources import (
    ACER, DAILY, GIE, GME, MONTHLY, NETWORK, POWER, PRICE, WEATHER,
    add_price_source, complete_requirements, gme_indicators, safe_source_url, source_evidence, useful_source,
)
from .models import Kind, Origin, Run
from .supervisor import execute


def _requested_period(item, day):
    """Keep exact dates for daily measures and month labels for monthly sources."""
    period=item.get("gas_day") or item.get("period")
    expected=day.replace(day=1).isoformat() if item.get("grain")=="mese" else day.isoformat()
    if item.get("status") not in ("available","partial"):
        return item
    points=item.get("points")
    if points:
        matching=[point for point in points if (point.get("day") or point.get("period"))==expected]
        if matching:
            return {**item,"period":expected,"from":expected,"to":expected,"points":matching,"n":len(matching)}
    values=item.get("values")
    if isinstance(values,dict) and values and all(isinstance(row,dict) and "period" in row for row in values.values()):
        matching={key:row for key,row in values.items() if row["period"]==expected}
        if matching:
            return {**item,"period":expected,"values":matching}
    elif period==expected:
        return item
    return {key:value for key,value in item.items() if key in
            ("source","source_url","url","scope","acquired","period","gas_day","grain","limitation")} | {
                "status":"unavailable",
                "reason":"Nessuna osservazione verificata per il periodo richiesto.",
            }


def collect_context(
    store, selected, context, now, state, *, requested=(), full=False, key="", terna=(),
    include_gie=False, include_weather=False, weather_snapshots=None, day=None, scope="IT", question="", clock,
):
    from .briefing_context import collect
    from .briefing_market_sources import collect_market_sources

    only=set(requested)-{GME}
    public={}
    if full or only.intersection(GIE) or WEATHER in only:
        public.update(collect(store,context,now,key=key,include_gie=include_gie,include_weather=include_weather,
                              weather_snapshots=weather_snapshots,clock=clock,only=None if full else only,
                              day=day,scope=scope))
    if full or only.intersection((MONTHLY,DAILY,PRICE,ACER,*POWER)):
        public.update(collect_market_sources(store,selected,now,state,terna=terna,clock=clock,
                                             only=None if full else only,day=day))
    if NETWORK in only:
        from .assistant_network import collect_network
        public[NETWORK]=collect_network(store,state,now,question,day=day)
    if PRICE in only:
        add_price_source(public)
    if not full:
        complete_requirements(public,[key for key in requested if key!=GME])
        public={key:public[key] for key in requested if key in public}
    if day is not None:
        public={key:_requested_period(item,day) for key,item in public.items()}
    return public


def gme_request(question, day):
    kinds=gme_indicators(question)
    return {"kinds":list(kinds),"day":day.isoformat() if day else None} if kinds else None


def lookup_report(question, public, now, *, day=None, scope="IT", reasoner=None, issue=None):
    """Use published readouts directly, even when the main demand bundle is absent."""
    available=any(map(useful_source,public.values()))
    main=next(iter(public.values()),{})
    gme=gme_request(question,day) if scope=="IT" and not issue else None
    lines=[source_evidence(key,item) for key,item in public.items() if useful_source(item)]
    summary=issue or " ".join(lines) or ("Prezzi GME nella consultazione locale." if gme else
                               "Nessun dato verificato per questo quesito nelle fonti consultate.")
    snapshot=json.dumps(public,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False)
    run=Run(
        question=question,source=Origin(name=main.get("source","GME" if gme else "Fonti operative"),
            kind=Kind.HISTORICAL,grain="monthly" if main.get("grain")=="mese" else "daily",
            fields=(),description="Evidenze selezionate per il quesito, con periodo e perimetro per fonte.",
            url=safe_source_url(main.get("source_url")),retrieved_at=now,latest_period=main.get("gas_day") or main.get("period")),
        input_sha256=sha256(snapshot.encode()).hexdigest(),summary=summary,
        assumptions={"source_lookup":True,"requested_country":scope,"requested_day":day.isoformat() if day else None,
                     "public_operational_context":public,"assistant_source_requirements":list(public),
                     "gme_request":gme},
    )
    return execute(run,{},[],set(),lambda _: [],lambda _: None,reasoner if available else None,planned_only=True)
