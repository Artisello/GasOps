"""Mocked protocol, quota and UI smoke tests. No outside calls."""
import base64
import io
import json
import zipfile
from datetime import date, timedelta

import pytest
import requests
import streamlit as st
from streamlit.testing.v1 import AppTest

from gasops_app import access
from gasops_app import gme_api as api, gme_market as g
from gasops_app.gme_market_page import STATE

DAY = date(2026, 11, 17)
SECRETS = {"gme":{"username":"fixture","password":"secret-fixture","base_url":g.ENDPOINT}}


def _configured_gme(monkeypatch):
    monkeypatch.setattr(st, "secrets", SECRETS)
    monkeypatch.setattr(access, "authorized_identity", lambda: pytest.fail("GME must not inspect OIDC"))


def _token(expiry=2_000_000_000):
    claims = base64.urlsafe_b64encode(json.dumps({"exp":expiry}).encode()).decode().rstrip("=")
    return "e30."+claims+".test"


def _quota(used=0):
    return {**{counter:used for counter, _, _ in api.QUOTAS},
            "Limits":{limit:100 for _, limit, _ in api.QUOTAS}}


def _response(rows):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream,"w") as archive:
        archive.writestr("data.json",json.dumps(rows))
    return {"requestId":"request-fixture","formatType":".json.zip","resultRequest":None,
            "contentResponse":base64.b64encode(stream.getvalue()).decode()}


class _Response:
    def __init__(self, data, status=200, headers=None):
        self.status_code = status
        self.data = data
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self,*args):
        pass

    def iter_content(self, chunk_size):
        yield json.dumps(self.data).encode()


class _Transport:
    def __init__(self, *responses):
        self.responses = iter(responses)
        self.calls = []

    def __call__(self, method, url, **options):
        self.calls.append((method, url, options))
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response

    @property
    def actions(self):
        return [(method, url.rsplit("/",1)[-1]) for method, url, _ in self.calls]


@pytest.fixture(autouse=True)
def _no_wait(monkeypatch):
    monkeypatch.setattr(api,"MIN_INTERVAL",0)


def _auth(token=None):
    return _Response({"success":True,"token":token or _token()})


def _data():
    return _Response(_response([{"FlowDate":20261117,"Product":"test","Price":"42.25"}]))


def _client(transport):
    return api.Client("fixture","secret-fixture",g.ENDPOINT,transport=transport)


def test_auth_quota_data_and_jwt_reuse():
    transport = _Transport(_auth(),_Response(_quota()),_data(),_Response(_quota(1)))
    client = _client(transport)
    snapshot = client.fetch("igi","IGI",DAY,DAY,DAY)
    assert client.quotas()["DataPerMinute"] == (1,100)
    assert transport.actions == [("POST","Auth"),("GET","GetMyQuotas"),("POST","RequestData"),("GET","GetMyQuotas")]
    assert transport.calls[0][2]["json"] == {"Login":"fixture","Password":"secret-fixture"}
    assert "json" not in transport.calls[1][2]
    assert transport.calls[2][2]["json"] == {"platform":"PublicMarketResults","segment":"IGI","dataName":"GAS_IGIndex",
                                             "intervalStart":"20261117","intervalEnd":"20261117","attributes":{}}
    assert all(kw["timeout"] and kw["stream"] and not kw["allow_redirects"] for _,_,kw in transport.calls)
    assert all(url.startswith(g.ENDPOINT+"/") and kw["headers"] == {"Authorization":"Bearer "+_token()}
               for _,url,kw in transport.calls[1:])
    assert snapshot["request_id"] == "request-fixture" and snapshot["origin"] == "api"
    assert str(snapshot["rows"][0]["Price"]) == "42.25"


def test_private_fetch_compatibility_uses_same_client(monkeypatch):
    _configured_gme(monkeypatch)
    row = {"FlowDate":20261117,"WeightedAveragePrice":42}
    transport = _Transport(_auth(),_Response(_quota()),_Response(_response([row])))
    payload = g.fetch_private("prices",DAY,DAY,"fixture","secret-fixture",transport=transport)
    assert json.loads(payload) == [row]
    assert transport.calls[-1][2]["json"]["dataName"] == "GAS_ImbalancePrice"


def test_renew_on_expiry_and_explicit_unauthorized_once(monkeypatch):
    now = [10.]
    monkeypatch.setattr(api,"time",lambda:now[0])
    tokens = [_token(80),_token(160),_token(240)]
    transport = _Transport(_auth(tokens[0]),_Response(_quota()),_auth(tokens[1]),_Response(_quota()),
                           _Response({},401),_auth(tokens[2]),_Response(_quota()))
    client = _client(transport)
    client.quotas()
    now[0] = 75.
    client.quotas()
    client.quotas()
    assert [action for _,action in transport.actions] == [
        "Auth","GetMyQuotas","Auth","GetMyQuotas","GetMyQuotas","Auth","GetMyQuotas"]
    assert transport.calls[-1][2]["headers"]["Authorization"] == "Bearer "+tokens[2]


def test_no_authentication_details_leak_and_no_redirects():
    transport = _Transport(_Response({"success":False,"Reason":"sensitive-fixture"}))
    with pytest.raises(api.GMEError,match="Autenticazione") as rejection:
        _client(transport).quotas()
    assert "sensitive-fixture" not in str(rejection.value)
    with pytest.raises(api.GMEError,match="ufficiale"):
        api.Client("fixture","secret-fixture",g.ENDPOINT+".invalid",transport=transport)
    assert len(transport.calls) == 1


def test_quota_full_and_invalid_period_never_send_data_request():
    transport = _Transport(_auth(),_Response(_quota(100)))
    client = _client(transport)
    with pytest.raises(ValueError,match="31"):
        client.fetch("igi","IGI",DAY-timedelta(days=31),DAY,DAY)
    with pytest.raises(ValueError,match="segmento"):
        client.fetch("igi","MGP-GAS",DAY,DAY,DAY)
    assert not transport.calls
    with pytest.raises(api.GMEError,match="esaurita"):
        client.fetch("igi","IGI",DAY,DAY,DAY)
    assert len(transport.calls) == 2


def test_retry_get_once_never_replay_ambiguous_post():
    transport = _Transport(_auth(),_Response({},503),_Response(_quota()),requests.ReadTimeout("sensitive-fixture"))
    with pytest.raises(api.GMEError,match="Connessione GME"):
        _client(transport).fetch("igi","IGI",DAY,DAY,DAY)
    assert [action for _,action in transport.actions] == ["Auth","GetMyQuotas","GetMyQuotas","RequestData"]


def test_429_respects_cooldown_without_automatic_retries():
    transport = _Transport(_auth(),_Response({},429,{"Retry-After":"2"}))
    client = _client(transport)
    for text in ("raggiunta","pausa"):
        with pytest.raises(api.GMEError,match=text):
            client.quotas()
    assert len(transport.calls) == 2


@pytest.mark.parametrize("profile", [None, access.PUBLIC, "unknown", access.PRIVATE])
def test_api_access_depends_only_on_secrets_and_data_stays_in_the_session(monkeypatch, profile):
    if profile is None:
        monkeypatch.delenv("GASOPS_PROFILE", raising=False)
    else:
        monkeypatch.setenv("GASOPS_PROFILE", profile)
    _configured_gme(monkeypatch)
    transport = _Transport(_auth(),_Response(_quota()),_data(),_Response(_quota()),_Response({},503))
    client = _client(transport)
    monkeypatch.setattr(api,"_account",lambda *args:client)
    script = ("from gasops_app.gme_market_page import overview_kpis, panel\n"
              "from datetime import date\npanel()\noverview_kpis(date(2026, 11, 17))")
    app = AppTest.from_string(script).run()
    assert len(app.selectbox(key="gme_dataset").options) == len(g.DATASETS)
    app.selectbox(key="gme_dataset").set_value("igi").run()
    app.date_input[0].set_value((DAY,DAY)).run()
    assert not app.exception and not transport.calls
    app.button(key="gme_igi_IGI_fetch").click().run()
    assert not app.exception and app.session_state[STATE][("igi","IGI")]["origin"] == "api"
    assert any(c.value == "Fonte: " + g.SOURCE for c in app.caption)
    app.button(key="gme_igi_IGI_fetch").click().run()
    assert len(transport.calls) == 3
    other_session = AppTest.from_string(script).run()
    assert not other_session.exception and other_session.session_state[STATE] == {}
    assert len(transport.calls) == 3
    app.date_input[0].set_value((DAY-timedelta(days=1),DAY)).run()
    app.button(key="gme_igi_IGI_fetch").click().run()
    assert not app.exception and ("igi","IGI") in app.session_state[STATE]
    assert any("ultima copia conservata" in w.value for w in app.warning)
    monkeypatch.setattr(st, "secrets", {})
    app.run()
    assert not app.exception and app.session_state[STATE] == {}
    assert not any(g.SOURCE in c.value for c in app.caption)
    assert any("non configurata" in info.value for info in app.info)


def test_missing_api_configuration_still_allows_real_file_import(monkeypatch):
    _configured_gme(monkeypatch)
    monkeypatch.setattr(st, "secrets", {"gme":{"username":"fixture"}})
    monkeypatch.setattr(api, "_account", lambda *args: pytest.fail("Incomplete credentials reached client"))
    app = AppTest.from_string("from gasops_app.gme_market_page import panel\npanel()")
    uploaded = g.parse(b'[{"FlowDate":20261117,"WeightedAveragePrice":42}]', "prices", DAY)
    app.session_state[STATE] = {("prices","GAS"):uploaded}
    app.run()
    assert not app.exception and app.get("file_uploader")
    assert any("provenienza dichiarata" in c.value for c in app.caption)
    assert not any("demo" in button.label.lower() or button.label == "Carica dall’API" for button in app.button)
    with pytest.raises(api.GMEError,match="incompleta"):
        api.session_client()


def test_full_quota_counters_expire_only_after_their_official_windows():
    from datetime import datetime, timezone
    quota = json.dumps({**_quota(100), "ActiveConnections":0,
                        "LastModifiedTime":"2026-11-26T10:54:18.303",
                        "LastModifiedHour":"2026-11-26T10:15:47.32"}).encode()
    def check(hour,minute,second):
        return api._parse_quotas(quota,datetime(2026,11,26,hour,minute,second,tzinfo=timezone.utc))
    assert check(9,55,17)["ConnectionsPerMinute"] == (100,100)
    assert check(9,55,19)["ConnectionsPerMinute"] == (0,100)
    assert check(9,55,19)["ConnectionsPerHour"] == (100,100)
    assert check(10,15,48)["ConnectionsPerHour"] == (0,100)
    assert check(10,15,48)["ActiveConnections"] == (0,100)
