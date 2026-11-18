"""Resolve explicit country questions before collecting evidence.

The default dashboard remains Italian. Germany is supported with isolated
Eurostat and GIE AGSI+ snapshots; other recognized geographies fail closed.
"""
import re
from datetime import datetime

from .agents import Assumptions, MarketContext
from .models import Kind, Origin, Run, utc_now
from .regulatory import Library
from .workflow import run_workflow, plan
from .models import Agent
from . import eurostat
from .operational_sources import load_agsi, attribution
from .briefing_context import inventory_context

COUNTRY_PATTERNS={
    "IT":r"\b(?:italia|italian[oaie]|italy)\b",
    "DE":r"\b(?:germania|tedesc[oahe]+|germany|german)\b",
    "OTHER":r"\b(?:europa|europe|europe[oaie]|francia|frances[ei]|france|spagna|spagnol[oaie]|spain|paesi bassi|olanda|dutch|netherlands|austria|austriac[oahe]+|belgio|belgium|polonia|poland|regno unito|uk|united kingdom|svizzera|switzerland|norvegia|norway|ucraina|ukraine|portogallo|portugal|grecia|greece|russia|stati uniti|usa|ungheria|repubblica ceca|danimarca|svezia|finlandia|turchia)\b",
}


def requested_country(question):
    matches=[code for code,pattern in COUNTRY_PATTERNS.items() if re.search(pattern,question,re.I)]
    if not matches or matches==["IT"]:return None
    return "DE" if matches==["DE"] else "unsupported"


def direct_market_question(question):
    targets={call.agent for call in plan(question,False)}
    return targets=={Agent.MARKET}


def country_report(store,question,country,model_name,reasoner,*,gie_key="",include_gie=True,
                   notify=None,clock=utc_now):
    now=clock()
    def unavailable(reason):
        name="Germania" if country=="DE" else "Perimetro richiesto"
        return Run(question=question,source=Origin(name=name,kind=Kind.HISTORICAL,grain="monthly",
            fields=(),description="Nessuna serie verificata per il quesito.",retrieved_at=now),
            input_sha256="",assumptions={"model":model_name,"requested_country":country,"scope_unavailable":True},
            summary=reason,finished_at=clock())
    if country!="DE":
        return unavailable("Il perimetro geografico o il confronto richiesto non è ancora supportato. Nessun dato italiano usato come sostituto. Sono disponibili analisi nazionali per Italia e Germania.")
    try:
        bundle=eurostat.load(store,geo="DE")
    except Exception:
        return unavailable("Bilancio mensile Eurostat della Germania non disponibile o non validabile. Riprova; nessun dato italiano usato come sostituto.")
    context=MarketContext(bundle,model_name,clock())
    public={"Copertura Germania":{"source":"Perimetro analitico Germania","scope":"DE","status":"unavailable",
                "reason":"Prezzi nazionali tedeschi/THE, flussi giornalieri e bilanciamento o settlement effettivi non integrati. Non usare prezzi PSV, dati SRG o normativa italiana."}}
    if include_gie:
        try:
            if not gie_key:raise ValueError("Chiave GIE non configurata.")
            snapshot=inventory_context(load_agsi(store,gie_key,"DE",now=now),clock(),"AGSI+")
            if snapshot["scope"]!="DE":raise ValueError("Perimetro non valido")
            public["AGSI+ Germania"]=snapshot
        except Exception:
            public["AGSI+ Germania"]={**attribution("AGSI+"),"scope":"DE","status":"unavailable",
                                        "reason":"Stoccaggi tedeschi non disponibili o non validabili."}
    report=run_workflow(context,Library(include_notes=False),Assumptions(model=model_name),question,
                        reasoner=reasoner,public_context=public,market_only=True,notify=notify)
    report.assumptions["requested_country"]=country
    return report
