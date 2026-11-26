from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import json
from types import SimpleNamespace

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from gasops_app import assistant_lookup, assistant_sources as sources
from gasops_app.ai_response import InvalidSynthesis, model_context, verify_measurements
from gasops_app.llm import CompatibleReasoner, LLMConfig
from gasops_app.mensile import Prices
from gasops_app.models import Agent, Citation, Kind, Provider, Result
from gasops_app.store import Store

NOW=datetime(2026,11,22,12,tzinfo=timezone.utc)
DAY=date(2026,11,21)


def test_provider_routing_distinguishes_prices_supply_and_geo():
    from gasops_app.country_analysis import requested_country
    assert sources.requested_sources("Ultimo differenziale GNL–TTF in Europa")== (sources.ACER,)
    assert requested_country("Ultimo differenziale GNL–TTF in Europa")=="EU"
    assert requested_country("Domanda di gas in Europa")=="unsupported"
    assert sources.requested_sources("Quali sono i prezzi di sbilanciamento SRG?")== (sources.GME,)
    assert sources.requested_sources("Quali sono i prelievi da stoccaggio?")== ("AGSI+",)
    assert sources.requested_sources("Qual è il flusso ENTSOG a Tarvisio?")== (sources.NETWORK,)
    assert sources.requested_sources("Previsione del carico elettrico Terna")== (sources.POWER[1],)
    assert sources.query_day("Prelievi del 21/11/2026")==DAY
    assert sources.query_day("Flusso del 21 novembre 2026")==DAY
    assert sources.query_day("Flusso di ieri",today=NOW.date())==DAY


def test_only_the_requested_inventory_is_read_for_an_exact_date(monkeypatch):
    from gasops_app import briefing_context as b, briefing_market_sources as m
    frame=pd.DataFrame([{"gas_day":DAY-timedelta(days=1),"status":"C","stock_twh":70},
                        {"gas_day":DAY,"status":"C","stock_twh":71}])
    calls=[]
    def agsi(store,key,scope,**kwargs):
        calls.append(scope)
        return {"frame":frame,"scope":scope,"failed":False,"acquired":NOW}
    def forbidden(*a,**k):
        pytest.fail("Unrelated adapter queried")
    monkeypatch.setattr(b,"load_agsi",agsi)
    for name in ("load_alsi","load_iip"):
        monkeypatch.setattr(b,name,forbidden)
    monkeypatch.setattr(m,"collect_market_sources",forbidden)
    def fetch(day):
        return assistant_lookup.collect_context(None,None,None,NOW,{},requested=("AGSI+",),scope="EU",day=day,
                key="fixture",include_gie=True,clock=lambda:NOW)["AGSI+"]
    item=fetch(DAY-timedelta(days=1))
    assert item["gas_day"]=="2026-11-20" and item["values"]=={"stock_twh":70.0}
    assert fetch(DAY-timedelta(days=2))["status"]=="unavailable"
    assert calls==["EU","EU"]


def test_cmem_lookup_without_demand_bundle_has_link_and_month(monkeypatch,tmp_path):
    from gasops_app import briefing_market_sources as m, session
    monkeypatch.setenv("GASOPS_STATE_DIR",str(tmp_path))
    monkeypatch.setattr(session,"utc_now",lambda:NOW)
    quote=Provider(name=sources.PRICE,kind=Kind.HISTORICAL,fields=("price_eur_mwh",),
                   description="Riferimento mensile",url=m.ARERA_URL,retrieved_at=NOW)
    monkeypatch.setattr(m,"load_arera",lambda store:Prices({"2026-10-01":Decimal("34.123")},quote))
    monkeypatch.setattr(m,"load_monthly",lambda *a:pytest.fail("Eurostat is not needed for CMEM,m"))
    monkeypatch.setattr(m,"load_daily",lambda *a:pytest.fail("ENTSOG is not needed for CMEM,m"))
    app=AppTest.from_string("""
from gasops_app.session import launch, Selection, PUBLIC
from gasops_app.assistant_page import _report
selection = Selection(PUBLIC, "Seasonal regression", 24, None)
report = launch(selection, "Qual è il CMEM,m del 21/10/2026?", ai_policy="off")
_report(report, selection)
""").run()
    assert not app.exception
    report=app.session_state["last_run"]
    data=report.assumptions["public_operational_context"]
    assert set(data)=={sources.PRICE}
    assert data[sources.PRICE]["period"]=="2026-10-01"
    assert data[sources.PRICE]["value"]==34.123
    assert any("Fonte ufficiale" in caption.value and m.ARERA_URL in caption.value for caption in app.caption)
    assert any("34,12 €/MWh" in text.value for text in app.text)


def test_entsog_point_is_dated_and_never_uses_bundled_operational_snapshot(monkeypatch,tmp_path):
    from gasops_app import assistant_network as n, gas_data
    from gasops_app.entsog import SOURCE
    from gasops_app.gas_calendar import gas_day_bounds
    from gasops_app.italian_network import Observation, verified_bindings
    network,items=n._catalog()
    tarvisio=next(item for item in items if item.name=="Tarvisio")
    binding=next(b for b in verified_bindings(network,tarvisio.id) if b.direction=="entry")
    first,last=gas_day_bounds(DAY)
    row=Observation(infrastructure_id=tarvisio.id,point_direction=binding.point_direction,
        indicator="Physical Flow",value=Decimal("0"),unit="GWh/d",period_from=first,period_to=last,
        gas_day=DAY,retrieved_at=NOW-timedelta(hours=1),observed_at=NOW.isoformat(),source="ENTSOG",
        source_url=SOURCE,source_id="fixture",quality_status="valid",publication_status="Confirmed")
    snapshot=SimpleNamespace(first=DAY,last=DAY,point_direction=binding.point_direction,
        acquired=row.retrieved_at,records=(row,),partial=False,failed=False)
    def context(network,bundled,state,now,**kwargs):
        assert not bundled
        return {"snapshots":[snapshot]}
    monkeypatch.setattr(gas_data,"source_context",context)
    store=Store(tmp_path/"state.sqlite3")
    item=n.collect_network(store,{},NOW,"Flusso fisico in ingresso a Tarvisio",day=DAY)
    assert item["values"]=={"Tarvisio · ingresso":{"flow_gwh_d":0.0}}
    assert n.collect_network(store,{},NOW,"Flusso fisico in uscita a Tarvisio",day=DAY)["status"]=="unavailable"
    assert n.collect_network(store,{},NOW,"Flusso fisico in ingresso a Tarvisio",day=DAY-timedelta(days=1))["status"]=="unavailable"
    assert n.collect_network(store,{},NOW,"Flusso fisico a un punto sconosciuto",day=DAY)["status"]=="unavailable"


def test_measurements_need_a_value_and_unit_from_that_sections_references():
    context={sources.PRICE:{"status":"available","unit":"€/MWh","value":34.123},
             sources.DAILY:{"status":"available","values":{"demand_gwh":100.234},"changes_pct":{"demand_gwh":2.3}},
             "AGSI+":{"status":"stale","values":{"stock_twh":70}}}
    def check(text,*refs):
        verify_measurements([{"text":text,"references":["src:"+ref for ref in refs]}],{},model_context(context))
    check("34,12 €/MWh.",sources.PRICE)
    check("100,2 GWh/giorno gas, +2,3%.",sources.DAILY)
    for answer,source in (("40 €/MWh",sources.PRICE),("34,12 MWh",sources.PRICE),
                          ("100,2 GWh",sources.PRICE),("70 TWh","AGSI+"),("−2,3%",sources.DAILY)):
        with pytest.raises(InvalidSynthesis,match="valore o un’unità"):
            check(answer,source)


def test_local_gme_question_does_not_call_provider_or_export_data(monkeypatch,tmp_path):
    from gasops_app import session
    from gasops_app.reports import markdown
    monkeypatch.setenv("GASOPS_STATE_DIR",str(tmp_path))
    model=CompatibleReasoner(LLMConfig("fixture","https://api.groq.com/openai/v1"))
    monkeypatch.setattr(session,"reasoner",lambda:model)
    monkeypatch.setattr(model,"summarize",lambda *a:pytest.fail("GME lookup must stay local"))
    app=AppTest.from_string("""
from gasops_app.session import launch, Selection, PUBLIC
launch(Selection(PUBLIC, "Seasonal regression", 24, None), "Indice IGI del 21/11/2026", ai_policy="required")
""").run()
    assert not app.exception
    report=app.session_state["last_run"]
    assert report.assumptions["gme_request"]=={"kinds":["igi"],"day":"2026-11-21"}
    assert report.assumptions["public_operational_context"]=={} and not report.ai_usage
    assert "quote fixture" not in markdown(report,{})
    assert model_context({"IGI · GME":{"source":"Gestore dei Mercati Energetici S.p.A.","value":500}})=={}


def test_response_retries_one_unsupported_number_with_cited_value(monkeypatch):
    public={sources.PRICE:{"source":sources.PRICE,"status":"available","unit":"€/MWh","value":34.123}}
    model=CompatibleReasoner(LLMConfig("fixture","https://api.groq.com/openai/v1"))
    replies=iter(("52 €/MWh.","34,12 €/MWh."))
    calls=[]
    def chat(messages):
        calls.append(messages[-1]["content"])
        return {"content":json.dumps({"sections":[{"id":"answer","text":next(replies),"references":["S1"]}]})}
    monkeypatch.setattr(model,"_chat",chat)
    report=assistant_lookup.lookup_report("Valore CMEM,m",public,NOW,reasoner=model)
    assert report.mode=="LLM-assisted"
    assert report.ai_sections[0]["text"]=="34,12 €/MWh." and model.format_retries==1
    assert len(calls)==2 and "52 €/MWh" not in calls[1]


def test_forecast_projection_supplies_selected_point_and_interval(monkeypatch):
    model=CompatibleReasoner(LLMConfig("fixture","https://api.groq.com/openai/v1"))
    forecast=Result(agent=Agent.FORECAST,summary="Proiezione dal modello",
        values={"forecast":{"points":[{"period":DAY.isoformat(),"estimate":108,
                                       "lower_80":100,"upper_80":117}]}},
        evidence=[Citation(document="ENTSOG",evidence="Prelievi dei tre aggregati")])
    def chat(messages):
        assert '"estimate":108' in messages[-1]["content"]
        return {"content":json.dumps({"sections":[{"id":"answer","text":"108 GWh, da 100 a 117 GWh.",
                                                  "references":["A1"]}]})}
    monkeypatch.setattr(model,"_chat",chat)
    answer,refs=model.interpret("Previsione per il 21/11/2026",{Agent.FORECAST:forecast})
    assert "108 GWh" in answer and refs==[Agent.FORECAST]
