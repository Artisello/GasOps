"""Question-specific public evidence policy for the operational assistant.

No new providers or private records. Requirements are checked against the
actual evidence snapshot, not against model-generated source names.
"""
import re

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
        names.extend((MONTHLY,DAILY,PRICE))
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
