from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pandas as pd
import pytest

from gasops_app.italiano import numero
from gasops_app.overview_indicators import price_snapshot
from gasops_app.supply_view import inventory_snapshot
from gasops_app.visuals import _kpi_markup


@pytest.mark.parametrize("value",[None,float("nan"),float("inf"),Decimal("NaN"),Decimal("Infinity")])
def test_missing_number(value):
    assert numero(value,2)=="—"
    markup=_kpi_markup("Prezzo",value,"€/MWh","Fonte ARERA",2,"teal")
    assert "gas-kpi-missing" in markup and "Non disponibile" in markup
    assert "€/MWh" not in markup and "Fonte ARERA" in markup


def test_zero_not_missing_and_negative_zero_normalized():
    assert numero(0,2)=="0,00"
    assert numero(Decimal("-0.001"),2)=="0,00"
    assert numero(Decimal("-0.001"),2,signed=True)=="+0,00"
    assert numero(Decimal("-1.25"),2)=="-1,25"
    assert "gas-kpi-missing" not in _kpi_markup("Saldo",0,"€","",2)


def test_price_invalid_latest_not_replaced_with_older():
    now=datetime(2026,11,18,tzinfo=timezone.utc)
    source=SimpleNamespace(refresh_failed=False,retrieved_at=now)
    with pytest.raises(ValueError,match="non valido"):
        price_snapshot(SimpleNamespace(rows={"2026-09-01":35,"2026-10-01":float("nan")},source=source),now)


def test_inventory_invalid_and_duplicate_rows():
    with pytest.raises(ValueError):
        inventory_snapshot(pd.DataFrame({"gas_day":[date(2026,11,17)],"stock_twh":[float("inf")]}),"AGSI+")
    frame=pd.DataFrame({"gas_day":[date(2026,11,17)]*2,"stock_twh":[10,11]})
    with pytest.raises(ValueError,match="Più osservazioni"):
        inventory_snapshot(frame,"AGSI+")
