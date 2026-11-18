from datetime import datetime, timezone
from decimal import Decimal

import pytest

from gasops_app.jarvis_archive import (template,parse_extract,import_session,revision_rows,latest_records,export_csv)

NOW=datetime(2026,11,18,tzinfo=timezone.utc)
HEAD=template()
PROV="balance,2026-09-01,2026-09-02T12:00+02:00,provisional,SRG,withdrawals,GWh,100,Report P"
FINAL="balance,2026-09-01,2026-11-15T12:00+01:00,definitive,SRG,withdrawals,GWh,104,Report D"


def raw(*rows):
    return (HEAD+"\n".join(rows)+"\n").encode()


def test_incremental_revision_and_idempotence():
    first=import_session(None,raw(PROV),now=NOW)
    second=import_session(first,raw(FINAL),now=NOW)
    duplicate=import_session(second,raw(FINAL),now=NOW)
    assert len(first["records"])==1 and len(duplicate["records"])==2
    assert len(duplicate["hashes"])==2
    row=revision_rows(duplicate["records"])[0]
    assert row["delta"]==Decimal("4")
    assert row["versions"]==2
    assert "user-declared public extract" in export_csv(duplicate["records"])


def test_conflicts_reject_whole_import():
    state=import_session(None,raw(PROV),now=NOW)
    with pytest.raises(ValueError):
        import_session(state,raw(FINAL,PROV.replace(",100,",",105,")),now=NOW)
    assert len(state["records"])==1


def test_units_not_joined_and_unpaired_not_zero():
    rs=parse_extract(raw(PROV,FINAL.replace("GWh,104","MWh,104000")),now=NOW)
    assert len(revision_rows(rs))==2
    assert all(r["delta"] is None for r in revision_rows(rs))


def test_later_provisional_not_final():
    later=PROV.replace("2026-09-02T12:00+02:00","2026-11-17T12:00+01:00")
    rs=parse_extract(raw(PROV,FINAL,later),now=NOW)
    assert revision_rows(rs)[0]["delta"] is None


def test_profile_versions_separate():
    a="wkr,2026-09-01,2026-08-31T10:00+02:00,forecast,climate:A,wkr,ratio,1.2,Report W"
    b=a.replace("2026-08-31T10:00+02:00,forecast","2026-09-02T10:00+02:00,observed").replace("1.2","1.1")
    q="q,2026-09-01,2026-11-01T10:00+01:00,published,cluster:X,q,percent,-0.02,Report Q"
    rs=parse_extract(raw(a,b,q),now=NOW)
    assert len(latest_records(rs))==2
    assert revision_rows(rs)==[]


@pytest.mark.parametrize("bad",[
    PROV.replace(",SRG,",",SHIPPER1,"),
    PROV.replace("+02:00",""),
    PROV.replace(",100,",",NaN,"),
    PROV.replace(",100,",",-1,"),
    PROV.replace("2026-09-02T12:00+02:00","2026-11-19T12:00+01:00"),
    PROV.replace(",Report P",",=BAD"),
    PROV.replace("2026-09-01","2026-02-30"),
])
def test_invalid_rows(bad):
    with pytest.raises(ValueError):
        parse_extract(raw(bad),now=NOW)
