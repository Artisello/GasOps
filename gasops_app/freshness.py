"""Shared temporal evidence, independent of transport and cache age.

Current means validated for the reference period, never a live API probe.
Historical, cached, partial and stale remain independent flags even when
one primary status is displayed. All timestamps retain their own meaning.
"""
from datetime import date, datetime, timedelta

LABELS = {"Current":"Validato per il periodo", "Historical":"Storico",
          "Cached":"Copia in cache", "Partial":"Parziale", "Stale":"Da aggiornare",
          "Unavailable":"Non disponibile", "Failed refresh":"Aggiornamento fallito"}


def timestamp(value):
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return value if isinstance(value, datetime) and value.utcoffset() is not None else None


def temporal_evidence(*, now, gas_day=None, period_from=None, period_to=None,
                      observed_at=None, published_at=None, retrieved_at=None,
                      current_day=None, valid=0, expected=0, cached=False,
                      failed=False, partial=False, ttl=timedelta(hours=12),
                      publication_status=None, historical=False):
    if timestamp(now) is None:
        raise ValueError("Riferimento temporale senza fuso orario.")
    if isinstance(gas_day, str):
        gas_day = date.fromisoformat(gas_day)
    at = timestamp(retrieved_at)
    age = now-at if at is not None and at <= now else None
    historical = historical or bool(gas_day and current_day and gas_day < current_day)
    future = bool(at and at > now) or bool(gas_day and current_day and gas_day > current_day)
    stale = bool(age is not None and age > ttl)
    partial = bool(partial or expected and valid < expected or at is None or future)
    state = ("Unavailable" if not valid else "Failed refresh" if failed else "Stale" if stale
             else "Partial" if partial else "Historical" if historical else "Cached" if cached else "Current")
    def serial(value):
        return value.isoformat() if value is not None else None
    return {"gas_day":serial(gas_day),
            "observation_period":{"from":serial(timestamp(period_from)),"to":serial(timestamp(period_to))},
            "observed_at":serial(timestamp(observed_at)), "published_at":serial(timestamp(published_at)),
            "retrieved_at":serial(at), "cache_age":age.total_seconds() if age is not None else None,
            "source_coverage":{"valid":valid,"expected":expected}, "publication_status":publication_status,
            "data_status":state, "historical":bool(historical), "cached":bool(cached),
            "partial":partial, "stale":stale, "refresh_failed":bool(failed)}


def label(evidence):
    return LABELS.get(evidence.get("data_status"), evidence.get("status", LABELS["Unavailable"]))


def style(evidence):
    return {"Current":"ok","Cached":"ok","Historical":"historical","Partial":"review",
            "Stale":"review","Failed refresh":"review"}.get(evidence.get("data_status"),"")


def measure_evidence(measure, now):
    """Presentation adapter for the existing system-status Measure, no new math."""
    from .gas_calendar import gas_day_bounds, closed_gas_day
    start,stop=gas_day_bounds(measure.gas_day)
    evidence=temporal_evidence(now=now,gas_day=measure.gas_day,period_from=start,period_to=stop,
        published_at=measure.observed_at,retrieved_at=measure.retrieved_at,current_day=closed_gas_day(now),
        valid=measure.coverage.valid if measure.value is not None else 0,expected=measure.coverage.expected,
        partial=measure.freshness=="partial",publication_status=measure.status)
    if measure.freshness=="stale" and evidence["data_status"]!="Unavailable":
        evidence.update(data_status="Stale",stale=True)
    return evidence
