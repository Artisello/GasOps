"""Question-specific public evidence policy for the operational assistant.

No new providers or private records. Requirements are checked against the
actual evidence snapshot, not against model-generated source names.
"""
import re
from math import isfinite
from .italiano import numero

MONTHLY="Eurostat / ARERA"
DAILY="ENTSOG · SRG"
PRICE="ARERA · CMEM,m"
GIE=("AGSI+","ALSI","IIP")
WEATHER="Open-Meteo"
POWER=("Terna · elettricità","Terna · outlook")
ACER="ACER · GNL"
MARKET=(MONTHLY,DAILY)
LABELS={MONTHLY:"Eurostat",DAILY:"ENTSOG",PRICE:"ARERA",WEATHER:"Open-Meteo",
        "AGSI+":"GIE AGSI+","ALSI":"GIE ALSI","IIP":"GIE IIP",
        POWER[0]:"Terna · consuntivi",POWER[1]:"Terna · previsioni",ACER:"ACER · GNL"}
TOPICS=(
    (MARKET,r"\b(?:domanda|consum[oi]|preliev[oi]|demand|consumption)\b"),
    ((MONTHLY,),r"eurostat|importaz|esportaz|produzione nazionale"),
    ((DAILY,),r"entsog|\bsrg\b|giornalier|settimanal"),
    ((PRICE,),r"arera|\bpsv\b|cmem|prezz|price"),
    ((ACER,),r"\bacer\b|\bttf\b|prezz.*(?:gnl|lng)|(?:gnl|lng).*prezz"),
    (("AGSI+",),r"agsi|stoccagg|storage|giacenz|scorte"),
    (("ALSI",),r"alsi|rigass|send.out|\bgnl\b|\blng\b"),
    (("IIP",),r"\biip\b|\bumm\b|indisponibil|outage"),
    (GIE,r"\bgie\b|sicurezza.*(?:fornitur|approvvigionament)"),
    ((WEATHER,),r"meteo|\bhdd\b|temperatur|climat|fredd|weather"),
    ((POWER[0],),r"terna|elettric|termoelettric|rinnovabil|fotovoltaic|eolic|power"),
    ((POWER[1],),r"msd1|outlook|prevision.*(?:terna|elettric|eolic)|(?:terna|elettric).*prevision"),
)


def requested_sources(question):
    question=question.casefold()
    names=[]
    for keys,pattern in TOPICS:
        if re.search(pattern,question,re.I):
            names.extend(keys)
    if re.search(r"\bmercat[oi]\b|\bmarket\b|panoramica|situazione.*gas|gas.*situazione",question):
        names.extend((MONTHLY,DAILY,PRICE,ACER,*GIE,WEATHER,*POWER))
    # Explicit questions about forecasts should consider both observed demand
    # and drivers, not invent a causal link to the current weather outlook.
    if re.search(r"prevision.*(?:gas|domanda|consum)|(?:gas|domanda|consum).*prevision",question):
        names.extend((MONTHLY,DAILY,WEATHER,*POWER))
    return tuple(dict.fromkeys(names))


def add_price_source(public):
    """Expose nested ARERA as a distinct, date-specific citation target."""
    if MONTHLY not in public:return public
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
                         "reason":"Fonte non disponibile per questa analisi o disattivata."}
    return public


def citation_requirements(public,requested):
    return tuple("src:"+key for key in requested if key in public)


def missing_citations(refs,required):
    return [ref for ref in required if ref not in refs]


def source_evidence(key,item):
    """Human-readable observations from validated snapshots, never model output."""
    status=item.get("status")
    if status!="available":
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
        parts=fields((("demand_gwh","Consumi nazionali" if key==MONTHLY else "Prelievi dei tre aggregati SRG","GWh"),))
        delta=fmt(item.get("changes_pct",{}).get("demand_gwh"))
        if delta is not None:
            parts.append("Variazione "+delta+"% · "+str(item.get("comparison","periodo precedente")))
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
    elif key==ACER:
        for field,label in (("eu","Prezzo GNL UE"),("benchmark","Differenziale GNL–TTF")):
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
        for field,label in (("Thermal","Termoelettrico"),("Wind","Eolico"),("Photovoltaic","Fotovoltaico"),("load","Fabbisogno")):
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
             "period":item.get("gas_day") or item.get("period") or item.get("from") or item.get("acquired"),
             "cited":key in cited,"required":key in required,"evidence":source_evidence(key,item)}
            for key,item in public.items()]
