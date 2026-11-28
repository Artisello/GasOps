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


def test_shared_chart_style_preserves_trace_semantics_and_axis_configuration():
    import plotly.graph_objects as go
    from gasops_app.visuals import CHART_FONT, MUTED, chart_style
    fig=go.Figure([
        go.Scatter(x=["2026-11-01","2026-11-02","2026-11-03"],y=[0,None,20],
                   name="Ingresso",connectgaps=False,line={"color":TEAL,"dash":"solid"},
                   hovertemplate="%{y:.1f} GWh/d"),
        go.Scatter(x=["2026-11-01","2026-11-02","2026-11-03"],y=[5,0,None],
                   name="Uscita",connectgaps=False,line={"color":"#83b4ff","dash":"dot"}),
    ])
    fig.update_layout(height=280,margin={"b":56,"t":32},hovermode="closest",dragmode=False,
                      legend={"orientation":"h","y":1.02},showlegend=True,
                      xaxis={"tickformat":"%d/%m","nticks":4,"fixedrange":True,
                             "range":["2026-10-31","2026-11-04"],"showgrid":False},
                      yaxis={"title":"GWh/d","tickformat":",.1f"})
    traces=[trace.to_plotly_json() for trace in fig.data]
    assert chart_style(fig) is fig
    assert [trace.to_plotly_json() for trace in fig.data]==traces
    assert fig.layout.font.family==CHART_FONT and fig.layout.font.color==MUTED
    assert fig.layout.separators==",."
    assert fig.layout.xaxis.automargin and fig.layout.yaxis.automargin
    assert fig.layout.margin.b==56 and fig.layout.height==280
    assert fig.layout.xaxis.nticks==4 and fig.layout.xaxis.tickformat=="%d/%m"
    assert list(fig.layout.xaxis.range)==["2026-10-31","2026-11-04"]
    assert fig.layout.xaxis.fixedrange and fig.layout.xaxis.showgrid is False
    assert fig.layout.yaxis.title.text=="GWh/d"
    assert fig.layout.legend.y==1.02 and fig.layout.hovermode=="closest"
    assert fig.layout.dragmode is False
    before=fig.to_json()
    chart_style(fig)
    assert fig.to_json()==before


def test_plot_renderer_keeps_read_only_and_interactive_modes(monkeypatch):
    import plotly.graph_objects as go
    from gasops_app import visuals
    calls=[]
    monkeypatch.setattr(visuals.st,"plotly_chart",lambda figure,**kwargs:calls.append((figure,kwargs)))
    for interactive in (True,False):
        fig=go.Figure(go.Bar(x=["A","B"],y=[1,2]))
        visuals.plot(fig,"test",interactive=interactive)
    for (figure,opts),interactive in zip(calls,(True,False)):
        assert figure.layout.separators==",."
        assert list(figure.data[0].y)==[1,2]
        assert opts["key"]=="test" and opts["theme"] is None
        assert opts["config"]["displayModeBar"]==("hover" if interactive else False)
        assert not opts["config"]["displaylogo"]
        assert not opts["config"]["scrollZoom"]
