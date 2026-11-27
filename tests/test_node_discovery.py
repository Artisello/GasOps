from dataclasses import replace
from datetime import datetime,timezone

import requests
from streamlit.testing.v1 import AppTest

from gasops_app import italian_network_page as view, session
from gasops_app.node_discovery import audit_nodes, aliases
from gasops_app.system_status_page import ARCHIVE_KEY


def test_bundled_node_catalog_does_not_duplicate_existing_telemetry():
    network,_,_=view.assets()
    report=audit_nodes(network,network.sources["opd"])
    assert report["catalog_rows"]==32
    assert report["operators"]==["IT-TSO-0001"]
    assert len(report["nodes"])==177
    assert sum(n["state"]=="already_mapped" for n in report["nodes"])==9
    assert sum(n["state"]=="no_exact_match" for n in report["nodes"])==168
    assert not any(n["state"] in ("review_required","verified") for n in report["nodes"])
    tarvisio=next(n for n in report["nodes"] if n["name"]=="Tarvisio")
    assert {c["mapped_id"] for c in tarvisio["candidates"]}=={"INET_BP_89"}
    assert {c["direction"] for c in tarvisio["candidates"]}=={"entry","exit"}


def test_new_catalog_match_remains_unverified_and_aggregates_excluded():
    network,_,_=view.assets()
    base={"operatorKey":"IT-TSO-0001","operatorLabel":"Snam","tSOCountry":"IT",
          "isInvalid":False,"directionKey":"entry","hasData":True}
    rows=[dict(base,pointKey="ITP-99999",pointLabel="Alessandria",pointType="Transmission Point"),
          dict(base,pointKey="DIS-99999",pointLabel="Cortemaggiore",pointType="Distribution Point"),
          dict(base,pointKey="ITP-99998",pointLabel="Alessandria Nord",pointType="Transmission Point"),
          dict(base,pointKey="ITP-99997",pointLabel="Gela",isInvalid=True)]
    original=network.bindings
    report=audit_nodes(network,{"rows":rows})
    n=next(n for n in report["nodes"] if n["name"]=="Alessandria")
    assert n["state"]=="review_required"
    assert [c["point"] for c in n["candidates"]]==["ITP-99999"]
    assert not n["candidates"][0]["mapped_id"]
    assert next(n for n in report["nodes"] if n["name"]=="Cortemaggiore")["state"]=="no_exact_match"
    assert network.bindings==original
    assert aliases("Tarvisio (IT) / Arnoldstein (AT)")=={"tarvisio","arnoldstein"}


def test_node_card_has_no_empty_operational_tabs(monkeypatch,tmp_path):
    monkeypatch.setenv("GASOPS_STATE_DIR",str(tmp_path))
    monkeypatch.setattr(session,"_configuration",lambda:None)
    monkeypatch.setattr(view,"utc_now",lambda:datetime(2026,11,23,12,tzinfo=timezone.utc))
    def forbidden(*a,**kw):raise AssertionError("Node card must not request API automatically")
    monkeypatch.setattr(requests.Session,"request",forbidden)
    app=AppTest.from_string("from gasops_app.italian_network_page import overview_panel\noverview_panel()",default_timeout=30)
    app.session_state[ARCHIVE_KEY]=True
    app.session_state[view.SELECTED]="INET_N_1612"
    app.run()
    assert not app.exception
    assert not app.tabs
    assert any("già associati ad altre infrastrutture" in c.value for c in app.caption)
    assert any(e.label=="Identità e geografia" for e in app.expander)
