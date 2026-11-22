import numpy as np
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from gasops_app.forecast import BAYESIAN, BacktestPoint, Forecast
from gasops_app.visuals import ROSE, TEAL, error_chart


def test_forecast_residual_cues_preserve_values_dates_and_zero():
    dates=pd.date_range("2026-11-01",periods=3)
    residuals=[-2.,0.,3.]
    forecast=Forecast(model=BAYESIAN,backtest=[
        BacktestPoint(period=day.date().isoformat(),train_end="2026-10-31",actual=100+value,estimate=100)
        for day,value in zip(dates,residuals)
    ])
    fig=error_chart(forecast,"daily")
    bars=fig.data[0]
    assert list(bars.x)==list(dates)
    np.testing.assert_array_equal(bars.y,residuals)
    assert list(bars.marker.color)==[ROSE,TEAL,TEAL]
    assert list(bars.marker.pattern.shape)==["/","",""]
    assert "Osservato − previsione" in bars.hovertemplate
    assert fig.layout.yaxis.title.text=="GWh"
    assert fig.layout.shapes[0].y0==fig.layout.shapes[0].y1==0


def test_deficit_histogram_cues_preserve_simulation_frequencies(monkeypatch):
    from gasops_app import risk_page
    from gasops_app.risk_view import gap_distribution

    figures={}
    monkeypatch.setattr(risk_page,"plot",lambda figure,key:figures.update({key:figure}))
    app=AppTest.from_string("from gasops_app.risk_page import risk_page\nrisk_page(auto_demo=True)",default_timeout=30).run()
    assert not app.exception
    result=app.session_state["risk_workspace_v2"]["result"]
    expected=gap_distribution(result.gap)
    fig=figures["risk_gap_distribution"]
    assert [trace.name for trace in fig.data]==["Carenza","Saldo ≥ 0"]
    for trace,mask,pattern in zip(fig.data,[expected["negative"],~expected["negative"]],["/",""]):
        np.testing.assert_array_equal(trace.x,expected["center"][mask])
        np.testing.assert_array_equal(trace.y,expected["pct"][mask])
        np.testing.assert_array_equal(trace.width,expected["width"][mask])
        assert trace.marker.pattern.shape==pattern
    assert sum(sum(trace.y) for trace in fig.data)==pytest.approx(100)
    assert fig.layout.xaxis.title.text=="Offerta − domanda (GWh/giorno gas)"
    assert fig.layout.yaxis.title.text=="% delle simulazioni"
