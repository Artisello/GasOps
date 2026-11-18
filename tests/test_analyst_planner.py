from datetime import date, datetime, timezone
from types import SimpleNamespace
import pandas as pd
import pytest

from gasops_app.analyst_planner import manifest,validate_plan,execute_plan
from gasops_app.data_analyst import Series,evidence_ids

TODAY=date(2026,11,18)
DAYS=pd.date_range("2026-10-01",periods=20).strftime("%Y-%m-%d")


def item(k,scale=1,remote=True):
    return Series(k,k,"GWh/giorno gas","gas_day","SRG","fixture","https://example.com","storico","a"*64,
                  pd.Series([scale*i for i in range(20)],index=DAYS,dtype=float),remote)


def plan(keys,tools,benchmarks=None,forecasts=None):
    return {"series":keys,"tools":tools,"from":"2026-10-01","to":"2026-10-20","benchmarks":benchmarks or [],"forecasts":forecasts or []}


def test_remote_catalog_and_unknown_tool_rejected():
    items={"gas":item("gas"),"private":item("private",remote=False)}
    allowed=manifest(items,[],[],"gas",TODAY,remote=True)
    assert [r["id"] for r in allowed["series"]]==["gas"]
    for wrong in (plan(["private"],["summary"]),plan(["gas"],["exec"]),plan(["gas"],["correlation"])):
        with pytest.raises(ValueError):validate_plan(wrong,allowed,TODAY)
    with pytest.raises(ValueError):validate_plan({**plan(["gas"],["summary"]),"to":"2027-01-01"},allowed,TODAY)


def test_automatic_calculations_and_lineage():
    items={"gas":item("gas"),"power":item("power",2)}
    m=manifest(items,[],[],"trend gas power",TODAY,remote=False)
    p=validate_plan(plan(["gas","power"],["trend","correlation","volatility"]),m,TODAY)
    r=execute_plan(p,items,[],[])
    assert r["correlations"][0]["pearson"]==pytest.approx(1)
    assert r["statistics"][0]["slope_per_calendar_day"]==pytest.approx(1)
    assert len(r["statistics"])==4
    assert "trend_gas" in evidence_ids(r)
    assert r["series"][0]["provenance"]=="a"*64


def test_revision_and_benchmark_only_selection():
    a,b="jarvis_withdrawal_provvisorio","jarvis_withdrawal_definitivo"
    items={a:item(a),b:item(b,2)}
    facts=[{"id":"ba","label":"Benchmark","period":"2025","unit":"%","source":"fixture","value":1},
           {"id":"bb","label":"Other","period":"2025","unit":"%","source":"fixture","value":2}]
    m=manifest(items,facts,[],"rettifiche",TODAY,remote=False)
    p=validate_plan(plan([a,b],["revisions"]),m,TODAY)
    r=execute_plan(p,items,facts,[])
    assert r["statistics"][0]["sum_absolute_deltas"]==190
    p=validate_plan(plan([],["benchmarks"],["ba"]),m,TODAY)
    r=execute_plan(p,items,facts,[])
    assert not r["series"] and [x["id"] for x in r["benchmarks"]]==["ba"]
    assert not validate_plan(plan([],[]),m,TODAY)["tools"]


def test_ui_requires_remote_consent_and_uses_plan(monkeypatch):
    from streamlit.testing.v1 import AppTest
    from gasops_app import autonomous_analyst_page as page
    from gasops_app.llm import LLMConfig
    calls=[]
    class Fake:
        config=LLMConfig("fixture","https://example.com/v1")
        def plan_dataset(self,q,m):
            calls.append("plan")
            assert [x["id"] for x in m["series"]]==["gas"]
            return plan(["gas"],["trend"])
        def interpret_dataset(self,q,r,ids):
            calls.append("interpret")
            assert "trend_gas" in ids
            return "Trend descrittivo: trend_gas.",["trend_gas"]
    monkeypatch.setattr(page,"reference_facts",lambda:[])
    def forecasts(state,*,include_restricted=False):
        # Remote evidence must never include restricted sources.
        assert include_restricted is False
        return []
    monkeypatch.setattr(page,"forecast_facts",forecasts)
    app=AppTest.from_string("import streamlit as st\nfrom gasops_app.autonomous_analyst_page import panel\npanel(*st.session_state['fixture'])")
    app.session_state["fixture"]=({"gas":item("gas"),"private":item("private",remote=False)},Fake(),datetime(2026,11,18,12,tzinfo=timezone.utc))
    app.run()
    app.text_area(key="auto_analyst_question").set_value("Trend del gas").run()
    assert app.button(key="auto_analyst_run").disabled and not calls
    app.checkbox(key="auto_analyst_consent").check().run()
    app.button(key="auto_analyst_run").click().run()
    assert not app.exception and not app.error
    assert calls==["plan","interpret"]
    assert app.session_state[page.STATE]["refs"]==["trend_gas"]
