"""Bounded evidence projection and structured response validation."""
from decimal import Decimal, InvalidOperation
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


_UNIT=r"(?:€|EUR)\s*/\s*MWh|GWh(?:\s*/\s*(?:giorno(?: gas)?|mese|[dg]))?|TWh|MWh|MW|bcm|Sm[3³]|°\s*C|%|€|EUR"
_CLAIM=re.compile(
    r"(?<![\w.,])(?P<number>[+−-]?(?:\d{1,3}(?:[. \u00a0]\d{3})+(?:,\d+)?|\d+(?:[,.]\d+)?))"
    r"\s*(?P<unit>"+_UNIT+r")(?![\w/])",re.I)
_LOWER_UPPER=re.compile(
    r"\b(?:da|tra|fra)\s+(?P<number>[+−-]?\d+(?:[.,]\d+)?)\s+"
    r"(?:e|a)\s+[+−-]?\d+(?:[.,]\d+)?\s*(?P<unit>"+_UNIT+r")(?![\w/])",re.I)
_SUFFIX_UNITS={"eur_mwh":"€/mwh","temperature_c":"°c","twh":"twh","gwh":"gwh","mwh":"mwh","pct":"%"}
_SEMANTIC_FIELDS={"load":"gwh","wind":"gwh","estimate":"gwh","lower_80":"gwh","upper_80":"gwh"}
_EURO_UNITS={"eur":"€","eur/mwh":"€/mwh"}


def _unit(raw):
    if isinstance(raw,str):
        # The source's period and scope remain independent of the energy unit.
        match=re.match(_UNIT,raw.strip(),re.I)
        if match:
            unit=re.sub(r"\s+","",match[0].lower())
            return "gwh" if unit.startswith("gwh/") else "sm3" if unit=="sm³" else _EURO_UNITS.get(unit,unit)
    return None


def _decimal_forms(raw):
    text=re.sub(r"\s+","",raw.replace("−","-"))
    if "," in text:
        options=(text.replace(".","").replace(",","."),)
    elif "." in text and re.fullmatch(r"[+-]?\d{1,3}(?:\.\d{3})+",text):
        options=(text,text.replace(".","")) if text.count(".")==1 else (text.replace(".",""),)
    else:
        options=(text,)
    return tuple((Decimal(form),len(form.partition(".")[2])) for form in options)


def _claims(text):
    # Include both ends of the standard Italian range "da x a y UNITÀ".
    for pattern in (_CLAIM,_LOWER_UPPER):
        for match in pattern.finditer(text):
            try:
                yield _unit(match["unit"]),_decimal_forms(match["number"])
            except InvalidOperation:
                continue


def _values(data, inherited=None):
    if isinstance(data,dict):
        if data.get("status") in ("stale","unavailable","failed"):
            return
        unit=_unit(data.get("unit")) or inherited
        for key,value in data.items():
            field_unit=next((u for tail,u in _SUFFIX_UNITS.items()
                             if key==tail or key.endswith("_"+tail) or "_"+tail+"_" in key),None)
            if inherited=="%" or key.endswith("_pct"):
                field_unit="%"
            if isinstance(value,(dict,list)):
                yield from _values(value,field_unit or unit)
            elif type(value) in (int,float):
                field_unit=field_unit or _SEMANTIC_FIELDS.get(key) or (unit if key=="value" else None)
                if field_unit:
                    amount=Decimal(str(value))
                    if amount.is_finite():
                        yield field_unit,amount
    elif isinstance(data,list):
        for item in data:
            yield from _values(item,inherited)


def model_context(context):
    """Expose usable tuples and keep source gaps as metadata only."""
    def usable(value):
        if isinstance(value,dict):
            # A multi-series snapshot can be available overall while one
            # constituent quote is stale. Filter at the model boundary only.
            if value.get("status") in ("unavailable","stale","failed"):
                keep={"source","scope","status","period","gas_day","grain","unit",
                      "acquired","reason","kind","limitation","definition"}
                return {k:usable(v) for k,v in value.items() if k in keep}
            return {k:usable(v) for k,v in value.items()}
        if isinstance(value,list):
            return [usable(v) for v in value]
        return value

    safe={}
    for key,item in compact_context(context).items():
        # GME observations stay in the local view even if another analysis
        # attaches market prices to a Run in the future.
        if re.search(r"\bGME\b|Gestore dei Mercati Energetici",key+" "+str(item.get("source","")),re.I):
            continue
        safe[key]=usable(item)
    return safe


def verify_price_semantics(sections, public):
    """Reject gas-price figures relabelled as electrical wholesale prices.

    This is a conservative domain guard, not a general semantic proof.
    No electricity-price adapter is currently integrated; Terna's energy
    observations and gas prices cannot substantiate an electricity quote.
    """
    from .assistant_sources import electricity_price_question
    for section in sections:
        # Keep decimal points and CMEM,m intact; split only sentence boundaries.
        sentences=re.split(r"(?<=[!?;])\s+|(?<!\bes)(?<!\bad)\.\s+|\n+",section["text"],flags=re.I)
        for sentence in sentences:
            for match in _CLAIM.finditer(sentence):
                if _unit(match["unit"])!="€/mwh":
                    continue
                # A gas quote and a missing electrical quote must be
                # stated separately, regardless of which comes first.
                if electricity_price_question(sentence):
                    raise InvalidSynthesis("Prezzo elettrico non verificabile: le fonti gas non sono quotazioni elettriche.")
            # A recommendation to use PSV/TTF as an electricity spot
            # price is erroneous even without a numerical claim.
            if electricity_price_question(sentence) and re.search(r"\b(?:psv|ttf|cmem)\b",sentence,re.I):
                if re.search(r"\b(?:esempio|es\.|consulta\w*|utilizz\w*|accedere|occorre|serve|usare)\b",sentence,re.I) and not re.search(r"\b(?:non|invece|distint\w*|gas naturale)\b",sentence,re.I):
                    raise InvalidSynthesis("PSV, TTF e CMEM,m non sono fonti dei prezzi elettrici.")


def verify_metric_bindings(sections, public):
    """Check explicit metric/value phrases, not just numbers sharing a unit.

    Deliberately narrow grammar: only direct labelled observations from public
    sources. Complex agent calculations and ambiguous prose still go through
    the existing numeric checks. No extra inference call.
    """
    from .assistant_sources import METRIC_CATALOG, metric_value
    for section in sections:
        refs=section["references"]
        if not refs or not all(ref.startswith("src:") for ref in refs):
            continue
        text=section["text"]
        for match in _CLAIM.finditer(text):
            prefix=text[max(0,match.start()-150):match.start()]
            unit=_unit(match["unit"])
            candidates=[]
            for source,metrics in METRIC_CATALOG.items():
                for metric in metrics:
                    if not metric.aliases or _unit(metric.unit)!=unit:
                        continue
                    pattern=r"(?<!\w)(?:"+"|".join(re.escape(a) for a in metric.aliases)+r")\s*(?:(?:è|sono)\s*(?:pari\s+a\s*)?|[:=])?\s*$"
                    label=re.search(pattern,prefix,re.I)
                    if label:
                        # Changes and comparisons are not absolute observations.
                        if re.search(r"(?:variazione|aumento|incremento|calo|diminuzione|differenza)\s+(?:del(?:la|le|lo)?|di|dei)\s*$",prefix[:label.start()],re.I):
                            continue
                        candidates.append((source,metric))
            if not candidates:
                continue
            try:
                forms=_decimal_forms(match["number"])
            except InvalidOperation:
                continue
            values=[]
            for source,metric in candidates:
                for ref in refs:
                    key=ref[4:]
                    if key==source or source=="AGSI+" and key.startswith("AGSI+ ·"):
                        value=metric_value(source,public.get(key,{}),metric)
                        if value is not None:
                            values.append(Decimal(str(value)))
            if not any(abs(amount-value)<=Decimal("0.5").scaleb(-places)
                       for value in values for amount,places in forms):
                raise InvalidSynthesis("Valore non associabile all’indicatore esplicitamente citato.")


def verify_measurements(sections, tools, public):
    """Check unit-bearing figures against the sources cited in each section."""
    verify_price_semantics(sections,public)
    verify_metric_bindings(sections,public)
    numbers={"src:"+name:set(_values(item)) for name,item in public.items()}
    for agent,item in tools.items():
        if item.get("status") not in ("completed","review"):
            continue
        statements=[item["summary"],*(ref["support"] for ref in item.get("sources",[]))]
        numbers[agent]={(unit,amount) for statement in statements for unit,forms in _claims(statement)
                        for amount,_ in forms} | set(_values(item.get("projection",{})))
    for section in sections:
        allowed=set().union(*(numbers.get(ref,set()) for ref in section["references"]))
        # Canonical energy quantities still support ordinary GWh citations.
        # Explicit monthly/daily denominators must also match known source grain.
        for match in _CLAIM.finditer(section["text"]):
            raw_unit=re.sub(r"\s+","",match["unit"].casefold())
            if not raw_unit.startswith("gwh/"):
                continue
            grain="mese" if raw_unit=="gwh/mese" else "giorno gas"
            compatible=set()
            for ref in section["references"]:
                item=public.get(ref[4:],{}) if ref.startswith("src:") else {}
                known=item.get("grain")
                unit=str(item.get("unit","")).casefold()
                if not known and unit.startswith("gwh/"):
                    known="mese" if "mese" in unit else "giorno gas"
                if known in (None,grain):
                    compatible.update(numbers.get(ref,set()))
            try:
                forms=_decimal_forms(match["number"])
            except InvalidOperation:
                continue
            if not any(unit=="gwh" and abs(amount-known)<=Decimal("0.5").scaleb(-places)
                       for unit,known in compatible for amount,places in forms):
                raise InvalidSynthesis("La sintesi confonde una quantità giornaliera e mensile.")
        for unit,forms in _claims(section["text"]):
            if not any(unit==known_unit and abs(amount-known)<=Decimal("0.5").scaleb(-places)
                       for known_unit,known in allowed for amount,places in forms):
                raise InvalidSynthesis("La sintesi riporta un valore o un’unità non riscontrabili nelle fonti citate.")


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
