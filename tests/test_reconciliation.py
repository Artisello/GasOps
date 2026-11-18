from datetime import date
from decimal import Decimal as D
import pytest
from gasops_app.operations_ledger import sample_rows
from gasops_app import reconciliation as m

CLOSE=date(2026,9,30)
USER="DEMO-001"


def report(rows):
    lines=[f"{x.user},{x.day},{x.version},REF-{x.day.day},{x.imbalance},{x.cash}" for x in rows if x.stage=="definitive"]
    return (m.template()+"\n".join(lines)+"\n").encode()


def test_complete_and_differences():
    balances=sample_rows()
    data=m.parse_report(report(balances),CLOSE)
    result=m.reconcile_days(balances,data["rows"],USER,2026,9,CLOSE)
    assert m.score(result)==dict(expected=30,compared=30,matched=30,exceptions=0,gross_difference=D(0),unknown=0)
    from dataclasses import replace
    changed=[replace(x,cash=x.cash+D(100),ds=x.ds+D(1)) if x.day.day==5 else replace(x,cash=x.cash-D(100)) if x.day.day==6 else x for x in data["rows"]]
    result=m.reconcile_days(balances,changed,USER,2026,9,CLOSE)
    assert m.score(result)["gross_difference"]==D(200)
    assert m.score(result)["exceptions"]==2


def test_version_and_missing_not_zero():
    from dataclasses import replace
    balances=sample_rows()
    data=m.parse_report(report(balances),CLOSE)["rows"]
    revised=replace(data[0],version=3)
    result=m.reconcile_days(balances,[*data[:-1],revised],USER,2026,9,CLOSE)
    assert result[0]["status"]=="VERSIONE DISCORDANTE" and result[0]["cash_delta"] is None
    assert result[-1]["status"]=="ESTRATTO ASSENTE"
    assert m.score(result)["unknown"]==2
    assert len(m.reconcile_days(balances,data,USER,2026,9,date(2026,9,10)))==10


def test_import_conflicts_rejected():
    line="DEMO-001,2026-09-01,2,R1,150,5700\n"
    assert len(m.parse_report((m.template()+line+line).encode(),CLOSE)["rows"])==1
    with pytest.raises(ValueError):m.parse_report((m.template()+line+line.replace("5700","5701")).encode(),CLOSE)
    with pytest.raises(ValueError):m.parse_report((m.template()+line).encode(),date(2026,8,31))
    with pytest.raises(ValueError):m.parse_report((m.template()+line.replace("5700","NaN")).encode(),CLOSE)


def test_documents_no_netting_multiple_or_incomplete():
    balances=sample_rows()
    from gasops_app.operations_ledger import monthly_preview
    p=monthly_preview(balances,USER,2026,9)
    raw=(m.template(m.DOCUMENT_FIELDS)+f"{USER},2026-09,short,F1,{p['short_group_eur']+100},2026-10-29\n"+
         f"{USER},2026-09,long,F2,{p['long_group_eur']-100},2026-10-29\n").encode()
    docs=m.parse_documents(raw,date(2026,11,18))["rows"]
    result=m.reconcile_documents(balances,docs,USER,2026,9,CLOSE)
    assert [r["delta"] for r in result]==[D(100),D(-100)]
    assert all(r["status"]=="DIFFERENZA" for r in result)
    from dataclasses import replace
    r=m.reconcile_documents(balances,[*docs,replace(docs[0],identifier="F3")],USER,2026,9,CLOSE)
    assert r[0]["status"]=="MULTIPLA · VERIFICA" and r[0]["delta"] is None
    assert all(r["expected"] is None for r in m.reconcile_documents(balances[:-2],docs,USER,2026,9,CLOSE))
    assert all(r["expected"] is None for r in m.reconcile_documents(balances,docs,USER,2026,9,date(2026,9,29)))


def test_document_date_and_duplicate():
    line="DEMO-001,2026-09,short,F1,100,2026-10-29\n"
    h=m.template(m.DOCUMENT_FIELDS)
    assert len(m.parse_documents((h+line+line).encode(),date(2026,11,18))["rows"])==1
    with pytest.raises(ValueError):
        m.parse_documents((h+line.replace("2026-10-29","2026-09-29")).encode(),date(2026,11,18))
    with pytest.raises(ValueError):
        m.parse_documents((h+line+line.replace(",100,",",101,")).encode(),date(2026,11,18))
