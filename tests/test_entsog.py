import json
from datetime import date,datetime,timedelta,timezone

import pytest

from gasops_app.entsog import POINTS, combine, gas_timestamp, month_windows, parse_month, _last_completed
from gasops_app.quality import inspect

NOW=datetime(2026,11,18,12,tzinfo=timezone.utc)
DAY=date(2026,11,16)

def record(point,day=DAY,value=1_000_000):
    return {"operatorKey":point[:11],"pointKey":point[11:-4],"directionKey":"exit",
            "indicator":"Physical Flow","periodType":"day","unit":"kWh/d",
            "periodFrom":day.isoformat()+"T06:00:00+01:00",
            "periodTo":(day+timedelta(days=1)).isoformat()+"T06:00:00+01:00",
            "flowStatus":"Provisional","value":value}

def test_complete_three_points_and_missing_period():
    records=[record(p,value=1_000_000*(i+1)) for i,p in enumerate(POINTS)]
    records.append(record(next(iter(POINTS)),DAY+timedelta(days=1)))
    m=parse_month({"operationalData":records},DAY,DAY+timedelta(days=1),NOW)
    bundle=combine([m],DAY,DAY+timedelta(days=1))
    values=inspect(bundle,NOW).usable
    assert values.iloc[0]["demand_gwh"]==6
    assert values["demand_gwh"].isna().sum()==1
    assert values["supply_gwh"].isna().all()
    assert bundle.origin.latest_period==DAY.isoformat()
    assert not bundle.origin.archive

def test_unknown_unit_and_no_complete_rejected():
    rows=[record(p) for p in POINTS]
    with pytest.raises(ValueError,match="Nessun giorno"):
        parse_month({"operationalData":rows[:2]},DAY,DAY,NOW)
    rows[0]["unit"]="m3/d"
    with pytest.raises(ValueError,match="Unità"):
        parse_month({"operationalData":rows},DAY,DAY,NOW)

def test_conflicts_not_double_counted():
    rows=[record(p) for p in POINTS]
    next_day=DAY+timedelta(days=1)
    rows += [record(p,next_day) for p in POINTS]
    rows.append(record(next(iter(POINTS)),next_day,2_000_000))
    m=parse_month({"operationalData":rows},DAY,next_day,NOW)
    bundle=combine([m],DAY,next_day)
    assert inspect(bundle,NOW).usable["demand_gwh"].isna().sum()==1
    assert "versioni_in_conflitto" in bundle.rows.iloc[1]["source_flag"]

def test_gas_day_dst_and_windows():
    assert gas_timestamp("2026-10-24T06:00:00+02:00")[1].hour==4
    assert gas_timestamp("2026-10-25T06:00:00+01:00")[1].hour==5
    assert gas_timestamp("2026-11-16T05:00:00")[2]
    with pytest.raises(ValueError):
        gas_timestamp("2026-11-16T01:00:00")
    assert _last_completed(NOW)==date(2026,11,17)
    assert _last_completed(NOW.replace(hour=2))==date(2026,11,16)
    assert list(month_windows(DAY,2))==[(date(2026,11,1),DAY),(date(2026,10,1),date(2026,10,31))]
