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
