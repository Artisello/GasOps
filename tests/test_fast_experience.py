from datetime import datetime, timezone
from streamlit.testing.v1 import AppTest

from gasops_app import agents, session
from gasops_app.data import synthetic
from gasops_app.forecast import Forecast, ForecastPoint, MODELS, choose


def result(model, *, empty=False):
    return Forecast(model=model,points=[] if empty else [ForecastPoint(period="2026-11-24",estimate=123)])


def test_reading_market_sections_never_fits_or_fetches(monkeypatch,tmp_path):
    monkeypatch.setenv("GASOPS_STATE_DIR",str(tmp_path))
    monkeypatch.setattr(session,"_configuration",lambda:None)
    def forbidden(*a,**k):raise AssertionError("Unexpected acquisition or model fit while reading")
    monkeypatch.setattr(agents,"forecast",forbidden)
    monkeypatch.setattr("requests.sessions.Session.request",forbidden)
    session.preview.clear()
    app=AppTest.from_string("from gasops_app.dashboard import market\nmarket()",default_timeout=20)
    app.session_state["selected_source"]=session.DEMO
    app.run()
    for section in ("Composizione e prezzi","Meteo","Modelli e dati","Consumi e previsioni"):
        app.radio(key="market_section").set_value(section).run()
        assert not app.exception
    assert app.button(key="market_forecast_calculate").label=="Calcola previsione"
    figure=app.get("plotly_chart")[0].proto.spec
    assert "Consumi osservati" in figure and "Previsione" not in figure


def test_explicit_forecast_is_reused_and_model_change_requires_another_action(monkeypatch,tmp_path):
    monkeypatch.setenv("GASOPS_STATE_DIR",str(tmp_path))
    monkeypatch.setattr(session,"_configuration",lambda:None)
    calls=[]
    def fake(series,grain,model):
        calls.append(model)
        return result(model)
    monkeypatch.setattr(agents,"forecast",fake)
    session.preview.clear()
    app=AppTest.from_string("from gasops_app.dashboard import market\nmarket()",default_timeout=20)
    app.session_state["selected_source"]=session.DEMO
    app.session_state["assumptions"]={"model":"Seasonal naive"}
    app.run()
    assert calls==[] and not app.exception
    app.button(key="market_forecast_calculate").click().run()
    assert calls==["Seasonal naive"] and not app.exception
    assert not any(button.key=="market_forecast_calculate" for button in app.button)
    app.run()
    assert calls==["Seasonal naive"]
    app.selectbox(key="market_model").set_value("Seasonal regression").run()
    assert calls==["Seasonal naive"] and not app.exception
    app.button(key="market_forecast_calculate").click().run()
    assert calls==["Seasonal naive","Seasonal regression"] and not app.exception


def test_manual_model_skips_unused_models_but_keeps_existing_fallback(monkeypatch):
    calls=[]
    def fake(series,grain,model):
        calls.append(model)
        return result(model)
    monkeypatch.setattr(agents,"forecast",fake)
    context=agents.MarketContext(synthetic(),"Seasonal naive",datetime.now(timezone.utc))
    assert context.projection.model=="Seasonal naive" and calls==["Seasonal naive"]
    # Explicit comparison still makes every model available, reusing the selected result.
    assert set(context.projections)==set(MODELS) and len(calls)==len(MODELS)
    calls.clear()
    def missing(series,grain,model):
        calls.append(model)
        return result(model,empty=model=="Seasonal naive")
    monkeypatch.setattr(agents,"forecast",missing)
    other=agents.MarketContext(synthetic(),"Seasonal naive",datetime.now(timezone.utc))
    actual=other.projection
    assert actual==choose(other.projections,other.forecast_scores,other.model)
    assert len(calls)==len(MODELS) and actual.model!="Seasonal naive"


def test_examples_open_the_existing_view_and_preserve_imports(monkeypatch):
    from types import SimpleNamespace
    from gasops_app import presentation
    state={"settlement_desk_csv_v1":{"sha":"existing-import"}}
    opened=[]
    monkeypatch.setattr(presentation.st,"session_state",state)
    monkeypatch.setattr(presentation.st,"Page",lambda *a,**kw:SimpleNamespace(url_path=kw["url_path"]))
    monkeypatch.setattr(presentation.st,"switch_page",lambda page:opened.append(page.url_path))
    presentation._open_example("Settlement")
    assert state[presentation.NAV]=="Settlement" and opened==["demo"]
    assert state["settlement_desk_csv_v1"]=={"sha":"existing-import"}
