from datetime import datetime, timezone

import pandas as pd
import pytest

from gasops_app import assistant_query as q, assistant_sources as src
from gasops_app.data_analyst import Series

NOW=datetime(2026,11,28,12,tzinfo=timezone.utc)


def test_relative_month_query_selects_national_imports_only():
    question="Come sono cambiate le importazioni di gas negli ultimi 12 mesi?"
    assert q.query_intent(question)
    p=q.build_plan(question,NOW)
    assert p=={"operation":"change","grain":"month","from":"2025-11-01","to":"2026-10-01",
               "metrics":[[src.MONTHLY,"imports_gwh"]]}


def test_range_query_selects_daily_srg():
    question="Media dei prelievi SRG dal 2026-11-01 al 2026-11-20"
    assert q.query_intent(question)
    p=q.build_plan(question,NOW)
    assert p["metrics"]==[[src.DAILY,"demand_gwh"]]
    assert p["from"]=="2026-11-01" and p["to"]=="2026-11-20"


@pytest.mark.parametrize("question",[
    "Media dei consumi nazionali negli ultimi 30 giorni",
    "Totale delle scorte negli ultimi 30 giorni",
    "Media del prezzo PSV negli ultimi 12 mesi",
    "Media e totale dei prelievi SRG negli ultimi 30 giorni",
    "Media del prezzo dell'elettricità negli ultimi 12 mesi",
    "Media delle importazioni in Germania negli ultimi 12 mesi",
    "Media dei prelievi SRG negli ultimi 91 giorni",
    "Media del CMEM,m negli ultimi 30 giorni",
    "Media delle importazioni da settembre 2026 a novembre 2026",
])
def test_unsupported_query_fails_closed(question):
    assert q.query_intent(question)
    with pytest.raises(ValueError):
        q.build_plan(question,NOW)


@pytest.mark.parametrize("question",[
    "Prezzo medio dell'elettricità ottobre 2026",
    "/scorte",
    "Previsione della domanda di gas nei prossimi 30 giorni",
    "Confronta le importazioni di ottobre 2026 e settembre 2026",
])
def test_other_paths_not_intercepted(question):
    assert not q.query_intent(question)


def item(source,field,dates,values,grain="month"):
    m=next(m for m in src.METRIC_CATALOG[source] if m.field==field)
    key=source+"|"+field
    return key,Series(key,m.label,m.unit,grain,"Italia",source,"https://example.org",
                     "Fixture","fixture",pd.Series(values,index=dates,dtype=float),False)


def test_sum_requires_full_window_and_uses_energy_unit():
    p=q.build_plan("Totale delle importazioni negli ultimi 3 mesi",NOW)
    k,s=item(src.MONTHLY,"imports_gwh",["2026-08-01","2026-09-01","2026-10-01"],[12,18,30])
    row=q.calculate(p,{k:s},{})["rows"][0]
    assert row["value"]==60 and row["unit"]=="GWh" and row["n"]==3
    k,s=item(src.MONTHLY,"imports_gwh",["2026-08-01","2026-10-01"],[12,30])
    row=q.calculate(p,{k:s},{})["rows"][0]
    assert row["value"] is None and row["n"]==2 and row["expected"]==3


def test_storage_ratio_change_is_percentage_points():
    p=q.build_plan("Variazione del riempimento degli stoccaggi negli ultimi 3 giorni",NOW)
    k,s=item("AGSI+","fill_pct",["2026-11-25","2026-11-26","2026-11-27"],[80,82,85],"gas_day")
    row=q.calculate(p,{k:s},{})["rows"][0]
    assert row["value"]==5 and row["unit"]=="p.p." and row["change_pct"] is None


def test_correlation_uses_exact_pair_of_metrics_and_complete_dates():
    p=q.build_plan("Correlazione tra prelievi SRG e riempimento degli stoccaggi negli ultimi 30 giorni",NOW)
    assert p["metrics"]==[["AGSI+","fill_pct"],[src.DAILY,"demand_gwh"]]
    dates=pd.date_range(p["from"],p["to"]).strftime("%Y-%m-%d")
    a,x=item("AGSI+","fill_pct",dates,range(30),"gas_day")
    b,y=item(src.DAILY,"demand_gwh",dates,range(0,60,2),"gas_day")
    result=q.calculate(p,{a:x,b:y},{})
    assert result["correlations"][0]["pearson"]==pytest.approx(1)
    assert result["correlations"][0]["n"]==30
    b,y=item(src.DAILY,"demand_gwh",dates[:-1],range(29),"gas_day")
    assert not q.calculate(p,{a:x,b:y},{})["correlations"]


def test_bad_plan_never_acquires(monkeypatch):
    monkeypatch.setattr(q,"acquire",lambda *a,**k:pytest.fail("Unexpected data acquisition"))
    report=q.query_report("Totale delle scorte negli ultimi 30 giorni",None,NOW)
    assert report.assumptions["assistant_data_query"] is True
    assert "assistant_query_evidence" not in report.assumptions
    assert report.mode=="Deterministic"


def test_report_keeps_serializable_local_evidence(monkeypatch):
    dates=["2026-08-01","2026-09-01","2026-10-01"]
    k,s=item(src.MONTHLY,"imports_gwh",dates,[10,20,30])
    monkeypatch.setattr(q,"acquire",lambda *a,**k:({s.id:s},{}))
    report=q.query_report("Media delle importazioni negli ultimi 3 mesi",None,NOW)
    assert report.mode=="Deterministic"
    assert report.assumptions["assistant_query_evidence"]["rows"][0]["value"]==20
    assert report.input_sha256 and not report.ai_usage
    report.model_dump_json()
