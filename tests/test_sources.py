from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json

import pandas as pd
import pymupdf
import pytest
import requests

from gasops_app import eurostat
from gasops_app.agents import Assumptions, MarketContext, RegulationArguments, regulation_result
from gasops_app.data import jrc_archive
from gasops_app.mensile import combine, load_monthly, parse_arera
from gasops_app.models import Kind, utc_now
from gasops_app.public_data import SourceUnavailable
from gasops_app.quality import inspect
from gasops_app.regulatory import Library, NETWORK, PIOMBINO
from gasops_app.store import Store
from gasops_app.workflow import run_workflow
from gasops_app.models import Agent


def test_pdf_retrieval_preserves_original_page():
    with pymupdf.open() as pdf:
        pdf.new_page().insert_text((50, 80), "Infrastructure index")
        pdf.new_page().insert_text((50, 80), "Calibration tolerance for metering equipment is audited annually.")
        content = pdf.tobytes()
    library = Library((("Technical annex.pdf", content), ("Broken.pdf", b"junk")))
    matches = library.search("calibration tolerance metering")
    assert matches[0].is_pdf
    assert matches[0].citation.page == 2
    assert "audited annually" in matches[0].citation.evidence
    assert library.documents[matches[0].citation.document].render(2).startswith(b"\x89PNG")
    assert library.errors
    assert not library.search("xyzzzunrelatedtoken")


def test_reviewed_edition_evidence_for_definition_and_exactly_seven_days():
    library = Library()
    definition = regulation_result(library, RegulationArguments(query="Come è definito il bilanciamento commerciale?"))
    assert definition.evidence[0].document == NETWORK and definition.evidence[0].page == 358
    notice = regulation_result(library, RegulationArguments(query="Cosa accade con un preavviso di sette giorni?"))
    assert notice.status == "review"
    gap = next(item for item in notice.findings if item.id == "notice-7")
    assert {(cite.document, cite.page) for cite in gap.citations} == {(PIOMBINO, 103), (PIOMBINO, 104)}
    assert "coefficient" not in notice.values


def _payload() -> dict:
    # A time-first layout exercises JSON-stat strides rather than relying on publisher axis order.
    balance_codes = tuple(reversed(eurostat.SERIES))
    months = (
        {"IC_OBS": 3600, "IC_CAL_MG": 3600, "IMP": 3780, "EXP": 180, "IPRD": 180, "STK_CHG_MG": 180},
        {"IMP": 1800, "EXP": 180, "IPRD": 360, "STK_CHG_MG": -360},
        {"IC_OBS": 7200, "IC_CAL_MG": 7200, "IMP": 7380, "EXP": 180, "IPRD": 720, "STK_CHG_MG": 720},
    )
    return {
        "source": "ESTAT", "class": "dataset", "updated": "2026-11-12T23:00:00+0100",
        "id": ["time", *eurostat.PARAMETERS, "nrg_bal"], "size": [3, 1, 1, 1, 1, len(balance_codes)],
        "dimension": {
            **{name: {"category": {"index": {code: 0}}} for name, code in eurostat.PARAMETERS.items()},
            "time": {"category": {"index": {"2026-08": 0, "2026-09": 1, "2026-10": 2}}},
            "nrg_bal": {"category": {"index": {code: i for i, code in enumerate(balance_codes)}}},
        },
        "value": {str(i * len(balance_codes) + j): month[code]
                  for i, month in enumerate(months) for j, code in enumerate(balance_codes) if code in month},
        "status": {str(2 * len(balance_codes) + balance_codes.index("IC_OBS")): "p"},
    }


def test_eurostat_sparse_periods_units_and_provisional_status():
    publication = datetime(2026, 11, 17, tzinfo=timezone.utc)
    result = eurostat.parse(_payload(), publication)
    assert result.origin.kind == Kind.HISTORICAL
    assert result.origin.grain == "monthly"
    assert result.rows["demand_gwh"].tolist() == ["1000.0", "", "2000.0"]
    assert result.rows["net_imports_gwh"].tolist() == [1000.0, 450.0, 2000.0]
    assert result.rows["stock_change_gwh"].tolist() == [50.0, -100.0, 200.0]
    assert result.rows["storage_gwh"].tolist() == [0.0, 100.0, 0.0]
    assert result.rows["source_flag"].tolist() == ["", "", "p"]
    assert result.rows["timestamp_utc"].str.endswith("+00:00").all()
    invalid = _payload()
    invalid["dimension"]["unit"] = {"category": {"index": {"MIO_M3": 0}}}
    with pytest.raises(ValueError, match="unit"):
        eurostat.parse(invalid, publication)


def test_eurostat_unavailable_keeps_verified_cache_and_never_substitutes(monkeypatch, tmp_path):
    def fail(*args, **kwargs):
        raise requests.Timeout()

    monkeypatch.setattr(requests, "get", fail)
    store = Store(tmp_path / "test.sqlite3")
    with pytest.raises(SourceUnavailable):
        eurostat.load(store)

    fetched = utc_now() - timedelta(days=2)
    store.cache(eurostat.CACHE_KEY, fetched.isoformat(), json.dumps(_payload()))
    result = eurostat.load(store, refresh=True)
    assert result.origin.cached and result.origin.refresh_failed
    assert result.origin.retrieved_at == fetched
    assert result.origin.kind == Kind.HISTORICAL


def _arera_html() -> str:
    return """<table><tr><td>2026</td><td>Euro/MWh</td><td>Euro/GJ</td><td>Euro/Smc*</td></tr>
      <tr><td>novembre</td><td>91,25</td><td></td><td></td></tr>
      <tr><td>ottobre</td><td><span>88,3585</span></td><td></td><td></td></tr>
      <tr><td>settembre</td><td>—</td><td></td><td></td></tr>
      <tr><td>2025</td><td></td><td></td><td></td></tr>
      <tr><td>dicembre</td><td>31,10</td><td></td><td></td></tr></table>"""


def test_arera_reads_the_published_unit_and_joins_exact_months():
    fetched = utc_now()
    prices = parse_arera(_arera_html(), fetched)
    assert prices.rows["2026-10-01"] == Decimal("88.3585")
    assert prices.rows["2025-12-01"] == Decimal("31.10")
    assert "2026-09-01" not in prices.rows
    assert prices.source.latest_period == "2026-11-01"
    joined = combine(eurostat.parse(_payload(), fetched), prices)
    usable = inspect(joined, fetched).usable
    assert joined.origin.companions == (prices.source,)
    assert usable.at[pd.Timestamp("2026-10-01"), "price_eur_mwh"] == 88.3585
    assert pd.isna(usable.at[pd.Timestamp("2026-09-01"), "price_eur_mwh"])
    assert usable.at[pd.Timestamp("2026-08-01"), "demand_gwh"] == 1000.0
    assert len(joined.rows) == 3
    with pytest.raises(ValueError, match="EUR/MWh"):
        parse_arera(_arera_html().replace("Euro/MWh", "Euro/Smc"), fetched)


def test_price_failure_preserves_actual_eurostat_without_filling(monkeypatch, tmp_path):
    source = eurostat.parse(_payload(), utc_now())

    def unavailable(*args, **kwargs):
        raise SourceUnavailable()

    monkeypatch.setattr("gasops_app.mensile.load_arera", unavailable)
    monkeypatch.setattr(eurostat, "load", lambda *_args, **_kwargs: source)
    bundle, warning = load_monthly(Store(tmp_path / "feeds.sqlite3"))
    assert bundle is source and warning.startswith("Prezzo ARERA")
    assert not bundle.origin.companions
    assert bundle.rows["price_eur_mwh"].eq("").all()


def test_offline_jrc_series_and_explicit_simulated_scenario():
    bundle = jrc_archive()
    assert bundle.origin.archive and bundle.origin.kind == Kind.HISTORICAL
    assert len(bundle.rows) == 2557
    assert bundle.rows["period"].iloc[0] == "2015-01-01"
    assert bundle.rows["period"].iloc[-1] == "2021-12-31"
    assert bundle.rows["demand_gwh"].iloc[-1] == 2227.698
    context = MarketContext(bundle, "Seasonal regression", utc_now())
    result = run_workflow(context, Library(), Assumptions(), "Cosa succede se la domanda aumenta del 10%?")
    assert not any(item.id == "stale" for item in result.findings)
    stress = result.results[Agent.SCENARIO]
    assert stress.values["baseline_kind"] == Kind.SYNTHETIC.value
    assert stress.evidence[0].document == "Italia · Dati di esempio"
    assert stress.values["kind"] == Kind.SIMULATION.value
    assert "non dati osservati" in stress.summary
