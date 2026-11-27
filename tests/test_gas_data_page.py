"""Offline UI tests against real routes; optional GIE values are synthetic."""
from datetime import date,datetime,timezone
from pathlib import Path

import pandas as pd
import pytest
import requests
from streamlit.testing.v1 import AppTest

from gasops_app import gas_data_page as page,session,italian_network_page as network_page
from gasops_app import source_health_page
from gasops_app.gas_data import MAP_STATE

ROOT=Path(__file__).resolve().parents[1]
NOW=datetime(2026,11,23,12,tzinfo=timezone.utc)
SCRIPT="from gasops_app.gas_data_page import panel\npanel()"


@pytest.fixture
def offline(monkeypatch,tmp_path):
    monkeypatch.setenv("GASOPS_STATE_DIR",str(tmp_path))
    monkeypatch.setattr(session,"_configuration",lambda:None)
    monkeypatch.setattr(page,"utc_now",lambda:NOW)
    monkeypatch.setattr(source_health_page,"utc_now",lambda:NOW)
    def forbidden(*a,**kw):raise AssertionError("Explorer filters and monitor must stay offline")
    monkeypatch.setattr(requests,"get",forbidden)
    monkeypatch.setattr(requests.Session,"request",forbidden)


def test_opening_view_has_real_data_without_impossible_provider_choices(offline):
    app=AppTest.from_string(SCRIPT,default_timeout=30).run()
    assert not app.exception
    assert app.selectbox(key="gas_explorer_provider").options==["ENTSOG"]
    assert app.selectbox(key="gas_explorer_entity").value=="IT-TSO-0001ITP-00093entry"
    assert app.selectbox(key="gas_explorer_indicator").value==("Physical Flow","GWh/d","gas_day")
    assert len(app.get("plotly_chart"))==1 and len(app.get("download_button"))==1
    assert "664,60" in app.metric[0].value
    assert not any(b.label in ("Carica dati","Aggiorna") for b in app.button)


def test_filters_comparison_period_and_csv_use_the_same_dataset(offline,monkeypatch):
    frames=[]
    charts=[]
    figures=[]
    original=page.attributed_csv
    series=page.timeseries
    def csv(result,**kw):
        frames.append(result["frame"].copy())
        return original(result,**kw)
    def chart(frame,*a,**kw):
        charts.append(frame.copy())
        figure=series(frame,*a,**kw)
        figures.append(figure)
        return figure
    monkeypatch.setattr(page,"attributed_csv",csv)
    monkeypatch.setattr(page,"timeseries",chart)
    app=AppTest.from_string(SCRIPT,default_timeout=30).run()
    app.multiselect(key="gas_explorer_comparison").set_value(["IT-TSO-0001ITP-00040entry"]).run()
    app.date_input(key="gas_explorer_period").set_value((date(2026,11,18),date(2026,11,20))).run()
    assert not app.exception and len(charts[-1].columns)==2
    ticks=figures[-1].layout.xaxis.tickvals
    assert len(ticks)==3 and len({d.strftime("%d/%m") for d in ticks})==len(ticks)
    exported=frames[-1]
    assert len(exported)==6 and exported.gas_day.min()==date(2026,11,18)
    assert exported.unit.unique().tolist()==["GWh/d"]
    assert set(exported.point_direction)=={"IT-TSO-0001ITP-00093entry","IT-TSO-0001ITP-00040entry"}
    table=app.dataframe[0].value
    assert set(table.gas_day)==set(exported.gas_day)
    assert set(table.point_direction)==set(exported.point_direction)
    app.radio(key="gas_explorer_visualization").set_value("Tabella").run()
    assert not app.exception and not app.get("plotly_chart")
    assert len(frames[-1])==6


def test_source_intervals_offer_table_without_misleading_daily_chart(offline):
    app=AppTest.from_string(SCRIPT,default_timeout=30).run()
    app.selectbox(key="gas_explorer_indicator").set_value(("Firm Technical","GWh/d","source_interval")).run()
    assert not app.exception
    assert app.radio(key="gas_explorer_visualization").options==["Tabella"]
    assert not app.get("plotly_chart") and len(app.get("download_button"))==1
    assert "period_from" in app.dataframe[0].value and "source_period_from" in app.dataframe[0].value


def test_interruptions_preserve_published_zero_without_claiming_an_active_event(offline):
    app=AppTest.from_string(SCRIPT,default_timeout=30).run()
    app.selectbox(key="gas_explorer_indicator").set_value(("Interruptions","GWh/d","gas_day")).run()
    assert not app.exception and app.dataframe[0].value.value.eq(0).all()
    assert any("zero non indica un evento attivo" in c.value for c in app.caption)


def test_gie_choices_only_appear_after_real_parsed_series_are_present(offline):
    app=AppTest.from_string(SCRIPT,default_timeout=30)
    day=date(2026,11,22)
    app.session_state["AGSI+_IT"]={"result":{"frame":pd.DataFrame([{"gas_day":day,"stock_twh":90.,"status":"C","review":False}]),
        "scope":"IT","acquired":NOW,"failed":False,"cached":False,"source":"Synthetic GIE fixture","source_url":"https://example.invalid/gie"}}
    app.run()
    assert not app.exception and app.selectbox(key="gas_explorer_provider").options==["ENTSOG","GIE · AGSI+"]
    app.selectbox(key="gas_explorer_provider").set_value("AGSI+").run()
    assert not app.exception and app.selectbox(key="gas_explorer_indicator").value==("Storage inventory","TWh","publisher_day")
    assert app.dataframe[0].value.infrastructure_id.isna().all()
    assert app.dataframe[0].value.observed_at.isna().all()
    assert "90,00" in app.metric[0].value


@pytest.mark.parametrize("mode",["demo","workbench"])
def test_map_drilldown_enters_explorer_with_same_point_and_period(offline,monkeypatch,mode):
    monkeypatch.setenv("GASOPS_APP_MODE",mode)
    app=AppTest.from_file(ROOT/"app.py",default_timeout=30).run()
    app.session_state[network_page.ARCHIVE_KEY] = True
    app.session_state[network_page.SELECTED]="it-lng-piombino"
    app.run()
    app.button(key="net_data_explorer_overview").click().run()
    assert not app.exception and app.radio(key="operational_platform").value=="EXPLORER"
    assert "Piombino" in app.selectbox(key="gas_explorer_entity").options[app.selectbox(key="gas_explorer_entity").index]
    assert app.date_input(key="gas_explorer_period").value==(date(2026,11,14),date(2026,11,20))
    assert app.session_state[network_page.SELECTED]=="it-lng-piombino"


def test_source_health_monitor_includes_map_diagnostics_and_uses_shared_export(offline):
    app=AppTest.from_string("from gasops_app.source_health_page import panel\npanel()",default_timeout=30).run()
    assert not app.exception
    table=app.dataframe[0].value
    assert table.Serie.str.contains("Mazara").any()
    assert "Stato fonte" in table and "Età copia più vecchia · h" in table
    assert len(app.get("download_button"))>=1


def test_geographic_pipeline_does_not_offer_an_unrelated_point_drilldown(offline):
    network=network_page.assets()[0]
    pipeline=next(i.id for i in network.infrastructure if i.category=="pipeline")
    app=AppTest.from_file(ROOT/"app.py",default_timeout=30).run()
    app.session_state[network_page.SELECTED]=pipeline
    app.run()
    assert not app.exception
    assert app.button(key="net_data_explorer_overview").disabled
    assert app.session_state[network_page.SELECTED]==pipeline


def test_unavailable_focus_is_explained_before_showing_other_series(offline):
    app=AppTest.from_string(SCRIPT,default_timeout=30)
    app.session_state[page.FOCUS]={"id":"unmapped","direction":"entry","first":date(2026,11,14),"last":date(2026,11,20)}
    app.run()
    assert not app.exception
    assert any("Nessuna osservazione disponibile per il punto richiesto" in c.value for c in app.caption)


def test_explorer_exposes_verified_bidirectionality(offline):
    app=AppTest.from_string(SCRIPT,default_timeout=30).run()
    assert not app.exception
    assert any("igor-direction-chip" in e.proto.body and "↘ Solo ingresso" in e.proto.body for e in app.get("html"))
    app.selectbox(key="gas_explorer_entity").set_value("IT-TSO-0001ITP-00040entry").run()
    assert not app.exception
    assert any("↔ Bidirezionale" in e.proto.body and "↘ Ingresso" in e.proto.body for e in app.get("html"))
    assert any("Direzione opposta: ↗ Uscita" in c.value for c in app.caption)
