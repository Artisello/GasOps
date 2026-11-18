from datetime import datetime,date,timezone
from gasops_app.management_report import report,markdown
from gasops_app.operations_ledger import sample_rows
from gasops_app.credit_snapshot import reconstruct,example
from gasops_app.market_efficiency import parse,template
from decimal import Decimal as D

NOW=datetime(2026,11,18,12,tzinfo=timezone.utc)


def test_empty_is_not_green(monkeypatch):
    monkeypatch.setenv("IGOR_WEATHER_ENABLED","1")
    r=report({},NOW,2026,11)
    assert r["closed_days"]==17
    assert len(r["signals"])==7
    assert not any(s["priority"]=="Alta" for s in r["signals"])
    assert any(s["area"]=="Credit Risk" for s in r["signals"])
    assert len(r["metrics"])==1 and r["metrics"][0]["area"]=="Data Quality"
    assert "non certificati" in markdown(r)


def test_credit_scope_and_period_and_exclusion():
    saved=reconstruct(example(),NOW.date())
    state={"credit_analytical_snapshot_v1":saved,"settlement_desk_csv_v1":{"rows":sample_rows()}}
    r=report(state,NOW,2026,9,"DEMO-001")
    credit=next(m for m in r["metrics"] if m["label"]=="EPSu")
    assert credit["period"]=="2026-11-18" and credit["value"]==D(883600)
    assert all(m["period"].startswith("2026-09") for m in r["metrics"] if m["area"]=="Settlement")
    assert "DEMO-001" not in markdown(r)
    saved["as_of"]="2026-11-17";saved["position"]["status"]="LIMITE"
    r=report(state,NOW,2026,9,"DEMO-001")
    assert any(s["title"]=="Snapshot credito storico" for s in r["signals"])
    assert not any(s["area"]=="Credit Risk" and s["priority"]=="Alta" for s in r["signals"])


def test_market_scope_and_partial():
    raw=(template()+"2026-11-01,title,complete,100,40,4500,1400,40\n2026-11-01,storage,complete,5,0,200,0,\n").encode()
    r=report({"market_efficiency_v1":parse(raw,date(2026,11,17))},NOW,2026,11)
    costs=[m for m in r["metrics"] if m["label"].startswith("Costo netto")]
    assert len(costs)==2 and {m["value"] for m in costs}=={D(3100),D(200)}
    assert all(m["status"]=="Parziale" for m in costs)


def test_malformed_isolated():
    r=report({"credit_analytical_snapshot_v1":{"bad":True}},NOW,2026,11)
    assert any(s["title"]=="Controllo non elaborabile" and s["area"]=="Credit Risk" for s in r["signals"])
    assert any(m["area"]=="Data Quality" for m in r["metrics"])
