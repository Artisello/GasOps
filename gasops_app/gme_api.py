"""Bounded client for the official GME API. No data persistence."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from functools import lru_cache
from threading import Lock
from time import monotonic, sleep, time
import base64
import binascii
import math
import re

import requests

from . import gme_market as market
from .gas_calendar import ROME

QUOTAS = (
    ("ActiveConnections", "MaxConcurrentConnections", "Connessioni attive"),
    ("ConnectionsPerMinute", "MaxConnectionsPerMinute", "Richieste / minuto"),
    ("ConnectionsPerHour", "MaxConnectionsPerHour", "Richieste / ora"),
    ("DataPerMinute", "MaxDataPerMinute", "Campi / minuto"),
    ("DataPerHour", "MaxDataPerHour", "Campi / ora"),
)
NETWORK_TIMEOUT = (4, 12)
MIN_INTERVAL = 0.5
ACCOUNT_LOCK = Lock()


class GMEError(ValueError):
    def __init__(self, message, *, status=None, transient=False):
        super().__init__(message)
        self.status = status
        self.transient = transient


def _endpoint(value):
    if not isinstance(value, str):
        raise GMEError("Indirizzo API GME non valido.")
    value = value.strip().rstrip("/")
    root = market.ENDPOINT.removesuffix("/api/v1")
    if value in (root, root.removesuffix("/request"), market.ENDPOINT):
        return market.ENDPOINT
    raise GMEError("Usa l’indirizzo HTTPS ufficiale del servizio API GME.")


def _expiry(token, now):
    # The token is an opaque credential for authorization. Read exp only
    # to schedule renewal. Only the GME server validates the signature.
    if (not isinstance(token, str) or len(token) > 8192 or
            not re.fullmatch(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", token)):
        raise GMEError("GME ha restituito un token non valido.")
    payload = token.split(".")[1]
    try:
        claims = market.json_object(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        expires = claims.get("exp", Decimal(now + 60)) if isinstance(claims, dict) else None
        if not isinstance(expires, Decimal) or not math.isfinite(expires) or expires <= now:
            raise ValueError
    except (ValueError, OverflowError, binascii.Error):
        raise GMEError("GME ha restituito un token non valido o scaduto.") from None
    return float(expires)


def _quota_count(mapping, name):
    value = mapping.get(name.casefold())
    if (not isinstance(value, Decimal) or not 0 <= value <= 10**12 or
            value != value.to_integral_value()):
        raise GMEError("Schema quote GME non riconosciuto.")
    return int(value)


def _window_ended(value, length, now):
    if not isinstance(value, str):
        return False
    try:
        stamp = datetime.fromisoformat(value)
        if stamp.tzinfo is None:
            # The live response uses the GME server's Italian local time.
            # During the fall DST overlap, allow for the later occurrence.
            stamp = stamp.replace(tzinfo=ROME, fold=1)
        return now - stamp.astimezone(timezone.utc) >= length
    except (ValueError, OverflowError):
        return False


def _parse_quotas(raw, now):
    quotas = market.json_object(raw)
    if not isinstance(quotas, dict) or not isinstance(quotas.get("limits"), dict):
        raise GMEError("Schema quote GME non riconosciuto.")
    counters = {
        counter: (_quota_count(quotas, counter), _quota_count(quotas["limits"], limit))
        for counter, limit, _ in QUOTAS
    }
    # GetMyQuotas can keep reporting the last recorded usage after the window.
    windows = (
        ("lastmodifiedtime", timedelta(minutes=1), ("ConnectionsPerMinute", "DataPerMinute")),
        ("lastmodifiedhour", timedelta(hours=1), ("ConnectionsPerHour", "DataPerHour")),
    )
    for stamp, length, fields in windows:
        if _window_ended(quotas.get(stamp), length, now):
            for field in fields:
                counters[field] = (0, counters[field][1])
    return counters


class Client:
    """One token and one outstanding HTTP request per account in this process."""

    def __init__(self, username, password, base_url, *, transport=None):
        if not all(isinstance(v, str) and v.strip() and len(v) <= 4096 for v in (username, password)):
            raise GMEError("Credenziali GME mancanti o non valide.")
        self._endpoint = _endpoint(base_url)
        self._username = username
        self._password = password
        if transport is None:
            session = requests.Session()
            session.trust_env = False
            transport = session.request
        self._transport = transport
        self._lock = Lock()
        self._token = None
        self._expires = 0.
        self._next_request = 0.
        self._blocked_until = 0.

    def _send(self, method, action, *, body=None, token=None):
        delay = self._next_request - monotonic()
        if delay > 0:
            sleep(delay)
        if monotonic() < self._blocked_until:
            raise GMEError("Quota GME in pausa. Riprova più tardi.", status=429)
        self._next_request = monotonic() + MIN_INTERVAL
        headers = {"Authorization": "Bearer " + token} if token else {}
        options = {"headers": headers, "timeout": NETWORK_TIMEOUT, "stream": True, "allow_redirects": False}
        if body is not None:
            options["json"] = body
        started = monotonic()
        try:
            with self._transport(method, self._endpoint + "/" + action, **options) as response:
                status = response.status_code
                if status == 429:
                    retry = response.headers.get("Retry-After", "")
                    seconds = int(retry) if retry.isascii() and retry.isdigit() and len(retry) <= 5 else 60
                    self._blocked_until = monotonic() + max(1, min(seconds, 3600))
                    raise GMEError("Quota GME raggiunta. Riprova più tardi.", status=429)
                if status in (401, 403):
                    raise GMEError("Accesso API GME rifiutato.", status=status)
                if status == 412:
                    raise GMEError("GME ha rifiutato la richiesta. Verifica intervallo, dataset e quote.", status=status)
                if status != 200:
                    raise GMEError(f"Servizio GME non disponibile (HTTP {status}).", status=status,
                                   transient=status in (502, 503, 504))
                output = bytearray()
                for chunk in response.iter_content(65536):
                    if monotonic() - started > 20:
                        raise GMEError("Tempo di risposta GME superato.", transient=True)
                    if len(output) + len(chunk) > market.MAX_BYTES:
                        raise GMEError("Risposta GME oltre 4 MiB. Riduci l’intervallo.")
                    output.extend(chunk)
                return bytes(output)
        except requests.RequestException:
            # Request exceptions can include headers, credentials or a response body.
            raise GMEError("Connessione GME non riuscita.", transient=True) from None

    def _authenticate(self):
        if self._token and time() < self._expires - 15:
            return self._token
        auth = market.json_object(self._send("POST", "Auth", body={"Login": self._username, "Password": self._password}))
        if not isinstance(auth, dict) or auth.get("success") is not True:
            raise GMEError("Autenticazione GME non riuscita.")
        token = auth.get("token")
        self._expires = _expiry(token, time())
        self._token = token
        return token

    def _authorized(self, method, action, body=None):
        token = self._authenticate()
        try:
            return self._send(method, action, body=body, token=token)
        except GMEError as error:
            if error.status != 401:
                raise
        # A 401 is an explicit rejection, unlike a timeout after POST.
        self._token = None
        return self._send(method, action, body=body, token=self._authenticate())

    def _quotas(self):
        try:
            raw = self._authorized("GET", "GetMyQuotas")
        except GMEError as error:
            if not error.transient:
                raise
            raw = self._authorized("GET", "GetMyQuotas")
        return _parse_quotas(raw, datetime.now(timezone.utc))

    def quotas(self):
        with self._lock:
            return self._quotas()

    def download(self, kind, segment, first, last, cutoff):
        market.validate_window(kind, segment, first, last, cutoff)
        spec = market.DATASETS[kind]
        # The working example in the user manual sends yyyyMMdd as strings.
        body = {"platform": "PublicMarketResults", "segment": segment, "dataName": spec.name,
                "intervalStart": first.strftime("%Y%m%d"), "intervalEnd": last.strftime("%Y%m%d"),
                "attributes": {}}
        with self._lock:
            quotas = self._quotas()
            if any(used >= limit for used, limit in quotas.values()):
                raise GMEError("Quota GME esaurita. Attendi il rinnovo prima di acquisire altri dati.")
            raw = self._authorized("POST", "RequestData", body)
            acquired = datetime.now(timezone.utc)
        payload, request_id = market.unpack_response(market.json_object(raw))
        snapshot = market.parse(payload, kind, last, segment=segment, first=first)
        return dict(snapshot, origin="api", first=first, last=last, acquired=acquired, request_id=request_id), payload

    def fetch(self, kind, segment, first, last, cutoff):
        return self.download(kind, segment, first, last, cutoff)[0]


@lru_cache(maxsize=2)
def _account(username, password, base_url):
    return Client(username, password, base_url)


def _secrets_client():
    values = market.credentials()
    if values is None:
        raise GMEError("Configurazione GME assente o incompleta nei Secrets.")
    with ACCOUNT_LOCK:
        return _account(values[0], values[1], _endpoint(values[2]))


def session_client():
    if not market.session_authorized():
        raise GMEError("GME è disponibile nei deployment privati configurati.")
    return _secrets_client()


def main():
    """Explicit local smoke test using exactly the Streamlit Secrets configuration."""
    import argparse
    from pathlib import Path
    from .gas_calendar import closed_gas_day
    from .models import utc_now

    parser = argparse.ArgumentParser(description="Verifica locale autorizzata del servizio API GME.")
    parser.add_argument("kind", choices=market.DATASETS)
    parser.add_argument("first", type=date.fromisoformat)
    parser.add_argument("last", type=date.fromisoformat)
    parser.add_argument("output", type=Path, nargs="?")
    parser.add_argument("--segment")
    parser.add_argument("--authorized-private-use", action="store_true")
    args = parser.parse_args()
    if not args.authorized_private_use:
        parser.error("Conferma l’uso privato autorizzato con --authorized-private-use.")
    if args.output and args.output.exists():
        parser.error("Il file di destinazione esiste già.")
    segment = args.segment or market.DATASETS[args.kind].segments[0]
    cutoff = closed_gas_day(utc_now())
    try:
        market.validate_window(args.kind, segment, args.first, args.last, cutoff)
        client = session_client()
        snapshot, payload = client.download(args.kind, segment, args.first, args.last, cutoff)
        if args.output:
            with args.output.open("xb") as file:
                file.write(payload)
    except (ValueError, OSError) as error:
        parser.exit(1, (str(error) if isinstance(error, ValueError) else "Impossibile scrivere l’estratto.") + "\n")
    print(f"Autenticazione e quote GME verificate. {len(snapshot['rows'])} record validati · {segment}.")

if __name__ == "__main__":
    main()
