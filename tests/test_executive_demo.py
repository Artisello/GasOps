from streamlit.testing.v1 import AppTest
from gasops_app.executive_demo import benchmark,operational_case,STUDY


def test_demo_calculations_from_existing_sources():
    it,changes=benchmark()
    assert float(it["imbalance_share"])==7.4
    assert float(it["net_adjusted_neutrality"])==0.03
    assert float(it["tso_buy_share"])==48
    o,b,s=operational_case()
    assert o["on_time_pct"]==60
    assert b["observed"]==16 and b["expected"]==17
    assert s["eligible"]==30 and s["expected"]==30


def test_demo_switches_offline_and_keeps_import_state(monkeypatch):
    import requests
    def forbid(*args,**kwargs):
        raise AssertionError("Executive demo contacted provider")
    monkeypatch.setattr(requests,"request",forbid)
    monkeypatch.setattr(requests,"get",forbid)
    monkeypatch.setattr(requests,"post",forbid)
    app=AppTest.from_string("from gasops_app.bso_kpi_page import page\npage()",default_timeout=30).run()
    assert not app.exception
    app.radio(key="bso_view").set_value("Executive demo").run()
    assert not app.exception
    assert app.radio(key="executive_stage").value=="Contesto"
    assert app.button(key="executive_prev").disabled
    assert any("7,4" in x.proto.body for x in app.get("html"))
    app.button(key="executive_next").click().run()
    assert not app.exception
    assert any("SIMULAZIONE" in w.value for w in app.warning)
    app.button(key="executive_next").click().run()
    assert not app.exception
    app.button(key="executive_run").click().run()
    assert not app.exception
    assert not app.error
    assert app.session_state[STUDY]["result"]["test_n"]>=14
    app.button(key="executive_next").click().run()
    assert not app.exception and app.button(key="executive_next").disabled
    app.radio(key="bso_view").set_value("Panoramica").run()
    assert not app.exception
    assert app.dataframe[0].value["Valore"].isna().all()
