"""Recent Italian sectoral exit flows via ENTSOG's public, keyless API.

Mapping reviewed from Bruegel tracker workbook (blob 9daf527c9f601432ada9f10d6a411214f1ac2132).
No supply, storage capacity, trading prices or official national coverage are inferred.
Live endpoint contract must be verified before claiming successful deployment.
"""
from calendar import monthrange
from dataclasses import dataclass, field
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
    valid_slots: int = 0
    expected_slots: int = 0
    metadata_warning: bool = False
    revisions: dict = field(default_factory=dict)


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
                *, cached=False, failed=False, allow_partial=False) -> Month:
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
        # page count. Historical windows require a fully validated grid;
        # the most recent window may explicitly retain validated partial data.
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
        raw_revision = item.get("lastUpdateDateTime", item.get("lastUpdateDate"))
        try:
            stamp = datetime.fromisoformat(raw_revision.replace("Z", "+00:00"))
            if stamp.tzinfo is None or stamp > retrieved_at:
                stamp = None
        except (AttributeError, ValueError):
            stamp = None
        grouped.setdefault(key,set()).add((stamp,number))
        flag=notes.setdefault(day,set())
        if metadata_warning:
            flag.add("metadati_totale_discordante")
        status=str(item.get("flowStatus") or "status_non_indicato")
        flag.add(status.replace(" ","_")[:80])
        if naive or end_naive:
            flag.add("timestamp_senza_offset_allineato")
    values,revisions={},{}
    for key, candidates in grouped.items():
        ordered = all(stamp is not None for stamp,_ in candidates)
        latest = max(stamp for stamp,_ in candidates) if ordered else None
        amounts = {value for stamp,value in candidates if not ordered or stamp == latest}
        if latest is not None:
            revisions[key] = latest
        if len(amounts)==1:
            values[key]=next(iter(amounts))
        else:
            values[key]=None
            notes[key[0]].add("versioni_in_conflitto")
    expected={(first+timedelta(days=i),field)
              for i in range((last-first).days+1) for field in FIELDS}
    complete=sum(values.get(key) is not None for key in expected)
    if metadata_warning and complete!=len(expected) and not allow_partial:
        raise SourceSchemaError(f"Copertura ENTSOG incompleta: {complete}/{len(expected)} valori giorno-settore validi; "
                                f"ricevuti {len(items)}, totale dichiarato {total}")
    if complete!=len(expected):
        # For the most recent window, preserve individually validated records.
        # This is not a complete response: missing and conflicting slots
        # remain missing; never assume their values or revision status.
        for day,field in expected:
            if values.get((day,field)) is None:
                notes.setdefault(day,set()).add("copertura_parziale")
    if not any(all(values.get((day,field)) is not None for field in FIELDS)
               for day in notes):
        raise SourceSchemaError("Nessun giorno con i tre aggregati ENTSOG completi.")
    return Month(values,notes,retrieved_at,cached,failed,complete,len(expected),metadata_warning,revisions)


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
    data,notes,revisions={},{},{}
    for month in months:
        notes.update(month.flags)
        for key,value in month.values.items():
            edition = month.revisions.get(key)
            known = revisions.get(key)
            if known is not None and (edition is None or edition<known):
                continue
            if known is not None and edition==known and value!=data[key]:
                value = None
                notes.setdefault(key[0],set()).add("versioni_in_conflitto")
            data[key],revisions[key] = value,edition
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


RANGE_CACHE = "entsog-srg-window-v1:"


def load_range(store, first, last, *, now=None, refresh=False):
    if not 0 <= (last-first).days < 31 or last > _last_completed(now or utc_now()):
        raise SourceSchemaError("Seleziona da 1 a 31 giorni gas conclusi.")
    def parse(text, acquired, **kwargs):
        return parse_month(json.loads(text),first,last,acquired,allow_partial=True,**kwargs)
    return retrieve(store,key=f"{RANGE_CACHE}{first}:{last}",name="ENTSOG · prelievi SRG",
        url=URL,params=query_params(first,last),parse=parse,ttl=timedelta(hours=12),
        attempts=1,timeout=(5,20),diagnostics=True,refresh=refresh)


def cached_ranges(store, first, last, now):
    """Read only validated SRG windows overlapping the requested interval."""
    results = []
    for key,_,size in store.cached_entries(RANGE_CACHE,window=(first,last),limit=24):
        if size>1_000_000:
            continue
        try:
            left,right = map(date.fromisoformat,key[len(RANGE_CACHE):].split(":"))
            at,raw = store.cached(key)
            acquired = datetime.fromisoformat(at)
            if acquired.tzinfo is None or acquired>now:
                continue
            results.append((left,right,parse_month(json.loads(raw),left,right,acquired,cached=True,allow_partial=True)))
        except (ValueError,TypeError,KeyError):
            continue
    return results


def load(store: Store, *, refresh=False, now: datetime|None=None, months=MAX_MONTHS) -> tuple[Bundle,str|None]:
    """Fetch bounded monthly windows sequentially; cache completed older months.

    Refresh current and preceding month only. Stop after an unavailable older
    month rather than hammering the public API. No silent synthetic fallback.
    """
    now = now or utc_now()
    last=_last_completed(now)
    loaded=[]
    warnings=[]
    earliest=last.replace(day=1)
    for i,(first,end) in enumerate(month_windows(last,months)):
        def parse(text,when,**kwargs):
            return parse_month(json.loads(text),first,end,when,allow_partial=i==0,**kwargs)
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
        if month.expected_slots and month.valid_slots<month.expected_slots:
            warnings.append(f"{first:%m/%Y}: copertura parziale ENTSOG {month.valid_slots}/{month.expected_slots} valori giorno-settore; soltanto i giorni completi contribuiscono al totale.")
    monthly_count = len(loaded)
    windows = cached_ranges(store,last-timedelta(days=89),last,now) if store is not None else []
    if windows:
        earliest = min(earliest,*(first for first,_,_ in windows))
        loaded = sorted((*loaded,*(window for _,_,window in windows)),key=lambda item:item.retrieved_at)
        if not monthly_count and not refresh:
            warnings.clear()
    if not loaded:
        raise SourceUnavailable("ENTSOG non disponibile. " + " ".join(warnings))
    bundle=combine(loaded,earliest,last)
    if monthly_count<months:
        warnings.append("Storico parziale: nessuna sostituzione con dati di esempio.")
    if any(m.metadata_warning for m in loaded):
        warnings.append("ENTSOG: totale dichiarato discordante; verificati i singoli valori ricevuti. Completezza delle eventuali revisioni non certificata.")
    if bundle.origin.refresh_failed:
        warnings.append("Una o più finestre usano l’ultima cache valida.")
    if (last-date.fromisoformat(bundle.origin.latest_period)).days>2:
        warnings.append("Ultimo giorno completo non recente: verifica pubblicazione e disponibilità.")
    return bundle," ".join(warnings) or None
