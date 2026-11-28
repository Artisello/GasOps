from datetime import datetime,timezone,timedelta
import json
import pandas as pd
from gasops_app.briefing_context import collect, inventory_context, iip_context
from gasops_app.agents import Assumptions, MarketContext
from gasops_app.data import synthetic
from gasops_app.llm import CompatibleReasoner, LLMConfig, configuration
from gasops_app.models import Agent
from gasops_app.regulatory import Library
from gasops_app.workflow import run_workflow

NOW=datetime(2026,11,18,12,tzinfo=timezone.utc)

def test_config_provider_key_without_url(monkeypatch):
    monkeypatch.delenv("GASOPS_LLM_URL",raising=False)
    c=configuration({"GROQ_API_KEY":"fixture","GASOPS_LLM_MODEL":"openai/gpt-oss-20b"})
    assert c.groq and c.model=="openai/gpt-oss-20b"


def test_inventory_context_stale_and_iip_count_no_raw_records():
    frame=pd.DataFrame([{"gas_day":NOW.date()-timedelta(days=1),"status":"C",
                       "stock_twh":70.,"fill_pct":75.,"review":False}])
    result={"frame":frame,"scope":"IT","acquired":NOW,"failed":False}
    assert inventory_context(result,NOW,"AGSI+")["values"]["stock_twh"]==70
    assert "values" not in inventory_context(result,NOW+timedelta(days=3),"AGSI+")
    iip=iip_context({"acquired":NOW,"failed":False,"messages":[{"private":"NOT_TRANSMITTED"}],
                     "reported_total":1,"pages":1,"partial":False,"pagination_verified":True},NOW)
    assert iip["received_records"]==1 and iip["coverage"]=="Completa"
    assert "NOT_TRANSMITTED" not in json.dumps(iip)


def test_no_automatic_context_network_without_opt_in(monkeypatch):
    def fail(*args,**kwargs):
        raise AssertionError("Source must not be fetched")
    monkeypatch.setattr("gasops_app.briefing_context.load_agsi",fail)
    monkeypatch.setattr("gasops_app.briefing_context.load_alsi",fail)
    monkeypatch.setattr("gasops_app.briefing_context.load_iip",fail)
    monkeypatch.setattr("gasops_app.briefing_context.analyse_gas_day",fail)
    assert collect(None,None,NOW,key="fixture")=={}


def test_groq_http_briefing_context_and_structured_probe(monkeypatch):
    seen=[]
    class Response:
        status_code=200
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def iter_content(self,chunk_size):
            yield json.dumps({"choices":[{"message":{"content":json.dumps(
                {"interpretation":"Controllare la domanda osservata e le scorte.",
                 "references":["market_intelligence"]})}}]}).encode()
    def post(url,**kwargs):
        seen.append(kwargs["json"])
        return Response()
    monkeypatch.setattr("gasops_app.llm.requests.post",post)
    config=LLMConfig("openai/gpt-oss-120b","https://api.groq.com/openai/v1","fixture")
    assert CompatibleReasoner(config,reserve=lambda:True).probe()
    ctx=MarketContext(synthetic(),"Seasonal regression",NOW)
    data={"AGSI+":{"source":"Gas Infrastructure Europe (GIE) – AGSI+","values":{"stock_twh":70.}},
          "ENTSOG · SRG":{"source":"ENTSOG","period":"2026-11-16","values":{"power_gwh":300.0}},
          "Terna · elettricità":{"source":"Terna","values":{"Thermal":{"value":200.0,"period":"2026-11-16"}}},
          "ACER · GNL":{"source":"ACER","values":{"eu":{"value":42.0,"period":"2026-11-16"}}}}
    run=run_workflow(ctx,Library(),Assumptions(),full=True,
                     reasoner=CompatibleReasoner(config,reserve=lambda:True),public_context=data)
    assert run.mode=="LLM-assisted" and run.interpretation and len(run.results)==6
    assert run.assumptions["public_operational_context"]==data
    assert len(seen)==2 and seen[-1]["response_format"]=={"type":"json_object"}
    sent=seen[-1]["messages"][-1]["content"]
    assert "stock_twh" in sent and "Gas Infrastructure Europe" in sent
    assert all(x in sent for x in ("power_gwh","Thermal","ACER","2026-11-16"))
    assert "EXECUTIVE_BRIEFING_V1" in sent and "Priorità di verifica" in sent
    assert "EXECUTIVE_BRIEFING_V1" not in seen[0]["messages"][-1]["content"]
    assert seen[-1]["max_completion_tokens"]==3072
    assert '"regulatory_intelligence"' not in sent and '"settlement"' not in sent
    assert '"scenario"' not in sent and "CVaR 95% del costo lordo" not in sent
    assert Agent.SCENARIO in run.results


def test_summary_diagnostics_and_completion_budget(monkeypatch):
    import pytest
    import requests
    from gasops_app.models import Result, Citation
    from gasops_app.supervisor import ModelUnavailable
    result=Result(agent=Agent.MARKET,summary="Consumi 100 GWh",evidence=[Citation(document="Test",evidence="100 GWh")])
    config=LLMConfig("openai/gpt-oss-120b","https://api.groq.com/openai/v1","fixture")
    seen=[]
    payload={"choices":[{"finish_reason":"length","message":{"content":""}}]}
    class Response:
        status_code=200
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def iter_content(self,chunk_size):yield json.dumps(payload).encode()
    def post(*args,**kwargs):
        seen.append(kwargs["json"])
        return Response()
    monkeypatch.setattr("gasops_app.llm.requests.post",post)
    with pytest.raises(ModelUnavailable,match="troncata"):
        CompatibleReasoner(config).interpret("Sintesi",{Agent.MARKET:result})
    assert seen[-1]["max_completion_tokens"]==2048
    payload["choices"][0]={"message":{"content":json.dumps({"interpretation":"Test","references":["NOT_ALLOWED"]})}}
    with pytest.raises(ModelUnavailable,match="riferimenti non verificabili"):
        CompatibleReasoner(config).interpret("Sintesi",{Agent.MARKET:result})
    payload["choices"][0]={"message":{"content":"not-json"}}
    with pytest.raises(ModelUnavailable,match="JSON"):
        CompatibleReasoner(config).interpret("Sintesi",{Agent.MARKET:result})
    def timeout(*args,**kwargs):raise requests.Timeout()
    monkeypatch.setattr("gasops_app.llm.requests.post",timeout)
    with pytest.raises(ModelUnavailable,match="Tempo di risposta"):
        CompatibleReasoner(config).interpret("Sintesi",{Agent.MARKET:result})


def test_gie_missing_key_has_attributed_source_status_without_http(monkeypatch):
    def fail(*args,**kwargs):
        raise AssertionError("Missing key must not trigger a request")
    for name in ("load_agsi","load_alsi","load_iip"):
        monkeypatch.setattr("gasops_app.briefing_context."+name,fail)
    result=collect(None,None,NOW,include_gie=True)
    assert set(result)=={"AGSI+","ALSI","IIP"}
    assert all(item["status"]=="unavailable" and item["source_url"] and "values" not in item for item in result.values())


def test_fresh_iip_uses_completion_clock_and_stale_cache_has_reason(monkeypatch):
    acquired=NOW+timedelta(seconds=1)
    result={"acquired":acquired,"failed":False,"messages":[{}],"reported_total":1,
            "pages":1,"partial":False,"pagination_verified":True}
    monkeypatch.setattr("gasops_app.briefing_context.load_iip",lambda *a,**k:result)
    def missing(*a,**k):
        raise ValueError("No inventory fixture")
    monkeypatch.setattr("gasops_app.briefing_context.load_agsi",missing)
    monkeypatch.setattr("gasops_app.briefing_context.load_alsi",missing)
    report=collect(None,None,NOW,key="fixture",include_gie=True,
                   clock=lambda:NOW+timedelta(seconds=2))
    assert report["IIP"]["status"]=="available" and report["IIP"]["received_records"]==1
    stale=iip_context({**result,"failed":True},NOW+timedelta(seconds=2))
    assert stale["status"]=="stale" and stale["received_records"] is None
    assert "non riuscito" in stale["reason"]
    aged=iip_context(result,acquired+timedelta(hours=3))
    assert aged["status"]=="stale" and "oltre 2 ore" in aged["reason"]


def test_iip_failed_refresh_retains_controlled_diagnostic():
    result={"acquired":NOW,"failed":True,"messages":[{}],"reported_total":1,
            "pages":1,"partial":False,"pagination_verified":True,"refresh_error":"HTTP 429"}
    item=iip_context(result,NOW)
    assert item["received_records"] is None and item["status"]=="stale"
    assert "HTTP 429" in item["reason"]


def test_executive_readout_keeps_observed_and_forecast_separate():
    from gasops_app.executive_briefing import outlook_delta, management_readout
    from gasops_app.models import Run,Result
    data=synthetic()
    run=Run(question="briefing",source=data.origin.model_copy(update={"grain":"monthly"}),
            input_sha256=data.fingerprint,assumptions={"public_operational_context":{"IIP":{"status":"stale"}}})
    run.results[Agent.MARKET]=Result(agent=Agent.MARKET,summary="fixture",
        values={"period":"2026-10-01","demand_gwh":100,"demand_gwh_change_pct":5})
    run.results[Agent.FORECAST]=Result(agent=Agent.FORECAST,summary="fixture",
        values={"forecast":{"points":[{"period":"2026-11-01","estimate":125}]}})
    assert outlook_delta(run)==25
    overview,forecast,priorities=management_readout(run)
    assert "dimostrativi" in overview and "+25,0%" in forecast
    assert "indisponibilità" in priorities[0]
    run.results[Agent.FORECAST].values["forecast"]["points"][0]["period"]="2027-01-01"
    assert outlook_delta(run) is None


def test_multi_source_acquisition_is_bounded_and_never_uses_private_session(monkeypatch):
    from types import SimpleNamespace
    from gasops_app import briefing_market_sources as m
    from gasops_app.models import Kind
    selected=SimpleNamespace(origin=SimpleNamespace(grain="monthly",kind=Kind.HISTORICAL,archive=False))
    daily=SimpleNamespace(origin=SimpleNamespace(grain="daily"))
    calls=[]
    def fetch_daily(store,*,now,months):
        calls.append(months)
        return daily,None
    monkeypatch.setattr(m,"load_daily",fetch_daily)
    monkeypatch.setattr(m,"load_monthly",lambda *_: (_ for _ in ()).throw(AssertionError("selected source must be reused")))
    monkeypatch.setattr(m,"market_context",lambda bundle,now:{"source":bundle.origin.grain,"status":"available","values":{"demand_gwh":100}})
    monkeypatch.setattr(m,"load_lng",lambda store:SimpleNamespace(rows=[{"date":"2026-11-16","eu":42}],failed=False,acquired=NOW))
    monkeypatch.setattr(m,"benchmarks",lambda:{"source":"historical","status":"available","kind":"historical benchmark"})
    state={"private_pdf":"SECRET_FIXTURE","jarvis_native_v1":{"frame":"PRIVATE_FIXTURE"}}
    result=m.collect_market_sources(None,selected,NOW,state,clock=lambda:NOW)
    assert calls==[2]
    assert result["ENTSOG · SRG"]["values"]["demand_gwh"]==100
    assert result["ACER · GNL"]["values"]["eu"]["value"]==42
    assert result["Terna · outlook"]["status"]=="unavailable"
    assert "SECRET_FIXTURE" not in json.dumps(result) and "PRIVATE_FIXTURE" not in json.dumps(result)
    assert m.collect_market_sources(None,synthetic(),NOW,{},clock=lambda:NOW)=={}


def test_terna_context_only_uses_complete_non_conflicting_observations():
    from gasops_app.briefing_market_sources import power_context
    rows=[{"gas_day":"2026-11-16","metric":"Thermal","gwh":123,"valid_slots":24,"expected_slots":24},
          {"gas_day":"2026-11-16","metric":"load","gwh":999,"valid_slots":23,"expected_slots":24},
          {"gas_day":"2026-11-16","metric":"Wind","gwh":20,"valid_slots":24,"expected_slots":24},
          {"gas_day":"2026-11-16","metric":"Wind","gwh":30,"valid_slots":24,"expected_slots":24}]
    data=power_context({"acquired":NOW.isoformat(),"rows":rows},NOW)
    assert data["values"]=={"Thermal":{"period":"2026-11-16","value":123.0}}
    assert data["status"]=="available" and "elettrici" in data["unit"]


def test_structured_briefing_sources_and_measured_usage(monkeypatch):
    from gasops_app.models import Result,Citation
    from gasops_app.supervisor import ModelUnavailable
    import pytest
    replies={"sections":[{"id":"summary","text":"Consumo osservato in aumento.","references":["market_intelligence"]},
                         {"id":"supply","text":"Stoccaggi da verificare.","references":["src:AGSI+"]}]}
    seen=[]
    class Response:
        status_code=200
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def iter_content(self,chunk_size):
            yield json.dumps({"choices":[{"message":{"content":json.dumps(replies)}}],
                              "usage":{"prompt_tokens":780,"completion_tokens":120,"total_tokens":900}}).encode()
    def post(*args,**kwargs):
        seen.append(kwargs["json"])
        return Response()
    monkeypatch.setattr("gasops_app.llm.requests.post",post)
    model=CompatibleReasoner(LLMConfig("openai/gpt-oss-120b","https://api.groq.com/openai/v1","fixture"))
    result=Result(agent=Agent.MARKET,summary="Consumo 100 GWh",evidence=[Citation(document="Eurostat",evidence="100 GWh")])
    context={"AGSI+":{"source":"GIE AGSI+","source_url":"https://agsi.gie.eu/","status":"available",
                       "gas_day":"2026-11-16","values":{"stock_twh":70.0}}}
    answer,refs=model.interpret("Bollettino",{Agent.MARKET:result},context=context,executive=True)
    assert "In sintesi" in answer and refs==[Agent.MARKET]
    assert model.last_sections[1]["references"]==["src:AGSI+"]
    prompt=seen[-1]["messages"][-1]["content"]
    assert "70.0" in prompt and "2026-11-16" in prompt and "https://agsi.gie.eu/" not in prompt
    assert model.usage_summary()["total_tokens"]==900
    replies["sections"][1]["references"]=["src:invented"]
    with pytest.raises(ModelUnavailable,match="riferimenti"):
        model.interpret("Bollettino",{Agent.MARKET:result},context=context,executive=True)
    assert model.last_sections==[]


def test_compact_context_keeps_units_periods_status_and_original():
    from gasops_app.ai_response import compact_context
    original={"Terna":{"source":"Terna","url":"https://dati.terna.it/","period":"2026-11-16",
                        "scope":"Italia elettrica","unit":"GWh elettrici","status":"stale",
                        "values":{"load":{"value":100,"period":"2026-11-16"}}}}
    projected=compact_context(original)
    assert projected["Terna"]=={k:v for k,v in original["Terna"].items() if k!="url"}
    assert "url" in original["Terna"]
    assert len(json.dumps(projected))<len(json.dumps(original))


def test_model_context_filters_stale_and_failed_at_all_levels_without_mutation():
    from copy import deepcopy
    from gasops_app.ai_response import compact_context, model_context

    original={
        "Terna":{"status":"stale","unit":"GWh elettrici","period":"2026-11-16",
                 "values":{"load":{"value":100}}},
        "ACER":{"status":"available","values":[
            {"status":"available","value":42},
            {"status":"failed","value":999,"unit":"€/MWh"},
            {"status":"unavailable","value":888}]},
        "GME":{"status":"available","value":77},
    }
    before=deepcopy(original)
    assert compact_context(original)==before
    safe=model_context(original)
    assert safe["Terna"]=={"status":"stale","unit":"GWh elettrici","period":"2026-11-16"}
    assert safe["ACER"]["values"]==[
        {"status":"available","value":42},
        {"status":"failed","unit":"€/MWh"},
        {"status":"unavailable"}]
    assert "GME" not in safe
    assert original==before



def test_section_parser_normalizes_only_known_references():
    import pytest
    from gasops_app.ai_response import parse_sections,reference_index,InvalidSynthesis
    agents=["market_intelligence"]
    context={"AGSI+":{"source":"GIE AGSI+"},"ALSI":{"source":"GIE ALSI"}}
    codes,aliases=reference_index(agents,context)
    assert codes=={"A1":"market_intelligence","S1":"src:AGSI+","S2":"src:ALSI"}
    sections,refs=parse_sections([
        {"id":"Sicurezza delle forniture","text":"Scorte da monitorare.","references":" GIE AGSI+ "},
        {"id":"Market","text":"Domanda da monitorare.","references":["s2","S2"]},
    ],("summary","market","supply"),agents,["src:AGSI+","src:ALSI"],2600,aliases=aliases)
    assert [section["id"] for section in sections]==["market","supply"]
    assert refs==["src:ALSI","src:AGSI+"]
    with pytest.raises(InvalidSynthesis,match="riferimenti non verificabili"):
        parse_sections([{"id":"market","text":"Dato.","references":["S9"]}],
                       ("summary","market","supply"),agents,["src:AGSI+"],2600,aliases=aliases)


def test_briefing_recovers_invalid_format_once_and_preserves_source_only_answer(monkeypatch):
    from gasops_app.models import Agent
    from gasops_app.llm import CompatibleReasoner,LLMConfig
    seen=[]
    reserves=[]
    replies=iter([
        {"sections":[{"id":"summary","text":"Dato.","references":["invented"]}]},
        {"interpretation":"Scorte osservate: 70 TWh.","references":["S1"]},
    ])
    class Response:
        status_code=200
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def iter_content(self,chunk_size):
            yield json.dumps({"choices":[{"message":{"content":json.dumps(next(replies))}}],
                              "usage":{"prompt_tokens":600,"completion_tokens":100,"total_tokens":700}}).encode()
    def post(*args,**kwargs):
        seen.append(kwargs["json"])
        return Response()
    def reserve():
        reserves.append(True)
        return True
    monkeypatch.setattr("gasops_app.llm.requests.post",post)
    model=CompatibleReasoner(LLMConfig("openai/gpt-oss-120b","https://api.groq.com/openai/v1","fixture"),reserve=reserve)
    run=run_workflow(MarketContext(synthetic(),"Seasonal regression",NOW),Library(),Assumptions(),
                     full=True,reasoner=model,public_context={"AGSI+":{"source":"GIE","status":"available","values":{"stock_twh":70}}})
    assert run.mode=="LLM-assisted" and run.interpretation_sources==[]
    assert run.ai_sections[0]["references"]==["src:AGSI+"]
    assert run.ai_usage["calls"]==run.ai_usage["reported_calls"]==len(reserves)==2
    assert run.ai_usage["format_retries"]==1 and run.ai_usage["total_tokens"]==1400
    assert "invented" not in seen[-1]["messages"][-1]["content"]
    assert "Recupero formato" in seen[-1]["messages"][-1]["content"]
    assert len(run.results)==len(Agent)


def test_briefing_format_retry_respects_quota(monkeypatch):
    from gasops_app.llm import CompatibleReasoner,LLMConfig
    calls=[]
    class Response:
        status_code=200
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def iter_content(self,chunk_size):
            yield json.dumps({"choices":[{"message":{"content":"not-json"}}]}).encode()
    def post(*args,**kwargs):
        calls.append(True)
        return Response()
    quota=iter([True,False])
    monkeypatch.setattr("gasops_app.llm.requests.post",post)
    model=CompatibleReasoner(LLMConfig("openai/gpt-oss-120b","https://api.groq.com/openai/v1","fixture"),reserve=lambda:next(quota))
    run=run_workflow(MarketContext(synthetic(),"Seasonal regression",NOW),Library(),Assumptions(),
                     full=True,reasoner=model)
    assert run.mode=="Deterministic fallback" and not run.ai_sections
    assert len(calls)==1 and run.ai_usage["calls"]==1
    assert any("Quota interna" in warning for warning in run.warnings)


def test_simple_demand_question_accepts_section_and_recovers_oversized_answer(monkeypatch):
    from gasops_app.country_analysis import direct_market_question
    from gasops_app.market import demand_trend_question
    q="Come è cambiata la domanda di gas nell’ultimo periodo?"
    assert direct_market_question(q) and demand_trend_question(q)
    assert not demand_trend_question("Perché è cambiata la domanda di gas?")
    replies=iter([
        {"sections":[{"id":"answer","text":"x"*6001,"references":["market_intelligence"]}]},
        {"interpretation":"I consumi sono aumentati nel periodo osservato.","references":["market_intelligence"]},
    ])
    seen=[]
    class Response:
        status_code=200
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def iter_content(self,chunk_size):
            yield json.dumps({"choices":[{"message":{"content":json.dumps(next(replies))}}]}).encode()
    def post(*args,**kwargs):
        seen.append(kwargs["json"])
        return Response()
    monkeypatch.setattr("gasops_app.llm.requests.post",post)
    model=CompatibleReasoner(LLMConfig("openai/gpt-oss-120b","https://api.groq.com/openai/v1","fixture"))
    run=run_workflow(MarketContext(synthetic(),"Seasonal regression",NOW),Library(),Assumptions(),
                     q,reasoner=model,planned_only=True)
    assert run.mode=="LLM-assisted" and len(seen)==2 and run.ai_usage["format_retries"]==1
    assert set(run.results)=={Agent.MARKET,Agent.QUALITY}
    assert "2–4 frasi" in seen[0]["messages"][-1]["content"]
    assert "Recupero formato" in seen[1]["messages"][-1]["content"]


def test_editorial_length_is_not_a_validation_failure():
    from gasops_app.ai_response import parse_sections
    sections,refs=parse_sections([{"id":"answer","text":"x"*2400,"references":["market_intelligence"]}],
                                 ("answer","evidence"),["market_intelligence"],[],6000)
    assert len(sections[0]["text"])==2400 and refs==["market_intelligence"]


def test_gie_freshness_respects_gas_day_at_midnight():
    from gasops_app.ai_response import compact_context
    # 18 Nov 23:02 UTC = 19 Nov 00:02 CET, current gas day remains 18 Nov.
    from datetime import date
    now=datetime(2026,11,18,23,2,tzinfo=timezone.utc)
    frame=pd.DataFrame([{"gas_day":date(2026,11,16),"status":"C","stock_twh":176.6,"fill_pct":86.8}])
    result={"frame":frame,"scope":"IT","acquired":now-timedelta(hours=1),"failed":False}
    fresh=inventory_context(result,now,"AGSI+")
    assert fresh["status"]=="available" and fresh["values"]["fill_pct"]==86.8
    stale=inventory_context(result,now+timedelta(hours=7),"AGSI+")
    assert stale["status"]=="stale" and "values" not in stale
    assert stale["last_observed_values"]["fill_pct"]==86.8
    assert "last_observed_values" not in compact_context({"AGSI+":stale})["AGSI+"]
    failed=inventory_context({**result,"failed":True},now,"AGSI+")
    assert failed["status"]=="stale" and "non riuscito" in failed["reason"]


def test_acer_semantics_keep_price_and_spread_distinct():
    from types import SimpleNamespace
    from gasops_app.briefing_market_sources import acer_context
    entry=acer_context(SimpleNamespace(rows=[{"date":"2026-11-17","eu":86.09,"benchmark":5.24}],
                                       failed=False,acquired=NOW),NOW)
    assert entry["values"]["eu"]["definition"]=="Valutazione prezzo GNL UE"
    assert "differenziale" in entry["values"]["benchmark"]["definition"]
    assert "non riserve" in entry["limitation"]


def test_executive_section_does_not_repeat_title():
    from gasops_app.ai_response import parse_sections
    sections,_=parse_sections([{"id":"market","text":"Mercato: domanda in aumento.","references":["market_intelligence"]}],
                             ("summary","market"),["market_intelligence"],[],6000)
    assert sections[0]["text"]=="domanda in aumento."


def test_assistant_requires_relevant_sources_and_recovers_missing_citations(monkeypatch):
    from gasops_app.models import Result,Citation
    from gasops_app.assistant_sources import requested_sources,MARKET,PRICE,WEATHER,POWER,GIE
    q="Come è cambiata la domanda di gas nell’ultimo periodo?"
    assert requested_sources(q)==MARKET
    assert WEATHER in requested_sources("Come il meteo influenza la domanda?")
    assert set(POWER)<=set(requested_sources("Previsioni della domanda di gas"))
    assert set(GIE)<=set(requested_sources("Situazione del mercato del gas"))
    assert PRICE in requested_sources("Qual è il prezzo PSV?")
    result=Result(agent=Agent.MARKET,summary="Consumi mensili 100 GWh",evidence=[Citation(document="Eurostat",evidence="100 GWh")])
    public={MARKET[0]:{"source":"Eurostat","status":"available","period":"2026-10-01","values":{"demand_gwh":100}},
            MARKET[1]:{"source":"ENTSOG","status":"available","period":"2026-11-17","values":{"demand_gwh":10}}}
    replies=iter([{"interpretation":"Domanda mensile 100 GWh.","references":["market_intelligence"]},
                  {"interpretation":"Eurostat: 100 GWh nel mese. ENTSOG: 10 GWh nel giorno gas.","references":["S1","S2"]}])
    seen=[]
    class Response:
        status_code=200
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def iter_content(self,chunk_size):
            yield json.dumps({"choices":[{"message":{"content":json.dumps(next(replies))}}]}).encode()
    def post(*args,**kwargs):
        seen.append(kwargs["json"])
        return Response()
    monkeypatch.setattr("gasops_app.llm.requests.post",post)
    from gasops_app.models import Run
    model=CompatibleReasoner(LLMConfig("openai/gpt-oss-120b","https://api.groq.com/openai/v1","fixture"))
    bundle=synthetic()
    run=Run(question=q,source=bundle.origin,input_sha256=bundle.fingerprint,
            assumptions={"assistant_source_requirements":list(MARKET),"public_operational_context":public},
            results={Agent.MARKET:result})
    model.summarize(run)
    assert len(seen)==2 and model.format_retries==1
    assert set(run.ai_sections[0]["references"])=={"src:"+x for x in MARKET}
    assert "Fonti pertinenti obbligatorie: S1, S2" in seen[0]["messages"][-1]["content"]


def test_source_evidence_separates_missing_and_cited():
    from gasops_app.assistant_sources import source_rows,add_price_source,complete_requirements,MARKET,PRICE,WEATHER,POWER
    from gasops_app.models import Run
    public={MARKET[0]:{"source":"Eurostat","status":"available","period":"2026-10-01","values":{"demand_gwh":100},
                       "price":{"source":"ARERA","status":"available","period":"2026-10-01","value":88.36}},
            WEATHER:{"source":"Open-Meteo","status":"available","points":[{"day":"2026-11-24","hdd":6.9,"temperature_c":11.1}]}}
    add_price_source(public)
    complete_requirements(public,[PRICE,WEATHER,POWER[0]])
    data=synthetic()
    run=Run(question="test",source=data.origin,input_sha256=data.fingerprint,
            assumptions={"public_operational_context":public,"assistant_source_requirements":[PRICE,WEATHER,POWER[0]]},
            ai_sections=[{"id":"answer","text":"test","references":["src:"+PRICE]}])
    rows={r["key"]:r for r in source_rows(run)}
    assert rows[PRICE]["cited"] and "88,36" in rows[PRICE]["evidence"]
    assert not rows[WEATHER]["cited"] and "6,9" in rows[WEATHER]["evidence"]
    assert rows[POWER[0]]["status"]=="unavailable" and rows[POWER[0]]["required"]


def test_source_router_uses_smaller_budget_and_measures_provider_time(monkeypatch):
    from gasops_app.llm import CompatibleReasoner, LLMConfig
    bodies=[]
    class Response:
        status_code=200
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def iter_content(self,chunk_size):
            yield json.dumps({"choices":[{"message":{"content":'{"sources":["4"]}'}}],
                              "usage":{"prompt_tokens":150,"completion_tokens":12,"total_tokens":162}}).encode()
    def post(*args,**kwargs):
        bodies.append(kwargs["json"])
        return Response()
    monkeypatch.setattr("gasops_app.llm.requests.post",post)
    times=iter([10.,10.125])
    monkeypatch.setattr("gasops_app.llm.perf_counter",lambda:next(times))
    model=CompatibleReasoner(LLMConfig("openai/gpt-oss-120b","https://api.groq.com/openai/v1","fixture"))
    assert model.select_public_sources("Quanto gas abbiamo a disposizione?")==("AGSI+",)
    assert bodies[0]["max_completion_tokens"]==768
    assert model.usage_summary()["provider_elapsed_ms"]==125
    assert model.usage_summary()["total_tokens"]==162


def test_iip_empty_unverified_is_not_evidence_of_zero():
    item={"acquired":NOW,"failed":False,"messages":[],"reported_total":None,
          "partial":True,"pagination_verified":False}
    assert iip_context(item,NOW)["received_records"] is None
    assert iip_context(item,NOW)["status"]=="unavailable"
    verified={**item,"reported_total":0,"partial":False,"pagination_verified":True}
    result=iip_context(verified,NOW)
    assert result["received_records"]==0 and result["status"]=="available"
    assert "non prova assenza" in result["limitation"]


def test_ai_event_semantics_rejects_categorical_absence():
    import pytest
    from gasops_app.ai_response import verify_event_semantics,InvalidSynthesis
    public={"IIP":{"status":"available","received_records":0,"coverage":"Completa"}}
    for text in ("Zero eventi attivi.", "Nessuna indisponibilità.", "Non ci sono interruzioni."):
        with pytest.raises(InvalidSynthesis,match="copertura degli avvisi"):
            verify_event_semantics([{"text":text}],public)
    for text in ("Zero record UMM restituiti.", "Nessun evento documentato nella copia.",
                 "Zero record non dimostra l'assenza di eventi attivi."):
        verify_event_semantics([{"text":text}],public)
