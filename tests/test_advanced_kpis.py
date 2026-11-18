from datetime import datetime,timezone,date
from decimal import Decimal
import pandas as pd
from gasops_app.advanced_kpis import (operations_scores,balancing_scores,archive_scores,participant_scores,
    benchmark_scores,historical_scores,storage_scores,network_scores,export_csv)
from gasops_app.bso_kpis import parse_tasks
from gasops_app.jarvis_archive import parse_extract,template

NOW=datetime(2026,11,18,12,tzinfo=timezone.utc)


def test_missing_not_zero():
    rows=operations_scores(None,NOW,2026,11)+balancing_scores(None,NOW,2026,11)+archive_scores([],NOW,2026,11,"withdrawals","GWh")+participant_scores(None,None,NOW,2026,11)
    assert len(rows)==10
    assert all(r.value is None and r.status=="Non disponibile" for r in rows)
    assert all(r.value is None for r in storage_scores(None,NOW)+network_scores(None,NOW))


def test_operations_and_sas_cohorts():
    tasks=parse_tasks(b"task_id,area,activity,due_at,completed_at\nA,operations,Test,2026-11-15,2026-11-15\nB,operations,Test,2026-11-16,\nC,operations,Test,2026-10-01,\n")
    a,b,c=operations_scores(tasks,NOW,2026,11)
    assert a.value==50 and b.value==2 and c.value==0
    frame=pd.DataFrame([{"gas_day":date(2026,11,10),"published_at":datetime(2026,11,10,10,tzinfo=timezone.utc),"sas_gwh":-10},
                        {"gas_day":date(2026,11,10),"published_at":datetime(2026,11,10,11,tzinfo=timezone.utc),"sas_gwh":20}])
    a,b,c=balancing_scores({"versions":frame},NOW,2026,11)
    assert a.value==20 and b.value==20 and c.value==100/17 and "1/17" in a.coverage


def test_aggregate_revisions_same_unit_and_month():
    records=parse_extract((template()+"\n".join([
        "balance,2026-11-01,2026-11-02T10:00+01:00,provisional,SRG,withdrawals,GWh,100,P",
        "balance,2026-11-01,2026-11-03T10:00+01:00,definitive,SRG,withdrawals,GWh,103,D",
        "balance,2026-11-02,2026-11-03T10:00+01:00,provisional,SRG,withdrawals,GWh,100,P",
        "balance,2026-11-02,2026-11-04T10:00+01:00,definitive,SRG,withdrawals,MWh,102000,D",
        "balance,2026-10-01,2026-10-02T10:00+02:00,provisional,SRG,withdrawals,GWh,100,P",
        "balance,2026-10-01,2026-10-03T10:00+02:00,definitive,SRG,withdrawals,GWh,150,D"])+"\n").encode(),now=NOW)
    a,b=archive_scores(records,NOW,2026,11,"withdrawals","GWh")
    assert a.value==100 and b.value==3 and "1/2" in a.coverage
    assert archive_scores(records,NOW,2026,11,"withdrawals","MWh")[0].value is None


def test_historical_provenance_and_export():
    rows=benchmark_scores()+historical_scores(None,NOW)
    assert len(rows)==7
    by={r.code:r for r in rows}
    assert by["baf_imbalance_share"].value==7.4
    assert by["mase_prod"].value==float(Decimal("3.233083852"))
    assert by["terna_gas"].value==126.9
    assert by["lng"].status=="Storico / non recente"
    csv=export_csv(rows)
    assert "2024/2025" in csv and "source_url" in csv
