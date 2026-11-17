from pathlib import Path

from streamlit.testing.v1 import AppTest

from gasops_app.public_data import SourceUnavailable
from gasops_app.session import ARCHIVE, DEMO


def test_overview_button_completes_offline_run(monkeypatch, tmp_path):
    monkeypatch.setenv("GASOPS_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("GASOPS_PDF_DIR", str(tmp_path))
    monkeypatch.setenv("GASOPS_LLM_MODEL", "")
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / "app.py", default_timeout=30)
    app.session_state["selected_source"] = DEMO
    app.run()
    assert not app.exception
    assert app.title[0].value == "Panoramica del mercato"
    assert app.button(key="analysis_launch").label == "Avvia analisi di mercato AI"
    app.button(key="analysis_launch").click().run()
    assert not app.exception
    report = app.session_state["last_run"]
    assert report.finished_at and len(report.results) == 6


def test_unavailable_public_feed_can_open_the_real_offline_archive(monkeypatch, tmp_path):
    monkeypatch.setenv("GASOPS_STATE_DIR", str(tmp_path))

    def unavailable(*args, **kwargs):
        raise SourceUnavailable("Eurostat non disponibile")

    monkeypatch.setattr("gasops_app.session.load_monthly", unavailable)
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / "app.py", default_timeout=30).run()
    assert app.error[0].value == "Eurostat non disponibile"
    app.button(key="overview_archive").click().run()
    assert not app.exception
    assert app.selectbox(key="overview_dataset").value == ARCHIVE
    assert app.session_state["active_bundle"].origin.archive
