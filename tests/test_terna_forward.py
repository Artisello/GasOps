from datetime import datetime,date,timedelta,timezone
import pandas as pd
import pytest
from gasops_app.terna_forward import parse,merge,paired,join_forward,REQUIRED,STATE,outlook
from gasops_app.entsog import _start

DAY=date(2026,11,19)
NOW=datetime(2026,11,18,12,tzinfo=timezone.utc)

def payload(kind):
    from gasops_app.data import ROME
    rows=[]
    for t in pd.date_range(_start(DAY),_start(DAY+timedelta(days=1)),freq="h",inclusive="left"):
        local=t.astimezone(ROME)
        for zone in sorted(REQUIRED):
            rows.append({"reference_date":local.strftime("%Y-%m-%d %H:%M:%S"),"offset":"+01:00","date_tz":"Europe/Rome",
                         "session_type":"MSD1","zone":zone,"load_MW":"1000" if kind=="load" else "100",
                         "prevision_date":"2026-11-18 09:00:00","publication_date":"2026-11-18"})
    return {"result":{"status":"Completed"},"forecast_load":rows}


def test_full_coverage_and_partial_proxy():
    l=parse(payload("load"),"load",DAY,DAY,NOW)
    w=parse(payload("wind"),"wind",DAY,DAY,NOW)
    assert l[0]["gwh"]==168 and w[0]["gwh"]==pytest.approx(16.8)
    b={"acquired":NOW.isoformat(),"first":str(DAY),"last":str(DAY),"session":"MSD1","rows":l+w}
    assert paired(b)[0]["load_minus_wind_gwh"]==pytest.approx(151.2)
    assert merge([], [b,b], NOW)==[b]
    assert outlook({STATE:[b]},NOW)["n"]==1
    p=payload("wind");p["forecast_load"].pop()
    assert parse(p,"wind",DAY,DAY,NOW)==[]
    p=payload("load");p["forecast_load"].append({**p["forecast_load"][0],"load_MW":"500"})
    assert parse(p,"load",DAY,DAY,NOW)==[]


def test_forward_cutoff_and_no_backfill_leakage():
    b={"acquired":NOW.isoformat(),"first":str(DAY),"last":str(DAY),"session":"MSD1",
       "rows":parse(payload("load"),"load",DAY,DAY,NOW)+parse(payload("wind"),"wind",DAY,DAY,NOW)}
    d=pd.DataFrame({"origin":[pd.Timestamp("2026-11-18")]},index=[pd.Timestamp(DAY)])
    result,cols=join_forward(d,[b],pd.Timestamp("2026-11-20"))
    assert result[cols].notna().all(axis=None)
    late={**b,"acquired":"2026-11-18T15:01:00+00:00"}
    result,cols=join_forward(d,[late],pd.Timestamp("2026-11-20"))
    assert result[cols].isna().all(axis=None)


def test_partial_outlook_remains_visible_without_proxy():
    b={"acquired":NOW.isoformat(),"first":str(DAY),"last":str(DAY),"session":"MSD1","rows":parse(payload("load"),"load",DAY,DAY,NOW)}
    fact=outlook({STATE:[b]},NOW)
    assert fact["points"]==[{"day":str(DAY),"load":168.0}]
    assert paired(b)==[]
