from datetime import date,datetime,timedelta,timezone
from decimal import Decimal as D
import pandas as pd
import pytest
from gasops_app.data import ROME
from gasops_app.intraday import merge_snapshot,archive_csv,evaluate,gas_end
from gasops_app.operating_rules import calendar,parse_balance,balance_checks,template
from gasops_app.operational_sources import jarvis_template

NOW=datetime(2026,11,18,14,tzinfo=ROME)


def raw(*lines):return (jarvis_template()+"\n".join(lines)+"\n").encode()


def test_merge_and_conflicts():
    a=raw("2026-11-18,2026-11-18T08:00:00+01:00,2200,-40,1000")
    b=raw("2026-11-18,2026-11-18T09:00:00+01:00,2200,-30,1000")
    r=merge_snapshot(None,a,NOW);r=merge_snapshot(r,b,NOW)
    assert len(r["versions"])==2
    assert len(merge_snapshot(r,b,NOW)["versions"])==2
    assert len(merge_snapshot(None,archive_csv(r["versions"]).encode(),NOW)["versions"])==2
    with pytest.raises(ValueError):merge_snapshot(r,raw("2026-11-18,2026-11-18T09:00:00+01:00,2200,-31,1000"),NOW)


def test_intraday_no_future_and_dst():
    day=NOW.date();rows=[]
    for i in range(65,0,-1):
        d=day-timedelta(days=i);end=gas_end(d)
        rows.extend([{"gas_day":d,"published_at":end-timedelta(hours=16),"sas_gwh":20.},
                     {"gas_day":d,"published_at":end-timedelta(minutes=30),"sas_gwh":25.}])
    rows.extend([{"gas_day":day,"published_at":NOW,"sas_gwh":10.},
                 {"gas_day":day,"published_at":gas_end(day)-timedelta(minutes=30),"sas_gwh":9999.}])
    p=evaluate(pd.DataFrame(rows),day,"sas_gwh",NOW)
    assert p["estimate"]==15 and p["n"]==65
    assert p["scores"]["mae_corrected"]==0 and p["scores"]["mae_raw"]==5
    assert p["scores"]["coverage_80"]==100
    assert p["remaining_hours"]==16


def test_calendar_and_gnc_residual():
    rows=calendar(date(2026,11,18),date(2026,10,1),{date(2026,11,30)})
    assert rows[0][1].hour==3 and rows[1][1].hour==11 and rows[1][1].minute==30
    assert rows[2][1]==date(2026,12,1) and rows[3][1]==date(2026,12,3)
    data=(template()+"2026-11-16,definitive,100,-5,80,2,1,3,8\n2026-11-17,definitive,100,0,90,1,2,-1,\n").encode()
    r=balance_checks(parse_balance(data,NOW),D(".01"))
    assert r[0]["GNC_calcolato"]==9 and r[0]["delta_GNC"]==1 and r[0]["esito"]=="Da verificare"
    assert r[1]["GNC_calcolato"]==8 and r[1]["delta_GNC"] is None
    with pytest.raises(ValueError):parse_balance((template()+"2026-11-18,definitive,100,0,90,1,2,0,7\n").encode(),NOW)



def test_gas_day_dst():
    assert gas_end(date(2026,3,28))-gas_end(date(2026,3,27))==timedelta(hours=23)
    assert gas_end(date(2026,10,24))-gas_end(date(2026,10,23))==timedelta(hours=25)


def test_network_and_calendar_panels_empty_without_demo():
    from streamlit.testing.v1 import AppTest
    app=AppTest.from_string("from gasops_app.operating_rules_page import network_panel,calendar_panel\nfrom gasops_app.models import utc_now\nfrom gasops_app.data import ROME\nnetwork_panel()\ncalendar_panel(utc_now().astimezone(ROME))").run()
    assert not app.exception
    assert len(app.metric)==0
    assert len(app.dataframe)==1
    assert len(app.dataframe[0].value)==6


def _sas_history(day, issued, count=65, error=5.):
    rows=[]
    for i in range(count,0,-1):
        d=day-timedelta(days=i)
        end=gas_end(d)
        rows.extend([{"gas_day":d,"published_at":end-(gas_end(day)-issued),"sas_gwh":20.},
                     {"gas_day":d,"published_at":end-timedelta(minutes=30),"sas_gwh":20.+error}])
    rows.append({"gas_day":day,"published_at":issued,"sas_gwh":-2.})
    return pd.DataFrame(rows)


def test_decision_support_candidate_and_distribution():
    from gasops_app.intraday import decision_support
    f=_sas_history(NOW.date(),NOW)
    r=decision_support(f,NOW.date(),NOW)
    assert r["status"]=="candidate"
    assert r["candidate"]["estimate"]==3.
    assert r["distribution"]=={"negative":0.,"zero":0.,"positive":1.}
    assert r["scores"]["mae_raw"]==5 and r["scores"]["mae_corrected"]==0
    assert r["scores"]["coverage_80"]==100 and r["scores"]["n"]==35


def test_decision_support_conservative_gates():
    from gasops_app.intraday import decision_support
    d=NOW.date()
    assert decision_support(_sas_history(d,NOW,20),d,NOW)["status"]=="insufficient"
    assert decision_support(_sas_history(d,NOW,35),d,NOW)["status"]=="unvalidated"
    assert decision_support(_sas_history(d,NOW,error=0),d,NOW)["status"]=="benchmark"
    assert decision_support(_sas_history(d,NOW),d,NOW+timedelta(hours=4))["status"]=="stale"
    near=gas_end(d)-timedelta(minutes=60)
    assert decision_support(_sas_history(d,near),d,near)["status"]=="near_close"


def test_decision_support_replay_no_future():
    from gasops_app.intraday import decision_support,replay_times
    d=NOW.date()
    frame=_sas_history(d,NOW)
    future=pd.DataFrame([{"gas_day":d,"published_at":gas_end(d)-timedelta(minutes=20),"sas_gwh":9999.}])
    frame=pd.concat([frame,future],ignore_index=True)
    tomorrow=gas_end(d)+timedelta(hours=1)
    assert replay_times(frame,d,tomorrow)==[NOW]
    assert decision_support(frame,d,tomorrow)["status"]=="replay_required"
    r=decision_support(frame,d,tomorrow,as_of=NOW)
    assert r["historical"] and r["published"]==-2. and r["candidate"]["estimate"]==3.
    with pytest.raises(ValueError):decision_support(frame,d,NOW,as_of=NOW)


def test_intraday_history_rejects_pre_gas_day_publication():
    from gasops_app.intraday import _pairs,gas_end
    # Equivalent cutoff on a normal day can precede its start when target day is 25 h.
    target=date(2026,10,24)
    prior=target-timedelta(days=2)
    issued=gas_end(target)-timedelta(hours=25)
    historical_start=gas_end(prior-timedelta(days=1))
    f=pd.DataFrame([{"gas_day":prior,"published_at":historical_start-timedelta(hours=1),"sas_gwh":2.},
                    {"gas_day":prior,"published_at":gas_end(prior)-timedelta(minutes=30),"sas_gwh":3.}])
    assert _pairs(f,"sas_gwh",target,issued,issued)==[]
