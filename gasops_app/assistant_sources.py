"""Question-specific public evidence policy for the operational assistant.

No new providers or private records. Requirements are checked against the
actual evidence snapshot, not against model-generated source names.
"""
import re
from datetime import date, timedelta
from math import isfinite
from urllib.parse import urlsplit
from .italiano import MESI, numero

MONTHLY="Eurostat / ARERA"
DAILY="ENTSOG · SRG"
PRICE="ARERA · CMEM,m"
GIE=("AGSI+","ALSI","IIP")
WEATHER="Open-Meteo"
POWER=("Terna · elettricità","Terna · outlook")
ACER="ACER · GNL"
NETWORK="ENTSOG · rete italiana"
GME="GME"
MASE="MASE · UNMIG"
MARKET=(MONTHLY,DAILY)
LABELS={MONTHLY:"Eurostat",DAILY:"ENTSOG",PRICE:"ARERA",WEATHER:"Open-Meteo",
        "AGSI+":"GIE AGSI+","ALSI":"GIE ALSI","IIP":"GIE IIP",
        POWER[0]:"Terna · consuntivi",POWER[1]:"Terna · previsioni",ACER:"ACER · GNL",NETWORK:NETWORK,GME:"GME",MASE:MASE}
TOPICS=(
    ((MONTHLY,),r"eurostat|import(?:az|at|are|iamo)|esport(?:az|at|are|iamo)|produzione nazionale"),
    ((DAILY,),r"entsog|\bsrg\b|giornalier|settimanal"),
    (("AGSI+",),r"agsi|stoccagg|storage|giacenz|scorte"),
    (("IIP",),r"\biip\b|\bumm\b|indisponibil|outage"),
    (GIE,r"\bgie\b|sicurezza.*(?:fornitur|approvvigionament)"),
    ((WEATHER,),r"meteo|\bhdd\b|temperatur|climat|fredd|weather"),
)
DATE_TEXT=r"(?<!\d)(?:\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4})(?!\d)"


def gme_indicators(question):
    """Recognize the two price datasets shown in the local GME readout."""
    igi=bool(re.search(r"\bigi\b|\big\s*index\b", question, re.I))
    imbalance=bool(re.search(r"prezz.{0,35}sbilanciament|sbilanciament.{0,25}prezz|\bimbalance price\b",
                              question,re.I))
    if igi or imbalance:
        return tuple(key for key, matched in (("igi",igi),("prices",imbalance)) if matched)
    return ("igi","prices") if re.search(r"\bgme\b",question,re.I) else ()


_MONTH_DATE=r"(?<!\d)(\d{1,2})\s+("+"|".join(MESI)+r")\s+(\d{4})(?!\d)"
_RELATIVE_DAY={"ieri":-1,"oggi":0,"domani":1}


def mentions_day(question):
    return bool(re.search(DATE_TEXT+"|"+_MONTH_DATE+r"|\b(?:ieri|oggi|domani)\b",question,re.I))


def query_day(question, *, today=None):
    days=set()
    try:
        for raw in re.findall(DATE_TEXT,question):
            if "/" in raw:
                day,month,year=map(int,raw.split("/"))
                days.add(date(year,month,day))
            else:
                days.add(date.fromisoformat(raw))
        for day,month,year in re.findall(_MONTH_DATE,question,re.I):
            days.add(date(int(year),MESI.index(month.casefold())+1,int(day)))
    except ValueError:
        return None
    if today is not None:
        days.update(today+timedelta(days=_RELATIVE_DAY[word])
                    for word in re.findall(r"\b(?:ieri|oggi|domani)\b",question.casefold()))
    return next(iter(days)) if len(days)==1 else None


def requested_sources(question):
    question=question.casefold()
    names=[key for keys,pattern in TOPICS if re.search(pattern,question) for key in keys]
    if re.search(r"\b(?:mase|unmig)\b",question):
        names.append(MASE)
        if MONTHLY in names and not re.search(r"\beurostat\b|import|esport",question):
            names.remove(MONTHLY)
    gme=bool(gme_indicators(question))
    if gme and DAILY in names and not re.search(r"entsog|preliev|consum|domanda",question):
        names.remove(DAILY)
    lng=bool(re.search(r"\b(?:gnl|lng)\b",question))
    price=bool(re.search(r"prezz|price|quotaz|differenziale",question))
    acer=bool(re.search(r"\b(?:acer|ttf)\b",question)) or (lng and price)
    if re.search(r"\b(?:arera|psv)\b|cmem",question) or (price and not (acer or gme)):
        names.append(PRICE)
    if acer:
        names.append(ACER)
    if re.search(r"alsi|rigass|send.out|terminal|inventari",question) or (lng and not price):
        names.append("ALSI")
    if gme:
        names.append(GME)
    demand=bool(re.search(r"\b(?:domanda|consum[oi]|preliev[oi]|demand|consumption)\b",question))
    other=bool(re.search(r"consum[oi] elettric|domanda elettric|electricity demand|preliev[oi] (?:da|dagli|di) stocc",question))
    if demand and not other and MASE not in names:
        explicit=set(names)&set(MARKET)
        if not explicit:
            names.extend((MONTHLY,) if re.search(r"\bmensil\w*",question) else (DAILY,) if mentions_day(question) else MARKET)
    power=bool(re.search(r"terna|elettric|termoelettric|rinnovabil|fotovoltaic|eolic|power",question))
    outlook=bool(re.search(r"msd1|outlook|previ[ds].*(?:terna|elettric|eolic)|(?:terna|elettric|eolic).*previ[ds]",question))
    if power and (not outlook or re.search(r"consuntiv|osservat|misurat",question)):
        names.append(POWER[0])
    if outlook:
        names.append(POWER[1])
    if re.search(r"\b(?:panoramica|situazione|quadro)\b.{0,35}\b(?:mercato|gas)\b",question) and not names:
        names.extend((MONTHLY,DAILY,PRICE,ACER,*GIE,WEATHER,*POWER))
    if not other and re.search(r"prevision.*(?:gas|domanda|consum)|(?:gas|domanda|consum).*prevision",question):
        names.extend((MONTHLY,DAILY,WEATHER,*POWER))
    if re.search(r"fluss|capacità|portata|transito|ingress|frontier|uscit",question):
        from .assistant_network import relevant
        if relevant(question):
            names.append(NETWORK)
            if DAILY in names and not re.search(r"preliev|consum|domanda",question):
                names.remove(DAILY)
    return tuple(dict.fromkeys(names))


# A small, discoverable command vocabulary. The natural-language expansion
# enters the same source-aware read-only pipeline as a typed question.
COMMANDS={
    "/consumi":"Quali sono gli ultimi consumi nazionali Eurostat e prelievi SRG disponibili?",
    "/scorte":"Quali sono le scorte di gas in Italia (AGSI+)?",
    "/gnl":"Quali sono gli inventari e i flussi dei terminali GNL italiani (ALSI)?",
    "/prezzi":"Qual è il riferimento mensile ARERA CMEM,m?",
    "/produzione":"Qual è la produzione nazionale mensile di gas Eurostat?",
    "/mase":"Qual è la produzione di gas nell’archivio MASE UNMIG?",
    "/previsioni":"Qual è la prossima previsione della domanda di gas?",
    "/bollettino":"Bollettino sul mercato del gas",
}


def expand_command(question):
    """Return a question and optional issue; unknown commands never run tools."""
    question=question.strip()
    if not question.startswith("/"):
        return question,None
    command,_,argument=question.partition(" ")
    base=COMMANDS.get(command.casefold())
    if base is None:
        return None,"Comando non riconosciuto. Apri Info per consultare i comandi."
    if argument.strip():
        if command.casefold()=="/bollettino":
            return None,"Il bollettino usa gli ultimi dati disponibili; scrivi una domanda per una data precisa."
        base+=" "+argument.strip()
    if len(base)>600:
        return None,"Domanda troppo lunga."
    return base,None


def useful_source(item):
    return item.get("status") in (None,"available","partial") and any(
        item.get(key) is not None and item[key]!={} and item[key]!=[]
        for key in ("value","values","points","received_records"))


def safe_source_url(value):
    if not isinstance(value,str) or any(char.isspace() or char in "()\\<>" for char in value):
        return None
    try:
        url=urlsplit(value)
        return value if url.scheme=="https" and url.hostname and not url.username and not url.password else None
    except ValueError:
        return None


def add_price_source(public):
    """Expose nested ARERA as a distinct, date-specific citation target."""
    if PRICE in public or MONTHLY not in public:return public
    monthly=public[MONTHLY]
    price=monthly.get("price")
    if isinstance(price,dict):
        public[PRICE]=dict(price)
    else:
        public[PRICE]={"source":"ARERA · CMEM,m","status":"unavailable",
                       "reason":"Prezzo mensile non disponibile nella serie validata."}
    return public


def complete_requirements(public,requested):
    # Missing/disabled sources are explicit limitations, not invented evidence.
    for key in requested:
        if key not in public:
            public[key]={"source":LABELS.get(key,key),"status":"unavailable",
                         "reason":("Indicatori GME consultabili nella vista locale." if key==GME else
                                   "Fonte non disponibile per questa analisi o disattivata.")}
    return public


def citation_requirements(public,requested):
    return tuple("src:"+key for key in requested if key in public)


def missing_citations(refs,required):
    return [ref for ref in required if ref not in refs]


def source_evidence(key,item):
    """Human-readable observations from validated snapshots, never model output."""
    status=item.get("status")
    if status not in ("available","partial"):
        return item.get("reason") or ("Ultimo dato non recente." if status=="stale" else "Dato non disponibile.")
    values=item.get("values",{})
    def fmt(value,decimals=1):
        if isinstance(value,(int,float)) and not isinstance(value,bool) and isfinite(value):
            return numero(value,decimals)
        return None
    def fields(spec):
        parts=[]
        for field,label,unit in spec:
            val=fmt(values.get(field))
            if val is not None:parts.append(label+" "+val+(" "+unit if unit else ""))
        return parts
    def point_fields(points, specs):
        parts=[]
        for point in points:
            line=[]
            for field,label,unit in specs:
                value=fmt(point.get(field))
                if value is not None:
                    line.append(label+" "+value+(" "+unit if unit else ""))
            if line:
                parts.append(str(point.get("day") or point.get("period") or "data non indicata")+": "+", ".join(line))
        return parts
    parts=[]
    if key in MARKET:
        specs=(("demand_gwh","Consumi nazionali"),("production_gwh","Produzione nazionale"),
               ("imports_gwh","Importazioni"),("exports_gwh","Esportazioni"),
               ("net_imports_gwh","Importazioni nette"),("stock_change_gwh","Variazione scorte"),
               ("supply_gwh","Disponibilità contabile")) if key==MONTHLY else (
               ("demand_gwh","Prelievi dei tre aggregati SRG"),("distribution_gwh","Distribuzione"),
               ("industry_gwh","Industria"),("power_gwh","Termoelettrico"))
        unit="GWh/mese" if key==MONTHLY else "GWh/giorno gas"
        for field,label in specs:
            value=fmt(values.get(field))
            if value is not None:
                change=fmt(item.get("changes_pct",{}).get(field))
                parts.append(label+" "+value+" "+unit+(" ("+change+"%)" if change is not None else ""))
        if any(fmt(item.get("changes_pct",{}).get(field)) is not None for field,_ in specs):
            parts.append("Variazioni: "+str(item.get("comparison","periodo precedente")))
    elif key==MASE:
        for label,row in values.items():
            value=fmt(row.get("value"),3 if row.get("unit")=="bcm" else 0)
            if value is not None:
                parts.append(label+" "+value+" "+row["unit"])
        parts.append("Archivio storico · "+str(item.get("period","periodo non indicato")))
    elif key==PRICE:
        val=fmt(item.get("value"),2)
        if val is not None:parts=["CMEM,m "+val+" €/MWh · riferimento mensile, non spot"]
        delta=fmt(item.get("change_pct"))
        if delta is not None:parts.append("Variazione "+delta+"% sul mese precedente")
    elif key.startswith("AGSI+"):
        parts=fields((("fill_pct","Riempimento","%"),("stock_twh","Giacenza","TWh"),("withdrawal_gwh_d","Prelievo","GWh/g"),("injection_gwh_d","Iniezione","GWh/g")))
    elif key=="ALSI":
        parts=fields((("inventory_gwh","Inventario GNL","GWh"),("sendout_gwh_d","Send-out","GWh/g")))
    elif key=="IIP":
        val=item.get("received_records")
        if type(val) is int and val>=0:
            parts=[str(val)+" record UMM (non eventi) · "+str(item.get("coverage","copertura non indicata"))]
        if item.get("request_from") and item.get("request_to"):
            parts.append(str(item["request_from"])+" – "+str(item["request_to"]))
    elif key==NETWORK:
        measures=(("flow_gwh_d","Flusso fisico","GWh/g"),("technical_gwh_d","Capacità tecnica","GWh/g"),
                  ("available_gwh_d","Capacità disponibile pubblicata","GWh/g"),
                  ("change_gwh_d","Variazione D−1","GWh/g"),("utilization_pct","Utilizzo","%"))
        for label,row in values.items():
            data=[name+" "+value+" "+unit for field,name,unit in measures if (value:=fmt(row.get(field))) is not None]
            if data:
                parts.append(label+" · "+", ".join(data))
        if item.get("coverage"):
            parts.append(item["coverage"])
    elif key==ACER:
        for field,label in (("eu","Prezzo GNL UE"),("nwe","Prezzo GNL Nord-Ovest"),
                            ("south","Prezzo GNL Sud"),("benchmark","Differenziale GNL–TTF")):
            row=values.get(field,{})
            val=fmt(row.get("value"),2)
            if row.get("status")=="available" and val is not None:
                parts.append(label+" "+val+" €/MWh ("+str(row.get("period","data non indicata"))+")")
    elif key==WEATHER:
        points=item.get("points",[])
        qualified=[p for p in points if fmt(p.get("hdd")) is not None]
        peak=max(qualified,key=lambda p:p["hdd"]) if qualified else None
        if peak:
            parts=point_fields([peak],(("hdd","Picco HDD",""),("temperature_c","Temperatura","°C")))
    elif key==POWER[0]:
        for field,label in (("Thermal","Termoelettrico"),("Wind","Eolico"),("Photovoltaic","Fotovoltaico"),("Hydro","Idroelettrico"),("Geothermal","Geotermico"),("load","Fabbisogno")):
            row=values.get(field,{})
            val=fmt(row.get("value"))
            if val is not None:
                parts.append(label+" "+val+" GWh elettrici ("+str(row.get("period","data non indicata"))+")")
    elif key==POWER[1]:
        parts=point_fields(item.get("points",[]), (("load","Carico previsto","GWh elettrici"),("wind","Eolico previsto","GWh elettrici"),("load_minus_wind_gwh","Carico meno eolico","GWh elettrici")))
    return " · ".join(parts) or "Nessun indicatore sintetico disponibile; consulta i dati di dettaglio."


def source_rows(run):
    public=run.assumptions.get("public_operational_context") or {}
    cited={ref[4:] for section in getattr(run,"ai_sections",[]) for ref in section.get("references",[])
           if isinstance(ref,str) and ref.startswith("src:")}
    required=set(run.assumptions.get("assistant_source_requirements",[]))
    # Consulted and cited are distinct; never infer that a source was used
    # merely because it was collected.
    return [{"key":key,"source":item.get("source",key),"status":item.get("status","non indicato"),
             "period":item.get("gas_day") or item.get("period") or item.get("from"),
             "acquired":item.get("acquired"),"scope":item.get("scope"),
             "url":safe_source_url(item.get("source_url") or item.get("url")),
             "limitation":item.get("limitation"),"cited":key in cited,
             "required":key in required,"evidence":source_evidence(key,item)}
            for key,item in public.items()]
