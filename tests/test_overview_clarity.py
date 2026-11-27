"""Italian controls and progressive detail without losing evidence or picking identity."""
from datetime import date,datetime,timezone
import json

import pytest
import requests
from streamlit.testing.v1 import AppTest

from gasops_app.system_status_page import ARCHIVE_KEY
from gasops_app import italian_network_page as view,session
from gasops_app.italian_network_map import deck

SCRIPT="from gasops_app.italian_network_page import overview_panel\noverview_panel()"


@pytest.fixture
def offline(monkeypatch,tmp_path):
    monkeypatch.setenv("GASOPS_STATE_DIR",str(tmp_path))
    monkeypatch.setattr(session,"_configuration",lambda:None)
    monkeypatch.setattr(view,"utc_now",lambda:datetime(2026,11,23,12,tzinfo=timezone.utc))
    def forbidden(*a,**kw):raise AssertionError("Overview interaction must remain offline")
    monkeypatch.setattr(requests.Session,"request",forbidden)
    monkeypatch.setattr(requests,"get",forbidden)


@pytest.mark.parametrize("archive",[False,True])
def test_italian_mode_labels_preserve_valid_selection_day_and_marker_identity(offline,archive):
    app=AppTest.from_string(SCRIPT,default_timeout=30)
    app.session_state[ARCHIVE_KEY]=archive
    app.run()
    assert not app.exception

    def scene():
        charts=app.get("deck_gl_json_chart")
        assert len(charts)==1
        layers={layer["id"]:layer for layer in json.loads(charts[0].proto.json)["layers"]}
        points=layers["infrastructure-points"]["data"]
        links=layers.get("pipeline-hit-targets",{})
        eligible={r["infra_id"] for r in points if r["active"]}
        if links.get("pickable"):
            eligible.update(f["properties"]["infra_id"] for f in links["data"]["features"])
        return points,eligible

    points,_=scene()
    identities=[(r["infra_id"],r["position"]) for r in points]
    day=app.date_input(key="system_status_gas_day").value
    for mode in ("FLOW","ATTENTION","SYSTEM"):
        previous=app.session_state[view.SELECTED]
        app.radio(key="net_reading_overview").set_value(mode).run()
        assert not app.exception
        assert app.radio(key="net_reading_overview").options==["Sistema","Flussi","Attenzione"]
        assert app.session_state[view.READING]==mode
        assert app.date_input(key="system_status_gas_day").value==day
        points,eligible=scene()
        selected=app.session_state[view.SELECTED]
        assert [(r["infra_id"],r["position"]) for r in points]==identities
        assert app.selectbox(key="net_overview_infrastructure").value==selected
        if previous in eligible:
            assert selected==previous
        elif eligible:
            assert selected in eligible
        else:
            assert selected is None
            assert not app.tabs
        if mode=="FLOW" and not archive:
            # Cold offline data must not silently fall back to bundled evidence.
            assert not eligible and selected is None
        if mode in ("FLOW","ATTENTION") and selected is not None:
            assert any(r["infra_id"]==selected and r["active"] for r in points)
        assert all(r["hit_radius"]==0 for r in points if not r["active"])


def test_secondary_evidence_is_collapsed_but_complete_and_exportable(offline):
    app=AppTest.from_string(SCRIPT,default_timeout=30)
    app.session_state[ARCHIVE_KEY] = True
    app.run()
    assert not app.exception
    secondary=[e for e in app.expander if e.label.startswith(("Bilancio giornaliero ·","Qualità delle fonti ·"))
               or e.label=="Capacità e dati commerciali"]
    assert len(secondary)==3 and all(not e.proto.expanded for e in secondary)
    assert sum(h.proto.body.count('class="gas-balance-cell"') for h in app.get("html"))==9
    assert any("Bilancio non riconciliabile" in c.value for c in app.caption)
    commercial=next(d.value for d in app.dataframe if "Periodo e validità" in d.value.columns)
    assert "Capacità tecnica firm" in set(commercial.Indicatore) and {"Valore","Unità"}<=set(commercial)
    assert app.get("download_button") and [t.label for t in app.tabs]==["Dati","Storico","Eventi","Fonti"]


def test_wider_targets_do_not_duplicate_markers_or_enable_hidden_objects():
    network,boundary,_=view.assets()
    visible=tuple(i for i in network.infrastructure if i.category in ("entry","lng","pipeline"))
    spec=json.loads(deck(network,boundary,visible,"INET_BP_65",stable_picking=True).to_json())
    layers={l["id"]:l for l in spec["layers"]}
    points=layers["infrastructure-points"]["data"]
    assert len(points)==len({r["infra_id"] for r in points})
    active=[r for r in points if r["active"]]
    assert all(r["hit_radius"]==0 for r in points if not r["active"])
    assert all(r["hit_radius"]>=r["icon_size"]/2+3 for r in active)
    assert len(active)==len(layers["category-symbols"]["data"]["features"])
    geometry={g.infrastructure_id:g.geometry["coordinates"] for g in network.geography}
    assert all(r["position"]==geometry[r["infra_id"]] for r in points)
    assert layers["infrastructure-points"]["getFillColor"][-1]==1
    assert not layers["category-symbols"]["pickable"]


def test_hover_values_are_readable_lines_instead_of_html_fragments():
    network,boundary,snapshots=view.assets()
    observations=view.merge_observations(snapshots)
    info=view.point_intelligence(network,"INET_BP_65",observations,date(2026,11,20),
        datetime(2026,11,23,12,tzinfo=timezone.utc),snapshots=snapshots)
    scene=deck(network,boundary,network.infrastructure,"INET_BP_65",day=date(2026,11,20),
        intelligence={"INET_BP_65":info})
    spec=json.loads(scene.to_json())
    points=next(l["data"] for l in spec["layers"] if l["id"]=="infrastructure-points")
    text=next(p["safe_value"] for p in points if p["infra_id"]=="INET_BP_65")
    assert "\n" in text and "GWh/d" in text and "<br" not in text
