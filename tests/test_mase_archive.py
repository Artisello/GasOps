from decimal import Decimal

import pytest

from gasops_app.mase_archive import REPORTS, observations, read_report, report_rows, as_bcm
from gasops_app.warehouse import Warehouse


def test_archive_coverage_and_units():
    rows = observations()
    national = {(r["period"], r["grain"]): r for r in rows if r["geography"] == "IT"}
    assert len(rows) == 123
    assert len([r for r in national.values() if r["grain"] == "year"]) == 22
    assert national[("2004","year")]["value"] == "12.92"
    assert national[("2025","year")]["value"] == "3233083852"
    assert national[("2026-02","month")]["value"] == "218708141"
    assert ("2026-03","month") not in national
    assert as_bcm("3233083852", "Sm3") == Decimal("3.233083852")
    assert as_bcm("12.92", "bcm") == Decimal("12.92")


def test_reports_ingested_idempotently(tmp_path):
    w = Warehouse(tmp_path / "w.db")
    for source in REPORTS:
        raw = read_report(source)
        assert w.ingest(source, raw)["status"] == "validated"
        assert not w.ingest(source, raw)["new_snapshot"]
    assert sum(r["observations"] for r in w.manifest()) == len(observations())


def test_report_missing_or_wrong_unit():
    source = "mase_unmig_databook_2025"
    raw = read_report(source)
    with pytest.raises(ValueError):
        report_rows(source, raw.replace(b"12.92,bcm", b"12.92,Sm3"))
    with pytest.raises(ValueError):
        report_rows(source, b"\n".join(raw.splitlines()[:-1]))
