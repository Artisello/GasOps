import json
from datetime import date, datetime, timezone
from decimal import Decimal as D

import pytest

from gasops_app import gme_market as g
from gasops_app.assistant_lookup import gme_request


def records(day, price=10):
    return [{"FlowDate": int(day.strftime("%Y%m%d")), "Market": "MGP",
             "Zone": "PUN", "Hour": i, "Price": price}
            for i in range(1, g.pun_hours(day)+1)]


def parsed(rows, first, last=None):
    return g.parse(json.dumps(rows).encode(), "pun", last or first, first=first)


@pytest.mark.parametrize("day,hours", [
    (date(2026, 3, 29), 23), (date(2026, 10, 25), 25),
    (date(2026, 11, 17), 24),
])
def test_complete_day_and_dst(day, hours):
    assert g.pun_hours(day) == hours
    rows = records(day, -2)
    item = parsed(rows + [{**rows[0], "Zone": "NORD", "Price": 900}], day)
    assert len(item["rows"]) == hours
    assert g.pun_mean(item, day, day) == D(-2)
    assert g.pun_mean(parsed(rows[:-1], day), day, day) is None
    assert g.pun_mean(parsed([{**rows[0], "Price": None}] + rows[1:], day), day, day) is None
    with pytest.raises(ValueError):
        parsed(rows + [rows[0]], day)
    with pytest.raises(ValueError):
        parsed([{**rows[0], "Market": "GAS"}], day)


def test_period_uses_all_hours_and_does_not_fill_missing_days():
    first, last = date(2026, 10, 24), date(2026, 10, 25)
    item = parsed(records(first, 0) + records(last, 98), first, last)
    assert g.pun_mean(item, first, last) == D(50)
    assert g.pun_mean(parsed(records(first), first), first, last) is None
    assert g.pun_closed_day(datetime(2026, 11, 27, 23, 30, tzinfo=timezone.utc)) == date(2026, 11, 27)


def test_pun_intent_and_period():
    assert gme_request("PUN Index GME", None) == {"kinds": ["pun"], "day": None}
    assert gme_request("Prezzo medio dell'energia elettrica ottobre 2026", None)["pun_month"] == "2026-10-01"
    assert gme_request("PUN orario", None)["pun_unsupported"]
    assert gme_request("PUN 2026", None)["pun_unsupported"]
    assert gme_request("PUN 2026-11-17", date(2026, 11, 17))["day"] == "2026-11-17"
    assert gme_request("PUN 2026-11-17 e 2026-11-18", None)["pun_unsupported"]
    assert gme_request("Consumi elettrici", None) is None
