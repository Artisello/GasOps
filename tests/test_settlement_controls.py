from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal as D

import pytest

from gasops_app.gas_calendar import closed_gas_day, gas_day_bounds
from gasops_app.operations_ledger import BalanceRow, monthly_preview, sample_rows
from gasops_app.settlement_desk import archive_csv, daily_controls, merge_csv, monthly_summary
from gasops_app.reconciliation import Reported, reconcile_days
from gasops_app.bso_kpis import settlement_metrics


def test_incremental_import_retains_versions_and_rejects_conflict_atomically():
    initial = sample_rows()[:4]
    saved = merge_csv(None, archive_csv(initial).encode())
    revision = replace(initial[1], version=3, withdrawn=initial[1].withdrawn + 5)
    updated = merge_csv(saved, archive_csv([initial[1], revision]).encode())
    assert updated["rows"] == [*initial[:2], revision, *initial[2:]]
    assert updated["added"] == 1 and updated["unchanged"] == 1
    assert len(updated["hashes"]) == 2
    before = updated.copy()
    conflict = replace(revision, withdrawn=revision.withdrawn + 1)
    other_day = replace(revision, day=date(2026, 9, 3))
    with pytest.raises(ValueError, match="conflitto"):
        merge_csv(updated, archive_csv([other_day, conflict]).encode())
    assert updated == before


def test_registry_can_be_restored_and_reimported_without_duplicate_money():
    rows = sample_rows()
    saved = merge_csv(None, archive_csv(rows).encode())
    replay = merge_csv(saved, archive_csv(list(reversed(rows))).encode())
    assert replay["sha"] == saved["sha"]
    assert len(replay["rows"]) == len(rows) and replay["added"] == 0
    restored = merge_csv(None, archive_csv(saved["rows"]).encode())
    assert restored["rows"] == saved["rows"]
    assert restored["sha"] == saved["sha"]


def test_legacy_session_is_upgraded_without_losing_the_original_hash():
    rows = sample_rows()[:2]
    legacy = {"rows": rows, "name": "old.csv", "sha": "previous-source-hash"}
    result = merge_csv(legacy, archive_csv(rows).encode())
    assert result["hashes"][0] == legacy["sha"]
    assert legacy["rows"] == rows
    assert result["added"] == 0


def test_future_definitives_are_excluded_until_the_gas_day_has_closed():
    rows = sample_rows()
    cutoff = date(2026, 9, 10)
    days = daily_controls(rows, "DEMO-001", 2026, 9, closed_day=cutoff)
    summary = monthly_summary(days)
    assert summary["eligible"] == 10 and summary["pending"] == 20 and summary["closed"] == 10
    assert summary["exceptions"] == 0
    assert not summary["complete"]
    assert days[10]["cash_eur"] is not None  # Supplied amount remains inspectable.
    assert not days[10]["eligible"]
    assert days[10]["delta_cash_eur"] is None
    assert days[10]["version_delta_cash_eur"] is None
    assert "Giorno gas non concluso" in days[10]["issues"]
    assert summary["credits"] == sum((row["cash_eur"] for row in days[:10] if row["cash_eur"] > 0), D(0))
    assert monthly_preview(rows, "DEMO-001", 2026, 9, closed_day=cutoff)["status"] == "BLOCKED_REVIEW"
    metrics = settlement_metrics(rows, "DEMO-001", 2026, 9, cutoff)
    assert metrics["eligible"] == 10 and metrics["expected"] == 10


@pytest.mark.parametrize(("now", "last_closed"), [
    ("2026-09-02T03:59:59+00:00", "2026-08-31"),
    ("2026-09-02T04:00:00+00:00", "2026-09-01"),
    ("2026-11-02T04:59:59+00:00", "2026-10-31"),
    ("2026-11-02T05:00:00+00:00", "2026-11-01"),
])
def test_closed_gas_day_changes_at_six_local_time(now, last_closed):
    assert closed_gas_day(datetime.fromisoformat(now)) == date.fromisoformat(last_closed)


def test_naive_reference_time_is_rejected():
    with pytest.raises(ValueError, match="fuso"):
        closed_gas_day(datetime(2026, 11, 20, 6))


@pytest.mark.parametrize(("day", "hours"), [("2026-03-28", 23), ("2026-10-24", 25), ("2026-11-20", 24)])
def test_gas_day_retains_dst_elapsed_hours(day, hours):
    start, end = gas_day_bounds(date.fromisoformat(day))
    assert start.tzinfo == end.tzinfo == timezone.utc
    assert (end - start).total_seconds() == hours * 3600


def test_definitive_to_definitive_revision_is_separate_from_provisional_bridge():
    provisional, final = sample_rows()[:2]
    corrected = replace(final, version=3, withdrawn=final.withdrawn + 25, sell=D(39))
    rows = [provisional, final, corrected]
    day = daily_controls(rows, "DEMO-001", 2026, 9, closed_day=date(2026, 9, 30))[0]
    assert day["previous_version"] == 2 and day["previous_stage"] == "definitive"
    assert day["version_delta_cash_eur"] == corrected.cash - final.cash
    assert day["delta_cash_eur"] == corrected.cash - provisional.cash
    assert day["version_quantity_effect_eur"] + day["version_price_effect_eur"] == day["version_delta_cash_eur"]
    assert day["delta_ds_mwh"] == corrected.imbalance - provisional.imbalance


def test_conflicting_version_is_quarantined_independently_of_row_order():
    original = sample_rows()[:2]
    conflict = replace(original[-1], withdrawn=original[-1].withdrawn + 1)
    left = daily_controls([*original, conflict], "DEMO-001", 2026, 9)[0]
    right = daily_controls([conflict, *original], "DEMO-001", 2026, 9)[0]
    assert left == right and not left["eligible"]
    assert left["ds_mwh"] is None and left["cash_eur"] is None
    assert "Versioni duplicate o in conflitto" in left["issues"]
    reported = Reported("DEMO-001", original[0].day, 2, "REF", D(150), D(5700))
    result = reconcile_days([*original, conflict], [reported], "DEMO-001", 2026, 9, original[0].day)
    assert result[0]["status"] == "BILANCIO NON VALIDABILE" and result[0]["cash_delta"] is None


def test_inverted_prices_block_the_commercial_preview():
    rows = sample_rows()
    rows[1] = replace(rows[1], buy=D(35), sell=D(38))
    preview = monthly_preview(rows, "DEMO-001", 2026, 9)
    assert preview["status"] == "REVIEW_REQUIRED" and preview["price_order_review"]


@pytest.mark.parametrize("field,value", [("injected", D(-1)), ("withdrawn", D(-1)), ("version", True),
                                         ("day",date(2101,1,1)), ("day",date.max)])
def test_direct_ledger_call_rejects_invalid_physical_or_version_inputs(field, value):
    with pytest.raises(ValueError):
        replace(sample_rows()[0], **{field: value})


def test_explicit_cutoff_keeps_kpi_evaluation_independent_of_wall_clock():
    rows=[replace(row,day=date(2030,11,row.day.day)) for row in sample_rows()]
    metrics=settlement_metrics(rows,"DEMO-001",2030,11,date(2030,11,10))
    assert metrics["eligible"]==10 and metrics["expected"]==10
    assert all(row["closed"] for row in metrics["records"])


def test_settlement_page_exposes_both_revision_bridges_and_downloads():
    from streamlit.testing.v1 import AppTest

    original = sample_rows()
    corrected = replace(original[1], version=3, withdrawn=original[1].withdrawn + 25, sell=D(39))
    saved = merge_csv(None, archive_csv([*original, corrected]).encode())
    app = AppTest.from_string("from gasops_app.settlement_desk_page import panel\npanel()", default_timeout=20)
    app.session_state["settlement_desk_csv_v1"] = {**saved, "name": "example.csv"}
    app.run()
    assert not app.exception
    assert app.radio(key="daily_desk_comparison").value == "Ultime due versioni"
    downloads = {item.proto.id.rsplit("-", 1)[-1] for item in app.get("download_button")}
    assert "desk_archive_export" in downloads and "daily_desk_export" in downloads
    app.radio(key="daily_desk_comparison").set_value("Provvisorio → definitivo").run()
    assert not app.exception
