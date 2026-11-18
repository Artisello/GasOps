from datetime import date,datetime,timedelta,timezone
from decimal import Decimal
import json
import pytest

from gasops_app import entsog_network as en

POINT=en.PRESETS["Mazara del Vallo (SRG, ingresso)"]
DAY=date(2026,11,10)
NOW=datetime(2026,11,18,12,tzinfo=timezone.utc)


def record(indicator="Physical Flow",value=2000000,day=DAY):
    return {"operatorKey":"IT-TSO-0001","pointKey":"ITP-00093","directionKey":"entry",
            "operatorLabel":"Snam Rete Gas","pointLabel":"Mazara del Vallo","indicator":indicator,
            "periodType":"day","unit":"kWh/d","periodFrom":day.isoformat()+"T06:00:00+01:00",
            "periodTo":(day+timedelta(days=1)).isoformat()+"T06:00:00+01:00",
            "flowStatus":"Provisional","value":value}


def parse(rows,last=DAY,meta=None):
    payload={"operationalData":rows,"meta":meta if meta is not None else
             {"count":len(rows),"total":len(rows),"offset":0,"limit":500}}
    return en.parse_network(payload,POINT,DAY,last,NOW)


def test_calculations_and_missing():
    r=parse([record(),record("Nomination",1500000),record("Renomination",1900000),
             record("Allocation",2100000),record("Firm Technical",4000000),record("Firm Booked",3000000)],
             DAY+timedelta(days=1))
    a,b=en.daily_metrics(r)
    assert len(r.rows)==14 and a["flow_minus_nomination"]==Decimal("0.5")
    assert a["flow_minus_renomination"]==Decimal("0.1")
    assert a["allocation_minus_flow"]==Decimal("0.1")
    assert a["technical_utilization_pct"]==50 and a["booked_technical_pct"]==75
    assert a["Firm Available"] is None and b["Physical Flow"] is None
    assert "ENTSOG TP Transport Data 18-11-2026" in en.export_csv(r)


def test_conflicts_missing_and_metadata():
    r=parse([record(),record(value=3000000),record("Nomination",0)],
            meta={"count":3,"total":4,"offset":0,"limit":500})
    assert r.metadata_warning
    assert r.rows[0]["quality"]=="conflitto"
    assert en.daily_metrics(r)[0]["Nomination"]==0
    assert en.daily_metrics(r)[0]["flow_minus_nomination"] is None


def test_na_negative_and_zero_capacity():
    r=parse([record(value=-1),record("Firm Technical",0),dict(record("Nomination",0),isNA=True)])
    assert r.rows[1]["quality"]=="N/A"
    assert en.daily_metrics(r)[0]["technical_utilization_pct"] is None


@pytest.mark.parametrize("patch", [{"directionKey":"exit"},{"unit":"m3/d"},{"periodType":"hour"},
                                   {"value":"NaN"},{"periodFrom":"2026-11-10T12:00:00+01:00"}])
def test_wrong_contract_rejected(patch):
    with pytest.raises(ValueError):
        parse([dict(record(),**patch)])


def test_counts_and_date_limits():
    with pytest.raises(ValueError):
        parse([record()],meta={"count":2,"total":2,"offset":0})
    with pytest.raises(ValueError):
        en.query_params(POINT,DAY,DAY+timedelta(days=31))
    with pytest.raises(ValueError):
        en.query_params("https://bad.example",DAY,DAY)


def test_loader_bounded_cached_and_no_future(monkeypatch):
    called=[]
    def fake(store,**kwargs):
        called.append(kwargs)
        return kwargs["parse"](json.dumps({"operationalData":[record()]}),NOW)
    monkeypatch.setattr(en,"retrieve",fake)
    result=en.load_network(None,POINT,DAY,DAY,now=NOW)
    assert result.point==POINT and len(called)==1
    assert called[0]["params"]["pointDirection"]==POINT
    assert called[0]["params"]["indicator"]==",".join(en.INDICATORS)
    assert called[0]["attempts"]==1 and called[0]["ttl"]==timedelta(hours=12)
    with pytest.raises(ValueError):
        en.load_network(None,POINT,NOW.date(),NOW.date(),now=NOW)
