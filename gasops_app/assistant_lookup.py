"""Targeted source acquisition for conversational lookups and briefings."""
from hashlib import sha256
import json
import re

from .assistant_sources import (
    ACER, DAILY, GIE, GME, MASE, MONTHLY, NETWORK, POWER, PRICE, WEATHER,
    add_price_source, complete_requirements, gme_indicators, safe_source_url, source_evidence, useful_source,
    electricity_price_question, query_months, query_days, mentions_day, explicit_period_comparison,
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


def _collect_context_uncached(
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


def collect_context(
    store, selected, context, now, state, *, requested=(), full=False, key="", terna=(),
    include_gie=False, include_weather=False, weather_snapshots=None, day=None, scope="IT", question="", clock,
):
    def collect(sources):
        return _collect_context_uncached(
            store,selected,context,now,state,requested=sources,full=full,key=key,terna=terna,
            include_gie=include_gie,include_weather=include_weather,weather_snapshots=weather_snapshots,
            day=day,scope=scope,question=question,clock=clock)
    # The validated public point-lookup projection is independent of the
    # question wording. Full briefings and selected/derived series are not.
    if full or selected is not None or context is not None or scope!="IT":
        return collect(requested)
    from .assistant_evidence_cache import collect_cached
    return collect_cached(store,state,now,requested,day,collect,clock)


def gme_request(question, day):
    kinds=gme_indicators(question)
    result={"kinds":list(kinds),"day":day.isoformat() if day else None}
    if electricity_price_question(question):
        # GME observations never enter the public evidence or provider payload.
        result["kinds"].append("pun")
        months=query_months(question)
        days=query_days(question)
        text=question.casefold()
        unsupported=(len(months)>1 or days is None or bool(days and len(days)>1)
            or explicit_period_comparison(question) or (months and (day or mentions_day(question)))
            or (not day and mentions_day(question))
            or bool(re.search(r"\b(?:settiman\w*|annuale|annui|annuo|orar\w*|quartorar\w*|domest\w*|bollett\w*|tariff\w*|zonal\w*|fasci\w*|ultim[oi]\s+\d+|ultim[oa]\s+(?:mese|anno)|mensil\w*|mesi|anni|giorni|prevision\w*|forecast|retail|contratt\w*)\b",text) and not months)
            or bool(re.search(r"\b(?:domest\w*|bollett\w*|tariff\w*|zonal\w*|fasci\w*|orar\w*|prevision\w*|forecast|retail|contratt\w*)\b",text))
            or (not months and not day and bool(re.search(r"\b20\d{2}\b",text))))
        if unsupported:
            result["pun_unsupported"]=True
        elif months:
            result["pun_month"]=months[0].isoformat()
    return result if result["kinds"] else None


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


def _document_libraries():
    """Read only the existing authorized archives, using the document desk's
    bounded caches and validation. Visitor/private indices remain session-local.
    Never use a stale remote manifest as current evidence after a failed read.
    """
    import streamlit as st
    from . import document_page as desk
    from .document_desk import identity, build
    from .access import document_directory, private_access
    from .data import ROOT
    from .document_archive import display_name
    libraries,notices=[],[]
    public=()
    try:
        public=desk._local_inputs(ROOT/"data"/"public-regulatory",shared=True)
    except OSError:
        notices.append("Archivio pubblico locale non leggibile.")
    remote=()
    try:
        config=desk._archive_config()
        if config:
            remote=tuple((display_name(k),raw) for k,raw in desk._read_remote(config))
    except Exception:
        notices.append("Archivio pubblico remoto non disponibile; nessuna copia precedente sostituita.")
    shared=(*remote,*public)
    if shared:
        docs,_=desk._public_index(identity(shared),shared)
        libraries.append(docs)
    private=()
    if private_access():
        try:
            path,is_public=document_directory(ROOT)
            if not is_public:
                private=desk._local_inputs(path,shared=False)
        except (OSError,PermissionError):
            notices.append("Archivio riservato non leggibile.")
    uploads=tuple(st.session_state.get(desk.VISITOR_UPLOADS,()))
    personal=(*uploads,*private)
    key=identity(personal)
    cache_key="assistant_private_pdf_index_v1"
    if personal:
        cached=st.session_state.get(cache_key)
        if not cached or cached[0]!=key:
            cached=(key,build(personal))
            st.session_state[cache_key]=cached
        libraries.append(cached[1])
    else:
        st.session_state.pop(cache_key,None)
    if any(docs.errors for docs in libraries):
        notices.append("Alcuni PDF non sono indicizzabili o superano i limiti dell’archivio.")
    return libraries,notices


def ranked_document_hits(libraries,question,limit):
    """Merge ranked candidates across archives before truncation.

    TF-IDF scores from independent indexes are not comparable. Rank by
    query-term coverage across all candidates, then local retrieval rank.
    Keep exact citations; no embeddings, model call or shared private cache.
    """
    from .document_desk import search, STOP
    from unicodedata import normalize, combining
    def terms(value):
        clean="".join(ch for ch in normalize("NFKD",value.casefold()) if not combining(ch))
        return {token for token in re.findall(r"[\w-]+",clean) if len(token)>=2 and token not in STOP}
    query=terms(question)
    candidates={}
    for docs in libraries:
        for rank,hit in enumerate(search(docs,question,limit=limit)):
            key=(hit.document,hit.page,hit.evidence)
            matches=query & terms(hit.evidence)
            title_matches=query & terms(hit.document)
            score=(len(matches),len(title_matches),-rank)
            if key not in candidates or score>candidates[key][0]:
                candidates[key]=(score,hit)
    return [hit for _,hit in sorted(candidates.values(),key=lambda row:row[0],reverse=True)[:limit]]


def document_lookup_report(question,public,now,*,reasoner=None):
    """Retrieve actual PDF passages independently of market-series availability.
    Private and visitor excerpts never travel to a remote model from chat.
    For a local model use the existing citation-checked document RAG.
    """
    from .document_rag import answer, MAX_PASSAGES
    from .models import Agent, Result, Step, utc_now
    libraries,notices=_document_libraries()
    hits=ranked_document_hits(libraries,question,MAX_PASSAGES)
    summary=("Passaggi pertinenti nei PDF. Verifica l’edizione applicabile." if hits else
             "Nessun passaggio pertinente trovato nei documenti consultabili.")
    run=lookup_report(question,public,now,reasoner=None,issue=summary)
    run.assumptions["assistant_document_lookup"]=True
    run.assumptions["document_count"]=sum(len(docs.documents) for docs in libraries)
    # This is not a dated market lookup and must not seed date follow-ups.
    run.assumptions["source_lookup"]=False
    run.source=Origin(name="Archivio documentale I.G.O.R.",kind=Kind.HISTORICAL,grain="daily",
                      fields=(),description="Estratti da PDF indicizzati, non validità normativa corrente.",retrieved_at=now)
    run.input_sha256=sha256(json.dumps({"public":public,"hits":[h.model_dump(mode="json") for h in hits]},
                              ensure_ascii=False,sort_keys=True,allow_nan=False).encode()).hexdigest()
    result=Result(agent=Agent.REGULATORY,status="completed" if hits else "unavailable",
                  summary=summary,evidence=hits,values={"document_count":run.assumptions["document_count"]})
    run.results[Agent.REGULATORY]=result
    run.steps[Agent.REGULATORY]=Step(agent=Agent.REGULATORY,status=result.status,started_at=now,finished_at=utc_now())
    run.warnings.extend(notices)
    if hits and reasoner is not None and reasoner.config.local:
        try:
            claims=answer(reasoner,question,hits)
            if claims:
                run.mode="LLM-assisted"
                run.model=reasoner.label
                run.interpretation="\n".join(claim["text"] for claim in claims)
                run.interpretation_sources=[Agent.REGULATORY]
                run.assumptions["document_claims"]=[{"text":c["text"],"citation":c["citation"].model_dump(mode="json")} for c in claims]
            else:
                run.warnings.append("Nessuna risposta AI verificabile; consulta gli estratti.")
        except Exception:
            run.warnings.append("Sintesi documentale non disponibile; consulta gli estratti.")
        if callable(getattr(reasoner,"usage_summary",None)):
            run.ai_usage=reasoner.usage_summary()
    elif hits and reasoner is not None:
        run.warnings.append("Ricerca PDF locale: nessun estratto inviato al provider remoto. La sintesi AI di documenti richiede il consenso nella sezione Norme e documenti o un modello locale.")
    run.finished_at=utc_now()
    return run
