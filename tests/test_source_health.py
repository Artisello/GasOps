from datetime import date,datetime,timedelta,timezone
from decimal import Decimal as D
import pandas as pd
from gasops_app import source_health as h
from gasops_app.data import frame_bundle,utc_starts
from gasops_app.models import Origin,Kind

NOW=datetime(2026,11,18,12,tzinfo=timezone.utc)


def test_empty_and_forecast_not_observed(monkeypatch):
    monkeypatch.setenv("IGOR_WEATHER_ENABLED","1")
    rows=h.session_health({},NOW)
    assert len(rows)==10
    assert all(r["valid"]==0 and r["status"].startswith("Non disponibile") for r in rows)
    assert next(r for r in rows if r["source"]=="Open-Meteo · outlook")["kind"]=="Previsione"


def test_attempt_and_coverage():
    end=date(2026,11,17)
    args=("source","scope","Osservato",{end:10},h.dates(end,2),NOW)
    assert h.row(*args,acquired=NOW-timedelta(hours=1))["status"]=="Da verificare"
    failed={"status":"Da aggiornare","at":NOW.isoformat()}
    assert h.row(*args,acquired=NOW-timedelta(hours=1),attempt=failed)["status"].startswith("Aggiornamento fallito")
    older={"status":"Da aggiornare","at":(NOW-timedelta(hours=2)).isoformat()}
    assert h.row(*args,acquired=NOW-timedelta(hours=1),attempt=older)["status"]=="Da verificare"


def test_same_entsog_scope_delta():
    index=pd.DatetimeIndex(["2026-11-16","2026-11-17"])
    f=pd.DataFrame({"period":index.strftime("%Y-%m-%d"),"timestamp_utc":[x.isoformat() for x in utc_starts(index,"daily")],
                    "energy_unit":"GWh","price_unit":"","source_flag":"","demand_gwh":[50,60],"power_gwh":[10,20]})
    b=frame_bundle(f,Origin(name="ENTSOG",url=h.ENTSOG_SOURCE,kind=Kind.HISTORICAL,fields=("demand_gwh","power_gwh"),
                     grain="daily",description="fixture",retrieved_at=NOW-timedelta(hours=1)))
    state={"live_public_bundles_v1":{"daily":b},"terna_power_v1":{"gas":{"gas":{"2026-11-16":10,"2026-11-17":21,"2026-11-18":99},
                             "acquired":NOW.isoformat()}}}
    r=h.compare_srg(state,NOW)
    assert len(r)==2 and r[0]["status"]=="Coincide" and r[1]["delta_gwh"]==D(1)
    assert h.session_health(state,NOW)[2]["valid"]==2


def test_future_acquisition_not_counted():
    d=date(2026,11,17)
    r=h.row("x","scope","Osservato",{d:1},[d],NOW,acquired=NOW+timedelta(minutes=1))
    assert r["status"]=="Timestamp futuro" and r["valid"]==0 and r["latest"] is None


def test_monthly_inspection_reused(monkeypatch):
    from gasops_app import live_sources as ls
    index=pd.DatetimeIndex(["2026-09-01","2026-10-01"])
    f=pd.DataFrame({"period":index.strftime("%Y-%m-%d"),"timestamp_utc":[x.isoformat() for x in utc_starts(index,"monthly")],
                    "energy_unit":"GWh","price_unit":"EUR/MWh","source_flag":"","demand_gwh":[50,60],"price_eur_mwh":[10,20]})
    b=frame_bundle(f,Origin(name="fixture",kind=Kind.HISTORICAL,fields=("demand_gwh","price_eur_mwh"),
                           grain="monthly",description="fixture",retrieved_at=NOW))
    state={ls.BUNDLES:{"monthly":b}}
    original=ls.inspect
    calls=[]
    def counted(*args):
        calls.append(1)
        return original(*args)
    monkeypatch.setattr(ls,"inspect",counted)
    cache={}
    assert len(ls.market_scores(state,NOW,inspections=cache))==2
    assert h.session_health(state,NOW,inspections=cache)[1]["valid"]==2
    assert len(calls)==1
    h.session_health(state,NOW)
    assert len(calls)==2
