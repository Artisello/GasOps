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


def test_shortcuts_expand_to_targeted_queries_and_unknown_commands_fail_closed():
    from gasops_app.workflow import DAILY_BRIEFING, plan
    for cmd,expected in (("/consumi",sources.MARKET),("/scorte",("AGSI+",)),
                         ("/gnl",("ALSI",)),("/prezzi",(sources.PRICE,)),
                         ("/produzione",(sources.MONTHLY,)),("/mase",(sources.MASE,))):
        question,issue=sources.expand_command(cmd)
        assert not issue and set(sources.requested_sources(question))==set(expected)
    question,issue=sources.expand_command("/scorte 21/11/2026")
    assert not issue and sources.query_day(question)==DAY
    assert sources.expand_command("/bollettino")== (DAILY_BRIEFING,None)
    assert sources.expand_command("/xyz")[0] is None
    assert sources.expand_command("/bollettino 21/11/2026")[0] is None
    assert sources.requested_sources("Consumi mensili italiani")== (sources.MONTHLY,)
    assert sources.requested_sources("Gas importato in Italia")== (sources.MONTHLY,)
    assert Agent.SCENARIO not in {c.agent for c in plan("La domanda è aumentata del 10%?",False)}
    assert Agent.SCENARIO not in {c.agent for c in plan("Dimmi se la domanda è aumentata del 10%",False)}
    scenario=next(c.arguments for c in plan("Simula un aumento del prezzo di 12,5 €/MWh",False)
                  if c.agent==Agent.SCENARIO)
    assert scenario.price_delta_eur_mwh==Decimal("12.5")


def test_mase_exact_archive_period_and_scope():
    from gasops_app.mase_archive import observations
    annual=assistant_lookup.mase_context("MASE produzione 2025")
    assert annual["status"]=="available" and annual["period"]=="2025"
    assert annual["kind"]=="historical archive"
    actual=next(r for r in observations() if r["period"]=="2025" and r["geography"]=="IT")
    assert annual["values"]["Produzione nazionale"]["value"]==float(actual["value"])
    assert annual["values"]["Produzione nazionale"]["unit"]==actual["unit"]
    assert annual["source_url"]==actual["source_url"]
    assert "non API live" in annual["limitation"]
    assert assistant_lookup.mase_context("MASE febbraio 2026")["period"]=="2026-02"
    assert assistant_lookup.mase_context("MASE Lombardia 2025")["scope"]=="Lombardia"
    assert assistant_lookup.mase_context("MASE novembre 2026")["status"]=="unavailable"
    assert assistant_lookup.mase_context("MASE 2024 e 2025")["status"]=="unavailable"


def test_public_readout_keeps_balance_components_and_frequency():
    monthly={"status":"available","values":{"demand_gwh":100,"production_gwh":5,"imports_gwh":90,"exports_gwh":0}}
    result=sources.source_evidence(sources.MONTHLY,monthly)
    assert "Produzione nazionale 5,0 GWh/mese" in result
    assert "Esportazioni 0,0 GWh/mese" in result
    assert "Importazioni 90,0 GWh/mese" in result
    daily={"status":"available","values":{"demand_gwh":100,"industry_gwh":20}}
    assert "Industria 20,0 GWh/giorno gas" in sources.source_evidence(sources.DAILY,daily)


def test_archive_units_are_checked_against_reference():
    public={sources.MASE:{"status":"available","values":{"Produzione nazionale":{"unit":"bcm","value":2.5}}}}
    def check(answer):
        verify_measurements([{"text":answer,"references":["src:"+sources.MASE]}],{},model_context(public))
    check("2,5 bcm.")
    with pytest.raises(InvalidSynthesis):
        check("5 bcm.")
    with pytest.raises(InvalidSynthesis):
        check("2,5 Sm3.")


def test_terna_uses_requested_historical_day_without_substituting_latest():
    from gasops_app.briefing_market_sources import power_context
    rows=[{"gas_day":d,"metric":"load","gwh":value,"valid_slots":24,"expected_slots":24}
          for d,value in (("2026-11-10",100),("2026-11-20",999))]
    item={"acquired":NOW.isoformat(),"rows":rows}
    exact=power_context(item,NOW,day=date(2026,11,10))
    assert exact["period"]=="2026-11-10" and exact["status"]=="available"
    assert exact["values"]["load"]["value"]==100
    with pytest.raises(ValueError):
        power_context(item,NOW,day=date(2026,11,11))


def _daily_turn(question="Scorte AGSI+ in Italia del 21/11/2026?", day="2026-11-21",
                *, stock=70., fill=80., scope="IT", kind="observed", status="available", review=False):
    item={"source":"GIE AGSI+","scope":scope,"gas_day":day,"kind":kind,"status":status,
          "quality_review":review,"values":{"stock_twh":stock,"fill_pct":fill}}
    return SimpleNamespace(question=question,assumptions={"source_lookup":True,"requested_day":day,
        "requested_country":scope,"public_operational_context":{"AGSI+":item}})


@pytest.mark.parametrize("query,expected",[
    ("E il 20/11/2026?","2026-11-20"),
    ("E il 20 novembre 2026?","2026-11-20"),
    ("E ieri?","2026-11-21"),
    ("E il giorno precedente?","2026-11-20"),
    ("E rispetto al 19/11/2026?","2026-11-19"),
    ("E rispetto allo stesso giorno della settimana precedente?","2026-11-14"),
    ("E rispetto al giorno precedente?","2026-11-20"),
])
def test_followup_replaces_date_without_losing_source_or_scope(query,expected):
    from gasops_app.country_analysis import requested_country
    prior=_daily_turn("Scorte AGSI+ in Germania del 21/11/2026?",scope="DE")
    resolved,issue=sources.resolve_followup(query,prior,today=NOW.date())
    assert issue is None and sources.query_day(resolved)==date.fromisoformat(expected)
    assert sources.requested_sources(resolved)==("AGSI+",)
    assert requested_country(resolved)=="DE"
    assert resolved.count("2026")==1


@pytest.mark.parametrize("query",["E il 31/11/2026?","E in Francia?","E rispetto alla settimana precedente?",
                                  "Fammi un grafico","Spiegami perché","E i consumi?"])
def test_unresolved_followup_never_starts_an_unrelated_analysis(query):
    resolved,issue=sources.resolve_followup(query,_daily_turn(),today=NOW.date())
    assert resolved is None and issue


def test_followup_without_context_or_with_unsupported_grain_requests_clarification():
    assert sources.resolve_followup("E ieri?",None,today=NOW.date())[0] is None
    prior=SimpleNamespace(question="Produzione nazionale mensile Eurostat",assumptions={"source_lookup":True})
    assert sources.resolve_followup("E ieri?",prior,today=NOW.date())[0] is None
    assert sources.resolve_followup("/consumi",_daily_turn(),today=NOW.date())==("/consumi",None)
    assert sources.resolve_followup("Qual è il prezzo ARERA?",_daily_turn(),today=NOW.date())==("Qual è il prezzo ARERA?",None)


def test_daily_comparison_uses_chronological_values_and_percentage_points():
    newer=_daily_turn(stock=74,fill=83)
    older=_daily_turn(day="2026-11-20",stock=70,fill=80)
    result={row["metric"]:row for row in sources.day_comparison(newer,older)}
    assert result["Giacenza"]["delta"]==4 and result["Giacenza"]["delta_unit"]=="TWh"
    assert result["Riempimento"]["delta"]==3 and result["Riempimento"]["delta_unit"]=="p.p."
    assert result["Giacenza"]["before_day"]=="2026-11-20"
    assert result["Giacenza"]["after_day"]=="2026-11-21"
    assert sources.day_comparison(newer,_daily_turn(day="2026-11-20",scope="DE"))==[]
    assert sources.day_comparison(newer,_daily_turn(day="2026-11-20",kind="estimated"))==[]
    assert sources.day_comparison(newer,_daily_turn(day="2026-11-20",status="partial"))==[]
    assert sources.day_comparison(newer,_daily_turn(day="2026-11-20",review=True))==[]
    assert sources.day_comparison(newer,_daily_turn(day="2026-11-20",status="stale"))==[]
    assert sources.day_comparison(newer,newer)==[]


def test_automatic_lookup_ignores_selected_dashboard_dataset(monkeypatch):
    from gasops_app import session
    calls=[]
    def collect(context,base,requested,**kwargs):
        calls.append((base,requested,kwargs))
        return {"AGSI+":{"source":"GIE AGSI+","scope":"IT","gas_day":"2026-11-21",
                         "status":"available","kind":"observed","values":{"stock_twh":70}}}
    monkeypatch.setattr(session,"_collect_assistant_sources",collect)
    monkeypatch.setattr(session,"automatic_selection",lambda *a,**k:pytest.fail("Lookup does not require a base series"))
    app=AppTest.from_string("""
from gasops_app import session
import streamlit as st
st.session_state["selected_source"]=session.DEMO
session.launch(None,"Scorte AGSI+ del 21/11/2026",ai_policy="off")
""").run()
    assert not app.exception
    assert len(calls)==1 and calls[0][0] is None
    assert calls[0][1]==("AGSI+",) and calls[0][2]["automatic"]
    assert app.session_state["selected_source"]==session.DEMO
    assert app.session_state["last_run"].assumptions["public_operational_context"]["AGSI+"]["values"]["stock_twh"]==70


def test_automatic_public_base_selects_grain_and_rejects_synthetic(monkeypatch):
    from dataclasses import replace
    from gasops_app import session
    from gasops_app.data import synthetic
    example=synthetic()
    calls=[]
    def load(grain):
        def fake(*args,**kwargs):
            calls.append(grain)
            return replace(example,origin=example.origin.model_copy(update={"kind":Kind.HISTORICAL,"grain":grain})),None
        return fake
    monkeypatch.setattr(session,"database",lambda:None)
    monkeypatch.setattr(session,"load_daily",load("daily"))
    monkeypatch.setattr(session,"load_monthly",load("monthly"))
    for question,grain in (("Previsione giornaliera della domanda","daily"),("Previsione mensile della domanda","monthly")):
        selected=session.automatic_selection(question)
        assert selected.bundle.origin.grain==grain and selected.model=="Automatic"
    assert calls==["daily","monthly"]
    monkeypatch.setattr(session,"load_monthly",lambda *a,**k:(example,None))
    assert session.automatic_selection("Previsione mensile della domanda").bundle is None


def test_fallback_source_router_is_allowlisted_and_read_only(monkeypatch):
    model=CompatibleReasoner(LLMConfig("fixture","http://localhost:11434/v1"))
    seen=[]
    def reply(messages,**kwargs):
        seen.extend(messages)
        return {"content":json.dumps({"sources":["4","5","4"]})}
    monkeypatch.setattr(model,"_chat",reply)
    assert model.select_public_sources("Quanto gas abbiamo a disposizione?")==("AGSI+","ALSI")
    assert "sources" in json.loads(seen[-1]["content"])
    monkeypatch.setattr(model,"_chat",lambda *a,**k:{"content":'{"sources":["https://unknown.example"]}'})
    with pytest.raises(ValueError):
        model.select_public_sources("Consulta una fonte")


def test_document_chat_retrieves_pdf_without_market_bundle_or_remote_transfer(monkeypatch):
    import pymupdf
    from gasops_app.document_desk import build
    from gasops_app import session
    with pymupdf.open() as pdf:
        pdf.new_page().insert_text((72,72),"La garanzia economica richiede un deposito cauzionale.")
        raw=pdf.tobytes()
    library=build((("norme.pdf",raw),))
    monkeypatch.setattr(assistant_lookup,"_document_libraries",lambda:([library],[]))
    model=CompatibleReasoner(LLMConfig("fixture","https://api.groq.com/openai/v1"))
    monkeypatch.setattr(model,"_chat",lambda *a,**k:pytest.fail("No PDF query or excerpt sent without separate consent"))
    monkeypatch.setattr(session,"assistant_reasoner",lambda:model)
    monkeypatch.setattr(session,"automatic_selection",lambda *a,**k:pytest.fail("PDF lookup requires no market bundle"))
    app=AppTest.from_string("""
from gasops_app.session import launch
launch(None,"Secondo il documento, quale deposito cauzionale è previsto?",ai_policy="automatic")
""").run()
    assert not app.exception
    report=app.session_state["last_run"]
    assert report.assumptions["assistant_document_lookup"]
    assert report.results[Agent.REGULATORY].evidence[0].page==1
    assert "deposito cauzionale" in report.results[Agent.REGULATORY].evidence[0].evidence
    assert report.mode=="Deterministic" and not report.ai_usage


def test_local_document_rag_keeps_verified_page_citation(monkeypatch):
    from gasops_app.regulatory import Library
    hit=Citation(document="norme.pdf",page=5,evidence="Il preavviso richiesto è pari a sette giorni.")
    monkeypatch.setattr(assistant_lookup,"_document_libraries",lambda:([Library(include_notes=False)],[]))
    monkeypatch.setattr("gasops_app.document_desk.search",lambda *a,**k:[hit])
    model=CompatibleReasoner(LLMConfig("fixture","http://localhost:11434/v1"))
    monkeypatch.setattr(model,"_chat",lambda *a,**k:{"content":json.dumps({"claims":[
        {"text":"Il preavviso è di sette giorni.","source":"D1","quote":hit.evidence}]})})
    report=assistant_lookup.document_lookup_report("Preavviso nel PDF?",{},NOW,reasoner=model)
    assert report.mode=="LLM-assisted"
    assert report.assumptions["document_claims"][0]["citation"]["page"]==5
    assert report.interpretation=="Il preavviso è di sette giorni."


def test_explicit_period_parser_distinguishes_days_and_months():
    assert sources.query_days("Confronta 20/11/2026 e 21 novembre 2026")==(
        date(2026,11,20),date(2026,11,21))
    assert sources.query_days("31/11/2026") is None
    assert sources.query_months("Settembre 2026 e 2026-10")==(
        date(2026,9,1),date(2026,10,1))
    assert sources.query_months("20 novembre 2026 e 2026-11-21")==()


def test_hub_quotes_are_not_other_price_indicators():
    assert sources.requested_sources("Prezzo TTF spot oggi")== (sources.TTF_QUOTE,)
    assert sources.requested_sources("Prezzo PSV day-ahead")== (sources.PSV_QUOTE,)
    assert sources.requested_sources("Prezzo PSV del 20/11/2026")== (sources.PSV_QUOTE,)
    assert sources.requested_sources("Riferimento mensile PSV ARERA CMEM,m")== (sources.PRICE,)
    assert sources.requested_sources("Differenziale GNL–TTF ACER")== (sources.ACER,)
    assert "non è il prezzo TTF" in sources.complete_requirements({},(sources.TTF_QUOTE,))[sources.TTF_QUOTE]["reason"]


def test_nested_stale_price_is_not_sent_to_model_and_frequency_is_checked():
    public={
        sources.ACER:{"status":"available","unit":"€/MWh","values":{
            "eu":{"value":40,"status":"available"},"benchmark":{"value":999,"status":"stale"}}},
        sources.MONTHLY:{"status":"available","grain":"mese","unit":"GWh/mese",
                         "values":{"demand_gwh":12000}},
    }
    safe=model_context(public)
    assert safe[sources.ACER]["values"]["benchmark"]=={"status":"stale"}
    verify_measurements([{"text":"12000 GWh/mese","references":["src:"+sources.MONTHLY]}],{},safe)
    with pytest.raises(InvalidSynthesis,match="giornaliera e mensile"):
        verify_measurements([{"text":"12000 GWh/giorno gas","references":["src:"+sources.MONTHLY]}],{},safe)


def test_period_comparison_uses_only_exact_compatible_observations():
    first,last="2026-09-01","2026-10-01"
    def snapshot(period,value):
        return {sources.PRICE:{"source":"ARERA","status":"available","scope":"IT","grain":"mese",
                               "unit":"€/MWh","period":period,"value":value}}
    a,b=snapshot(first,40),snapshot(last,50)
    rows=sources.period_comparison(a,b,first=first,last=last,monthly=True)
    assert len(rows)==1 and rows[0]["delta"]==10 and rows[0]["delta_pct"]==25
    assert not sources.period_comparison(a,b,first=first,last="2026-11-01",monthly=True)
    b[sources.PRICE]["quality_review"]=True
    assert not sources.period_comparison(a,b,first=first,last=last,monthly=True)


def test_automatic_assistant_compares_two_months_without_llm_or_latest_substitution(monkeypatch):
    from gasops_app import session
    monkeypatch.setattr(session,"utc_now",lambda:NOW)
    calls=[]
    def collect(context,selected,requested,**kw):
        calls.append((requested,kw["day"]))
        value={date(2026,9,1):40,date(2026,10,1):50}[kw["day"]]
        return {sources.PRICE:{"source":"ARERA","status":"available","scope":"IT","grain":"mese",
                              "unit":"€/MWh","period":kw["day"].isoformat(),"value":value}}
    monkeypatch.setattr(session,"_collect_assistant_sources",collect)
    app=AppTest.from_string("""
from gasops_app.session import launch
from gasops_app.assistant_page import _report
report=launch(None,"Confronta CMEM,m settembre 2026 e ottobre 2026",ai_policy="off")
_report(report,None)
""").run()
    assert not app.exception
    report=app.session_state["last_run"]
    assert report.assumptions["assistant_period_comparison"]
    assert report.assumptions["assistant_comparison"][0]["delta"]==10
    assert len(app.dataframe)==1
    assert calls==[((sources.PRICE,),date(2026,9,1)),((sources.PRICE,),date(2026,10,1))]


def test_precise_gie_requests_actual_historical_window(monkeypatch):
    from gasops_app import briefing_context as b
    historical=date(2025,1,15)
    calls=[]
    def fetch(store,key,scope,**kwargs):
        calls.append((kwargs["first"],kwargs["last"]))
        return {"frame":pd.DataFrame([{"gas_day":historical,"status":"C","stock_twh":70}]),
                "scope":scope,"acquired":NOW,"failed":False}
    monkeypatch.setattr(b,"load_agsi",fetch)
    item=b.collect(None,None,NOW,key="fixture",include_gie=True,only={"AGSI+"},
                   day=historical,clock=lambda:NOW)["AGSI+"]
    assert item["gas_day"]==historical.isoformat() and item["status"]=="available"
    assert calls==[(historical,historical)]
    assert b.collect(None,None,NOW,key="fixture",include_gie=True,only={"AGSI+"},
                     day=NOW.date(),clock=lambda:NOW)["AGSI+"]["status"]=="unavailable"
    assert len(calls)==1


def test_precise_srg_uses_bounded_historical_range(monkeypatch):
    from gasops_app import briefing_market_sources as m
    historical=date(2025,1,15)
    calls=[]
    def fetch(store,first,last,**kwargs):
        calls.append((first,last))
        return object()
    monkeypatch.setattr(m,"load_daily_range",fetch)
    monkeypatch.setattr(m,"combine_daily",lambda *a:object())
    monkeypatch.setattr(m,"market_context",lambda bundle,now,day=None:{
        "status":"available","period":day.isoformat(),"values":{"demand_gwh":120}})
    monkeypatch.setattr(m,"load_daily",lambda *a,**k:pytest.fail("Do not load latest SRG history"))
    result=m.collect_market_sources(None,None,NOW,{},only={sources.DAILY},day=historical,
                                   clock=lambda:NOW)
    assert result[sources.DAILY]["period"]==historical.isoformat()
    assert calls==[(historical-timedelta(days=13),historical)]


@pytest.mark.parametrize("question",[
    "Il prezzo medio dell'energia elettrica all'ingrosso in Italia per ottobre 2026",
    "Qual è il PUN Index GME?",
    "Prezzo elettrico di oggi",
    "Costo giornaliero dell’elettricità",
    "Prezzo dell'elettricità secondo ARERA",
])
def test_electricity_price_is_not_gas_or_terna(question):
    assert sources.requested_sources(question)==(sources.ELECTRIC_PRICE,)
    assert not sources.gme_indicators(question)


def test_mixed_electricity_and_lng_price_keeps_explicit_gap():
    keys=sources.requested_sources("Prezzo dell'elettricità e del GNL")
    assert set(keys)=={sources.ELECTRIC_PRICE,sources.ACER}
    assert "non integrati" in sources.complete_requirements({},keys)[sources.ELECTRIC_PRICE]["reason"]


def test_reject_real_regression_gas_value_relabelled_as_electricity():
    public={
        sources.PRICE:{"status":"available","unit":"€/MWh","value":88.3585},
        sources.ACER:{"status":"available","unit":"€/MWh","values":{"eu":{"status":"available","value":86.598}}},
    }
    refs=["src:"+key for key in public]
    def check(answer):
        verify_measurements([{"text":answer,"references":refs}],{},model_context(public))
    with pytest.raises(InvalidSynthesis,match="Prezzo elettrico"):
        check("Il prezzo medio dell'energia elettrica all'ingrosso in Italia per il mese di ottobre 2026 è 88,36 €/MWh; il prezzo del GNL a livello UE è 86,60 €/MWh.")
    with pytest.raises(InvalidSynthesis,match="Prezzo elettrico"):
        check("88,36 €/MWh è il prezzo elettrico.")
    with pytest.raises(InvalidSynthesis,match="PSV"):
        check("Per approfondire il costo giornaliero dell'elettricità occorre accedere a dataset con granularità oraria (es. prezzi spot PSV).")
    check("Prezzo elettrico non disponibile. CMEM,m del gas: 88,36 €/MWh. Prezzo GNL UE: 86,60 €/MWh.")


def test_electricity_only_gap_returns_without_acquisition_or_model_call(monkeypatch):
    from gasops_app import session
    monkeypatch.setattr(session,"assistant_reasoner",lambda:SimpleNamespace())
    monkeypatch.setattr(session,"_collect_assistant_sources",lambda *a,**k:pytest.fail("No unrelated sources"))
    monkeypatch.setattr(session,"automatic_selection",lambda *a,**k:pytest.fail("No unrelated base series"))
    app=AppTest.from_string("""
from gasops_app.session import launch
launch(None,"Prezzo medio dell'energia elettrica ottobre 2026",ai_policy="automatic")
""").run()
    assert not app.exception
    report=app.session_state["last_run"]
    assert report.mode=="Deterministic" and not report.ai_usage
    assert set(report.assumptions["public_operational_context"])=={sources.ELECTRIC_PRICE}


@pytest.mark.parametrize("command",["/scorte","/consumi","/gnl","/prezzi","/produzione","/mase","/avvisi","/igi"])
def test_fast_commands_are_readouts_only(command):
    assert sources.fast_lookup_command(command)
    assert not sources.expand_command(command)[1]
    assert not sources.fast_lookup_command(command+" 20/11/2026")
    assert not sources.fast_lookup_command("/bollettino")
    assert not sources.fast_lookup_command("/previsioni")


def test_fast_storage_readout_does_not_call_model(monkeypatch):
    from gasops_app import session
    monkeypatch.setattr(session,"assistant_reasoner",lambda:SimpleNamespace())
    calls=[]
    def collect(*args,**kwargs):
        calls.append(args[2])
        return {"AGSI+":{"status":"available","source":"AGSI+","scope":"IT","gas_day":"2026-11-21",
                         "values":{"stock_twh":70}}}
    monkeypatch.setattr(session,"_collect_assistant_sources",collect)
    app=AppTest.from_string("""
from gasops_app.session import launch
launch(None,"/scorte",ai_policy="automatic")
""").run()
    assert not app.exception and calls==[("AGSI+",)]
    report=app.session_state["last_run"]
    assert report.assumptions["assistant_fast_lookup"]
    assert report.mode=="Deterministic" and not report.ai_usage


def test_pdf_candidates_are_ranked_across_archives_before_truncation(monkeypatch):
    weaker=Citation(document="a.pdf",page=1,evidence="La garanzia è prevista.")
    stronger=Citation(document="b.pdf",page=3,evidence="La garanzia economica richiede un deposito cauzionale.")
    monkeypatch.setattr("gasops_app.document_desk.search",lambda docs,*a,**k:docs)
    hits=assistant_lookup.ranked_document_hits([[weaker],[stronger,stronger]],
                "garanzia economica deposito cauzionale",1)
    assert hits==[stronger]
