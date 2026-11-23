"""GME market results: authorized private use only; no public fetch or AI context."""
import base64
import binascii
import io
import json
import os
import zipfile
from datetime import date,datetime,timedelta
from decimal import Decimal as D
from hashlib import sha256

SOURCE="Gestore dei Mercati Energetici S.p.A."
TERMS="https://www.mercatoelettrico.org/Home/InterfacciaAPI"
MANUAL="https://gme.mercatoelettrico.org/Portals/0/Documents/it-IT/20251015Manuale_tecnico_API.pdf"
ENDPOINT="https://api.mercatoelettrico.org/request/api/v1"
DATASETS={
    "prices":("GAS","GAS_ImbalancePrice",("FlowDate",),("MaxPurchaseSRGPrice","MinSaleSRGPrice","WeightedAveragePrice","MGASVolumes")),
    "mgs":("MGS","GAS_MGSAuctionResults",("FlowDate","StorageCompany","Type"),("Price","Volumes","SRGPurchases","SRGSales","Participants")),
    "mpl":("MPL","GAS_MPLAuctionResults",("SessionDate","GasDay","Reason","Type","OfferPoint"),("Price","Volumes","SRGVolumes","Participants")),
}
MAX_BYTES=4*1024*1024
MAX_ROWS=10000


def private_enabled():
    # Operator-side opt-in only for a non-public, authorized installation.
    from .access import private_access
    return os.getenv("IGOR_GME_PRIVATE_AUTHORIZED")=="1" and private_access()


def _object(pairs):
    out={}
    for k,v in pairs:
        k=k.casefold()
        if k in out:raise ValueError("Campi JSON duplicati.")
        out[k]=v
    return out


def _json(raw):
    if not raw or len(raw)>MAX_BYTES:raise ValueError("JSON vuoto o oltre 4 MiB.")
    def invalid(_):raise ValueError("Numero non finito.")
    try:return json.loads(raw,parse_float=D,parse_int=D,parse_constant=invalid,object_pairs_hook=_object)
    except (UnicodeError,ValueError,RecursionError):raise ValueError("JSON non valido.") from None


def decode_response(raw):
    """Documented JSON envelope and a single bounded JSON ZIP member."""
    envelope=_json(raw)
    if not isinstance(envelope,dict) or envelope.get("resultrequest") not in (None,"") or envelope.get("formattype")!=".json.zip":
        raise ValueError("Risposta GME non riuscita o formato non supportato.")
    try:
        content=base64.b64decode(envelope["contentresponse"],validate=True)
        with zipfile.ZipFile(io.BytesIO(content)) as z:
            members=z.infolist()
            if len(members)!=1 or members[0].is_dir() or not members[0].filename.lower().endswith(".json") or members[0].file_size>MAX_BYTES:
                raise ValueError("Archivio GME non valido o troppo grande.")
            with z.open(members[0]) as f:
                payload=f.read(MAX_BYTES+1)
        if len(payload)>MAX_BYTES:raise ValueError("Limite decompressione superato.")
        return payload
    except (KeyError,TypeError,binascii.Error,zipfile.BadZipFile,RuntimeError,OSError):
        raise ValueError("Archivio GME non leggibile.") from None


def _date(value):
    s=str(value)
    if len(s)!=8 or not s.isascii() or not s.isdigit():raise ValueError("Data GME non valida.")
    return datetime.strptime(s,"%Y%m%d").date()


def _number(value):
    if value is None:return None
    if isinstance(value,bool) or not isinstance(value,(D,str)):raise ValueError("Valore numerico non valido.")
    try:n=D(value)
    except ArithmeticError:raise ValueError("Numero non valido.") from None
    if not n.is_finite() or abs(n)>D("1e15") or n.as_tuple().exponent < -12:raise ValueError("Valore fuori limite.")
    return n


def parse(raw,kind,cutoff):
    """Native field names from GME technical guide §§5.17, 5.19, 5.20.
    Exact supported list shape only; no guesses for undocumented wrappers.
    Null remains null; identical or conflicting duplicate keys rejected.
    """
    _,_,keys,fields=DATASETS[kind]
    data=_json(raw)
    if isinstance(data,dict) and "contentresponse" in data:
        data=_json(decode_response(raw))
    if not isinstance(data,list) or not 0<len(data)<=MAX_ROWS:raise ValueError("Atteso elenco JSON di record GME.")
    result={}
    for item in data:
        if not isinstance(item,dict) or not all(k.casefold() in item for k in keys+fields):
            raise ValueError("Campi GME mancanti: schema non riconosciuto.")
        row={}
        for key in keys:
            v=item[key.casefold()]
            if key in ("FlowDate","SessionDate","GasDay"):
                v=_date(v)
                if v>cutoff or v<date(2016,10,1):raise ValueError("Data fuori dai giorni conclusi.")
                v=v.isoformat()
            elif not isinstance(v,str) or not v.strip() or len(v)>120 or any(ord(c)<32 for c in v):
                raise ValueError("Dimensione di mercato non valida.")
            row[key]=v
        for key in fields:
            v=_number(item[key.casefold()])
            if key in ("Volumes","MGASVolumes","SRGPurchases","SRGSales","SRGVolumes","Participants") and v is not None and v<0:
                raise ValueError("Quantità negativa: convenzione non riconosciuta.")
            if key=="Participants" and v is not None and v!=v.to_integral_value():raise ValueError("Numero operatori non intero.")
            row[key]=v
        k=tuple(row[x] for x in keys)
        if k in result:raise ValueError("Chiave GME duplicata: non aggregare automaticamente revisioni o sessioni.")
        result[k]=row
    return {"kind":kind,"rows":tuple(result[k] for k in sorted(result)),"sha":sha256(raw).hexdigest(),"synthetic":False}


def study_prices(row,title_volume,rate,history=None):
    from .commercial_controls import imbalance_prices
    return imbalance_prices(date.fromisoformat(row["FlowDate"]),title_volume,row["WeightedAveragePrice"],
                            row["MaxPurchaseSRGPrice"],row["MinSaleSRGPrice"],rate,history)


def demo(kind,cutoff):
    d=lambda i:int((cutoff-timedelta(days=i)).strftime("%Y%m%d"))
    if kind=="prices":
        rows=[dict(FlowDate=d(i),MaxPurchaseSRGPrice=47+i,MinSaleSRGPrice=40+i,
                   WeightedAveragePrice=43+i,MGASVolumes=12000+i*1000) for i in range(7)]
    elif kind=="mgs":
        rows=[dict(FlowDate=d(i),StorageCompany="DEMO-HS",Type=t,Price=42+i,
                   Volumes=1000+i*100,SRGPurchases=600,SRGSales=0,Participants=4)
              for i in range(7) for t in ("Bilanciamento","Neutralità")]
    else:
        rows=[dict(SessionDate=d(i),GasDay=d(i),Reason="Bilanciamento",Type="Acquisto",
                   OfferPoint="DEMO-PUNTO",Price=45+i,Volumes=800,SRGVolumes=600,Participants=3)
              for i in range(7)]
    saved=parse(json.dumps(rows).encode(),kind,cutoff)
    saved["synthetic"]=True
    return saved


def fetch_private(kind,first,last,login,password,*,post=None):
    """Explicit local CLI operation. Never used by the shared Streamlit app."""
    if not private_enabled():raise ValueError("Accesso privato autorizzato non configurato.")
    if not login or not password or first>last or (last-first).days>=31:raise ValueError("Credenziali o periodo (max 31 giorni) non validi.")
    from .bso_kpis import closed_gas_day
    from .models import utc_now
    if last>closed_gas_day(utc_now()):raise ValueError("Solo giorni gas conclusi.")
    if post is None:
        import requests
        post=requests.post
    def request(path,body,headers=None):
        # Never log response bodies, token, or credential-bearing exceptions.
        try:
            with post(ENDPOINT+path,json=body,headers=headers or {},timeout=(5,30),
                      stream=True,allow_redirects=False) as r:
                if r.status_code!=200:raise ValueError("GME: HTTP "+str(r.status_code))
                parts=[];size=0
                for chunk in r.iter_content(65536):
                    size+=len(chunk)
                    if size>MAX_BYTES:raise ValueError("Risposta oltre 4 MiB.")
                    parts.append(chunk)
                return b"".join(parts)
        except ValueError:raise
        except Exception:raise ValueError("Connessione GME non riuscita.") from None
    auth=_json(request("/Auth",{"login":login,"password":password}))
    token=auth.get("token") if isinstance(auth,dict) and auth.get("success") is True else None
    if not isinstance(token,str) or not token or len(token)>8192 or any(c.isspace() for c in token):
        raise ValueError("Autenticazione GME non riuscita.")
    segment,name,_,_=DATASETS[kind]
    raw=request("/RequestData",{"platform":"PublicMarketResults","segment":segment,"dataName":name,
                "intervalStart":first.strftime("%Y%m%d"),"intervalEnd":last.strftime("%Y%m%d"),"attributes":{}},
                {"Authorization":"Bearer "+token})
    payload=decode_response(raw)
    saved=parse(payload,kind,last)
    date_key="FlowDate" if kind!="mpl" else "SessionDate"
    if any(date.fromisoformat(r[date_key])<first for r in saved["rows"]):raise ValueError("Dati fuori intervallo richiesto.")
    return payload


def main():
    import argparse
    import getpass
    from pathlib import Path
    p=argparse.ArgumentParser(description="GME: solo installazione locale autorizzata, senza redistribuzione.")
    p.add_argument("kind",choices=DATASETS)
    p.add_argument("first",type=date.fromisoformat)
    p.add_argument("last",type=date.fromisoformat)
    p.add_argument("output",type=Path)
    p.add_argument("--authorized-private-use",action="store_true")
    args=p.parse_args()
    if not args.authorized_private_use or not private_enabled():p.error("Conferma i diritti d’uso e configura IGOR_GME_PRIVATE_AUTHORIZED=1.")
    if args.output.exists():p.error("Il file di destinazione esiste già.")
    try:
        payload=fetch_private(args.kind,args.first,args.last,input("Login GME: "),getpass.getpass("Password GME: "))
        with args.output.open("xb") as f:f.write(payload)
    except (ValueError,OSError) as exc:p.exit(1,str(exc)+"\n")
    print("Estratto validato salvato localmente. Fonte: "+SOURCE)


if __name__=="__main__":
    main()
