from datetime import date,datetime,timezone,timedelta
from decimal import Decimal as D
import pandas as pd
import pytest
from gasops_app import linepack as m
from gasops_app.intraday import gas_end

DAY=date(2026,11,17)
NOW=gas_end(DAY)+timedelta(hours=1)


def fixture(day,offsets,values):
    start=gas_end(day-timedelta(days=1))
    return pd.DataFrame({"gas_day":[day]*len(offsets),
                         "published_at":[start+timedelta(hours=i) for i in offsets],
                         "expected_linepack_gwh":values})


def test_revisions_never_fill_missing_or_infer_physical_delta():
    f=fixture(DAY,[0,1,3,4,5],[100,90,None,110,105])
    r=m.revisions(f,DAY,NOW)
    assert r["complete_hours"]==24 and r["covered_hours"]==4
    assert r["range_gwh"]==20 and r["largest_revision"]["revision_gwh"]==-10
    assert [x["revision_gwh"] for x in r["rows"]]==[None,-10,None,None,-5]
    assert r["historical"] and r["latest"]["expected_gwh"]==105


def test_revisions_as_of_and_last_missing():
    f=fixture(DAY,[0,1,2,3],[100,99,None,105])
    now=gas_end(DAY-timedelta(days=1))+timedelta(hours=2,minutes=30)
    r=m.revisions(f,DAY,now)
    assert r["latest"]["expected_gwh"] is None and r["last_valid"]["expected_gwh"]==99
    assert r["complete_hours"]==2 and r["covered_hours"]==2
    assert len(r["rows"])==3 and not r["historical"]


@pytest.mark.parametrize("day,hours",[(date(2026,3,28),23),(date(2026,10,24),25)])
def test_dst_distinct_hours(day,hours):
    f=fixture(day,list(range(hours)),[100]*hours)
    r=m.revisions(f,day,gas_end(day))
    assert r["complete_hours"]==hours and r["covered_hours"]==hours


def test_physical_delta_independent_and_stage():
    r=m.physical_delta(DAY,NOW,D(100),D(90),D(-10))
    assert r["delta"]==-10 and r["difference"]==0
    assert m.physical_delta(DAY,NOW,D(100),D(90))["status"]=="Solo calcolo"
    assert m.physical_delta(DAY,NOW,D(100),D(90),D(-9))["status"]=="Da verificare"
    with pytest.raises(ValueError):m.physical_delta(DAY,gas_end(DAY)-timedelta(seconds=1),D(100),D(90))
    with pytest.raises(ValueError):m.physical_delta(DAY,NOW,D(-1),D(90))
    assert m.balance_candidates([{"gas_day":DAY.isoformat(),"stage":"definitive","delta_LPC":D(-10)},
                                 {"gas_day":DAY.isoformat(),"stage":"provisional","delta_LPC":D(-9)}],DAY)=={"definitive":D(-10),"provisional":D(-9)}


def test_linepack_page_offline():
    from streamlit.testing.v1 import AppTest
    app=AppTest.from_string("import streamlit as st\nfrom gasops_app.linepack_page import panel\npanel(*st.session_state['fixture'])")
    app.session_state["fixture"]=(fixture(DAY,[0,1,2],[100,90,95]),DAY,NOW,"test")
    app.run()
    assert not app.exception
    assert len(app.get("plotly_chart"))==1
    assert any("Linepack atteso" in x.proto.body for x in app.get("html"))


def test_physical_panel_defaults_empty():
    from streamlit.testing.v1 import AppTest
    app=AppTest.from_string("from gasops_app.linepack_page import physical_panel\nfrom gasops_app.models import utc_now\nphysical_panel(utc_now(),'test')").run()
    assert not app.exception
    assert app.number_input(key="test_lpc_open").value is None
    assert app.number_input(key="test_lpc_close").value is None
    app.number_input(key="test_lpc_open").set_value(100.)
    app.number_input(key="test_lpc_close").set_value(90.).run()
    assert not app.exception
    assert any("ΔLPC ricostruito" in x.proto.body and "Solo calcolo" in x.proto.body for x in app.get("html"))
