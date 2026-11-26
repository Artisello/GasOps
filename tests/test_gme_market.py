import base64,io,json,zipfile
from datetime import date, datetime, timedelta, timezone
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


def _archive(payload, extension="json"):
    z=io.BytesIO()
    with zipfile.ZipFile(z,"w",compression=zipfile.ZIP_DEFLATED) as f:
        f.writestr("data."+extension,payload)
    return json.dumps({"RequestId":"quota-fixture","FormatType":f".{extension}.zip","ResultRequest":None,
                       "ContentResponse":base64.b64encode(z.getvalue()).decode()}).encode()


def _snapshot(kind, rows, first=DAY, last=DAY):
    parsed = g.parse(json.dumps(rows).encode(), kind, last, first=first)
    return dict(parsed, first=first, last=last, origin="api",
                acquired=datetime(2026,11,20,10,tzinfo=timezone.utc))


@pytest.mark.parametrize(("kind","segment","code","record","field","unit"), [
    ("prices","GAS","GAS_ImbalancePrice",{"FlowDate":20261117,"WeightedAveragePrice":"41.04"},"WeightedAveragePrice","€/MWh"),
    ("igi","IGI","GAS_IGIndex",{"FlowDate":20261117,"Product":"test","Price":"41.04"},"Price","€/MWh"),
    ("continuous","MT-GAS","GAS_ContinuousTrading",{"FlowDate":20261117,"Market":"MT","Product":"test","MWhVolumes":"41.04"},"MWhVolumes","MWh"),
    ("curve","PBZ-Edison stoccaggi","GAS_DemandAndSupply",{"FlowDate":20261117,"Market":"PBZ-Edison stoccaggi","Type":"Acquisto","Price":"41.04"},"Price","€/MWh"),
    ("mgas","MI-GAS","GAS_MGASAuctionResults",{"FlowDate":20261117,"Market":"MI","Product":"test","TotalVolumesMW":"41.04"},"TotalVolumesMW","MW"),
    ("mgs","MGS","GAS_MGSAuctionResults",{"FlowDate":20261117,"StorageCompany":"test","Type":"Altro","SRGSales":"41.04"},"SRGSales",None),
    ("mpl","MPL","GAS_MPLAuctionResults",{"SessionDate":20261117,"GasDay":20261118,"Reason":"Operativo","Type":"Vendita","OfferPoint":"test","SRGVolumes":"41.04"},"SRGVolumes",None),
    ("pgr","PGR","GAS_PGRResults",{"Date":20261117,"VolumeAllocated":"41.04"},"VolumeAllocated",None),
])
def test_catalog_preserves_segment_schema_and_units(kind,segment,code,record,field,unit):
    spec = g.DATASETS[kind]
    assert spec.name == code and spec.units[field] == unit
    snapshot = g.parse(json.dumps([record]).encode(),kind,DAY,segment=segment,first=DAY)
    assert snapshot["segment"] == segment and snapshot["rows"][0][field] == D("41.04")
    assert snapshot["missing"] == len(spec.units)-1


def test_rejects_wrong_market_duplicate_fields_and_large_or_unsafe_archives():
    record = {"FlowDate":20261117,"Market":"MGP","Product":"test","MWhVolumes":1}
    with pytest.raises(ValueError,match="segmento"):
        g.parse(json.dumps([record]).encode(),"continuous",DAY,segment="MI-GAS")
    with pytest.raises(ValueError):
        g.parse(b'[{"FlowDate":20261117,"Product":"test","Price":1,"PRICE":2}]',"igi",DAY)
    with pytest.raises(ValueError):
        g.parse(b'[{"FlowDate":20261117,"Product":"test","Price":1e1000001}]',"igi",DAY)
    with pytest.raises(ValueError,match="decompressione"):
        g.decode_response(_archive(b" "*(g.MAX_BYTES+1)))
    with pytest.raises(ValueError,match="XML"):
        g.parse(_archive(b"<!DOCTYPE records><records/>","xml"),"igi",DAY)


def test_xml_accepts_scalar_records_and_null_never_becomes_zero():
    xml = b"""<Rows xmlns="urn:test"><Row><FlowDate>20261117</FlowDate>
    <MaxPurchaseSRGPrice/><WeightedAveragePrice>0</WeightedAveragePrice>
    </Row></Rows>"""
    result = g.parse(_archive(xml,"xml"),"prices",DAY)
    assert result["request_id"] == "quota-fixture"
    row = result["rows"][0]
    assert row["WeightedAveragePrice"] == D(0) and row["MaxPurchaseSRGPrice"] is None
    assert g.parse(b"[]","igi",DAY)["rows"] == ()


def test_settlement_matches_closed_gas_day_and_preserves_imported_prices():
    from gasops_app.gme_analysis import settlement_preview
    from gasops_app.operations_ledger import BalanceRow
    item = _snapshot("prices", [{"FlowDate":20261117,"WeightedAveragePrice":42,
                                "MaxPurchaseSRGPrice":44,"MinSaleSRGPrice":40}])
    for injected, amount in [(0, "-440.00"), (20, "400.00")]:
        row = BalanceRow("test",DAY,1,"definitive",D(injected),D(0),D(0),D(10),D(4),D(3))
        priced, cash = settlement_preview(item,row,D(2000),D(1),ordinary=True)
        assert priced["buy"] == D(44) and cash == D(amount)
        assert row.buy == D(4) and row.sell == D(3)
    with pytest.raises(ValueError,match="Regime"):
        settlement_preview(item,row,D(2000),D(1),ordinary=False)
    with pytest.raises(ValueError,match="30 giorni"):
        settlement_preview(item,row,D(1999),D(1),ordinary=True)
    with pytest.raises(ValueError,match="acquisiti"):
        settlement_preview(dict(item,origin="demo"),row,D(2000),D(1),ordinary=True)


def test_backtest_never_fits_holdout_or_bridges_missing_dates():
    from gasops_app.gme_analysis import price_backtest
    first = DAY - timedelta(days=30)
    records = [{"FlowDate":int((first+timedelta(days=i)).strftime("%Y%m%d")),
                "Product":"test","Price":10+i} for i in range(31) if i != 28]
    initial = price_backtest(_snapshot("igi",records,first), "test")
    for item in records:
        if item["FlowDate"] >= 20261111:
            item["Price"] *= 100
    holdout_changed = price_backtest(_snapshot("igi",records,first), "test")
    assert initial["lower"] == holdout_changed["lower"] == 1
    assert initial["upper"] == holdout_changed["upper"] == 1
    assert initial["train_days"] == 23 and initial["test_days"] == 5
    assert initial["mae"] == 1 and holdout_changed["mae"] > 1


def test_gme_date_must_be_closed_by_acquisition_on_dst_boundary():
    from gasops_app.gme_analysis import price_backtest
    from gasops_app.gas_calendar import gas_day_bounds
    last = date(2026,10,24)
    first = last - timedelta(days=30)
    start, end = gas_day_bounds(last)
    assert end-start == timedelta(hours=25)
    rows = [{"FlowDate":int((first+timedelta(days=i)).strftime("%Y%m%d")),
             "Product":"test","Price":42} for i in range(31)]
    snapshot = _snapshot("igi",rows,first,last)
    with pytest.raises(ValueError,match="non conclusi"):
        price_backtest(dict(snapshot,acquired=end-timedelta(seconds=1)), "test")
    assert price_backtest(dict(snapshot,acquired=end), "test")["test_days"] == 7


def test_gme_string_null_and_missing_mgs_type_preserve_observed_scope():
    records = [
        {"FlowDate":"20261117","StorageCompany":"fixture","Type":"","Price":"null","Volumes":"0"},
        {"FlowDate":"20261117","StorageCompany":"fixture","Type":"Bilanciamento","Price":"43.20","Volumes":25},
    ]
    payload = g.parse(json.dumps(records).encode(),"mgs",DAY)["rows"]
    assert payload[0]["Type"] is None and payload[0]["Price"] is None and payload[0]["Volumes"] == 0
    assert payload[1]["Type"] == "Bilanciamento" and payload[1]["Price"] == D("43.20")


def test_offer_curve_can_have_different_volumes_at_the_same_price():
    point = {"FlowDate":20261117,"Market":"MGP","Type":"Acquisto","Price":42,"Volumes":10}
    payload = json.dumps([point,{**point,"Volumes":20}]).encode()
    assert len(g.parse(payload,"curve",DAY)["rows"]) == 2
    with pytest.raises(ValueError,match="duplicata"):
        g.parse(json.dumps([point,point]).encode(),"curve",DAY)
