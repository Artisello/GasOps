"""Read-only data for questions about verified Italian network points."""
from datetime import timedelta
from functools import lru_cache
import re


@lru_cache(maxsize=1)
def _catalog():
    from .italian_network import load_network_assets, verified_bindings
    network=load_network_assets()
    identifiers={binding.infrastructure_id for binding in verified_bindings(network)}
    return network,tuple(item for item in network.infrastructure if item.id in identifiers)


def _points(question, items):
    question=question.casefold()
    return tuple(item for item in items if re.search(
        r"(?<!\w)"+re.escape(item.name.split(" · ",1)[0].casefold())+r"(?!\w)",question))


def _aggregate(question):
    return bool(re.search(r"\bfrontiere italiane\b|\b(?:totale|complessiv\w*|aggregat\w*)\b.{0,45}"
                          r"\b(?:ingress[oi]|uscit[ae]|frontiere)\b|\b(?:alle|dalle) frontiere\b",question,re.I))


def relevant(question):
    if not re.search(r"\b(?:fluss[oi]|capacità|portata|transito|ingress[oi]|frontier[ae]|uscit[ae])\b",question,re.I):
        return False
    if _aggregate(question) or re.search(r"\bflusso fisico\b|\b(?:punt[oi] di (?:ingresso|uscita)|frontier[ae])\b",question,re.I):
        return True
    try:
        return bool(_points(question,_catalog()[1]))
    except (OSError,ValueError,KeyError):
        return False


def collect_network(store, state, now, question, *, day=None):
    from .entsog import SOURCE
    from .gas_calendar import closed_gas_day
    from .gas_data import source_context
    from .italian_network import merge_observations, point_intelligence, validated_observations, verified_bindings
    from .operational_acquisition import failures, journal
    from .system_status import build_status

    network,items=_catalog()
    points=_points(question,items)
    last=day or closed_gas_day(now)
    source={"source":"ENTSOG · rete italiana","source_url":SOURCE,"scope":"Italia · punti verificati",
            "gas_day":last.isoformat(),"unit":"GWh/giorno gas","kind":"observed",
            "limitation":"Flussi e capacità riferiti ai soli punti verificati. Il perimetro non misura il bilancio fisico nazionale."}
    missing={**source,"status":"unavailable","reason":"Nessun dato verificato in cache per il perimetro richiesto."}
    if last>closed_gas_day(now):
        return {**missing,"reason":"Il giorno gas richiesto non è concluso."}
    if not points and not _aggregate(question):
        return {**missing,"reason":"Indica il nome del punto ENTSOG o il totale alle frontiere italiane."}
    if len(points)>3:
        return {**missing,"reason":"Indica fino a tre punti per il confronto."}
    context=source_context(network,(),state,now,store=store,first=last-timedelta(days=6),last=last)
    snapshots=context["snapshots"]
    if not points:
        result=build_status(network,snapshots,{},now,gas_day=day)
        measure=result.entry_flow_observed
        if re.search(r"\b(?:uscit[ae]|esportaz\w*|exit)\b",question,re.I):
            measure=next(component.measure for component in result.components if component.id=="exports")
        if measure.value is None:
            return missing
        return {**source,"scope":measure.scope,"gas_day":measure.gas_day.isoformat(),
                "acquired":measure.retrieved_at.isoformat(),
                "status":"stale" if measure.freshness=="stale" and day is None else
                         "partial" if measure.coverage.valid<measure.coverage.expected else "available",
                "coverage":f"{measure.coverage.valid}/{measure.coverage.expected} punti",
                "values":{measure.source:{"flow_gwh_d":float(measure.value)}}}

    observations=validated_observations(network,merge_observations(snapshots),now,nonnegative=True)
    direction="exit" if re.search(r"\b(?:uscit[ae]|exit)\b",question,re.I) else (
        "entry" if re.search(r"\b(?:ingress[oi]|entry)\b",question,re.I) else None)
    bindings=tuple(binding for point in points for binding in verified_bindings(network,point.id)
                   if direction is None or binding.direction==direction)
    identities={binding.point_direction for binding in bindings}
    chosen=day or max((row.gas_day for row in observations if row.point_direction in identities
                      and row.indicator=="Physical Flow" and row.value is not None and row.gas_day and row.gas_day<=last),default=last)
    failed=failures(journal(store),chosen) if store is not None else ()
    labels={item.id:item.name for item in points}
    values,acquisitions={},[]
    previous_copy=False
    for binding in bindings:
        info=point_intelligence(network,binding.infrastructure_id,observations,chosen,now,
                                direction=binding.direction,snapshots=snapshots,failures=failed)
        if not info["available"]:
            continue
        if info["status"]["failed"] or (day is None and info["stale"]):
            previous_copy=True
            continue
        label=labels[binding.infrastructure_id]+" · "+("ingresso" if binding.direction=="entry" else "uscita")
        flat={"flow_gwh_d":info["values"].get("Physical Flow"),
              "technical_gwh_d":info["values"].get("Firm Technical"),
              "available_gwh_d":info["headroom_gwh_d"],"change_gwh_d":info["change_gwh_d"],
              "utilization_pct":info["utilization_pct"]}
        if any(value is not None for value in flat.values()):
            values[label]={name:float(value) for name,value in flat.items() if value is not None}
            acquisitions.append(info["status"]["oldest"])
    if not values:
        result={**missing,"scope":" · ".join(labels.values()),"gas_day":chosen.isoformat()}
        if previous_copy:
            result.update(status="stale",reason="Ultima copia ENTSOG non recente o aggiornamento non riuscito.")
        return result
    return {**source,"gas_day":chosen.isoformat(),"acquired":min(acquisitions).isoformat(),
            "status":"partial" if len(values)<len(bindings) else "available",
            "coverage":f"{len(values)}/{len(bindings)} punti/direzioni","values":values}
