"""Bounded evidence projection and structured response validation."""
from .supervisor import ModelUnavailable

SECTION_TITLES={
    "summary":"In sintesi","market":"Mercato","supply":"Sicurezza delle forniture",
    "balancing":"Bilanciamento e previsioni","risk":"Esposizione e rischi",
    "priorities":"Priorità di verifica","answer":"Risposta","evidence":"Evidenze",
    "limits":"Limiti","next":"Verifiche successive",
}

# Remove redundant navigation/audit fields only; source labels, observation
# periods, units, status, limitations and measurements stay in the payload.
# The original full snapshot remains in Run.assumptions for traceability.
METADATA={"url","source_url","id","provenance"}

def compact_context(context):
    def compact(value):
        if isinstance(value,dict):
            return {k:compact(v) for k,v in value.items() if k not in METADATA and v is not None}
        if isinstance(value,list):
            return [compact(v) for v in value]
        return value
    return {key:compact(value) for key,value in context.items() if isinstance(value,dict)}


def parse_sections(raw, ids, agents, sources, limit):
    def fail():
        raise ModelUnavailable("Struttura o riferimenti della sintesi AI non validi.")
    if not isinstance(raw,list) or not 1<=len(raw)<=len(ids):
        fail()
    allowed=set(agents)|set(sources)
    sections=[];refs=[];previous=-1;size=0
    for item in raw:
        if not isinstance(item,dict):
            fail()
        key=item.get("id");content=item.get("text");references=item.get("references")
        if not isinstance(key,str) or key not in ids or ids.index(key)<=previous:
            fail()
        if not sections and key!=ids[0]:
            fail()
        if not isinstance(content,str) or not content.strip():
            fail()
        size+=len(content.strip())
        if size>limit or not isinstance(references,list) or not references or len(references)>len(allowed):
            fail()
        if any(not isinstance(ref,str) or ref not in allowed for ref in references):
            fail()
        previous=ids.index(key)
        references=list(dict.fromkeys(references))
        refs.extend(ref for ref in references if ref not in refs)
        sections.append({"id":key,"text":content.strip(),"references":references})
    if not any(ref in agents for ref in refs):
        fail()
    return sections,refs
