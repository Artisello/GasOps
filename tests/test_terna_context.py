from datetime import date,datetime,timedelta,timezone
import pandas as pd
import pytest
from gasops_app.terna_context import gas_days,parse_industry,batch,merge,join_context,latest_rows
from gasops_app.data import ROME
from gasops_app.entsog import _start

NOW=datetime(2026,11,18,12,tzinfo=timezone.utc)
DAY=date(2026,11,19)
SCOPE=["SUD_ISOLE","A2A","TERMOELETTRICO","GAS NATURALE"]

def records():
    return [{"market_date":t.astimezone(ROME).strftime("%Y-%m-%d %H:%M:%S"),"offset":"+01:00","date_tz":"Europe/Rome","macroarea":SCOPE[0],"macrouser_name":SCOPE[1],"plant_type":SCOPE[2],"prevailing_fuel":SCOPE[3],"available_capacity_MW":"350"}
        for t in pd.date_range(_start(DAY),_start(DAY+timedelta(days=1)),freq="h",inclusive="left")]

def test_capacity_units_scope_and_cutoff():
    raw=records()
    rows=gas_days("capacity",raw,DAY,DAY)
    assert rows==[{"period":str(DAY),"scope":SCOPE,"value":350.0,"hours":24}]
    assert gas_days("capacity",raw[:-1],DAY,DAY)==[]
    assert gas_days("capacity",raw+[{**raw[0],"available_capacity_MW":"400"}],DAY,DAY)==[]
    b=batch("capacity",rows,NOW)
    assert merge([], [b,b], NOW)==[b]
    samples=pd.DataFrame({"origin":[pd.Timestamp("2026-11-18")]},index=[pd.Timestamp(DAY)])
    df,cols=join_context(samples,[b],"capacity",SCOPE,pd.Timestamp("2026-11-20"))
    assert df[cols].iloc[0,0]==350
    df,cols=join_context(samples,[{**b,"acquired":"2026-11-18T15:01:00+00:00"}],"capacity",SCOPE,pd.Timestamp("2026-11-20"))
    assert pd.isna(df[cols].iloc[0,0])

def test_industry_scope_and_prior_period():
    ref=date(2026,9,1)
    raw={"result":{"status":"Completed"},"monthly_index_industrial_electrical_consumption":[
      {"year":"2026","month":"09","region":"Lombardia","sector":"CHIMICA","tension_type":"AT","consumption_Gwh":"9","monthly_imcei":"105"}]}
    rows=parse_industry(raw,ref)
    assert rows[0]["imcei"]==105 and rows[0]["value"]==9
    b=batch("industry",rows,NOW)
    assert merge([], [b], NOW)==[b]
    scope=rows[0]["scope"]
    assert latest_rows([b],"industry",scope,NOW,"imcei")[0]["value"]==105
    df=pd.DataFrame({"origin":[pd.Timestamp("2026-11-18")]},index=[pd.Timestamp(DAY)])
    r,cols=join_context(df,[b],"industry",scope,pd.Timestamp("2026-11-20"))
    assert r[cols].iloc[0,0]==105

def test_signed_exchange_and_incomplete_grid():
    raw=[{"date":r["market_date"],"date_offset":r["offset"],"date_tz":"Europe/Rome","country":"Austria","import":"50","export":"100","scheduled_foreign_exchange_MW":"-50"} for r in records()]
    rows=gas_days("exchange",raw,DAY,DAY)
    assert rows[0]["value"]==pytest.approx(-1.2)
    assert gas_days("exchange",raw[:-1],DAY,DAY)==[]
