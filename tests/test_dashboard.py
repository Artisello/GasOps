from pathlib import Path

from streamlit.testing.v1 import AppTest


def test_overview_button_completes_offline_run(monkeypatch, tmp_path):
    monkeypatch.setenv("GASOPS_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("GASOPS_PDF_DIR", str(tmp_path))
    monkeypatch.setenv("GASOPS_LLM_MODEL", "")
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / "app.py", default_timeout=30).run()
    assert not app.exception
    assert app.title[0].value == "Market overview"
    app.button(key="analysis_launch").click().run()
    assert not app.exception
    report = app.session_state["last_run"]
    assert report.finished_at and len(report.results) == 6
