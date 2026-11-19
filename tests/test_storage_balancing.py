from datetime import datetime, timezone
from decimal import Decimal as D
import pytest

from gasops_app.storage_balancing import (system_balance,user_balance,mgs_limits,
                                            parse_system_csv,template,closed_hs1_day)

def test_system_balance_and_independent_check():
    r=system_balance(D(800),D(-40),D(2),observed_closing=D(758),
                     confirmed_renominations=D(-35),snt=D(1))
    assert r["closing"]==758 and r["delta"]==-42
    assert r["residual"]==0 and r["status"]=="Entro tolleranza"
    assert r["stop"]==-5 and r["st"]==-4
    r=system_balance(D(800),D(20),D(2))
    assert r["closing"]==818 and r["residual"] is None and r["stop"] is None
    assert r["status"]=="Solo calcolo"
    assert system_balance(D(10),D(-20),D(1))["findings"]
    assert system_balance(D(800),D(-40),D(2),observed_closing=D(759))["findings"]
    with pytest.raises(ValueError):system_balance(D(10),D(2),D(-1))

@pytest.mark.parametrize("direction,allocation,closing,effect",[
    ("injection","4","84.98","-.02"),
    ("withdrawal","-4","76.98","-.02"),
    ("injection","-4","77.02",".02"),
    ("withdrawal","4","85.02",".02")])
def test_user_consumption_sign_follows_system_direction(direction,allocation,closing,effect):
    r=user_balance(D(80),D(allocation),D(1),direction,D(".5"),
                   space=D(100),guarantee=D(10),injection_limit=D(8),withdrawal_limit=D(8))
    assert r["closing"]==D(closing) and r["consumption_effect"]==D(effect)
    assert not r["findings"]

def test_user_exceptions_and_mgs():
    r=user_balance(D(10),D(-20),D(0),"withdrawal",D(1),space=D(100),guarantee=D(5),
                   injection_limit=D(8),withdrawal_limit=D(8))
    assert r["closing"]<0 and len(r["findings"])>=3
    assert r["free_stock"]==0
    with pytest.raises(ValueError):
        user_balance(D(1),D(0),D(0),"injection",D(101),space=D(2),guarantee=D(0),injection_limit=D(1),withdrawal_limit=D(1))
    r=mgs_limits(*map(D,[20,80,8,8,10,2]))
    assert r["buy"]==12 and r["sell"]==60
    r=mgs_limits(*map(D,[1,2,3,4,5,6]))
    assert r["buy"]==0 and r["sell"]==0 and len(r["findings"])==2

def test_csv_missing_values_and_fixed_standard_time():
    now=datetime(2026,7,12,4,30,tzinfo=timezone.utc)
    assert closed_hs1_day(now).isoformat()=="2026-07-10"
    line="2026-07-10,800,-40,2,758,-35,1\n"
    empty="2026-07-09,800,10,2,,,\n"
    result=parse_system_csv((template()+line+empty).encode(),now)
    assert result[0]["residual"] is None and result[0]["st"] is None
    assert result[1]["closing"]==758 and result[1]["st"]==-4
    for bad in (line+line,line.replace("07-10","07-11"),line.replace(",2,",",-2,"),line.replace("800","NaN")):
        with pytest.raises(ValueError):parse_system_csv((template()+bad).encode(),now)

def test_hs1_views_without_network(monkeypatch):
    from streamlit.testing.v1 import AppTest
    from gasops_app import operational_sources_page as supply
    monkeypatch.setattr(supply,"configured_key",lambda:None)
    def forbidden(*args,**kwargs):raise AssertionError("HS1 does not request GIE")
    monkeypatch.setattr(supply,"load_agsi",forbidden)
    app=AppTest.from_string("from gasops_app.operational_sources_page import operational_context\noperational_context()")
    app.session_state["storage_view"]="Bilanciamento HS1"
    app.run()
    assert not app.exception
    assert any("Giacenza finale calcolata" in el.proto.body and "758,000" in el.proto.body for el in app.get("html"))
    for view,label in (("Utente","Giacenza finale"),("Limiti MGS","Vendita teorica massima")):
        app.radio(key="hs1_mode").set_value(view).run()
        assert not app.exception
        assert any(label in el.proto.body for el in app.get("html"))
