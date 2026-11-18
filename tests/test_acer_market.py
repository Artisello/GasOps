from datetime import datetime,timezone
from decimal import Decimal
import pytest
from gasops_app.acer_market import parse_lng,with_spreads,bundled_lng,balancing_rows,lng_export

NOW=datetime(2026,11,18,12,tzinfo=timezone.utc)
HEAD="Date,North-West Europe price (EUR/MWh),South Europe price (EUR/MWh),EU price (EUR/MWh),LNG Benchmark (EUR/MWh)\n"


def test_public_archive_and_benchmark():
    result=bundled_lng()
    assert len(result.rows)==19
    assert result.rows[0]["date"]=="2026-09-01"
    assert result.rows[-1]["eu"]==Decimal("74.114")
    assert with_spreads(result.rows)[-1]["south_minus_nwe"]==Decimal("0.965")
    assert "ACER" in lng_export(result)
    rows=balancing_rows()
    assert len(rows)==47
    it={r["metric"]:r["value"] for r in rows if r["zone"]=="IT"}
    assert it=={"imbalance_share":Decimal("9.7"),"net_adjusted_neutrality":Decimal("0.03")}


def test_missing_signed_and_idempotent():
    line="2026.11.11,85.215,84.653,84.573,-2.079\n"
    result=parse_lng(HEAD+line+line+"2026.11.12,,NA,80.0,\n",NOW)
    assert len(result.rows)==2
    assert result.rows[0]["benchmark"]==Decimal("-2.079")
    assert with_spreads(result.rows)[0]["south_minus_nwe"]==Decimal("-0.562")
    assert with_spreads(result.rows)[1]["south_minus_nwe"] is None


@pytest.mark.parametrize("text",[HEAD+"2026-11-19,1,2,3,4\n",HEAD+"2026-11-10,1,2,3,4\n2026-11-10,1,2,3,5\n",
    HEAD.replace("EUR/MWh","USD/MMBtu")+"2026-11-10,1,2,3,4\n",
    HEAD+"2026-11-10,1,2,NaN,4\n","<html>bad</html>"])
def test_invalid_csv(text):
    with pytest.raises(ValueError):
        parse_lng(text,NOW)
