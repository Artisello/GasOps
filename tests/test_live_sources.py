from datetime import datetime,timezone,timedelta
import pandas as pd
from gasops_app import live_sources as ls

NOW=datetime(2026,11,18,12,tzinfo=timezone.utc)


def test_refresh_is_independent_preserves_prior_and_throttles(monkeypatch):
    state={"AGSI+_IT":{"result":{"scope":"IT","frame":pd.DataFrame({"stock_twh":[1]})}}}
    calls=[]
    def fail(*a,**k):
        calls.append("agsi")
        raise ValueError("fixture failure")
    def alsi(*a,**k):
        calls.append("alsi")
        return {"scope":"IT","frame":pd.DataFrame({"inventory_gwh":[1]}),"failed":False}
    monkeypatch.setattr(ls,"load_agsi",fail)
    monkeypatch.setattr(ls,"load_alsi",alsi)
    assert ls.refresh(state,None,NOW,["agsi","alsi"],gie="fixture",clock=lambda:NOW)
    assert state["AGSI+_IT"]["result"]["frame"].iloc[0,0]==1
    assert state["ALSI_IT"]["result"]["frame"].iloc[0,0]==1
    assert state[ls.STATUS]["sources"]["agsi"]["status"]=="Da aggiornare"
    assert not ls.refresh(state,None,NOW+timedelta(seconds=1),["alsi"],gie="fixture",clock=lambda:NOW)
    assert calls==["agsi","alsi"]


def test_no_implicit_source_or_demo(monkeypatch):
    from streamlit.testing.v1 import AppTest
    from gasops_app import live_sources_page as page
    monkeypatch.setattr(page,"configured_key",lambda:None)
    monkeypatch.setattr(page,"credentials",lambda *args:(None,None))
    monkeypatch.setattr(page,"refresh",lambda *args,**kwargs: (_ for _ in ()).throw(AssertionError("Unexpected network")))
    app=AppTest.from_string("from gasops_app.live_sources_page import controls\ncontrols('fixture')").run()
    assert not app.exception
    assert not app.button(key="fixture_live_refresh").disabled
    assert ls.STATUS not in app.session_state
    assert not app.checkbox
    app.multiselect(key="fixture_live_sources").set_value([]).run()
    assert app.button(key="fixture_live_refresh").disabled
    assert ls.STATUS not in app.session_state


def test_refresh_one_click(monkeypatch):
    from streamlit.testing.v1 import AppTest
    from gasops_app import live_sources_page as page
    monkeypatch.setattr(page,"configured_key",lambda:None)
    monkeypatch.setattr(page,"credentials",lambda *args:(None,None))
    monkeypatch.setattr(page,"database",lambda:None)
    calls=[]
    def refresh(state,store,now,selected,**kwargs):
        calls.append(tuple(selected))
        return True
    monkeypatch.setattr(page,"refresh",refresh)
    app=AppTest.from_string("from gasops_app.live_sources_page import controls\ncontrols('fixture')").run()
    assert not app.exception and not calls
    app.multiselect(key="fixture_live_sources").set_value(["monthly"]).run()
    assert not calls
    app.button(key="fixture_live_refresh").click().run()
    assert not app.exception and calls==[("monthly",)]
