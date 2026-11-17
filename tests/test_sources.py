from datetime import datetime, timedelta, timezone
import json

import pandas as pd
import pymupdf
import pytest
import requests

from gasops_app import eurostat
from gasops_app.agents import RegulationArguments, regulation_result
from gasops_app.models import Kind, utc_now
from gasops_app.regulatory import Library, NETWORK, PIOMBINO
from gasops_app.store import Store


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
    definition = regulation_result(library, RegulationArguments(query="How is commercial balancing defined?"))
    assert definition.evidence[0].document == NETWORK and definition.evidence[0].page == 358
    notice = regulation_result(library, RegulationArguments(query="What happens at exactly seven days of notice?"))
    assert notice.status == "review"
    gap = next(item for item in notice.findings if item.id == "notice-7")
    assert {(cite.document, cite.page) for cite in gap.citations} == {(PIOMBINO, 103), (PIOMBINO, 104)}
    assert "coefficient" not in notice.values


def _payload() -> dict:
    return {
        "source": "ESTAT", "class": "dataset", "updated": "2026-11-12T23:00:00+0100",
        "id": [*eurostat.PARAMETERS, "time"], "size": [1, 1, 1, 1, 1, 3],
        "dimension": {
            **{name: {"category": {"index": {code: 0}}} for name, code in eurostat.PARAMETERS.items()},
            "time": {"category": {"index": {"2026-08": 0, "2026-09": 1, "2026-10": 2}}},
        },
        "value": {"0": 3600, "2": 7200},
        "status": {"2": "p"},
    }


def test_eurostat_sparse_periods_units_and_provisional_status():
    publication = datetime(2026, 11, 17, tzinfo=timezone.utc)
    result = eurostat.parse(_payload(), publication)
    assert result.origin.kind == Kind.HISTORICAL
    assert result.origin.grain == "monthly"
    assert result.rows["demand_gwh"].tolist() == ["1000.0", "", "2000.0"]
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
    with pytest.raises(eurostat.SourceUnavailable):
        eurostat.load(store)

    fetched = utc_now() - timedelta(days=2)
    store.cache(eurostat.CACHE_KEY, fetched.isoformat(), json.dumps(_payload()))
    result = eurostat.load(store, refresh=True)
    assert result.origin.cached and result.origin.refresh_failed
    assert result.origin.retrieved_at == fetched
    assert result.origin.kind == Kind.HISTORICAL
