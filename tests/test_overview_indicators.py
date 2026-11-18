from datetime import datetime,timezone,date,timedelta
from decimal import Decimal
from types import SimpleNamespace

import pandas as pd
from gasops_app.overview_indicators import price_snapshot,supply_snapshot,current_rows


def test_indicators_keep_independent_periods_and_stale_label():
    now=datetime(2026,11,18,12,tzinfo=timezone.utc)
    p=price_snapshot(SimpleNamespace(rows={"2026-10-01":Decimal("35.123")},
                    source=SimpleNamespace(refresh_failed=False,retrieved_at=now)),now)
    frame=pd.DataFrame([{"gas_day":date(2026,11,10),"stock_twh":100.,"fill_pct":80.,"status":"C"},
                        {"gas_day":date(2026,11,17),"stock_twh":95.,"fill_pct":76.,"status":"E"}])
    a=supply_snapshot({"scope":"IT","frame":frame,"failed":False,"acquired":now},now,"AGSI+")
    rows=current_rows({"price":p,"storage":a,"lng":{"error":True}},now,gie_enabled=True)
    assert rows[0][1]==35.123 and "Ottobre 2026" in rows[0][3]
    assert rows[1][1]==76 and "17 nov 2026" in rows[1][3] and "Stimato" in rows[1][3]
    assert "-4,0 p.p." in rows[1][3] and rows[2][1] is None
    assert "Da aggiornare" in current_rows({"price":p},now+timedelta(days=1),gie_enabled=False)[0][3]


def test_indicators_no_network_on_ordinary_rerun(monkeypatch):
    from streamlit.testing.v1 import AppTest
    from gasops_app import overview_indicators as module
    calls=[]
    monkeypatch.setattr(module,"configured_key",lambda:"fixture")
    monkeypatch.setattr(module,"database",lambda:None)
    monkeypatch.setattr(module,"acquire_indicators",lambda *a,**k:calls.append(1) or {"price":{"error":True}})
    app=AppTest.from_string("from gasops_app.overview_indicators import panel\npanel()").run()
    assert not app.exception and calls==[]
    from gasops_app.operational_sources import attribution
    for platform in ("AGSI+","ALSI"):
        source=attribution(platform)
        assert any("["+source["source"]+"]("+source["source_url"]+")" in e.value
                   for e in app.markdown)
    app.button(key="overview_public_refresh").click().run()
    assert not app.exception and calls==[1]
    app.run()
    assert not app.exception and calls==[1]
    app.button(key="overview_public_refresh").click().run()
    assert not app.exception and calls==[1]



def test_reuse_only_validated_monthly_price_and_italian_supply():
    from gasops_app.overview_indicators import reuse_indicators
    now=datetime(2026,11,18,12,tzinfo=timezone.utc)
    source=SimpleNamespace(fields=("price_eur_mwh",),refresh_failed=False,retrieved_at=now)
    origin=SimpleNamespace(grain="monthly",companions=(source,))
    ctx=SimpleNamespace(bundle=SimpleNamespace(origin=origin),
        inspection=SimpleNamespace(usable=pd.DataFrame({"price_eur_mwh":[35.,None]},index=pd.to_datetime(["2026-09-01","2026-10-01"]))))
    values=reuse_indicators({},ctx,{},now)
    assert values["price"]["value"]==35 and values["price"]["period"]=="Settembre 2026"
    assert reuse_indicators({"price":{"error":True}},ctx,{},now)=={"price":{"error":True}}
