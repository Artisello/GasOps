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


def test_attempt_diagnostics_do_not_infer_api_success_from_data():
    assert h.acquisition_diagnostic(NOW)["attempt_outcome"]=="not_recorded"
    rows=h.session_health({},NOW)
    assert all(r["attempt"] is None and r["attempt_outcome"]=="not_recorded" for r in rows)


def test_attempt_diagnostics_choose_latest_known_attempt_without_raw_content():
    old={"at":(NOW-timedelta(hours=2)).isoformat(),"outcome":"acquired"}
    latest={"at":NOW.isoformat(),"failed":True,"reason_code":"access_denied","duration_seconds":1.5,
            "note":"fixture-secret"}
    future={"at":(NOW+timedelta(minutes=1)).isoformat(),"outcome":"acquired"}
    result=h.acquisition_diagnostic(NOW,("manual_source_batch",old),("operational_source_window",latest),("future",future))
    assert result["attempt"]==NOW.isoformat() and result["attempt_outcome"]=="failed"
    assert result["attempt_reason_code"]=="access_denied" and result["attempt_duration_seconds"]==1.5
    assert "fixture-secret" not in str(result)


def test_operational_journal_visible_without_loaded_inventory():
    state={"operational_acquisition":{"connections":{"agsi":{"at":NOW.isoformat(),"outcome":"no_observation","partial":True}}}}
    row=next(r for r in h.session_health(state,NOW) if r["source"]=="GIE · AGSI+")
    assert row["attempt"]==NOW.isoformat() and row["attempt_outcome"]=="no_observation"
    assert not row["refresh_failed"] and row["valid"]==0


def test_point_attempt_scope_is_exact_day_and_not_a_network_probe():
    day=date(2026,11,17)
    state={"operational_acquisition":{"attempts":{"p":{day.isoformat():[NOW.isoformat(),True,True]}}}}
    assert h.point_attempt(state,"p",day,NOW)["attempt_basis"]=="point_physical_flow"
    assert h.point_attempt(state,"p",day,NOW)["attempt_outcome"]=="completed_unverified"
    assert h.point_attempt(state,"p",day-timedelta(days=1),NOW)["attempt_outcome"]=="not_recorded"


def test_error_code_is_bounded():
    from gasops_app.public_data import acquisition_error_code,SourceUnavailable
    assert acquisition_error_code(SourceUnavailable("Terna: HTTP 403."))=="access_denied"
    assert acquisition_error_code(SourceUnavailable("GIE: HTTP 429."))=="rate_limit"
    assert acquisition_error_code(ValueError("secret string"))=="validation_or_unavailable"
