from copy import deepcopy
from decimal import Decimal
from pathlib import Path

import numpy as np
import pytest
import requests
from streamlit.testing.v1 import AppTest

from gasops_app import demo_forecast
from gasops_app.demo_cases import briefing, cases
from gasops_app.presentation import NAV, VIEWS

ROOT = Path(__file__).resolve().parents[1]


def test_read_only_default_can_explore_every_view_offline_without_changing_imports(monkeypatch):
    monkeypatch.delenv("GASOPS_APP_MODE", raising=False)
    def forbidden(*args, **kwargs):
        raise AssertionError("La demo non deve contattare provider o aprire la configurazione.")
    monkeypatch.setattr(requests.Session, "request", forbidden)
    monkeypatch.setattr("gasops_app.session.sidebar", forbidden)
    imported = {"sha": "user-evidence", "rows": ["do not overwrite"]}
    app = AppTest.from_file(ROOT / "app.py", default_timeout=30)
    app.session_state["settlement_desk_csv_v1"] = deepcopy(imported)
    app.run()
    assert not app.exception and app.title[0].value == "Il dato diventa una spiegazione."
    assert app.radio(key=NAV).options == list(VIEWS)
    # Direct, non-sequential exploration; results need no run/model/data controls.
    for view in ("Previsioni", "Settlement", "Sviluppi", "Balancing", "Operations", "In sintesi"):
        app.radio(key=NAV).set_value(view).run()
        assert not app.exception and not app.error
        assert not app.get("file_uploader")
        for kind in ("text_input", "text_area", "number_input", "date_input", "selectbox", "checkbox"):
            assert not app.get(kind), (view, kind)
        assert not any(b.label in ("Avanti", "Indietro", "Esegui backtest storico") for b in app.button)
        assert app.session_state["settlement_desk_csv_v1"] == imported
        assert "selected_source" not in app.session_state
        if view == "Previsioni":
            assert len(app.get("plotly_chart")) == 1
            assert any("314" in h.proto.body for h in app.get("html"))
            assert any("67,9%" in h.proto.body for h in app.get("html"))
        if view == "Settlement":
            assert any("-4.200" in h.proto.body for h in app.get("html"))
    assert not app.sidebar.button and not app.sidebar.radio
    app.button(key="demo_open_settlement").click().run()
    assert not app.exception and app.radio(key=NAV).value == "Settlement"


@pytest.mark.parametrize("mode", ["", "demo", "unknown"])
def test_only_explicit_server_workbench_mode_exposes_operational_controls(monkeypatch, mode):
    monkeypatch.setenv("GASOPS_APP_MODE", mode)
    app = AppTest.from_file(ROOT / "app.py", default_timeout=30).run()
    assert not app.exception and app.radio(key=NAV).value == "In sintesi"
    assert not app.get("file_uploader") and not app.sidebar.selectbox


def test_demonstrated_numbers_and_briefing_reconcile_with_shared_engines():
    pack = cases()
    b, r, o = pack["balancing"], pack["revision"], pack["operations"]
    prior, final = pack["versions"]
    assert b["latest"] == 23 and b["delta"] == 8 and b["sign_change_at"].hour == 12
    assert r["delta_cash_eur"] == final.cash - prior.cash == Decimal("-4200.00")
    assert r["quantity_effect_eur"] + r["price_effect_eur"] == r["delta_cash_eur"]
    assert final.imbalance - prior.imbalance == -100 and final.buy == prior.buy == 42
    assert pack["settlement"]["eligible"] == pack["settlement"]["expected"] == 30
    assert pack["settlement"]["revised"] == 1
    assert len(o["overdue"]) == 2 and len(o["upcoming"]) == 3
    text = " ".join(briefing(pack))
    assert "+23 GWh" in text and "-4.200 €" in text and "2 attività scadute" in text


def test_precomputed_public_result_matches_a_fresh_chronological_backtest():
    snapshot, fresh = demo_forecast.load(), demo_forecast.build()
    assert snapshot["source_sha256"] == fresh["source_sha256"]
    assert snapshot["result"]["test_n"] == fresh["result"]["test_n"] == 28
    assert snapshot["result"]["last_observed"] == "2021-12-31"
    for saved, computed in zip(snapshot["result"]["records"], fresh["result"]["records"], strict=True):
        assert saved.keys() == computed.keys()
        for key in saved:
            if isinstance(saved[key], (float, int)):
                assert np.isclose(saved[key], computed[key], rtol=1e-7, atol=1e-7), key
            else:
                assert saved[key] == computed[key]
    for model, score in fresh["result"]["scores"].items():
        for metric, value in score.items():
            assert snapshot["result"]["scores"][model][metric] == pytest.approx(value, rel=1e-7)


def test_stale_precomputed_evidence_is_rejected_and_shown_as_unavailable(monkeypatch):
    monkeypatch.setattr(demo_forecast, "provenance", lambda: {"source_sha256": "changed"})
    with pytest.raises(ValueError, match="rigenerato"):
        demo_forecast.load()
    app = AppTest.from_string("from gasops_app.presentation import page\npage()", default_timeout=30)
    app.session_state[NAV] = "Previsioni"
    app.run()
    assert not app.exception and app.error
    assert not app.get("plotly_chart")
