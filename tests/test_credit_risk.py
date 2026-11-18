from decimal import Decimal as D
import pytest

from gasops_app.credit_risk import (additional_guarantee_90, credit_position,
    lng_psv_security, lng_security, patt_horizon, stress_patt)


@pytest.mark.parametrize("bal,tr,days",[(0,0,3),(10,10,3),(10,11,5),(20,0,5),
                                        (0,21,7),(21,15,7)])
def test_horizon(bal,tr,days):
    assert patt_horizon(D(bal),D(tr),verifiable=True)==days


def test_horizon_missing():
    assert patt_horizon(verifiable=False)==7
    with pytest.raises(ValueError):
        patt_horizon(D(5),None,verifiable=True)
    with pytest.raises(ValueError):
        patt_horizon(D(101),D(0),verifiable=True)


@pytest.mark.parametrize("eps,status",[(89,"OK"),(90,"ATTENZIONE"),(100,"LIMITE"),(101,"LIMITE")])
def test_net_guarantee(eps,status):
    p=credit_position(D(eps),D(0),D(0),[D(80),D(40)],D(20))
    assert p["meps"]==100 and p["ratio"]==eps and p["status"]==status
    assert p["condition_met"]==(eps<100)


def test_zero_negative_meps():
    p=credit_position(D(0),D(0),D(0),[D(100)],D(100))
    assert p["ratio"] is None and p["status"]=="LIMITE"
    p=credit_position(D(-10),D(0),D(0),[D(0)],D(5))
    assert p["condition_met"] and p["status"]=="VERIFICA MEPSu"


def test_stress_and_increment():
    delta=stress_patt(3,D(500),D(40),D(22),D(0))
    assert delta==D(73200)
    assert stress_patt(7,D(500),D(40),D(22),D(100))==D(175680)
    p=credit_position(D(420000),D(280000),D(220000)+delta,[D(1100000)],D(100000))
    assert p["eps"]==D(993200)
    assert additional_guarantee_90(p)==D("103555.56")


def test_invalid_inputs():
    for v in (D("NaN"),D("Infinity"),None):
        with pytest.raises(ValueError):
            credit_position(v,D(0),D(0),[D(100)],D(0))
    with pytest.raises(ValueError):
        credit_position(D(0),D(0),D(0),[D(-1)],D(0))
    with pytest.raises(ValueError):
        stress_patt(4,D(1),D(1),D(0),D(0))


def test_lng_distinct_rules():
    p=lng_security([D(180),D(200),D(150),D(20)],D(1300),D(80),D(750))
    assert p["required"]==610 and p["headroom"]==140
    p=lng_security([D(180),D(200),D(150)],D(2000),D(80),D(750))
    assert p["required"]==800 and p["headroom"]==-50
    assert lng_psv_security(D(90000),D(105000))==105000
    with pytest.raises(ValueError):
        lng_security([D(100)],D(99),D(0),D(0))
