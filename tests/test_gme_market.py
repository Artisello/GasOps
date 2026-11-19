import base64,io,json,zipfile
from datetime import date
from decimal import Decimal as D
import pytest
from gasops_app import gme_market as g

DAY=date(2026,11,17)


def test_native_fields_null_and_duplicate():
    r={"FlowDate":20261117,"MaxPurchaseSRGPrice":45,"MinSaleSRGPrice":None,
       "WeightedAveragePrice":42,"MGASVolumes":0}
    s=g.parse(json.dumps([r]).encode(),"prices",DAY)
    assert s["rows"][0]["MinSaleSRGPrice"] is None and s["rows"][0]["MGASVolumes"]==0
    with pytest.raises(ValueError):g.parse(json.dumps([r,r]).encode(),"prices",DAY)
    with pytest.raises(ValueError):g.parse(json.dumps([{**r,"FlowDate":20261118}]).encode(),"prices",DAY)
    with pytest.raises(ValueError):g.study_prices(s["rows"][0],D(2000),D(1))


def test_envelope_bounded_and_case_insensitive():
    payload=b'[{"FlowDate":20261117,"MaxPurchaseSRGPrice":45,"MinSaleSRGPrice":40,"WeightedAveragePrice":42,"MGASVolumes":12345}]'
    z=io.BytesIO()
    with zipfile.ZipFile(z,"w") as f:f.writestr("data.json",payload)
    envelope=json.dumps({"requestId":"1","formatType":".json.zip","resultRequest":None,
                         "contentResponse":base64.b64encode(z.getvalue()).decode()}).encode()
    assert g.decode_response(envelope)==payload
    s=g.parse(envelope,"prices",DAY)
    r=g.study_prices(s["rows"][0],D(2000),D(1))
    assert r["buy"]==45 and r["sell"]==40
    with pytest.raises(ValueError):g.study_prices(s["rows"][0],D(1999),D(1))
    with pytest.raises(ValueError):g.decode_response(b'{"formatType":".xml.zip","contentResponse":"x"}')


def test_public_default_blocks_fetch(monkeypatch):
    monkeypatch.delenv("IGOR_GME_PRIVATE_AUTHORIZED",raising=False)
    def forbidden(*a,**kw):raise AssertionError("no network")
    with pytest.raises(ValueError,match="privato"):g.fetch_private("prices",DAY,DAY,"x","y",post=forbidden)


def test_demo_views_are_offline(monkeypatch):
    from streamlit.testing.v1 import AppTest
    monkeypatch.delenv("IGOR_GME_PRIVATE_AUTHORIZED",raising=False)
    app=AppTest.from_string("from gasops_app.gme_market_page import panel\npanel()").run()
    assert not app.exception and not app.get("file_uploader")
    for kind in g.DATASETS:
        app.radio(key="gme_view").set_value(kind).run()
        app.button(key="gme_demo").click().run()
        assert not app.exception
        assert any("Demo sintetica" in c.value for c in app.caption)
