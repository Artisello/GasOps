"""Explicit, bounded refresh; rendering and filtering never call these loaders."""
from datetime import timedelta
import sqlite3

from .entsog import _last_completed
from .italian_network_events import load_interruptions
from .italian_network_sources import load_catalog, load_point, load_facility
from .operational_sources import load_agsi, load_iip
from .public_data import SourceUnavailable

STATE = "italian_network_data_v1"
FAILURES = (SourceUnavailable, ValueError, OSError, sqlite3.Error)


def refresh_network(state, store, network, identifier, direction, first, last, now, *, api_key=None):
    if not 0 <= (last-first).days < 31 or last > _last_completed(now):
        raise ValueError("Seleziona da 1 a 31 giorni gas conclusi")
    if identifier not in {i.id for i in network.infrastructure}:
        raise ValueError("Infrastruttura non riconosciuta")
    saved = dict(state.get(STATE, {}))
    if saved.get("attempted") and now-saved["attempted"] < timedelta(minutes=1):
        return ("Aggiornamento già richiesto: attendi un minuto.",)
    saved["attempted"] = now
    state[STATE] = saved
    notices, failures = [], dict(saved.get("failures", {}))
    try:
        catalog = load_catalog(store, refresh=True)
        saved["catalog"] = catalog
        if catalog["failed"]:
            failures["catalog"] = now
            notices.append("Catalogo ENTSOG: ultima copia valida, aggiornamento non riuscito.")
        else:
            failures.pop("catalog", None)
    except FAILURES:
        catalog = saved.get("catalog", network.sources["opd"])
        notices.append("Catalogo ENTSOG non aggiornato; associazioni della copia verificata.")
        failures["catalog"] = now

    points = [b for b in network.bindings_for(identifier, "ENTSOG") if b.direction == direction]
    if points:
        binding = points[0]
        verified = [r for r in catalog["rows"] if r["operatorKey"] == binding.operator_id
            and r["pointKey"] == binding.external_id and r["directionKey"] == binding.direction
            and r["pointLabel"] == binding.expected_label and r["hasData"] is True and r["isInvalid"] is False]
        if len(verified) != 1:
            notices.append("Associazione ENTSOG da verificare nel catalogo: punto non aggiornato.")
            failures[binding.point_direction] = now
        else:
            try:
                result = load_point(store, binding, first, last, refresh=True, now=now)
                snapshots = dict(saved.get("snapshots", {}))
                snapshots[(binding.point_direction, first, last)] = result
                saved["snapshots"] = dict(sorted(snapshots.items(), key=lambda p:p[1].acquired)[-24:])
                if result.failed:
                    failures[binding.point_direction] = now
                    notices.append("Dati ENTSOG: ultima cache valida, aggiornamento non riuscito.")
                else:
                    failures.pop(binding.point_direction, None)
                    notices.append("Dati ENTSOG acquisiti per il punto selezionato.")
                if result.partial:
                    notices.append("Copertura ENTSOG parziale: verifica il dettaglio qualità.")
            except FAILURES:
                failures[binding.point_direction] = now
                notices.append("Dati ENTSOG non aggiornati; la copia precedente resta disponibile.")
            try:
                result = load_interruptions(store, binding, first, last, refresh=True)
                saved.setdefault("interruptions", {})[binding.point_direction] = result
                if result["failed"]:
                    failures["interruptions:"+binding.point_direction] = now
                    notices.append("Interruzioni ENTSOG: ultima cache valida.")
                else:
                    failures.pop("interruptions:"+binding.point_direction, None)
            except FAILURES:
                failures["interruptions:"+binding.point_direction] = now
                notices.append("Interruzioni ENTSOG non aggiornate.")

    if api_key:
        for binding in network.bindings_for(identifier):
            if binding.provider not in ("AGSI+", "ALSI"):
                continue
            try:
                result = load_facility(store, api_key, binding, first, last, refresh=True)
                saved.setdefault("facilities", {})[(binding.provider, binding.external_id)] = result
                if result["failed"]:
                    failures[binding.provider+":"+binding.external_id] = now
                else:
                    failures.pop(binding.provider+":"+binding.external_id, None)
                notices.append("Dati GIE dell’impianto acquisiti." if not result["failed"] else "GIE impianto: ultima cache valida.")
            except FAILURES:
                failures[binding.provider+":"+binding.external_id] = now
                notices.append("Dati GIE dell’impianto non aggiornati.")
        # Reuse the canonical states and loaders of the existing GIE views.
        for key, loader in (("AGSI+_IT", load_agsi), ("gie_iip", load_iip)):
            previous = dict(state.get(key, {}))
            previous["attempted"] = now
            try:
                result = loader(store, api_key, now=now, refresh=True)
                previous.update(result=result, error="Ultima cache valida" if result["failed"] else None)
                if result["failed"]:
                    failures["context:"+key] = now
                    notices.append("Contesto GIE: ultima cache valida, aggiornamento non riuscito.")
                else:
                    failures.pop("context:"+key, None)
            except FAILURES:
                previous["error"] = "Fonte non aggiornata; eventuale copia precedente conservata."
                failures["context:"+key] = now
                notices.append("Contesto GIE non aggiornato: "+("scorte nazionali." if key == "AGSI+_IT" else "avvisi IIP."))
            state[key] = previous
    elif network.bindings_for(identifier, "AGSI+") or network.bindings_for(identifier, "ALSI"):
        notices.append("GIE impianto non interrogato: accesso server non configurato.")
    saved["failures"] = failures
    saved["notices"] = tuple(notices)
    state[STATE] = saved
    return tuple(notices)
