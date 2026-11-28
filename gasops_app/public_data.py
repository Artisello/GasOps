"""Download con validazione, cache SQLite e fallback all'ultima copia verificata."""

from collections.abc import Callable
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta
import logging
import json
from typing import TypeVar

import requests

from .models import utc_now
from .store import Store

T = TypeVar("T")
LOG = logging.getLogger(__name__)
_NETWORK_ALLOWED = ContextVar("gasops_network_allowed", default=True)
VALIDATION_ERRORS = (ValueError, TypeError, KeyError, IndexError, OverflowError)


class SourceSchemaError(ValueError):
    """Controlled validation detail; messages must be static and contain no raw data."""


class SourceUnavailable(RuntimeError):
    """La fonte non ha restituito dati validi e la cache non è utilizzabile."""


class NoObservation(SourceSchemaError):
    """Structurally valid response without a usable observation."""


class SourceNoObservation(SourceUnavailable):
    """The provider responded, but no usable observation was returned."""


DIAGNOSTIC_CODES=frozenset(("rate_limit","access_denied","timeout","connection","http_error",
                            "validation_or_unavailable","no_observation","deferred","unknown"))


def acquisition_error_code(error):
    """Classify controlled errors; never return arbitrary message text."""
    if isinstance(error,SourceNoObservation):return "no_observation"
    if isinstance(error,requests.Timeout):return "timeout"
    if isinstance(error,requests.ConnectionError):return "connection"
    status=getattr(error,"status",None)
    if isinstance(error,requests.HTTPError) and error.response is not None:
        status=error.response.status_code
    if status==429:return "rate_limit"
    if status in (401,403):return "access_denied"
    if type(status) is int:return "http_error"
    # Only controlled adapter messages can supply textual error codes.
    if isinstance(error,(SourceUnavailable,SourceSchemaError,str)):
        reason=str(error).casefold()
        if "http 429" in reason or "limite richieste" in reason:return "rate_limit"
        if any(v in reason for v in ("http 401","http 403","accesso gie negato")):return "access_denied"
        if "tempo di risposta" in reason or "timeout" in reason:return "timeout"
        if "connessione" in reason:return "connection"
        if "http " in reason:return "http_error"
    return "validation_or_unavailable"


def network_allowed():
    return _NETWORK_ALLOWED.get()


@contextmanager
def cached_only(enabled=True):
    """Request-local read policy; never changes another visitor's acquisition."""
    token = _NETWORK_ALLOWED.set(_NETWORK_ALLOWED.get() and not enabled)
    try:
        yield
    finally:
        _NETWORK_ALLOWED.reset(token)


def retrieve(
    store: Store,
    *,
    key: str,
    name: str,
    url: str,
    parse: Callable[..., T],
    ttl: timedelta,
    params: dict | None = None,
    refresh: bool = False,
    attempts: int = 2,
    headers: dict | None = None,
    timeout: tuple[float, float] = (3, 5),
    diagnostics: bool = False,
    max_bytes: int = 1_000_000,
) -> T:
    now = utc_now()
    existing = store.cached(key)
    if existing and not refresh:
        try:
            cached_at = datetime.fromisoformat(existing[0])
            if timedelta(0) <= now - cached_at < ttl:
                return parse(existing[1], cached_at, cached=True)
        except VALIDATION_ERRORS:
            LOG.warning("Cache non valida per %s", name)

    if not _NETWORK_ALLOWED.get():
        if existing:
            try:
                at = datetime.fromisoformat(existing[0])
                if at.utcoffset() is not None and at <= now:
                    return parse(existing[1], at, cached=True)
            except VALIDATION_ERRORS:
                pass
        raise SourceUnavailable(name + ": nessuna copia valida. Usa Aggiorna dati per consultare la fonte.")

    reason = "nessun dato verificato"
    for attempt in range(attempts):
        try:
            # Never forward API credentials to a redirect target.
            secure = {"headers": headers, "allow_redirects": False} if headers else {}
            with requests.get(url, params=params, timeout=timeout, stream=True, **secure) as response:
                if headers and 300 <= response.status_code < 400:
                    raise SourceSchemaError("Redirect autenticato non consentito")
                response.raise_for_status()
                body = bytearray()
                for part in response.iter_content(chunk_size=16_384):
                    body.extend(part)
                    if len(body) > max_bytes:
                        raise SourceSchemaError("Risposta superiore al limite di dimensione")
            text = body.decode("utf-8-sig")
            result = parse(text, now)
        except NoObservation:
            # A validated empty publication is not a transport failure, and
            # must never overwrite a previously usable raw response.
            if existing:
                try:
                    at=datetime.fromisoformat(existing[0])
                    if at.utcoffset() is not None and at<=now:
                        result=parse(existing[1],at,cached=True)
                        if diagnostics and isinstance(result,dict):
                            return {**result,"no_observation":True,"attempted_at":now.isoformat()}
                except VALIDATION_ERRORS:
                    pass
            raise SourceNoObservation(name+": nessuna osservazione utilizzabile restituita.") from None
        except (requests.RequestException, *VALIDATION_ERRORS) as error:
            # Do not expose URLs, response bodies, credentials, or raw exceptions.
            if isinstance(error, requests.Timeout):
                reason = "tempo di risposta superato"
            elif isinstance(error, requests.HTTPError):
                status = error.response.status_code if error.response is not None else None
                reason = f"HTTP {status}" if status is not None else "errore HTTP"
            elif isinstance(error, requests.RequestException):
                reason = "errore di connessione"
            elif isinstance(error, json.JSONDecodeError):
                reason = "risposta non JSON"
            elif isinstance(error, SourceSchemaError):
                reason = str(error).rstrip(".")
            else:
                reason = "dati assenti o schema non valido"
            LOG.warning("%s: tentativo %s fallito (%s)", name, attempt + 1, reason)
            if isinstance(error,requests.HTTPError) and error.response is not None and error.response.status_code in (400,401,403,404,405,410,422,429):
                # Repeating the same rejected request cannot repair credentials,
                # parameters or a quota. Keep the valid cache and allow recovery.
                break
            continue
        store.cache(key, now.isoformat(), text)
        return result

    if existing:
        try:
            result = parse(existing[1], datetime.fromisoformat(existing[0]), cached=True, failed=True)
            # Diagnostics contain controlled messages only, never response bodies or credentials.
            if diagnostics and isinstance(result, dict):
                return {**result, "refresh_error": reason}
            return result
        except VALIDATION_ERRORS:
            LOG.warning("Nessuna cache verificata per %s", name)

    if diagnostics:
        raise SourceUnavailable(f"{name}: {reason}.")
    raise SourceUnavailable(f"{name} non disponibile. Puoi riprovare o aprire l’archivio JRC o i dati di esempio.")
