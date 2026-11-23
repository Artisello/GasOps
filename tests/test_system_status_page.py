"""Offline rendering and navigation through the real Demo and Workbench routes."""
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
import requests
from streamlit.testing.v1 import AppTest

from gasops_app import italian_network_page as view, session
from gasops_app.system_status import build_status
from gasops_app.system_status_page import DAY_KEY, SELECTED_DAY

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026,11,22,12,tzinfo=timezone.utc)


@pytest.fixture
def offline(monkeypatch, tmp_path):
    monkeypatch.setenv("GASOPS_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(session, "_configuration", lambda:None)
    monkeypatch.setattr(view, "utc_now", lambda:NOW)
    def forbidden(*a, **kw):
        raise AssertionError("No API calls during status, date, threshold or map navigation")
    monkeypatch.setattr(requests.Session, "request", forbidden)
    monkeypatch.setattr(requests, "request", forbidden)
    monkeypatch.setattr(requests, "get", forbidden)


@pytest.mark.parametrize("mode", ["demo", "workbench"])
def test_system_status_has_four_kpis_nine_components_and_keeps_demo_separate(offline, monkeypatch, mode):
    monkeypatch.setenv("GASOPS_APP_MODE", mode)
    app = AppTest.from_file(ROOT/"app.py", default_timeout=30).run()
    assert not app.exception
    assert app.title[0].value == "I.G.O.R. — Sistema Gas Italiano"
    bodies = [h.proto.body for h in app.get("html")]
    grid = next(h for h in bodies if 'class="gas-kpi-grid"' in h)
    assert grid.count('class="gas-kpi"')+grid.count('class="gas-kpi gas-kpi-missing"') == 4
    assert sum(h.count('class="gas-balance-cell"') for h in bodies) == 9
    assert app.date_input(key=DAY_KEY).value == date(2026,11,20)
    assert any("2/9 componenti" in c.value for c in app.caption)
    assert any("Indicatori di attenzione calcolati da I.G.O.R." == c.value for c in app.caption)
    assert any("Bilancio non riconciliabile" in c.value for c in app.caption)
    assert len(app.get("deck_gl_json_chart")) == 1
    assert not any(b.key == "net_refresh" for b in app.button)
    if mode == "demo":
        assert any("Prova con un esempio" == s.value for s in app.subheader)
        assert any("separati dai dati pubblici" in c.value for c in app.caption)
    else:
        assert not any("Prova con un esempio" == s.value for s in app.subheader)


def test_finding_opens_verified_point_with_same_day_and_preserves_evidence(offline, monkeypatch):
    monkeypatch.setenv("GASOPS_APP_MODE", "demo")
    n, _, snapshots = view.assets()
    status = build_status(n, snapshots, {}, NOW, interruptions=(view.bundled_interruptions(),))
    finding = next(f for f in status.attention if f.rule == "capacity_utilization")
    app = AppTest.from_file(ROOT/"app.py", default_timeout=30)
    app.session_state["unrelated_evidence"] = {"sha":"keep"}
    app.run()
    app.button(key="system_attention_"+finding.id).click().run()
    assert not app.exception and app.radio(key="operational_platform").value == "MAP"
    assert app.selectbox(key="net_infrastructure").value == finding.infrastructure_id
    assert app.date_input(key="net_period").value == (status.gas_day, status.gas_day)
    assert app.session_state["unrelated_evidence"] == {"sha":"keep"}


def test_selected_day_survives_date_threshold_reruns_and_return_from_map(offline, monkeypatch):
    monkeypatch.setenv("GASOPS_APP_MODE", "demo")
    app = AppTest.from_file(ROOT/"app.py", default_timeout=30).run()
    chosen = date(2026,11,19)
    app.date_input(key=DAY_KEY).set_value(chosen).run()
    assert not app.exception and app.session_state[SELECTED_DAY] == chosen
    app.number_input(key="system_capacity_pct").set_value(99).run()
    assert not app.exception and app.date_input(key=DAY_KEY).value == chosen
    assert not any("utilizzo capacità oltre soglia" in e.label for e in app.expander)
    app.button(key="net_overview_open").click().run()
    assert not app.exception and app.date_input(key="net_period").value[-1] == chosen
    links = {l.proto.page:l.proto.page_script_hash for l in app.get("page_link")}
    app._page_hash = links[""]
    app.run()
    assert not app.exception and app.date_input(key=DAY_KEY).value == chosen


def test_active_day_is_labeled_and_map_drilldown_uses_last_completed_day(offline, monkeypatch):
    monkeypatch.setenv("GASOPS_APP_MODE", "demo")
    app = AppTest.from_file(ROOT/"app.py", default_timeout=30).run()
    app.date_input(key=DAY_KEY).set_value(date(2026,11,22)).run()
    assert not app.exception
    assert any("Giorno gas attivo" in h.proto.body for h in app.get("html"))
    assert any("0/9 componenti" in c.value for c in app.caption)
    app.button(key="net_overview_open").click().run()
    assert not app.exception and app.date_input(key="net_period").value[-1] == date(2026,11,21)
