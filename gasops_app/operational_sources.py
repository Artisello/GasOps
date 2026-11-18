"""Optional public operational context. No merging with the demand or settlement series."""
import csv
from datetime import date, datetime, timedelta
from hashlib import sha256
from io import StringIO
import json
import math

import pandas as pd

from .data import ROME
from .models import utc_now
from .public_data import retrieve

AGSI_URL = "https://agsi.gie.eu/api"
AGSI_SOURCE = "https://agsi.gie.eu/"
JARVIS_SOURCE = "https://jarvis.snam.it/public-data?lang=it"
GME_SOURCE = "https://gme.mercatoelettrico.org/it-it/Home/Esiti/Gas/PrezzoSbilanciamento/Esiti/PrezzoSbilanciamento"
GME_TERMS = "https://www.mercatoelettrico.org/Portals/0/Documents/it-IT/20261013CONDIZIONI_GENERALI_API.pdf"
JARVIS_COLUMNS = ("gas_day","published_at","expected_withdrawal_gwh","sas_gwh","expected_linepack_gwh")
STORAGE_COLUMNS = {"gasInStorage":"stock_twh","workingGasVolume":"capacity_twh","full":"fill_pct",
                   "injection":"injection_gwh_d","withdrawal":"withdrawal_gwh_d"}


def number(value, *, signed=False):
    if value is None or str(value).strip() in ("", "-", "N/A", "n/a"):
        return None
    if isinstance(value,bool):
        raise ValueError("Valore numerico non valido.")
    try:
        v=float(value)
    except (ValueError,TypeError):
        raise ValueError("Valore numerico non valido.") from None
    if not math.isfinite(v) or (not signed and v<0):
        raise ValueError("Valore numerico non valido.")
    return v


def parse_agsi(text, acquired, *, scope, cached=False, failed=False):
    payload=json.loads(text)
    if not isinstance(payload,dict) or int(payload.get("last_page",0))!=1:
        raise ValueError("Risposta AGSI incompleta o paginata.")
    data=payload.get("data")
    if not isinstance(data,list) or not 1<=len(data)<=92:
        raise ValueError("Numero di record AGSI non valido.")
    today=acquired.astimezone(ROME).date()
    rows={}
    for item in data:
        if str(item["code"]).upper()!=scope:
            raise ValueError("Perimetro AGSI non riconosciuto.")
        day=date.fromisoformat(item["gasDayStart"])
        if not today-timedelta(days=91)<=day<today:
            raise ValueError("Giorno-gas AGSI fuori intervallo.")
        status=item["status"]
        if status not in ("C","E","N"):
            raise ValueError("Stato AGSI non riconosciuto.")
        row={"gas_day":day, "status":status}
        for source,target in STORAGE_COLUMNS.items():
            row[target]=None if status=="N" else number(item.get(source))
        if day in rows and rows[day]!=row:
            raise ValueError("Pubblicazioni AGSI in conflitto.")
        rows[day]=row
    frame=pd.DataFrame(list(rows.values())).sort_values("gas_day").reset_index(drop=True)
    if not frame["stock_twh"].notna().any():
        raise ValueError("Giacenze AGSI non disponibili.")
    # Keep source percentages as published (including values above 100%).
    # Show a mismatch rather than overwriting the publisher's fields.
    frame["review"]=((frame["capacity_twh"]<=0) |
        ((frame["stock_twh"]/frame["capacity_twh"]*100-frame["fill_pct"]).abs()>0.5))
    return {"frame":frame,"scope":scope,"acquired":acquired,"cached":cached,"failed":failed}


def load_agsi(store,api_key,scope="IT",*,now=None):
    if scope not in ("IT","EU") or not api_key or not api_key.strip():
        raise ValueError("Chiave AGSI o perimetro non valido.")
    now=now or utc_now()
    today=now.astimezone(ROME).date()
    last=today-timedelta(days=1)
    params={"from":(last-timedelta(days=89)).isoformat(),"to":last.isoformat(),"size":100,"page":1}
    params.update({"country":"IT"} if scope=="IT" else {"type":"eu"})
    def parse(text,acquired,**kwargs):
        return parse_agsi(text,acquired,scope=scope,**kwargs)
    return retrieve(store,key="agsi-public-v1-"+scope,name="GIE AGSI+",url=AGSI_URL,
                    parse=parse,ttl=timedelta(hours=24),params=params,
                    attempts=1,headers={"x-key":api_key.strip()})


def jarvis_template():
    # Deliberately header-only; no fabricated source observations.
    return ",".join(JARVIS_COLUMNS)+"\n"


def parse_jarvis(content:bytes, *, now=None):
    """Explicitly mapped public report extract, not the native publisher format.

    Preserve every publication time; same day/version conflicts fail closed.
    The input fields are estimates from the report, not recomputed SAS.
    """
    if not content or len(content)>1_000_000:
        raise ValueError("CSV vuoto o superiore a 1 MB.")
    now=now or utc_now()
    try:
        raw=content.decode("utf-8-sig")
        reader=csv.DictReader(StringIO(raw),strict=True)
        if tuple(reader.fieldnames or ())!=JARVIS_COLUMNS:
            raise ValueError("Usa esattamente le intestazioni del modello GasOps.")
        rows={}
        for i,item in enumerate(reader):
            if i>=2000 or None in item or any(v is None for v in item.values()):
                raise ValueError("CSV non valido o superiore a 2.000 record.")
            gas_day=date.fromisoformat(item["gas_day"])
            issued=datetime.fromisoformat(item["published_at"].replace("Z","+00:00"))
            if issued.tzinfo is None or issued>now:
                raise ValueError("La pubblicazione richiede data e offset, non futuri.")
            # Estimates for G only, not G+1/G+2; require the publication
            # inside the indicated Italian gas day.
            local=issued.astimezone(ROME)
            label=local.date() if local.hour>=6 else local.date()-timedelta(days=1)
            if gas_day!=label:
                raise ValueError("Pubblicazione non appartenente al giorno-gas G.")
            row={"gas_day":gas_day,"published_at":issued,
                 "expected_withdrawal_gwh":number(item["expected_withdrawal_gwh"]),
                 "sas_gwh":number(item["sas_gwh"],signed=True),
                 "expected_linepack_gwh":number(item["expected_linepack_gwh"])}
            if all(row[k] is None for k in JARVIS_COLUMNS[2:]):
                raise ValueError("Riga priva di stime.")
            key=(gas_day,issued)
            if key in rows and rows[key]!=row:
                raise ValueError("Versioni Jarvis in conflitto.")
            rows[key]=row
    except (UnicodeError,csv.Error) as exc:
        raise ValueError("CSV non leggibile.") from exc
    if not rows:
        raise ValueError("Nessuna pubblicazione importata.")
    versions=pd.DataFrame(list(rows.values())).sort_values(["gas_day","published_at"])
    latest=versions.drop_duplicates("gas_day",keep="last").reset_index(drop=True)
    return {"versions":versions,"latest":latest,"sha256":sha256(content).hexdigest()}
