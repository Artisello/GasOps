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
