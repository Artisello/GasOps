from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID

import pytest

from gasops_app import terna_power as power
from gasops_app.terna_diagnostics import probe
from gasops_app.public_data import cached_only, SourceUnavailable

NOW = datetime(2026, 11, 28, 12, tzinfo=timezone.utc)


def test_oauth_403_is_distinct_and_not_repeated_in_batch(monkeypatch):
    calls = []

    @contextmanager
    def request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        yield SimpleNamespace(status_code=403)

    monkeypatch.setattr(power.requests, "request", request)
    with power.token_batch():
        for _ in range(3):
            with pytest.raises(power.TernaHTTPError) as error:
                power.get_token("fixture-id", "fixture-secret")
            assert error.value.status == 403
            assert "OAuth" in str(error.value)
            assert "fixture-secret" not in str(error.value)
    assert len(calls) == 1
    assert calls[0][2]["headers"]["Content-Type"] == "application/x-www-form-urlencoded"


def test_service_403_contains_safe_correlation_id(monkeypatch):
    monkeypatch.setattr(power, "get_token", lambda *_: "fixture-token")
    calls = []

    @contextmanager
    def request(method, url, **kwargs):
        calls.append(kwargs)
        yield SimpleNamespace(status_code=403)

    monkeypatch.setattr(power.requests, "request", request)
    result = probe("id", "secret", "Total Load", now=NOW)
    assert result["oauth"] == "OK"
    assert result["status"] == "HTTP 403"
    assert result["business_id"] == calls[0]["headers"]["businessID"]
    UUID(result["business_id"])
    assert "fixture-token" not in str(result)
    assert calls[0]["allow_redirects"] is False


@pytest.mark.parametrize("blocked", [power.GEN, power.LOAD])
def test_one_service_denied_other_preserved(monkeypatch, blocked):
    day = power.latest_day(NOW)
    monkeypatch.setattr(power, "get_token", lambda *_: "fixture-token")

    def request(method, url, **kwargs):
        if url == blocked:
            raise power.TernaHTTPError(403, power._SERVICES[url])
        return {"test": True}

    monkeypatch.setattr(power, "_json_request", request)
    monkeypatch.setattr(power, "parse_power", lambda payload, kind, *args: [{"metric": kind, "gwh": 12}])
    result = power.load_power("id", "secret", day, day, now=NOW)
    assert len(result["rows"]) == 1
    assert result["rows"][0]["metric"] == ("load" if blocked == power.GEN else "generation")
    assert "HTTP 403" in result["warning"]


def test_probe_respects_disabled_network(monkeypatch):
    monkeypatch.setattr(power, "get_token", lambda *_: pytest.fail("unexpected network call"))
    with cached_only():
        result = probe("id", "secret", "OAuth", now=NOW)
    assert result["status"] == "Non verificato"


def test_probe_http_success_distinct_from_invalid_coverage(monkeypatch):
    monkeypatch.setattr(power, "get_token", lambda *_: "fixture-token")
    monkeypatch.setattr(power, "_json_request", lambda *a, **k: {})
    result = probe("id", "secret", "Actual Generation", now=NOW)
    assert result["oauth"] == "OK"
    assert result["status"] == "HTTP 200"
    assert "non validabile" in result["detail"]


def test_reject_unlisted_endpoint_before_network(monkeypatch):
    monkeypatch.setattr(power.requests, "request", lambda *a, **k: pytest.fail("unexpected network call"))
    with pytest.raises(SourceUnavailable):
        power._json_request("GET", "https://example.com/")
