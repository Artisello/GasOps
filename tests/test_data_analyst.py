from datetime import datetime,timezone
import json
import pandas as pd
import pytest
from gasops_app.data_analyst import catalog,unique_series,Series,analyse,can_share,evidence_ids,forecast_facts
from gasops_app.llm import CompatibleReasoner,LLMConfig

NOW=datetime(2026,11,18,12,tzinfo=timezone.utc)


def test_real_bundled_catalog_and_empty_overlap():
    c,issues=catalog({},NOW)
    assert "jrc_demand_gwh" in c and "acer_eu" in c and "mase_production" in c
    assert not issues
    result=analyse(c,["jrc_demand_gwh","acer_eu"],"2000-01-01","2026-11-18")
    assert len(result["series"])==2 and not result["correlations"]
    assert result["series"][0]["n"]>2500
    assert result["series"][1]["n"]==19


def test_exact_dates_conflicts_and_no_shared_restricted_source():
    dates=pd.date_range("2026-09-01",periods=20).strftime("%Y-%m-%d")
    raw=list(zip(dates,range(20)))+[(dates[0],999)]
    s=unique_series(raw)
    assert len(s)==19 and dates[0] not in s
    a=Series("a","Gas","GWh","gas_day","SRG","fixture","","test","sha",s)
    b=Series("b","Power","GWh","gas_day","IT","fixture","","test","sha",s*2,False)
    out=analyse({"a":a,"b":b},["a","b"],"2026-09-01","2026-09-30")
    assert out["correlations"][0]["pearson"]==pytest.approx(1)
    assert not can_share({"a":a,"b":b},["a","b"])
    assert out["series"][0]["first"]==dates[1]


def test_model_rejects_invented_evidence(monkeypatch):
    m=CompatibleReasoner(LLMConfig("fixture","http://localhost:11434/v1"))
    data={"series":[{"id":"a","value":1}]}
    monkeypatch.setattr(m,"_chat",lambda *a,**k:{"content":json.dumps({"interpretation":"Test","references":["invented"]})})
    with pytest.raises(ValueError):
        m.interpret_dataset("Domanda",data,evidence_ids(data))
    monkeypatch.setattr(m,"_chat",lambda *a,**k:{"content":json.dumps({"interpretation":"Test a","references":["a"]})})
    assert m.interpret_dataset("Domanda",data,evidence_ids(data))==("Test a",["a"])


def test_no_stale_forecast_without_matching_annual():
    assert forecast_facts({"snam_forecast_result_v1":{"hashes":[(2026,"a")]}})==[]


def test_analyst_no_model_no_network(monkeypatch):
    import requests
    from streamlit.testing.v1 import AppTest
    from gasops_app import data_analyst_page
    monkeypatch.setattr(data_analyst_page,"reasoner",lambda:None)
    def forbidden(*a,**k):raise AssertionError("Unexpected network")
    monkeypatch.setattr(requests.Session,"request",forbidden)
    app=AppTest.from_string("from gasops_app.data_analyst_page import panel\npanel()",default_timeout=30).run()
    assert not app.exception
    app.button(key="analyst_run").click().run()
    assert not app.exception and not app.error
    assert app.session_state[data_analyst_page.STATE]["payload"]["series"]
    assert app.session_state[data_analyst_page.STATE]["answer"] is None


def test_native_coefficients_not_mixed_or_shared():
    f=pd.DataFrame([
        {"family":"wkr","edition":"Consuntivo","metric":"Zona 11","unit":"coefficiente (come pubblicato)","value":"1.1","gas_day":"2026-11-16","sha256":"a"*64},
        {"family":"wkr","edition":"Previsione","metric":"Zona 11","unit":"coefficiente (come pubblicato)","value":"1.2","gas_day":"2026-11-16","sha256":"b"*64}])
    c,_=catalog({"jarvis_native_v1":{"frame":f}},NOW)
    keys=[k for k in c if k.startswith("jarvis_coef_")]
    assert len(keys)==2 and not can_share(c,keys)
    r=analyse(c,keys,"2026-11-01","2026-11-18")
    assert not r["correlations"] and {x["last_value"] for x in r["series"]}=={1.1,1.2}
