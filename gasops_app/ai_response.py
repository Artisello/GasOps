"""Bounded evidence projection and structured response validation."""
import re
from .supervisor import ModelUnavailable
from .models import AGENT_LABELS, Agent

SECTION_TITLES={
    "summary":"In sintesi","market":"Mercato","supply":"Sicurezza delle forniture",
    "balancing":"Bilanciamento e previsioni","risk":"Esposizione e rischi",
    "priorities":"Priorità di verifica","answer":"Risposta","evidence":"Evidenze",
    "limits":"Limiti","next":"Verifiche successive",
}

# Remove redundant navigation/audit fields only; source labels, observation
# periods, units, status, limitations and measurements stay in the payload.
# The original full snapshot remains in Run.assumptions for traceability.
METADATA={"url","source_url","id","provenance","last_observed_values"}

def compact_context(context):
    def compact(value):
        if isinstance(value,dict):
            return {k:compact(v) for k,v in value.items() if k not in METADATA and v is not None}
        if isinstance(value,list):
            return [compact(v) for v in value]
        return value
    return {key:compact(value) for key,value in context.items() if isinstance(value,dict)}


class InvalidSynthesis(ModelUnavailable):
    """Recoverable format failure; never include raw model output."""


def reference_index(agents, public):
    # Short identifiers reduce copying mistakes and output tokens. Canonical
    # identifiers remain stable in exports and stored runs.
    codes={f"A{i}":ref for i,ref in enumerate(agents,1)}
    codes.update({f"S{i}":"src:"+key for i,key in enumerate(public,1)})
    aliases={}
    def add(label,ref):
        if isinstance(label,str) and label.strip():
            aliases.setdefault(label.strip().casefold(),set()).add(ref)
    for code,ref in codes.items():
        add(code,ref);add(ref,ref)
    for key,value in public.items():
        ref="src:"+key
        add(key,ref)
        add(value.get("source"),ref)
    return codes,{key:next(iter(refs)) for key,refs in aliases.items() if len(refs)==1}


def normalize_references(raw, aliases):
    if isinstance(raw,str):
        raw=[raw]
    if not isinstance(raw,list) or not 1<=len(raw)<=64:
        raise InvalidSynthesis("Riferimenti della sintesi AI mancanti o non validi.")
    refs=[]
    for ref in raw:
        resolved=aliases.get(ref.strip().casefold()) if isinstance(ref,str) else None
        if resolved is None:
            raise InvalidSynthesis("La sintesi contiene riferimenti non verificabili.")
        if resolved not in refs:refs.append(resolved)
    return refs


def parse_sections(raw, ids, agents, sources, limit, *, aliases=None):
    if aliases is None:
        aliases={ref.casefold():ref for ref in (*agents,*sources)}
    if not isinstance(raw,list) or not 1<=len(raw)<=len(ids):
        raise InvalidSynthesis("Numero o formato delle sezioni AI non valido.")
    names={key.casefold():key for key in ids}
    names.update({SECTION_TITLES[key].casefold():key for key in ids})
    sections=[];seen=set();size=0
    for item in raw:
        if not isinstance(item,dict):
            raise InvalidSynthesis("Formato della sezione AI non valido.")
        label=item.get("id")
        key=names.get(label.strip().casefold()) if isinstance(label,str) else None
        content=item.get("text")
        if key is None or key in seen:
            raise InvalidSynthesis("Sezione AI sconosciuta o duplicata.")
        if not isinstance(content,str) or not content.strip():
            raise InvalidSynthesis("Testo della sezione AI mancante.")
        # Strip only redundant, exact section headings (not substantive text).
        prefix=[SECTION_TITLES[key],key]
        if key=="summary":prefix+=["Conclusioni","Executive summary"]
        if key=="supply":prefix+=["Offerta"]
        if key=="balancing":prefix+=["Bilanciamento"]
        if key=="risk":prefix+=["Rischio"]
        content=content.strip()
        clean=re.sub(r"^(?:"+"|".join(re.escape(x) for x in prefix)+r")\s*:\s*","",content,count=1,flags=re.I)
        if clean.strip():content=clean
        size+=len(content.strip())
        if size>limit:
            raise InvalidSynthesis("Sintesi AI troppo lunga.")
        refs=normalize_references(item.get("references"),aliases)
        seen.add(key)
        sections.append({"id":key,"text":content.strip(),"references":refs})
    # Accept formatting differences without altering the interpretation.
    # In particular, source-only sections and a missing optional introduction
    # do not justify discarding otherwise attributable content.
    sections.sort(key=lambda item:ids.index(item["id"]))
    refs=list(dict.fromkeys(ref for item in sections for ref in item["references"]))
    return sections,refs


def reference_labels(run,references):
    public=run.assumptions.get("public_operational_context") or {}
    labels=[]
    for ref in references:
        if ref.startswith("src:"):
            item=public.get(ref[4:],{})
            label=str(item.get("source",ref[4:]))
            period=item.get("gas_day") or item.get("period") or item.get("acquired")
            if period:label+=" · "+str(period)[:10] if not item.get("period") else " · "+str(period)
            if item.get("status") in ("stale","unavailable"):
                label+=" · "+("non recente" if item["status"]=="stale" else "non disponibile")
        else:
            try:
                agent=Agent(ref)
                label=AGENT_LABELS[agent]
            except (ValueError,KeyError):continue
            result=run.results.get(agent)
            if result and agent in (Agent.MARKET,Agent.FORECAST,Agent.QUALITY):
                docs=list(dict.fromkeys(cite.document for cite in result.evidence))
                if docs:label+=" ("+"; ".join(docs)+")"
        if label not in labels:labels.append(label)
    return labels
