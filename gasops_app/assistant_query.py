"""Deterministic, bounded historical queries for the main assistant.

Use the central semantic catalog, validated source adapters and existing
statistical engine. No arbitrary SQL, generated code, private GME data or
model calls. Only explicit historical intervals enter this path.
"""
from datetime import date, timedelta
from hashlib import sha256
import json
import re

import pandas as pd

from . import assistant_sources as src
from .data import ROME
from .gas_calendar import closed_gas_day
from .models import Kind, Origin, Run
from .public_data import SourceUnavailable

DAILY_LIMIT=90
MONTHLY_LIMIT=36
OPS={
    "correlation":r"\bcorrelazion\w*",
    "std":r"\bdeviazione\s+standard\b",
    "sum":r"\b(?:totale|complessiv\w*|somma|cumulat\w*)\b",
    "mean":r"\bmedi[aoei]\b",
    "min":r"\bminim\w*\b",
    "max":r"\bmassim\w*\b",
    "change":r"\b(?:variazion\w*|cambiat\w*|andamento|cresciut\w*|aumentat\w*|diminuit\w*)\b",
}
RELATIVE=re.compile(r"\bultim[ie]\s+(\d{1,4})\s+(giorni|mesi)\b",re.I)
EXCLUDED=r"\b(?:prevision\w*|forecast|simul\w*|scenario|stress|settlement|pdf|document\w*|contratt\w*|normativ\w*|articolo)\b"


def operation(question):
    # "totale medio" describes an average of a total series, not a sum.
    found=[key for key,pattern in OPS.items() if re.search(pattern,question,re.I)]
    if "mean" in found and "sum" in found:
        found.remove("sum")
    if len(found)==1:
        return found[0]
    return None


def query_intent(question):
    if question.startswith("/") or re.search(EXCLUDED,question,re.I):
        return False
    if not any(re.search(p,question,re.I) for p in OPS.values()):
        return False
    if RELATIVE.search(question) or re.search(r"\bultim[ie]\s+\d+\s+(?:settiman\w*|ann\w*)\b",question,re.I):
        return True
    # A two-point comparison remains in the existing point lookup path.
    return bool(re.search(r"\b(?:dal|dall[’']|da|tra|fra)\b",question,re.I)
                and re.search(r"\b(?:al|all[’']|a|fino|e)\b",question,re.I)
                and (len(src.query_months(question))>=2 or len(src.query_days(question) or ())>=2))


def shift_month(day,n):
    i=day.year*12+day.month-1+n
    year,month=divmod(i,12)
    return date(year,month+1,1)


def interval(question,now):
    today=now.astimezone(ROME).date()
    latest_month=shift_month(today,-1)
    latest_day=closed_gas_day(now)
    months=src.query_months(question)
    days=src.query_days(question,today=today)
    relatives=RELATIVE.findall(question)
    if days is None or (months and days) or len(relatives)>1 or (relatives and (months or days)):
        raise ValueError("Indica un solo intervallo valido, senza combinare mesi e giorni.")
    if relatives:
        n,unit=relatives[0]
        n=int(n)
        limit=MONTHLY_LIMIT if unit.lower()=="mesi" else DAILY_LIMIT
        if not 1<=n<=limit:
            raise ValueError("Intervallo massimo: 90 giorni gas o 36 mesi conclusi.")
        grain="month" if unit.lower()=="mesi" else "gas_day"
        last=latest_month if grain=="month" else latest_day
        first=shift_month(last,1-n) if grain=="month" else last-timedelta(days=n-1)
    elif len(months)==2 and not days:
        first,last=months
        grain="month"
    elif days and len(days)==2 and not months:
        first,last=days
        grain="gas_day"
    else:
        raise ValueError("Indica due date, due mesi oppure gli ultimi N giorni/mesi.")
    expected=(pd.date_range(first,last,freq="MS" if grain=="month" else "D")
              if (last-first).days<=1100 else ())
    if (first<date(2018,1,1) or not len(expected)
        or len(expected)>(MONTHLY_LIMIT if grain=="month" else DAILY_LIMIT)
        or last>(latest_month if grain=="month" else latest_day)):
        raise ValueError("Periodo non supportato: dal 2018, massimo 36 mesi o 90 giorni gas conclusi.")
    return grain,first,last


def metric_keys(question,grain):
    """Conservative explicit aliases; never use a sibling as a substitute."""
    text=question.casefold().replace("’","'")
    if src.electricity_price_question(text) or re.search(
            r"\b(?:psv|ttf|igi|gnl|lng|gme|acer|mase|unmig|terna|hdd|meteo|temperatur\w*|eolic\w*|fotovoltaic\w*|umm|capacità|linepack|jarvis|transit\w*|nomina\w*|allocazion\w*)\b",text):
        raise ValueError("Indicatore non ancora supportato dal motore su intervalli; nessuna fonte sostitutiva.")
    if re.search(r"\b(?:elettric\w*|power)\b",text) and not re.search(r"\b(?:gas|metano|srg|entsog)\b",text):
        raise ValueError("Il mercato elettrico non è un indicatore di gas.")
    if re.search(r"\b(?:nord|sud|lombardia|sicilia|piemonte|regione|regional\w*|bergamo|milano|tarvisio|mazara|melendugno|passo gries)\b",text):
        raise ValueError("Perimetro regionale o di punto non supportato.")
    chosen=[]
    def add(source,field):
        chosen.append((source,field))
    storage=bool(re.search(r"\b(?:stoccagg\w*|agsi|scorte|giacenz\w*|riempimento)\b",text))
    if storage:
        if grain!="gas_day":
            raise ValueError("Le serie di stoccaggio usano giorni gas, non mesi aggregati.")
        if re.search(r"riempiment|percentuale",text):
            add("AGSI+","fill_pct")
        if re.search(r"\b(?:giacenz\w*|scorte|gas in stoccaggio)\b",text):
            add("AGSI+","stock_twh")
        if re.search(r"preliev",text):
            add("AGSI+","withdrawal_gwh_d")
        if re.search(r"iniezion|immiss",text):
            add("AGSI+","injection_gwh_d")
        if not chosen:
            raise ValueError("Specifica giacenza, riempimento, prelievi o iniezioni degli stoccaggi.")
    if re.search(r"\b(?:cmem|arera)\b",text):
        if grain!="month":
            raise ValueError("CMEM,m è un riferimento mensile, non giornaliero.")
        add(src.PRICE,"value")
    elif re.search(r"\b(?:prezz\w*|quotazion\w*|cost\w*)\b",text):
        raise ValueError("Specifica CMEM,m per il riferimento mensile gas; non equivale a prezzi spot.")
    if re.search(r"importazion|esportazion|produzione nazionale|disponibilit[aà] contabil",text):
        if grain!="month":
            raise ValueError("Importazioni, esportazioni e produzione nazionale richiedono il bilancio mensile Eurostat.")
        if re.search(r"importazion",text):
            add(src.MONTHLY,"net_imports_gwh" if re.search(r"importazion\w*\s+nett",text) else "imports_gwh")
        if re.search(r"esportazion",text):
            add(src.MONTHLY,"exports_gwh")
        if re.search(r"produzione nazionale",text):
            add(src.MONTHLY,"production_gwh")
        if re.search(r"disponibilit[aà] contabil",text):
            add(src.MONTHLY,"supply_gwh")
    sector=False
    for pattern,field in ((r"\b(?:industria|industrial\w*)\b","industry_gwh"),
                          (r"\b(?:distribuzion\w*|residenzial\w*|domestic\w*)\b","distribution_gwh"),
                          (r"\b(?:termoelettric\w*|generazion\w* elettric\w*)\b","power_gwh")):
        if re.search(pattern,text):
            if grain!="gas_day":
                raise ValueError("Il dettaglio dei settori SRG è giornaliero; indica giorni gas.")
            add(src.DAILY,field)
            sector=True
    if not sector and re.search(r"\b(?:consum\w*|domanda|preliev\w*)\b",text) and not (
            storage and not re.search(r"\b(?:srg|entsog|consum\w*|domanda)\b",text)):
        explicit_srg=bool(re.search(r"\b(?:srg|entsog|preliev\w*)\b",text)) and not storage
        if grain=="month" and explicit_srg:
            raise ValueError("SRG è giornaliero; non sostituire i prelievi con il bilancio nazionale.")
        if grain=="gas_day" and re.search(r"\b(?:nazional\w*|eurostat)\b",text):
            raise ValueError("Il consumo nazionale Eurostat è mensile. I prelievi SRG sono un proxy distinto.")
        add(src.MONTHLY if grain=="month" else src.DAILY,"demand_gwh")
    if not chosen:
        raise ValueError("Indicatore non riconosciuto. Specifica consumi, importazioni, produzione, CMEM,m o stoccaggi.")
    return tuple(dict.fromkeys(chosen))


def build_plan(question,now):
    from .country_analysis import requested_country
    if requested_country(question) is not None:
        raise ValueError("Il motore su intervalli supporta per ora soltanto l'Italia.")
    op=operation(question)
    if not op:
        raise ValueError("Richiedi una sola operazione: media, totale, minimo, massimo, variazione, deviazione standard o correlazione.")
    grain,first,last=interval(question,now)
    keys=metric_keys(question,grain)
    if len(keys)>3:
        raise ValueError("Seleziona al massimo tre indicatori.")
    if op=="correlation" and (len(keys)!=2 or grain!="gas_day"):
        raise ValueError("La correlazione richiede due serie con la stessa frequenza giornaliera gas.")
    if op=="sum" and any(source not in (src.MONTHLY,src.DAILY) for source,_ in keys):
        raise ValueError("Non sommare prezzi, percentuali, scorte o flussi di stoccaggio in questo motore.")
    return {"operation":op,"grain":grain,"from":first.isoformat(),"to":last.isoformat(),
            "metrics":[list(key) for key in keys]}


def acquire(store,plan,now,gie_key=""):
    """Fetch each required family once (SRG at most three bounded windows)."""
    from . import eurostat, entsog
    from .mensile import load_arera
    from .operational_sources import load_agsi
    from .quality import inspect
    from .data_analyst import Series, unique_series
    first,last=map(date.fromisoformat,(plan["from"],plan["to"]))
    items={};issues={}
    for source in dict.fromkeys(key[0] for key in plan["metrics"]):
        fields=[field for family,field in plan["metrics"] if family==source]
        try:
            if source==src.MONTHLY:
                bundle=eurostat.load(store,geo="IT")
            elif source==src.DAILY:
                parts=[]
                cursor=first
                while cursor<=last:
                    end=min(cursor+timedelta(days=30),last)
                    try:
                        parts.append(entsog.load_range(store,cursor,end,now=now))
                    except SourceUnavailable:
                        pass
                    cursor=end+timedelta(days=1)
                bundle=entsog.combine(parts,first,last)
            else:
                bundle=None
            if bundle is not None:
                if bundle.origin.archive or bundle.origin.kind not in (Kind.LIVE,Kind.HISTORICAL):
                    raise ValueError("Origine non compatibile")
                frame=inspect(bundle,now).usable
                source_name,url=bundle.origin.name,bundle.origin.url
                status="Ultima cache valida" if bundle.origin.refresh_failed else "Dato pubblicato; soggetto a revisione"
                origin=bundle.fingerprint
                scope="Italia" if source==src.MONTHLY else "Tre aggregati di prelievo SRG; non consumo nazionale"
                raw={field:zip(frame.index.date,frame[field]) for field in fields if field in bundle.origin.fields}
            elif source==src.PRICE:
                result=load_arera(store)
                source_name,url=result.source.name,result.source.url
                status="Ultima cache valida" if result.source.refresh_failed else "Riferimento mensile gas, non spot"
                origin=result.source.retrieved_at.isoformat()
                scope="Italia";raw={"value":result.rows.items()}
            elif source=="AGSI+":
                result=load_agsi(store,gie_key,"IT",now=now,first=first,last=last)
                if result["scope"]!="IT":
                    raise ValueError("Perimetro non compatibile")
                frame=result["frame"]
                source_name,url=result["source"],result["source_url"]
                status="Ultima cache valida" if result["failed"] else "Dati GIE, possibili stime e revisioni"
                origin=result["acquired"].isoformat()
                scope="Italia · perimetro GIE"
                raw={field:zip(frame.gas_day,frame[field]) for field in fields if field in frame}
            else:
                raise ValueError("Fonte non supportata")
            for field in fields:
                metric=next(m for m in src.METRIC_CATALOG[source] if m.field==field)
                key=source+"|"+field
                values=unique_series(raw.get(field,()))
                items[key]=Series(key,metric.label,metric.unit,plan["grain"],scope,source_name,url or "",
                                  status,origin,values,False)
        except (SourceUnavailable,ValueError,TypeError,KeyError,OSError,ArithmeticError):
            issues[source]="Fonte non disponibile o non validabile per l'intervallo."
    return items,issues


def calculate(plan,items,issues):
    from .data_analyst import stats,analyse,MIN_PAIRS
    first,last=plan["from"],plan["to"]
    expected={d.date().isoformat() for d in pd.date_range(first,last,freq="MS" if plan["grain"]=="month" else "D")}
    out=[];valid=[]
    op=plan["operation"]
    for source,field in plan["metrics"]:
        key=source+"|"+field
        metric=next(m for m in src.METRIC_CATALOG[source] if m.field==field)
        item=items.get(key)
        count=len(expected.intersection(item.values.index)) if item is not None else 0
        row={"id":key,"metric":metric.label,"source":item.source if item is not None else source,
             "scope":item.scope if item is not None else "Italia","unit":metric.unit,"n":count,
             "expected":len(expected),"url":src.safe_source_url(item.url) if item is not None else None,
             "status":item.status if item is not None else issues.get(source,"Non disponibile"),
             "provenance":item.origin if item is not None else None,"value":None}
        if count!=len(expected):
            row["reason"]="Periodo incompleto: nessuna statistica sostitutiva."
        else:
            valid.append(key)
            s=stats(item,first,last)
            v=item.values.loc[(item.values.index>=first)&(item.values.index<=last)]
            if op=="sum":
                row["value"]=float(v.sum());row["unit"]="GWh"
            elif op=="std":
                if count<MIN_PAIRS:
                    row["reason"]="Servono almeno 14 osservazioni per la deviazione standard."
                else:
                    row["value"]=float(v.std(ddof=1))
            elif op=="change":
                row["value"]=s["change"]
                row["change_pct"]=s["change_pct"] if metric.quantity!="ratio" else None
                if metric.quantity=="ratio":row["unit"]="p.p."
                row["first_value"]=s["first_value"];row["last_value"]=s["last_value"]
            elif op!="correlation":
                row["value"]=s[op]
        out.append(row)
    result={"plan":plan,"rows":out,"correlations":[]}
    if op=="correlation" and len(valid)==2:
        result["correlations"]=analyse(items,valid,first,last)["correlations"]
    return result


def query_report(question,store,now,*,gie_key=""):
    try:
        plan=build_plan(question,now)
    except ValueError as error:
        return Run(question=question,source=Origin(name="Motore analitico",kind=Kind.HISTORICAL,grain="daily",
            fields=(),description="Nessuna acquisizione eseguita.",retrieved_at=now),input_sha256="",
            assumptions={"assistant_data_query":True},summary=str(error),finished_at=now,validated_at=now)
    items,issues=acquire(store,plan,now,gie_key)
    payload=calculate(plan,items,issues)
    digest=sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True,allow_nan=False).encode()).hexdigest()
    found=bool(payload["correlations"] or any(row["value"] is not None for row in payload["rows"]))
    return Run(question=question,source=Origin(name="Motore analitico · fonti selezionate",kind=Kind.HISTORICAL,
        grain="monthly" if plan["grain"]=="month" else "daily",fields=(),description="Calcoli deterministici sulle serie validate.",
        retrieved_at=now,latest_period=plan["to"]),input_sha256=digest,
        assumptions={"assistant_data_query":True,"assistant_query_evidence":payload},
        summary="Calcolo locale completato." if found else "Nessun risultato calcolabile per l'intervallo richiesto.",
        finished_at=now,validated_at=now)
