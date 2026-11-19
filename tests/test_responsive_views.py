from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
from gasops_app.source_session_cache import recent_source,remember_source,forget_source


def test_render_reuse_keeps_warnings_and_source_timestamp():
    now=datetime(2026,11,19,1,tzinfo=timezone.utc)
    bundle=SimpleNamespace(origin=SimpleNamespace(refresh_failed=False,retrieved_at=now-timedelta(hours=1)))
    state={}
    remember_source(state,"monthly",bundle,"Copertura parziale",now)
    same=recent_source(state,"monthly",now+timedelta(seconds=59),bundle)
    assert same==(bundle,"Copertura parziale")
    assert same[0].origin.retrieved_at==now-timedelta(hours=1)
    assert recent_source(state,"monthly",now+timedelta(seconds=60),bundle) is None
    assert recent_source(state,"daily",now,None) is None
    assert recent_source(state,"monthly",now-timedelta(seconds=1),bundle) is None
    assert recent_source(state,"monthly",now,SimpleNamespace()) is None
    assert recent_source({},"monthly",now,bundle) is None
    forget_source(state,"monthly")
    assert recent_source(state,"monthly",now,bundle) is None


def test_never_memoize_failed_refresh():
    now=datetime(2026,11,19,1,tzinfo=timezone.utc)
    failed=SimpleNamespace(origin=SimpleNamespace(refresh_failed=True))
    state={}
    remember_source(state,"daily",failed,"Errore",now)
    assert recent_source(state,"daily",now,None) is None


def test_balancing_inactive_panels_not_executed(monkeypatch):
    from streamlit.testing.v1 import AppTest
    from gasops_app import workbench
    calls=[]
    def scenario():calls.append("scenario")
    def participant():calls.append("participant")
    monkeypatch.setattr(workbench,"_scenario_panel",scenario)
    monkeypatch.setattr(workbench,"_settlement_panel",participant)
    app=AppTest.from_string("from gasops_app.workbench import balancing\nbalancing()").run()
    assert not app.exception and calls==["scenario"]
    app.radio(key="balancing_view").set_value("Sbilanciamento del partecipante").run()
    assert not app.exception and calls==["scenario","participant"]


def test_market_inactive_charts_not_executed(monkeypatch):
    from streamlit.testing.v1 import AppTest
    from gasops_app import dashboard
    from gasops_app.session import DEMO
    def forbidden(*args,**kwargs):
        raise AssertionError("Invisible tab must not render supporting charts")
    monkeypatch.setattr(dashboard,"_supporting_charts",forbidden)
    app=AppTest.from_string("from gasops_app.dashboard import market\nmarket()",default_timeout=30)
    app.session_state["selected_source"]=DEMO
    app.run()
    assert not app.exception
    assert app.radio(key="market_section").value=="Consumi e previsioni"
