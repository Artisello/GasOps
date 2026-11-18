"""Public refresh coordinator: independent providers, last valid results retained.

Explicit user refresh only, no hidden provider calls, no synthetic fallback.
"""
from datetime import timedelta
from .data import ROME
from .models import Kind,utc_now
from .quality import inspect
from .public_data import SourceUnavailable
from .advanced_kpis import entry
from .mensile import load_monthly
from .entsog import load as load_daily
from .operational_sources import load_agsi,load_alsi,GIE_LINKS
from .terna_power import load_power,latest_day
from .terna_history import make_batch,merge,STATE as HISTORY
from .acer_market import load_lng

BUNDLES="live_public_bundles_v1"
STATUS="live_public_refresh_v1"
LABELS={"monthly":"Eurostat + ARERA","daily":"ENTSOG · SRG","agsi":"GIE · AGSI+","alsi":"GIE · ALSI","terna":"Terna · consuntivi","terna_forward":"Terna · previsioni MSD1","terna_capacity":"Terna · capacità disponibile","terna_industry":"Terna · IMCEI","acer":"ACER","weather":"Open-Meteo · temperature e HDD"}


def validated_inspection(bundle,now,kind,*,inspections=None):
    origin=bundle.origin
    if origin.archive or origin.kind not in (Kind.HISTORICAL,Kind.LIVE) or origin.grain!=kind:
        raise ValueError("Perimetro non valido")
    key=id(bundle)
    checked=inspections.get(key) if inspections is not None else None
    if checked is None:
        checked=inspect(bundle,now)
        if inspections is not None:inspections[key]=checked
    frame=checked.usable
    if frame.empty or not frame["demand_gwh"].notna().any():
        raise ValueError("Nessun consumo utilizzabile")
    return checked


def valid_bundle(bundle,now,kind):
    validated_inspection(bundle,now,kind)
    return bundle


def refresh(state,store,now,selected,*,gie=None,terna=None,clock=utc_now):
    """Only explicit selected sources, shared key names with their dedicated views."""
    previous=state.get(STATUS,{})
    last=previous.get("attempted")
    if last and now-last<timedelta(seconds=60):
        return False
    records=dict(previous.get("sources",{}))
    state[STATUS]={"attempted":now,"sources":records}
    bundles=dict(state.get(BUNDLES,{}))
    def attempt(name,fn):
        try:
            note=fn()
            records[name]={"status":"Da verificare" if note else "Acquisito","at":clock().isoformat(),"note":note or ""}
        except Exception:
            records[name]={"status":"Da aggiornare","at":clock().isoformat(),
                           "note":"Fonte temporaneamente non disponibile. Ultimo dato valido conservato, se presente."}
    def market(name,loader,grain):
        bundle,warning=loader(store,refresh=True)
        bundles[name]=valid_bundle(bundle,now,grain)
        state[BUNDLES]=dict(bundles)
        old=bundle.origin
        return "Cache o copertura da verificare." if old.refresh_failed or warning else ""
    def inventory(name,platform,loader):
        key=platform+"_IT"
        try:
            result=loader(store,gie,"IT",now=now,refresh=True)
            if result["scope"]!="IT" or result["frame"].empty:
                raise ValueError("Perimetro o copertura")
            state[key]={"attempted":now,"result":result}
            return "Cache non aggiornata." if result["failed"] else ""
        except Exception:
            saved=state.get(key,{})
            state[key]={**saved,"attempted":now,"error":"Aggiornamento non disponibile"}
            raise
    def power():
        # Respect the same throttle as the dedicated page.
        key="terna_power_attempt_v1"
        last=state.get(key)
        if last and now-last<timedelta(seconds=60):
            return "Acquisizione recente: riprova più tardi."
        state[key]=now
        end=latest_day(now)
        p=load_power(*terna,end-timedelta(days=13),end,now=now)
        batch=make_batch(p,clock())
        prior=state.get("terna_power_v1",{})
        old_power=prior.get("power",{})
        gas=prior.get("gas") if (old_power.get("first"),old_power.get("last"))==(p["first"],p["last"]) else None
        state["terna_power_v1"]={"power":p,"gas":gas}
        try:
            state[HISTORY]=merge(state.get(HISTORY,[]),[batch])
        except ValueError:
            return "Dati acquisiti; archivio di sessione al limite."
        return p["warning"] or ""
    def forward():
        from .terna_forward import acquire,merge,STATE,ATTEMPT
        last=state.get(ATTEMPT)
        if last and now-last<timedelta(seconds=60):return "Acquisizione recente"
        state[ATTEMPT]=now
        today=now.astimezone(ROME).date()
        b,notes=acquire(*terna,today,today+timedelta(days=1),now)
        state[STATE]=merge(state.get(STATE,[]),[b],clock())
        return " · ".join(notes)
    def context_signal(kind):
        from .terna_context import acquire,merge,STATE as CONTEXT
        today=now.astimezone(ROME).date()
        first=today if kind=="capacity" else (today.replace(day=1)-timedelta(days=1)).replace(day=1)
        last=today+timedelta(days=1) if kind=="capacity" else first
        try:b=acquire(*terna,kind,first,last,now)
        except (SourceUnavailable,ValueError):
            if kind!="industry":raise
            first=(first-timedelta(days=1)).replace(day=1)
            b=acquire(*terna,kind,first,first,now)
        state[CONTEXT]=merge(state.get(CONTEXT,[]),[b],clock())
        return ""
    def acer():
        key="acer_lng_attempt_v1"
        last=state.get(key)
        if last and now-last<timedelta(seconds=60):
            return "Acquisizione recente: riprova più tardi."
        state[key]=now
        r=load_lng(store,refresh=True)
        if not r.rows:raise ValueError("Serie assente")
        state["acer_lng_result_v1"]=r
        return "Cache non aggiornata." if r.failed else ""
    from .weather_source import refresh as refresh_weather
    actions={"weather":lambda:refresh_weather(state,store,now,force=True),
             "monthly":lambda:market("monthly",load_monthly,"monthly"),
             "daily":lambda:market("daily",load_daily,"daily"),
             "agsi":lambda:inventory("agsi","AGSI+",load_agsi),
             "alsi":lambda:inventory("alsi","ALSI",load_alsi),
             "terna":power,"terna_forward":forward,"terna_capacity":lambda:context_signal("capacity"),"terna_industry":lambda:context_signal("industry"),"acer":acer}
    for name in dict.fromkeys(selected):
        if name not in actions or name in ("agsi","alsi") and not gie or name in ("terna","terna_forward","terna_capacity","terna_industry") and not terna:
            continue
        attempt(name,actions[name])
    return True


def remember_bundle(state,bundle,now):
    if bundle is None:return
    try:
        grain=bundle.origin.grain
        if grain not in ("monthly","daily"):return
        valid_bundle(bundle,now,grain)
        key="monthly" if grain=="monthly" else "daily"
        state[BUNDLES]={**state.get(BUNDLES,{}),key:bundle}
    except (ValueError,TypeError,KeyError,AttributeError):
        return


def market_scores(state,now,*,inspections=None):
    out=[]
    bundles=state.get(BUNDLES,{})
    for k,b in bundles.items():
        if k not in ("monthly","daily"):continue
        try:
            f=validated_inspection(b,now,k,inspections=inspections)
            daily=k=="daily"
            specs=[("demand_gwh","srg_withdrawals" if daily else "national_demand","Prelievi SRG" if daily else "Consumo nazionale",
                    "GWh/giorno gas" if daily else "GWh/mese")]
            if daily:
                specs += [("power_gwh","srg_power","Prelievi termoelettrici SRG","GWh/giorno gas"),
                          ("industry_gwh","srg_industry","Prelievi industria SRG","GWh/giorno gas")]
            else:specs += [("price_eur_mwh","psv","PSV · riferimento ARERA","€/MWh")]
            for field,code,label,unit in specs:
                if field not in b.origin.fields:continue
                v=f.usable[field].dropna()
                if v.empty:continue
                d=v.index[-1].date()
                if d>now.astimezone(ROME).date():continue
                age=(now.astimezone(ROME).date()-d).days
                source=b.origin
                if field=="price_eur_mwh":
                    source=next((s for s in b.origin.companions if field in s.fields),source)
                deadline=3 if daily else 93
                status="Storico / da aggiornare" if age>deadline or source.refresh_failed else "Ultimo dato pubblicato"
                attempt=state.get(STATUS,{}).get("sources",{}).get(k,{})
                if attempt.get("status")=="Da aggiornare":
                    from datetime import datetime
                    at=datetime.fromisoformat(attempt["at"])
                    if at>=source.retrieved_at:
                        status="Ultimo dato valido · aggiornamento sospeso"
                out.append(entry("Mercato",code,label,v.iloc[-1],unit,d.isoformat() if daily else d.strftime("%Y-%m"),
                    "SRG · perimetro parziale" if daily else "Italia",source.name,source.url or "",status,
                    "Acquisito "+source.retrieved_at.isoformat(timespec="minutes"),
                    "Osservazione disponibile più recente della metrica, non previsione. Frequenze e perimetri distinti."))
        except (ValueError,TypeError,KeyError,AttributeError):
            continue
    return out
