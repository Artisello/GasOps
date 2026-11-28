from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("mode", ["", "demo", "unknown"])
def test_default_mode_exposes_operational_features_without_demo_workspace(monkeypatch, mode):
    monkeypatch.setenv("GASOPS_APP_MODE", mode)
    app = AppTest.from_file(ROOT / "app.py", default_timeout=30).run()
    assert not app.exception and app.title[0].value == "I.G.O.R. - Sistema Gas Italiano"
    assert len(app.get("page_link")) == 10
    assert "demo" not in {link.proto.page for link in app.get("page_link")}
    assert not any(r.key == "demo_view" for r in app.radio)
    assert not app.get("file_uploader") and not app.sidebar.selectbox


def test_retired_demo_selection_migrates_to_operational_indicators():
    app = AppTest.from_string("from gasops_app.bso_kpi_page import page\npage()", default_timeout=30)
    app.session_state["bso_view"] = "Executive demo"
    app.run()
    assert not app.exception
    assert app.radio(key="bso_view").value == "Panoramica"
    assert "Esempio completo" not in app.radio(key="bso_view").options
