from datetime import date,timedelta
from decimal import Decimal as D
import pytest
from gasops_app import incentives as m


def test_parameters_and_percent_scaling():
    assert m.incentive(1,date(2026,11,1),D("5"))==0
    assert m.incentive(2,date(2026,1,1),D("4"))==-5000
    assert m.parameters(1,date(2026,4,1))==m.PARAMS["1s"]
    assert m.parameters(4,date(2026,4,1))==m.PARAMS["4w"]
    assert m.parameters(6,date(2026,10,1))==m.PARAMS["6w"]
    assert m.incentive(3,date(2026,1,1),D("15"))==20000
    assert m.incentive(6,date(2026,6,1),D("1"))==10000
    assert m.incentive(2,date(2026,1,1),None) is None


def test_volatility():
    q=lambda h,l:(D(h),D(l),D(h),D(l))
    assert m.volatility_factor(D(-100),"quotato",q(107,93))==1
    assert m.volatility_factor(D(-100),"quotato",q(109,91))==D(".5")
    assert m.volatility_factor(D(-100),"quotato",q(111,89))==0
    assert m.volatility_factor(D(5),"ignoto",(None,)*4)==1
    assert m.volatility_factor(D(-5),"ignoto",(None,)*4) is None
    assert m.volatility_factor(D(-5),"non_quotato",(None,)*4)==1


def test_annual_complete_and_partial():
    def make(year):
        start=date(year,1,1)
        return [m.Day(start+timedelta(days=i),"definitivo",(D(0),D(0),D(0),D(0),D(0),D(100)),
                       "ignoto",(None,)*4) for i in range((date(year+1,1,1)-start).days)]
    a=make(2026); b=make(2027)
    assert m.annual_amount(a[:-1],2026) is None
    assert m.annual_amount(a,2026)>0 # I6 floored at zero through 2026
    assert m.annual_amount(b,2027)==D(-5000000)
    assert m.annual_amount(make(2028),2028)==D(-5000000)
    assert m.annual_amount(a[:-1]+[a[0]],2026) is None


def test_parser():
    head=m.template()
    line="2026-01-01,definitivo,5,4,15,35,5,1,ignoto,,,,\n"
    rows,digest=m.parse_csv((head+line+line).encode(),date(2026,2,1))
    assert len(rows)==1 and len(digest)==64 and rows[0].h is None
    with pytest.raises(ValueError):m.parse_csv((head+line+line.replace(",5,4,",",6,4,")).encode(),date(2026,2,1))
    with pytest.raises(ValueError):m.parse_csv((head+line.replace(",5,4,",",NaN,4,")).encode(),date(2026,2,1))
    with pytest.raises(ValueError):m.parse_csv((head+line).encode(),date(2025,12,31))
