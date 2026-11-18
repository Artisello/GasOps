"""ACER UX regressions; all tests remain offline."""
from datetime import date,datetime,timezone
from decimal import Decimal
from types import SimpleNamespace
import pandas as pd
from streamlit.testing.v1 import AppTest

from gasops_app import acer_market_page as page
from gasops_app.acer_market import bundled_lng,cached_lng,CACHE_KEY
from gasops_app.acer_baf_2026 import all_baf_rows
from gasops_app.acer_baf_page import selected_zones,zone_subset,zone_figure,trend_figure,CURRENT,PREVIOUS

NOW=datetime(2026,11,18,12,tzinfo=timezone.utc)


def test_zone_statistics_and_filter_do_not_impute_missing():
    compare,current,mid,it,rank=selected_zones(all_baf_rows(),"imbalance_share")
    assert len(current)==23 and mid==Decimal("1.3")
    assert it[CURRENT]==Decimal("7.4") and rank==1
    lower=zone_subset(current,"Valori più bassi")
    assert len(lower)==6 and any(r["zone"]=="IT" for r in lower)
    fig=zone_figure(lower,"imbalance_share",mid,True)
    assert len(fig.data)==2
    assert "NL" not in fig.data[1].y
    assert "NL" in fig.data[0].y
    assert fig.data[0].marker.color[0]=="#65dfbf"
    assert fig.layout.shapes[0].x0==1.3
    _,current,_,_,_=selected_zones(all_baf_rows(),"tso_buy_share")
    assert len(current)==8


def test_neutrality_chart_preserves_signed_values_and_zero():
    _,current,mid,it,rank=selected_zones(all_baf_rows(),"net_adjusted_neutrality")
    fig=zone_figure(current,"net_adjusted_neutrality",mid,False)
    assert min(fig.data[0].x)<0 and fig.layout.xaxis.range[0]<min(fig.data[0].x)
    assert "0,03 €/MWh" in fig.data[0].text
    assert any(x==0 for x in fig.data[0].x)
    assert rank==10


def test_lng_cards_use_own_publication_dates():
    f=pd.DataFrame({"date":["2026-11-14","2026-11-17"],"eu":[81.,82.],
                    "benchmark":[-2.,None],"south_minus_nwe":[None,None]})
    cards=page.latest_cards(f,date(2026,11,18))
    assert cards[0][1]==82 and "17" in cards[0][3] and "+1,000" in cards[0][3]
    assert cards[1][1]==-2 and "14" in cards[1][3]
    assert cards[2][1] is None


def test_cache_read_only_and_future_timestamp():
    source=bundled_lng()
    from gasops_app.acer_market import ROOT
    raw=(ROOT/"data/acer/lng-september-2026-extract.csv").read_text()
    def cached(key):
        assert key==CACHE_KEY
        return NOW.isoformat(),raw
    stored=cached_lng(SimpleNamespace(cached=cached),NOW)
    assert stored.cached and stored.rows==source.rows
    assert cached_lng(SimpleNamespace(cached=lambda key:("2027-01-01T00:00:00+00:00",raw)),NOW) is None


def test_acer_offline_navigation_and_historical_lng(monkeypatch):
    monkeypatch.setattr(page,"utc_now",lambda:NOW)
    monkeypatch.setattr(page,"database",lambda:SimpleNamespace(cached=lambda key:None))
    def forbidden(*args,**kwargs):
        raise AssertionError("No request without an explicit refresh")
    monkeypatch.setattr(page,"load_lng",forbidden)
    app=AppTest.from_string("from gasops_app.acer_market_page import panel\npanel()").run()
    assert not app.exception
    assert app.radio(key="acer_mode").value=="Benchmark bilanciamento"
    assert app.radio(key="acer_baf_view").value=="Confronto zone"
    assert len(app.get("plotly_chart"))==1
    app.selectbox(key="acer_baf_metric_2026").set_value("net_adjusted_neutrality").run()
    assert not app.exception
    app.radio(key="acer_baf_view").set_value("Trend europeo").run()
    assert not app.exception
    app.selectbox(key="acer_baf_eu_metric").set_value("imbalance_share").run()
    assert not app.exception and len(app.get("plotly_chart"))==1
    app.radio(key="acer_mode").set_value("Prezzi GNL").run()
    assert not app.exception and len(app.get("plotly_chart"))==2
    assert any("Estratto storico incluso" in w.value for w in app.warning)
    assert app.button(key="acer_update").label=="Aggiorna da ACER"
