from decimal import Decimal as D

from gasops_app.acer_baf_2026 import report_2026_rows,all_baf_rows,zone_changes,SELECTED


def test_2026_coverage_and_italy():
    rows=report_2026_rows()
    assert len(rows)==83
    it={r["metric"]:r["value"] for r in rows if r["zone"]=="IT" and r["gas_year"]=="2024/2025"}
    assert it=={"imbalance_share":D("7.4"),"net_adjusted_neutrality":D("0.03"),"tso_buy_share":D("48")}
    assert len([r for r in rows if r["zone"]==SELECTED])==24
    by={(r["gas_year"],r["metric"]):r["value"] for r in rows if r["zone"]==SELECTED}
    assert by[("2024/2025","tso_action_days_share")]==D("32")
    assert by[("2024/2025","tso_action_volume_share")]==D("0.32")
    assert by[("2024/2025","imbalance_share")]==D("2.5")


def test_comparison_missing_and_rounded_values():
    rows=all_baf_rows()
    assert len(rows)==130
    for metric,expected in (("imbalance_share",D("-2.3")),("net_adjusted_neutrality",D("0.00")),("tso_buy_share",D("-42"))):
        it=next(r for r in zone_changes(rows,metric) if r["zone"]=="IT")
        assert it["delta"]==expected
    nl=next(r for r in zone_changes(rows,"imbalance_share") if r["zone"]=="NL")
    assert nl["2023/2024"] is None and nl["2024/2025"]==D("0") and nl["delta"] is None
    bg=next(r for r in zone_changes(rows,"net_adjusted_neutrality") if r["zone"]=="BG")
    assert bg["2024/2025"]==D("-0.02")
