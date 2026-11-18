from datetime import date,datetime,timedelta,timezone
from decimal import Decimal as D
import pytest
from gasops_app import terna_power as t

DAY=date(2025,10,25)
NOW=datetime(2026,11,18,12,tzinfo=timezone.utc)


def generation(day=DAY,field="Thermal"):
    start,end=t._start(day),t._start(day+timedelta(days=1))
    rows=[]
    for i in range(int((end-start).total_seconds()/3600)):
        local=(start+timedelta(hours=i)).astimezone(t.ROME)
        rows.append({"date":local.strftime("%Y-%m-%d %H:%M:%S"),"date_tz":"Europe/Rome",
                     "date_offset":local.isoformat()[-6:],"actual_generation_GWh":"2","primary_source":field})
    return rows


def payload(rows,key="actual_generation"):
    return {"result":{"status":"Completed"},key:rows}


def test_annual():
    rows=t.annual_rows()
    assert len(rows)==17
    v={r["metric"]:r["value"] for r in rows}
    assert v["gas_gross"]==D("126.9")
    assert v["production_for_consumption"]+v["net_imports"]==v["demand"]


def test_dst_and_missing():
    rows=generation()
    assert len(rows)==25
    out=t.parse_power(payload(rows),"generation",DAY,DAY)
    thermal=next(r for r in out if r["metric"]=="Thermal")
    assert thermal["gwh"]==50 and thermal["expected_slots"]==25
    assert next(r for r in out if r["metric"]=="Wind")["gwh"] is None
    out=t.parse_power(payload(rows[:-1]+generation(field="Wind")),"generation",DAY,DAY)
    assert out[0]["gwh"] is None and out[0]["valid_slots"]==24


def test_conflict_and_invalid_offset():
    rows=generation()
    with pytest.raises(ValueError):
        t.parse_power(payload(rows+[dict(rows[0],actual_generation_GWh="3")]),"generation",DAY,DAY)
    with pytest.raises(ValueError):
        t.parse_power(payload([dict(rows[0],date_offset="+03:00")]),"generation",DAY,DAY)


def test_quarter_hour_conversion():
    d=date(2025,11,1)
    rows=[]
    for i in range(96):
        local=(t._start(d)+timedelta(minutes=15*i)).astimezone(t.ROME)
        rows.append({"date":local.strftime("%Y-%m-%d %H:%M:%S"),"date_tz":"Europe/Rome",
           "date_offset":local.isoformat()[-6:],"bidding_zone":"Italy","total_load_MW":"1000",
           "forecast_total_load_MW":"1100"})
    out=t.parse_power(payload(rows,"total_load"),"load",d,d)
    assert out[0]["gwh"]==24 and out[1]["gwh"]==D("26.4")


def test_pairs_and_bounds():
    rows=[{"gas_day":str(DAY+timedelta(days=i)),"metric":"Thermal","gwh":D(i+1)} for i in range(7)]
    gas={r["gas_day"]:float(r["gwh"])*2 for r in rows}
    pairs=t.paired(rows,gas)
    assert t.correlation(pairs)==pytest.approx(1)
    assert t.correlation(pairs[:6]) is None
    assert t.correlation([dict(r,sr_gas_gwh=1) for r in pairs]) is None
    assert t.dates(DAY,DAY,NOW)["dateTo"]=="26/10/2025"
    with pytest.raises(ValueError):
        t.dates(DAY,DAY+timedelta(days=14),NOW)
    with pytest.raises(ValueError):
        t.dates(NOW.date(),NOW.date(),NOW)


def test_no_redirect_or_token_leak(monkeypatch):
    calls=[]
    def fake(method,url,**kwargs):
        calls.append((method,url,kwargs))
        return {"access_token":"abc","token_type":"bearer"}
    monkeypatch.setattr(t,"_json_request",fake)
    assert t.get_token("id","secret")=="abc"
    assert calls[0][1]==t.TOKEN
    assert calls[0][2]["data"]["grant_type"]=="client_credentials"
