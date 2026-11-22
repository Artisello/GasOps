"""UI smoke tests for Terna views without real credentials or network."""
from datetime import datetime,date,timezone
from decimal import Decimal
import pandas as pd
from streamlit.testing.v1 import AppTest
from gasops_app import terna_power_page as power,terna_forward_page as forward,terna_context_page as context
from gasops_app import terna_forward,terna_context
from gasops_app.terna_charts import comparison_bars,timeseries
from gasops_app.visuals import TEAL

NOW=datetime(2026,11,18,12,tzinfo=timezone.utc)


def test_bar_labels_and_time_gaps():
    name="Produzione destinata al consumo"
    fig=comparison_bars([(name,Decimal("265.3"),TEAL)],"TWh")
    assert list(fig.data[0].y)==[name]
    assert list(fig.data[0].text)==["265,3 TWh"]
    assert fig.layout.yaxis.automargin and not fig.layout.xaxis.visible
    f=pd.DataFrame({"Carico":[1.,3.]},index=["2026-11-14","2026-11-16"])
    chart=timeseries(f,"GWh elettrici",forecast=True)
    assert len(chart.data[0].x)==3
    assert pd.isna(chart.data[0].y[1])
    assert chart.data[0].mode=="lines+markers" and not chart.data[0].connectgaps
    assert chart.data[0].line.dash=="dash"


def test_terna_annual_is_default_and_navigation_needs_no_credentials(monkeypatch):
    for module in (power,forward,context):
        monkeypatch.setattr(module,"credentials",lambda *args:("",""))
        monkeypatch.setattr(module,"utc_now",lambda:NOW)
    app=AppTest.from_string("from gasops_app.terna_power_page import panel\npanel()").run()
    assert not app.exception
    assert app.radio(key="terna_mode").value=="Statistiche annuali"
    assert len(app.get("plotly_chart"))==3
    assert any("Potenza installata" in e.value for e in app.markdown)
    for mode in ("Giorni gas","Previsioni elettriche","Capacità e industria","Statistiche annuali"):
        app.radio(key="terna_mode").set_value(mode).run()
        assert not app.exception,mode


def test_daily_saved_data_visible_without_credentials(monkeypatch):
    monkeypatch.setattr(power,"credentials",lambda *args:("",""))
    monkeypatch.setattr(power,"utc_now",lambda:NOW)
    app=AppTest.from_string("from gasops_app.terna_power_page import panel\npanel()")
    app.session_state["terna_mode"]="Giorni gas"
    app.session_state[power.STATE]={"power":{"first":date(2026,11,16),"last":date(2026,11,16),
        "acquired":NOW.isoformat(),"warning":None,"rows":[
            {"gas_day":"2026-11-16","metric":"Thermal","gwh":Decimal("300"),"valid_slots":24,"expected_slots":24},
            {"gas_day":"2026-11-16","metric":"load","gwh":Decimal("800"),"valid_slots":96,"expected_slots":96}]},
        "gas":None}
    app.run()
    assert not app.exception
    assert len(app.get("plotly_chart"))==2
    assert any("Confronto ENTSOG non disponibile" in e.value for e in app.caption)


def test_forecast_and_capacity_render_partial_public_snapshots(monkeypatch):
    for module in (forward,context):
        monkeypatch.setattr(module,"credentials",lambda *args:("",""))
        monkeypatch.setattr(module,"utc_now",lambda:NOW)
    app=AppTest.from_string("from gasops_app.terna_power_page import panel\npanel()")
    app.session_state["terna_mode"]="Previsioni elettriche"
    app.session_state[terna_forward.STATE]=[{"acquired":NOW.isoformat(),"first":"2026-11-19","last":"2026-11-19",
        "session":"MSD1","rows":[{"day":"2026-11-19","metric":"load","gwh":168.0,"slots":24,"minutes":60}]}]
    app.session_state[terna_context.STATE]=[terna_context.batch("capacity",[
        {"period":"2026-11-19","scope":["SUD_ISOLE","A2A","TERMOELETTRICO","GAS NATURALE"],"value":350.0,"hours":24}],NOW)]
    app.run()
    assert not app.exception and len(app.get("plotly_chart"))==1
    app.radio(key="terna_mode").set_value("Capacità e industria").run()
    assert not app.exception and len(app.get("plotly_chart"))==1
    assert any("350,00 MW" in m.value for m in app.metric)
