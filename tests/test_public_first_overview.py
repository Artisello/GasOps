from datetime import datetime,timezone
import pandas as pd
from gasops_app.advanced_kpis import latest_power_scores,native_balance_scores
from streamlit.testing.v1 import AppTest

NOW=datetime(2026,11,18,14,tzinfo=timezone.utc)


def power_fixture():
    return {"power":{"acquired":"2026-11-18T09:00:00+00:00","rows":[
        {"gas_day":"2026-11-16","metric":"Thermal","gwh":351,"valid_slots":24,"expected_slots":24},
        {"gas_day":"2026-11-17","metric":"Thermal","gwh":999,"valid_slots":23,"expected_slots":24},
        {"gas_day":"2026-11-16","metric":"load","gwh":801,"valid_slots":96,"expected_slots":96},
        {"gas_day":"2026-11-17","metric":"load_forecast","gwh":999,"valid_slots":96,"expected_slots":96}]}}


def balance_fixture():
    rows=[("2026-10-01","provvisorio","100"),("2026-10-01","definitivo","102"),
          ("2026-10-02","provvisorio","110"),("2026-10-02","definitivo","111"),
          ("2026-10-02","definitivo","112"),("2026-11-01","provvisorio","130"),
          ("2026-11-19","definitivo","999")]
    return {"frame":pd.DataFrame([dict(gas_day=d,edition=e,value=v,family="bilanci",unit="GWh",metric="Totale Prelevato",sha256="a"*64) for d,e,v in rows])}


def test_terna_complete_observed_only():
    rows={r.code:r for r in latest_power_scores(power_fixture(),NOW)}
    assert rows["terna_thermal_day"].value==351
    assert rows["terna_load_day"].value==801
    assert all(r.period=="2026-11-16" and r.unit=="GWh elettrici" for r in rows.values())
    assert latest_power_scores(None,NOW)==[]


def test_native_balance_no_arbitrary_revision_selection():
    rows={r.code:r for r in native_balance_scores(balance_fixture(),NOW)}
    assert rows["native_final"].value==102 and rows["native_final"].period=="2026-10-01"
    assert rows["native_provisional"].value==130
    assert rows["native_revision"].value==2 and rows["native_revision"].period=="2026-10"
    assert "1 giorni" in rows["native_revision"].coverage
    assert all("inferita" in r.status for r in rows.values())


def test_public_overview_populates_without_network(monkeypatch):
    from gasops_app import advanced_kpi_page
    import requests
    def forbidden(*args,**kwargs):
        raise AssertionError("Overview must not call API")
    monkeypatch.setattr(requests.Session,"request",forbidden)
    monkeypatch.setattr(advanced_kpi_page,"utc_now",lambda:NOW)
    app=AppTest.from_string("from gasops_app.advanced_kpi_page import panel\npanel()",default_timeout=30)
    app.session_state["terna_power_v1"]=power_fixture()
    app.session_state["jarvis_native_v1"]=balance_fixture()
    app.run()
    assert not app.exception
    metrics={m.label:m.value for m in app.metric}
    assert metrics["Generazione termoelettrica"]=="351,0 GWh elettrici"
    assert metrics["Prelievi · definitivo"]=="102,0 GWh"
    assert metrics["Sbilanciamenti / volume"]=="7,4 %"
    assert next(t.value for t in app.dataframe if set(t.value.columns)=={"Area","KPI","Valore","Unità","Periodo","Copertura","Stato"})["Valore"].isna().all()
