"""Public refresh coordinator: independent providers, last valid results retained.

Explicit user refresh only, no hidden provider calls, no synthetic fallback.
"""
from datetime import timedelta
from time import monotonic
from .data import ROME
from .models import Kind,utc_now
from .quality import inspect
from .public_data import SourceUnavailable
from .advanced_kpis import entry
from .mensile import load_monthly
from .entsog import load as load_daily
from .operational_sources import load_agsi,load_alsi,load_iip,GIE_LINKS
from .terna_power import load_power,latest_day,token_batch,TernaHTTPError
from .terna_history import make_batch,merge,STATE as HISTORY
from .acer_market import load_lng

BUNDLES="live_public_bundles_v1"
STATUS="live_public_refresh_v1"
LABELS={"monthly":"Eurostat + ARERA","daily":"ENTSOG · SRG","agsi":"GIE · AGSI+","alsi":"GIE · ALSI","terna":"Terna · consuntivi","terna_forward":"Terna · previsioni MSD1","terna_capacity":"Terna · capacità disponibile","terna_industry":"Terna · IMCEI","acer":"ACER","weather":"Open-Meteo · temperature e HDD"}
LABELS.update(network="ENTSOG · punti della rete italiana",iip="GIE · avvisi IIP")


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


def refresh(state,store,now,selected,*,gie=None,terna=None,clock=utc_now,progress=None,network_days=7,gie_scopes=("IT",)):
    """Only explicit selected sources, shared key names with their dedicated views."""
    if network_days not in (7,30) or not gie_scopes or any(s not in ("IT","EU","DE") for s in gie_scopes):
        raise ValueError("Periodo o perimetro non supportato")
    selected=tuple(dict.fromkeys(selected))
    if not selected:return False
    previous=state.get(STATUS,{})
    last=previous.get("attempted")
    if last and now-last<timedelta(seconds=60):
        return False
    records=dict(previous.get("sources",{}))
    state[STATUS]={"attempted":now,"sources":records}
    bundles=dict(state.get(BUNDLES,{}))
    from .public_data import acquisition_error_code, SourceNoObservation
    evidence={}
    def validated(records,*,cached=False,failed=False):
        evidence.update(validated=True,records=int(records),reachable=True if not cached and not failed else None,
                        outcome="failed" if failed else "cached" if cached else "acquired")
    def attempt(name,fn):
        start=monotonic()
        evidence.clear()
        try:
            note=fn()
            records[name]={"status":"Da verificare" if note else "Acquisito","at":clock().isoformat(),"note":note or ""}
        except SourceNoObservation as error:
            evidence.update(outcome="no_observation",reason_code="no_observation")
            records[name]={"status":"Da verificare","at":clock().isoformat(),"note":"Nessuna osservazione utilizzabile restituita."}
        except SourceUnavailable as error:
            evidence.update(outcome="no_observation" if isinstance(error,SourceNoObservation) else "failed",
                            reason_code=evidence.get("reason_code") or acquisition_error_code(error))
            records[name]={"status":"Da aggiornare","at":clock().isoformat(),
                           "note":str(error) if name.startswith("terna") else
                           "Fonte temporaneamente non disponibile. Ultimo dato valido conservato, se presente."}
        except Exception as error:
            evidence.update(outcome="failed",reason_code=acquisition_error_code(error))
            records[name]={"status":"Da aggiornare","at":clock().isoformat(),
                           "note":"Fonte temporaneamente non disponibile. Ultimo dato valido conservato, se presente."}
        records[name]["duration_seconds"]=round(monotonic()-start,2)
        records[name].update(evidence)
        records[name].setdefault("outcome","review" if records[name]["status"]=="Da verificare" else "completed_unverified")
        if records[name]["outcome"]=="acquired" and records[name]["status"]=="Da verificare":
            records[name]["outcome"]="partial"
    def market(name,loader,grain):
        bundle,warning=loader(store,refresh=True)
        bundles[name]=valid_bundle(bundle,now,grain)
        state[BUNDLES]=dict(bundles)
        old=bundle.origin
        validated(len(bundle.rows),cached=old.retrieved_at<now,failed=old.refresh_failed)
        return "Cache o copertura da verificare." if old.refresh_failed or warning else ""
    def inventory_scope(platform,loader,scope):
        key=platform+"_"+scope
        try:
            result=loader(store,gie,scope,now=now,refresh=True)
            if result["scope"]!=scope or result["frame"].empty:
                raise ValueError("Perimetro o copertura")
            state[key]={"attempted":now,"result":result}
            validated(evidence.get("records",0)+len(result["frame"]),cached=bool(result.get("cached")),failed=result["failed"])
            if result["failed"]:evidence["reason_code"]=acquisition_error_code(result.get("refresh_error",""))
            if result.get("no_observation"):evidence.update(outcome="no_observation",reason_code="no_observation")
            return "Cache non aggiornata." if result["failed"] else "Nessuna osservazione utilizzabile restituita." if result.get("no_observation") else ""
        except SourceNoObservation:
            saved=state.get(key,{})
            state[key]={**saved,"attempted":now,"outcome":"no_observation"}
            raise
        except Exception:
            saved=state.get(key,{})
            state[key]={**saved,"attempted":now,"error":"Aggiornamento non disponibile"}
            raise
    def inventory(platform,loader):
        notes=[]
        acquired=0
        for scope in dict.fromkeys(gie_scopes):
            if platform=="ALSI" and scope=="DE":continue
            try:
                note=inventory_scope(platform,loader,scope)
                acquired+=1
                if note:notes.append(scope+": "+note)
            except Exception as error:
                evidence["reason_code"]=acquisition_error_code(error)
                notes.append(scope+": aggiornamento non disponibile; eventuale copia precedente conservata.")
        if not acquired:
            if evidence.get("reason_code")=="no_observation":
                raise SourceNoObservation("Nessuna osservazione utilizzabile restituita.")
            raise SourceUnavailable("Nessun perimetro disponibile")
        return " · ".join(notes)
    def network():
        from .italian_network import load_network_assets
        from .italian_network_refresh import refresh_network_batch,STATE
        from .gas_calendar import closed_gas_day
        last=closed_gas_day(now)
        refresh_network_batch(state,store,load_network_assets(),last-timedelta(days=network_days-1),last,now,api_key=gie)
        saved=state.get(STATE,{})
        if saved.get("attempted")!=now:return "Acquisizione della rete già richiesta nell’ultimo minuto."
        summary=saved.get("summary",{})
        if not summary.get("snapshots") and not summary.get("facilities"):raise ValueError("Nessun dato acquisito")
        catalog=saved.get("catalog",{})
        validated(sum(len(s.records) for s in saved.get("snapshots",{}).values() if s.first==last-timedelta(days=network_days-1) and s.last==last)
            +sum(len(r["frame"]) for r in saved.get("facilities",{}).values()),
            cached=bool(catalog.get("cached",True)),failed=bool(catalog.get("failed")))
        return "Copertura parziale: controlla punti rinviati, associazioni e qualità nella mappa." if summary.get("partial") else ""
    def iip():
        previous=state.get("gie_iip",{})
        state["gie_iip"]={**previous,"attempted":now}
        try:result=load_iip(store,gie,now=now,refresh=True)
        except Exception:
            state["gie_iip"]={**previous,"attempted":now,"error":"Aggiornamento non disponibile"}
            raise
        state["gie_iip"]={"attempted":now,"result":result}
        validated(len(result["messages"]),cached=bool(result.get("cached")),failed=bool(result.get("failed")))
        return "Ultima copia valida; aggiornamento incompleto." if result.get("failed") else "Copertura parziale degli avvisi." if result.get("partial") else ""
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
        validated(len(p["rows"]))
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
        validated(len(b["rows"]))
        return " · ".join(notes)
    def context_signal(kind):
        from .terna_context import acquire,merge,STATE as CONTEXT
        today=now.astimezone(ROME).date()
        first=today if kind=="capacity" else (today.replace(day=1)-timedelta(days=1)).replace(day=1)
        last=today+timedelta(days=1) if kind=="capacity" else first
        try:b=acquire(*terna,kind,first,last,now)
        except TernaHTTPError:
            raise
        except (SourceUnavailable,ValueError):
            if kind!="industry":raise
            first=(first-timedelta(days=1)).replace(day=1)
            b=acquire(*terna,kind,first,first,now)
        state[CONTEXT]=merge(state.get(CONTEXT,[]),[b],clock())
        validated(len(b["rows"]))
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
        validated(len(r.rows),cached=r.cached,failed=r.failed)
        return "Cache non aggiornata." if r.failed else ""
    from .weather_source import refresh as refresh_weather
    actions={"weather":lambda:refresh_weather(state,store,now,force=True),
             "monthly":lambda:market("monthly",load_monthly,"monthly"),
             "daily":lambda:market("daily",load_daily,"daily"),
             "agsi":lambda:inventory("AGSI+",load_agsi),
             "alsi":lambda:inventory("ALSI",load_alsi),"network":network,"iip":iip,
             "terna":power,"terna_forward":forward,"terna_capacity":lambda:context_signal("capacity"),"terna_industry":lambda:context_signal("industry"),"acer":acer}
    with token_batch():
        for index,name in enumerate(selected):
            if name not in actions or name in ("agsi","alsi","iip") and not gie or name in ("terna","terna_forward","terna_capacity","terna_industry") and not terna:
                continue
            if progress:progress(index,len(selected),LABELS[name])
            attempt(name,actions[name])
    if progress:progress(len(selected),len(selected),"Acquisizione conclusa")
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
