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
