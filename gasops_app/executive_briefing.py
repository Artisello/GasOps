"""Concise management readout from already validated briefing results.

No model calls, external requests, or inference of missing operational positions.
"""
from datetime import date
from math import isfinite

from .italiano import numero
from .models import Agent, Kind


def _number(value):
    return value if isinstance(value,(int,float)) and not isinstance(value,bool) and isfinite(value) else None


def _values(run,agent):
    result=run.results.get(agent)
    return result.values if result and result.status in ("completed","review") else {}


def outlook_delta(run):
    """Compare the first forecast only with an immediately preceding observation."""
    facts=_values(run,Agent.MARKET)
    series=_values(run,Agent.FORECAST).get("forecast",{})
    points=series.get("points",[])
    actual=_number(facts.get("demand_gwh"))
    if not points or actual is None or actual<=0:
        return None
    estimate=_number(points[0].get("estimate"))
    if estimate is None:
        return None
    try:
        old=date.fromisoformat(facts["period"])
        new=date.fromisoformat(points[0]["period"])
    except (ValueError,TypeError,KeyError):
        return None
    comparable=((new-old).days==1 if run.source.grain=="daily"
                else new.year*12+new.month-old.year*12-old.month==1)
    return 100*(estimate/actual-1) if comparable else None


def management_readout(run):
    public=run.assumptions.get("public_operational_context") or {}
    facts=_values(run,Agent.MARKET)
    demand=_number(facts.get("demand_gwh_change_pct"))
    price=_number(facts.get("price_eur_mwh_change_pct"))
    historical=run.source.archive or run.source.refresh_failed or any(f.id=="stale" for f in run.findings)
    if run.source.kind==Kind.SYNTHETIC:
        overview="Dati dimostrativi: non descrivono il mercato corrente."
    elif historical:
        overview="Base informativa storica o non aggiornata: verificare l’attualità prima di utilizzarla."
    elif demand is not None and price is not None and demand>0 and price>0:
        overview="Consumi e prezzo medio aumentano insieme: monitorare la pressione sulla domanda e il costo del gas. Non dimostra uno sbilanciamento fisico."
    elif demand is not None and price is not None and demand<0 and price<0:
        overview="Consumi e prezzo medio diminuiscono nel confronto disponibile. Il dato non certifica l’equilibrio della rete."
    else:
        overview="Lettura alla frequenza della fonte: verificare separatamente domanda, prezzo e stato fisico della rete."
    delta=outlook_delta(run)
    forecast=("Prima stima "+numero(delta,1,signed=True)+"% rispetto all’ultimo consumo osservato; non è una variazione già realizzata."
              if delta is not None else "Confronto diretto tra previsione e ultimo consumo non disponibile.")
    priorities=[]
    failures=[f.title for f in run.findings if f.id.startswith("execution-")]
    if failures:
        priorities.append("Verificare gli errori di esecuzione prima di utilizzare i risultati interessati.")
    if any(name in public and (public[name].get("status")!="available" or
           (name=="IIP" and public[name].get("coverage")!="Completa"))
           for name in ("AGSI+","ALSI","IIP","Open-Meteo")):
        priorities.append("Controllare le fonti operative incomplete, in particolare le comunicazioni di indisponibilità se IIP non è verificato.")
    if run.source.kind!=Kind.SYNTHETIC and not historical:
        priorities.append("Confrontare la previsione con prelievi, nomination e indicatori di bilanciamento aggiornati.")
    else:
        priorities.append("Aggiornare la base osservata prima di interpretare la previsione.")
    priorities.append("Verificare posizioni, prezzi applicabili e garanzie nel dossier settlement; gli scenari qui sono simulazioni.")
    return overview,forecast,priorities[:3]
