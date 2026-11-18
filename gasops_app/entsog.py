"""Recent Italian sectoral exit flows via ENTSOG's public, keyless API.

Mapping reviewed from Bruegel tracker workbook (blob 9daf527c9f601432ada9f10d6a411214f1ac2132).
No supply, storage capacity, trading prices or official national coverage are inferred.
Live endpoint contract must be verified before claiming successful deployment.
"""
from calendar import monthrange
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
import json
import math

import pandas as pd

from .data import ROME, Bundle, frame_bundle, utc_starts
from .models import Kind, Origin, utc_now
from .public_data import SourceUnavailable, SourceSchemaError, retrieve
from .store import Store

URL = "https://transparency.entsog.eu/api/v1/operationaldatas"
SOURCE = "https://transparency.entsog.eu/"
POINTS = {
    "it-tso-0001dis-00005exit": "distribution_gwh",
    "it-tso-0001fnc-00006exit": "power_gwh",
    "it-tso-0001fnc-00005exit": "industry_gwh",
}
FIELDS = tuple(POINTS.values())
# Preserve operator/point key capitalization specified by the API; the
# direction remains lowercase. Normalization is for matching responses only.
QUERY_POINTS = tuple(point[:-4].upper() + point[-4:] for point in POINTS)
MAX_MONTHS = 13


@dataclass
class Month:
    values: dict
    flags: dict
    retrieved_at: datetime
    cached: bool
    failed: bool


def _start(day):
    return datetime.combine(day,time(6),ROME).astimezone(timezone.utc)


def gas_timestamp(value):
    try:
        if not isinstance(value,str):
            raise ValueError("not a timestamp")
        stamp = datetime.fromisoformat(value.replace("Z","+00:00"))
    except ValueError as exc:
        raise SourceSchemaError("Timestamp ENTSOG non riconosciuto") from exc
    if stamp.tzinfo is not None:
        local = stamp.astimezone(ROME)
        if local.time() != time(6):
            raise SourceSchemaError("Intervallo ENTSOG non allineato al giorno gas italiano.")
        return local.date(), stamp.astimezone(timezone.utc), False
    # A naive timestamp is accepted only if the 06:00 local or equivalent UTC
    # convention uniquely matches the Italian gas-day boundary. Preserve a flag.
    day = stamp.date()
    expected = _start(day)
    if stamp.time() == time(6) or stamp == expected.replace(tzinfo=None):
        return day, expected, True
    raise SourceSchemaError("Timestamp senza offset ENTSOG non riconducibile alle 06:00.")


def parse_month(payload: dict, first: date, last: date, retrieved_at: datetime,
                *, cached=False, failed=False) -> Month:
    if not isinstance(payload,dict):
        raise SourceSchemaError("Risposta ENTSOG non valida.")
    items = payload.get("operationalData",payload.get("operationaldatas"))
    if not isinstance(items,list):
        raise SourceSchemaError("Array operationalData assente")
    if not items:
        raise SourceSchemaError("Nessun record restituito")
    if len(items)>=500:
        raise SourceSchemaError("Limite risposta raggiunto (500 record)")
    meta=payload.get("meta") or {}
    if not isinstance(meta,dict):
        raise SourceSchemaError("Metadati ENTSOG non validi")
    metadata_warning=False
    try:
        count=int(meta["count"]) if meta.get("count") is not None else None
        total=int(meta["total"]) if meta.get("total") is not None else None
        offset=int(meta.get("offset",0))
    except (ValueError,TypeError,OverflowError) as exc:
        raise SourceSchemaError("Conteggi ENTSOG non validi") from exc
    if offset!=0 or (count is not None and count!=len(items)):
        raise SourceSchemaError("Conteggio o offset di pagina incoerente")
    if total is not None and total!=len(items):
        # Live probe (2026-11-18): count=21, total=24, offset=0, limit=500
        # for seven gas days and three points. The total is not sufficient
        # to establish whether this particular requested grid is incomplete.
        # Do not accept a saturated page, a smaller total or a mismatched
        # page count; only a fully validated grid may override the total.
        try:
            limit=int(meta["limit"]) if meta.get("limit") is not None else 500
        except (ValueError,TypeError,OverflowError) as exc:
            raise SourceSchemaError("Limite pagina ENTSOG non valido") from exc
        if (total<len(items) or count!=len(items) or
                (limit!=-1 and limit<=len(items))):
            raise SourceSchemaError("Risposta ENTSOG incompleta: conteggio o limite di pagina incoerente")
        metadata_warning=True
    grouped, notes = {}, {}
    for item in items:
        required={"operatorKey","pointKey","directionKey","indicator","periodType","unit","periodFrom","periodTo"}
        if not isinstance(item,dict) or not required<=item.keys():
            raise SourceSchemaError("Record ENTSOG privo di uno o più campi obbligatori")
        point = (str(item["operatorKey"])+str(item["pointKey"])+str(item["directionKey"])).lower()
        if point not in POINTS or item["indicator"]!="Physical Flow" or str(item["periodType"]).lower()!="day":
            raise SourceSchemaError("Punto, indicatore o granularità ENTSOG inattesi.")
        if str(item["unit"]).strip().lower()!="kwh/d":
            raise SourceSchemaError("Unità ENTSOG non riconosciuta; atteso kWh/d.")
        day,start,naive=gas_timestamp(item["periodFrom"])
        end_day,end,end_naive=gas_timestamp(item["periodTo"])
        if end_day!=day+timedelta(days=1) or end!=_start(end_day) or start!=_start(day):
            raise SourceSchemaError("Intervallo ENTSOG non giornaliero.")
        if not first<=day<=last:
            continue
        key=(day,POINTS[point])
        value=item.get("value")
        na=str(item.get("isNA","false")).lower() in ("true","1")
        if value is None or value=="" or na:
            number=None
        else:
            if isinstance(value,bool):
                raise SourceSchemaError("Valore ENTSOG non numerico.")
            try:
                number=float(value)
            except (ValueError,TypeError,OverflowError) as exc:
                raise SourceSchemaError("Valore di flusso ENTSOG non numerico") from exc
            if not math.isfinite(number) or number<0:
                raise SourceSchemaError("Flusso ENTSOG non valido.")
            number/=1_000_000
        # Conflicting releases remain missing, never pick an arbitrary version.
        grouped.setdefault(key,set()).add(number)
        flag=notes.setdefault(day,set())
        if metadata_warning:
            flag.add("metadati_totale_discordante")
        status=str(item.get("flowStatus") or "status_non_indicato")
        flag.add(status.replace(" ","_")[:80])
        if naive or end_naive:
            flag.add("timestamp_senza_offset_allineato")
    values={}
    for key, candidates in grouped.items():
        if len(candidates)==1:
            values[key]=next(iter(candidates))
        else:
            values[key]=None
            notes[key[0]].add("versioni_in_conflitto")
    if metadata_warning:
        # Require a real, non-conflicting observation for every requested
        # day and sector. Counts alone cannot detect a missing point/day
        # hidden by duplicate records. No partial window is treated as full.
        expected={(first+timedelta(days=i),field)
                  for i in range((last-first).days+1) for field in FIELDS}
        complete=sum(values.get(key) is not None for key in expected)
        if complete!=len(expected):
            raise SourceSchemaError(f"Copertura ENTSOG incompleta: {complete}/{len(expected)} valori giorno-settore validi; "
                                    f"ricevuti {len(items)}, totale dichiarato {total}")
    if not any(all(values.get((day,field)) is not None for field in FIELDS)
               for day in notes):
        raise SourceSchemaError("Nessun giorno con i tre aggregati ENTSOG completi.")
    return Month(values,notes,retrieved_at,cached,failed)


def _last_completed(now: datetime) -> date:
    local=now.astimezone(ROME)
    current=local.date() if local.time()>=time(6) else local.date()-timedelta(days=1)
    return current-timedelta(days=1)


def month_windows(last: date, months: int=MAX_MONTHS):
    if not 1<=months<=MAX_MONTHS:
        raise SourceSchemaError("Numero di mesi fuori limite.")
    start=last.replace(day=1)
    for _ in range(months):
        end=min(last,start.replace(day=monthrange(start.year,start.month)[1]))
        yield start,end
        start=(start-timedelta(days=1)).replace(day=1)


def combine(months: list[Month], first: date, last: date) -> Bundle:
    if not months:
        raise SourceUnavailable("ENTSOG non disponibile; scegli Eurostat o l’archivio locale.")
    data,notes={},{}
    for month in months:
        data.update(month.values)
        notes.update(month.flags)
    periods=pd.date_range(first,last,freq="D")
    rows=[]
    latest=None
    for stamp,utc in zip(periods,utc_starts(periods,"daily"),strict=True):
        day=stamp.date()
        row={field:data.get((day,field)) for field in FIELDS}
        complete=all(v is not None for v in row.values())
        flags=set(notes.get(day,set()))
        if not complete:
            flags.add("aggregati_incompleti")
        else:
            latest=day
        rows.append({**row,"demand_gwh":sum(row.values()) if complete else None,
                     "period":day.isoformat(),"timestamp_utc":utc.isoformat(),
                     "energy_unit":"GWh","source_flag":" ".join(sorted(flags))})
    if latest is None:
        raise SourceUnavailable("ENTSOG: nessun giorno completo.")
    return frame_bundle(pd.DataFrame(rows),Origin(
        name="ENTSOG · aggregati di prelievo SRG",kind=Kind.HISTORICAL,grain="daily",
        fields=("demand_gwh",*FIELDS),url=SOURCE,retrieved_at=max(m.retrieved_at for m in months),
        latest_period=latest.isoformat(),cached=all(m.cached for m in months),
        refresh_failed=any(m.failed for m in months),
        description="Somma dei tre aggregati di uscita Snam Rete Gas (distribuzione, termoelettrico, industria) "
                    "pubblicati come Physical Flow su ENTSOG. Valori giornalieri kWh/d divisi per 1.000.000 "
                    "per ottenere GWh per giorno gas; nessun fattore orario aggiunto. "
                    "Proxy dei prelievi del perimetro SRG, non totale nazionale certificato. "
                    "Le distribuzioni non coincidono necessariamente con i soli consumi domestici. "
                    "Mapping Bruegel; nessun dato mancante trasformato in zero. Status e revisioni "
                    "della fonte possono cambiare. Non include offerta, scorte o prezzi."
    ))


def query_params(first: date, last: date):
    return {"pointDirection":",".join(QUERY_POINTS),"from":first.isoformat(),
            "to":last.isoformat(),"indicator":"Physical Flow","periodType":"day",
            "timeZone":"CET","limit":500}


def load(store: Store, *, refresh=False, now: datetime|None=None) -> tuple[Bundle,str|None]:
    """Fetch bounded monthly windows sequentially; cache completed older months.

    Refresh current and preceding month only. Stop after an unavailable older
    month rather than hammering the public API. No silent synthetic fallback.
    """
    last=_last_completed(now or utc_now())
    loaded=[]
    warnings=[]
    earliest=last.replace(day=1)
    for i,(first,end) in enumerate(month_windows(last)):
        def parse(text,when,**kwargs):
            return parse_month(json.loads(text),first,end,when,**kwargs)
        try:
            month=retrieve(store,key=f"entsog-srg-three-v4-{first:%Y-%m}",name="ENTSOG",
                url=URL,parse=parse,ttl=timedelta(hours=12 if i<2 else 24*30),
                refresh=refresh and i<2,attempts=1,timeout=(5,20),diagnostics=True,
                params=query_params(first,end))
        except SourceUnavailable as exc:
            warnings.append(f"{first:%m/%Y}: {exc}")
            # Early-month publication lag is possible; try the preceding month once.
            if i==0:
                continue
            break
        loaded.append(month)
        earliest=first
    if not loaded:
        raise SourceUnavailable("ENTSOG non disponibile. " + " ".join(warnings))
    bundle=combine(loaded,earliest,last)
    if len(loaded)<MAX_MONTHS:
        warnings.append("Storico parziale: nessuna sostituzione con dati di esempio.")
    if any("metadati_totale_discordante" in str(flag) for flag in bundle.rows["source_flag"]):
        warnings.append("ENTSOG: totale dichiarato discordante; griglia giorno-settore richiesta verificata integralmente. Completezza delle eventuali revisioni non certificata.")
    if bundle.origin.refresh_failed:
        warnings.append("Una o più finestre usano l’ultima cache valida.")
    if (last-date.fromisoformat(bundle.origin.latest_period)).days>2:
        warnings.append("Ultimo giorno completo non recente: verifica pubblicazione e disponibilità.")
    return bundle," ".join(warnings) or None
