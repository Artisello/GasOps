from datetime import datetime,timezone
from decimal import Decimal as D
import pytest
from gasops_app import reconciliation as m

NOW=datetime(2026,7,12,12,tzinfo=timezone.utc)


def source(*lines):
    return m.parse_interface((m.template(m.INTERFACE_FIELDS)+"\n".join(lines)+"\n").encode(),NOW)["rows"]


def test_demo_quantifies_only_comparable_allocations():
    demo=m.interface_demo(NOW)
    rows=m.reconcile_interfaces(demo["transport"]["rows"],demo["operator"]["rows"])
    assert len(rows)==4
    assert rows[0]["expected_transport_mwh"]==D(40000)
    assert rows[0]["delta_mwh"]==0
    assert rows[1]["delta_mwh"]==D(200)
    assert rows[2]["status"]=="VERSIONI NON ALLINEATE" and rows[2]["delta_mwh"] is None
    assert rows[3]["status"]=="ESTRATTO ASSENTE" and rows[3]["delta_mwh"] is None
    assert m.interface_score(rows)==dict(received_keys=4,compared=2,matched=1,differences=1,
                                        unknown=2,absolute_difference_mwh=D(200))


def test_sign_and_period_alignment():
    a=source("U,2026-07-10,HS1,CET_FIXED,B,S1,-8",
             "U,2026-07-10,PIOMBINO,CET_FIXED,B,S2,0")
    b=source("U,2026-07-10,HS1,CET_FIXED,B,H1,8",
             "U,2026-07-10,PIOMBINO,EUROPE_ROME,B,L1,0")
    r=m.reconcile_interfaces(a,b)
    assert r[0]["delta_mwh"]==0 and r[0]["status"]=="QUADRA"
    assert r[1]["status"]=="PERIODO DISCORDANTE" and r[1]["delta_mwh"] is None
    assert m.interface_score(m.reconcile_interfaces((),b))["absolute_difference_mwh"] is None


def test_differences_not_netted_and_tolerance():
    a=source("A,2026-07-10,HS1,CET_FIXED,B,R1,10",
             "B,2026-07-10,HS1,CET_FIXED,B,R2,-10",
             "C,2026-07-10,PIOMBINO,CET_FIXED,B,R3,1.001")
    b=source("A,2026-07-10,HS1,CET_FIXED,B,O1,-8",
             "B,2026-07-10,HS1,CET_FIXED,B,O2,8",
             "C,2026-07-10,PIOMBINO,CET_FIXED,B,O3,1")
    s=m.interface_score(m.reconcile_interfaces(a,b))
    assert s["absolute_difference_mwh"]==D("4.001") and s["matched"]==1


def test_parser_rejects_duplicates_future_bad_units_and_interfaces():
    line="U,2026-07-10,HS1,CET_FIXED,B,R,42"
    for lines in [(line,line),(line.replace("07-10","07-12"),),
                  (line.replace("HS1","PSV"),),(line.replace("42","NaN"),),
                  (line.replace("CET_FIXED","UNKNOWN"),),
                  (line.replace("HS1","PIOMBINO").replace("42","-42"),)]:
        with pytest.raises(ValueError):source(*lines)


def test_interface_desk_offline():
    from streamlit.testing.v1 import AppTest
    from gasops_app import interface_reconciliation_page as page
    app=AppTest.from_string("from gasops_app.interface_reconciliation_page import panel\npanel()").run()
    assert not app.exception
    assert any("Nessun dossier" in e.value for e in app.caption)
    app.button(key="interface_demo").click().run()
    assert not app.exception
    assert app.session_state[page.STATE]["synthetic"]
    assert any("Coppie quadrate" in e.proto.body for e in app.get("html"))
    assert len(app.dataframe[0].value)==3
    app.checkbox(key="interface_only").set_value(False).run()
    assert len(app.dataframe[0].value)==4
    app.selectbox(key="interface_point").set_value("PIOMBINO").run()
    assert not app.exception and len(app.dataframe[0].value)==2
    app.button(key="interface_clear").click().run()
    assert not app.exception and any("Nessun dossier" in e.value for e in app.caption)
