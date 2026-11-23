"""Explicit, bounded refresh; rendering and filtering never call these loaders."""
from datetime import timedelta
from time import monotonic
import sqlite3

from .entsog import _last_completed
from .italian_network_events import load_interruptions
from .italian_network_sources import load_catalog, load_point, load_facility
from .operational_sources import load_agsi, load_iip
from .public_data import SourceUnavailable

STATE = "italian_network_data_v1"
FAILURES = (SourceUnavailable, ValueError, OSError, sqlite3.Error)


def refresh_network(state, store, network, identifier, direction, first, last, now, *, api_key=None,
                    targets=None, include_context=True, progress=None):
    if not 0 <= (last-first).days < 31 or last > _last_completed(now):
        raise ValueError("Seleziona da 1 a 31 giorni gas conclusi")
    targets=tuple(dict.fromkeys(targets if targets is not None else ((identifier,direction),)))
    known={i.id for i in network.infrastructure}
    if not targets or len(targets)>24 or any(i not in known or d not in (None,"entry","exit") for i,d in targets):
        raise ValueError("Infrastruttura non riconosciuta")
    saved = dict(state.get(STATE, {}))
    if saved.get("attempted") and now-saved["attempted"] < timedelta(minutes=1):
        return ("Aggiornamento già richiesto: attendi un minuto.",)
    saved["attempted"] = now
    state[STATE] = saved
    notices, failures = [], dict(saved.get("failures", {}))
    started=monotonic()
    pending=[]
    updated=facilities=0
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

    points={b.point_direction:b for i,d in targets for b in network.bindings_for(i,"ENTSOG")
        if b.direction==d and b.mapping_confidence=="confirmed"}
    prior_pending=set(saved.get("pending",()))
    points=dict(sorted(points.items(),key=lambda item:item[0] not in prior_pending))
    for index,binding in enumerate(points.values()):
        if monotonic()-started>90:
            pending.extend(list(points)[index:])
            break
        if progress:progress(index,len(points),binding.expected_label)
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
                updated+=1
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
        bindings={(b.provider,b.external_id):b for i,_ in targets for b in network.bindings_for(i)
            if b.provider in ("AGSI+","ALSI") and b.mapping_confidence=="confirmed"}
        bindings=dict(sorted(bindings.items(),key=lambda item:':'.join(item[0]) not in prior_pending))
        for index,binding in enumerate(bindings.values()):
            if monotonic()-started>90:
                pending.extend(provider+":"+eic for provider,eic in list(bindings)[index:])
                break
            try:
                result = load_facility(store, api_key, binding, first, last, refresh=True)
                saved.setdefault("facilities", {})[(binding.provider, binding.external_id)] = result
                facilities+=1
                if result["failed"]:
                    failures[binding.provider+":"+binding.external_id] = now
                else:
                    failures.pop(binding.provider+":"+binding.external_id, None)
                notices.append("Dati GIE dell’impianto acquisiti." if not result["failed"] else "GIE impianto: ultima cache valida.")
            except FAILURES:
                failures[binding.provider+":"+binding.external_id] = now
                notices.append("Dati GIE dell’impianto non aggiornati.")
        # Reuse the canonical states and loaders of the existing GIE views.
        for key, loader in ((("AGSI+_IT", load_agsi), ("gie_iip", load_iip)) if include_context else ()):
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
    elif any(network.bindings_for(i,"AGSI+") or network.bindings_for(i,"ALSI") for i,_ in targets):
        notices.append("GIE impianto non interrogato: accesso server non configurato.")
    if pending:notices.append(f"Acquisizione parziale: {len(pending)} punti rinviati al prossimo aggiornamento.")
    saved["pending"]=tuple(pending)
    relevant={"catalog",*points,*("interruptions:"+point for point in points)}
    if api_key:
        relevant.update(b.provider+":"+b.external_id for b in bindings.values())
        if include_context:relevant.update(("context:AGSI+_IT","context:gie_iip"))
    saved["summary"]={"points_requested":len(points),"snapshots":updated,"facilities":facilities,
        "partial":bool(pending or relevant.intersection(failures) or any(s.partial or s.failed for s in saved.get("snapshots",{}).values()
            if s.first==first and s.last==last))}
    if len(points)>1:notices.append(f"Rete: {updated}/{len(points)} estrazioni disponibili · {facilities} impianti GIE.")
    notices=list(dict.fromkeys(notices))
    saved["failures"] = failures
    saved["notices"] = tuple(notices)
    state[STATE] = saved
    return tuple(notices)


def refresh_network_batch(state,store,network,first,last,now,*,api_key=None,progress=None):
    """Same map engine and caches, for all verified Italian point directions."""
    from .italian_network import verified_bindings
    targets=[(b.infrastructure_id,b.direction) for b in verified_bindings(network)]
    if api_key:
        targets.extend((b.infrastructure_id,None) for b in network.bindings
            if b.provider in ("AGSI+","ALSI") and b.mapping_confidence=="confirmed")
    targets=list(dict.fromkeys(targets))
    pending=set(state.get(STATE,{}).get("pending",()))
    if pending:
        retry=[(i,d) for i,d in targets if any(b.point_direction in pending or b.provider+":"+b.external_id in pending
            for b in network.bindings_for(i) if b.direction==d or d is None)]
        if retry:targets=retry
    if not targets:raise ValueError("Nessuna associazione verificata disponibile")
    return refresh_network(state,store,network,*targets[0],first,last,now,api_key=api_key,
        targets=targets,include_context=False,progress=progress)
