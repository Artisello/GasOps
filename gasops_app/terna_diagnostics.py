"""Explicit, read-only Terna access probe. Never exposes credentials or response bodies."""
from datetime import timedelta

from .data import ROME
from .models import utc_now
from .public_data import SourceUnavailable, network_allowed
from . import terna_power as power

SERVICES = ("OAuth", "Actual Generation", "Total Load", "Load Forecast", "Wind Production Forecast")


def probe(client, secret, service, *, now=None):
    if service not in SERVICES:
        raise ValueError("Servizio non supportato")
    now = now or utc_now()
    result = {"service": service, "checked_at": now.isoformat(),
              "oauth": "Non verificato", "status": "Non verificato",
              "detail": "", "business_id": None}
    if not network_allowed():
        result["detail"] = "Accesso rete disattivato."
        return result
    try:
        token = power.get_token(client, secret)
        result["oauth"] = "OK"
        if service == "OAuth":
            result["status"] = "OK"
            return result
        observed = service in ("Actual Generation", "Total Load")
        day = power.latest_day(now) if observed else now.astimezone(ROME).date()
        if observed:
            kind = "generation" if service == "Actual Generation" else "load"
            url = power.GEN if kind == "generation" else power.LOAD
            params = power.dates(day, day, now)
            params.update({"type": list(power.SOURCES)} if kind == "generation" else {"biddingZone": "Italy"})
        else:
            from . import terna_forward as forward
            kind = "load" if service == "Load Forecast" else "wind"
            url = forward.LOAD if kind == "load" else forward.WIND
            params = {"dateFrom": day.strftime("%d/%m/%Y"),
                      "dateTo": (day + timedelta(days=1)).strftime("%d/%m/%Y"),
                      "sessionType": forward.SESSION}
        payload = power._json_request("GET", url, params=params,
            headers={"Authorization": "Bearer " + token, "Accept": "application/json"})
        result["status"] = "HTTP 200"
        try:
            rows = power.parse_power(payload, kind, day, day) if observed else forward.parse(payload, kind, day, day, now)
            valid = any(r.get("gwh") is not None for r in rows)
            result["detail"] = "Copertura validata." if valid else "Accesso riuscito; copertura incompleta."
        except (ValueError, KeyError, TypeError, IndexError, OverflowError):
            result["detail"] = "Accesso riuscito; schema o copertura non validabile."
    except power.TernaHTTPError as error:
        if result["oauth"] != "OK":
            result["oauth"] = "HTTP " + str(error.status)
        result.update(status="HTTP " + str(error.status), detail=str(error),
                      business_id=error.business_id)
    except SourceUnavailable as error:
        result.update(status="Non disponibile", detail=str(error))
    return result
