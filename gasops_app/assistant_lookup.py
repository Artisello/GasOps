"""Targeted source acquisition for conversational lookups and briefings."""
from hashlib import sha256
import json
import re

from .assistant_sources import (
    ACER, DAILY, GIE, GME, MASE, MONTHLY, NETWORK, POWER, PRICE, WEATHER,
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


def mase_context(question, day=None):
    """Read the validated public UNMIG archive; never present it as live."""
    from .mase_archive import observations, MASE_SOURCE, REGIONS
    from .italiano import MESI
    missing={"source":MASE,"source_url":MASE_SOURCE,"scope":"Italia",
             "status":"unavailable","kind":"historical archive"}
    text=question.casefold()
    months=set(re.findall(r"(?<!\d)(\d{4}-(?:0[1-9]|1[0-2]))(?![\d-])",text))
    for month,year in re.findall(r"\b("+"|".join(MESI)+r")\s+(\d{4})\b",text):
        months.add(f"{year}-{MESI.index(month)+1:02d}")
    if day is not None:
        months.add(day.strftime("%Y-%m"))
    years=set(re.findall(r"(?<!\d)(?:19|20)\d{2}(?!\d)",text))
    if len(months)>1 or len(years)>1:
        return {**missing,"reason":"Indica un solo mese o anno; per confronti usa Esplora dati."}
    period=next(iter(months),None) or next(iter(years),None)
    regions=[region for region in REGIONS if re.search(r"(?<!\w)"+re.escape(region.casefold())+r"(?!\w)",text)]
    if len(regions)>1:
        return {**missing,"reason":"Indica una sola regione."}
    geos=("region:"+regions[0],) if regions else ("IT","IT:onshore","IT:offshore")
    rows=[row for row in observations() if row["geography"] in geos]
    if period is None:
        grain="month" if re.search(r"mensil|ultimo mese",text) else "year"
        period=max((row["period"] for row in rows if row["grain"]==grain),default=None)
    selected=[row for row in rows if row["period"]==period]
    if not selected:
        return {**missing,"period":period,"reason":"Nessuna osservazione nell’archivio UNMIG per il periodo e l’area richiesti."}
    labels={"IT":"Produzione nazionale","IT:onshore":"Terraferma","IT:offshore":"Mare"}
    row=selected[0]
    return {"source":MASE,"source_url":row["source_url"],"scope":regions[0] if regions else "Italia",
            "period":period,"grain":"mese" if row["grain"]=="month" else "anno",
            "kind":"historical archive","status":"available",
            "values":{labels.get(item["geography"],item["geography"].removeprefix("region:")):
                      {"value":float(item["value"]),"unit":item["unit"],"period":period} for item in selected},
            "limitation":row["edition"]+" · trascrizione di report pubblico, non API live. bcm = miliardi di metri cubi; Sm3 = metri cubi standard."}


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
    if MASE in only:
        public[MASE]=mase_context(question,day)
    if NETWORK in only:
        from .assistant_network import collect_network
        public[NETWORK]=collect_network(store,state,now,question,day=day)
    if PRICE in only:
        add_price_source(public)
    if not full:
        complete_requirements(public,[key for key in requested if key!=GME])
        public={key:public[key] for key in requested if key in public}
    if day is not None:
        public={key:item if key==MASE else _requested_period(item,day) for key,item in public.items()}
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
