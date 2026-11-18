from datetime import date
from decimal import Decimal as D
import pytest
from gasops_app import market_efficiency as m

C=date(2026,10,3)


def load(*lines):
    return m.parse((m.template()+"\n".join(lines)+"\n").encode(),C)


def test_economics_and_coverage():
    s=load("2026-10-01,title,complete,100,40,4500,1400,40",
           "2026-10-02,title,complete,0,0,0,0,",
           "2026-10-03,title,partial,500,0,25000,0,40")
    r,detail=m.evaluate(s["rows"],2026,10,"title",C)
    assert r["expected_days"]==3 and r["complete_days"]==2 and r["partial_days"]==1
    assert r["gross_mwh"]==140 and r["net_cost_eur"]==3100
    assert r["buy_vwap"]==45 and r["sell_vwap"]==35 and r["spread"]==10
    assert r["differential_eur"]==700 and r["comparable_mwh"]==140
    assert r["differential_eur_mwh"]==5
    assert detail[2]["net_cost_eur"] is None


def test_missing_not_zero_and_negative_price():
    s=load("2026-10-01,title,complete,100,50,-1000,-250,-6",
           "2026-10-02,locational,complete,500,0,25000,0,")
    r,detail=m.evaluate(s["rows"],2026,10,"title",C)
    assert r["net_cost_eur"]==-750 and r["differential_eur"]==-450
    assert r["missing_days"]==2 and detail[1]["buy_mwh"] is None
    r,_=m.evaluate(s["rows"],2026,10,"storage",C)
    assert r["gross_mwh"] is None and r["net_cost_eur"] is None
    r,_=m.evaluate(s["rows"],2026,10,"locational",C)
    assert r["differential_eur"] is None


def test_no_benchmark_is_not_zero():
    s=load("2026-10-01,title,complete,10,0,400,0,")
    r,_=m.evaluate(s["rows"],2026,10,"title",C)
    assert r["differential_eur"] is None and r["comparable_days"]==0


def test_conflicts_and_invalid():
    line="2026-10-01,title,complete,10,0,400,0,40"
    assert len(load(line,line)["rows"])==1
    for bad in ("2026-10-04,title,complete,10,0,400,0,40",
                "2026-10-01,title,complete,0,0,400,0,40",
                "2026-10-01,storage,complete,10,0,400,0,40",
                "2026-10-01,title,complete,NaN,0,400,0,40",
                "2026-10-01,title,complete,-10,0,400,0,40"):
        with pytest.raises(ValueError):load(bad)
    with pytest.raises(ValueError):load(line,line.replace("400","401"))
