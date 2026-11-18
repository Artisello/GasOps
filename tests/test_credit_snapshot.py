from datetime import date
from decimal import Decimal as D
import copy,json
import pytest
from gasops_app import credit_snapshot as m

NOW=date(2026,11,18)


def test_example_reconstructed():
    r=m.reconstruct(m.example(),NOW)
    p=r["position"]
    assert r["horizon"]==3 and r["pr_eur_kwh"]==D(".040000")
    assert p["pfat"]==420000 and p["pdet"]==244000 and p["c"]==100000
    assert p["patt"]==D(219600) and p["eps"]==D(883600)
    assert p["meps"]==1000000 and p["status"]=="OK"
    assert r["patt_rows"][-1]["within_horizon"] is False
    assert D(r["patt_rows"][-1]["patt_eur"])==D(58560)


def test_price_rounding_and_complete_month():
    x=m.example()
    for p in x["prior_prices"]:p["buy_eur_mwh"]="42.12356"
    assert m.reconstruct(x,NOW)["pr_eur_mwh"]==D("42.124")
    x["prior_prices"].pop()
    with pytest.raises(ValueError):m.reconstruct(x,NOW)


def test_coverage_and_duplicate_and_future():
    x=m.example();x["coverage"]["psv"]=False
    with pytest.raises(ValueError):m.reconstruct(x,NOW)
    x=m.example();x["obligations"].append(copy.deepcopy(x["obligations"][0]))
    with pytest.raises(ValueError):m.reconstruct(x,NOW)
    x=m.example();x["psv"][0]["registered_day"]="2026-11-19"
    with pytest.raises(ValueError):m.reconstruct(x,NOW)
    x=m.example();x["withdrawals"].pop()
    with pytest.raises(ValueError):m.reconstruct(x,NOW)


def test_overdue_and_signed_purchase():
    x=m.example();x["psv"][0]["net_sale_mwh"]="-1200"
    r=m.reconstruct(x,NOW)
    assert r["position"]["patt"]==D(102480)
    assert r["position"]["meps"]==D(1000000)
    x["regularity"]["balancing_irregular_eur"]="10001"
    with pytest.raises(ValueError):m.reconstruct(x,NOW) # now 5-day coverage required


def test_json_snapshot_and_nonverifiable():
    x=m.example()
    raw=json.dumps(x).encode()
    assert len(m.load(raw,NOW)["sha256"])==64
    with pytest.raises(ValueError):m.load(b'{"schema":1,"schema":2}',NOW)
    x["regularity"]={"verifiable":False,"balancing_total_eur":None,"balancing_irregular_eur":None,
                     "transport_total_eur":None,"transport_irregular_eur":None}
    assert m.regularity(x["regularity"])==(7,None,None)
