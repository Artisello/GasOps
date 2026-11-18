"""Read-only, declared daily RdB action economics; not regulatory neutrality."""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal as D, InvalidOperation
from calendar import monthrange
from hashlib import sha256
import csv,io,re

FIELDS=("gas_day","scope","coverage","buy_mwh","sell_mwh","buy_eur","sell_eur","reference_eur_mwh")
SCOPES={"title":"STSP title · MGAS","locational":"Locational · MPL","storage":"Gas in stoccaggio · MGS"}
SOURCE="https://www.mercatoelettrico.org/Home/Esiti/Gas/PrezzoSbilanciamento/Esiti/PrezzoSbilanciamento"
ACER="https://www.acer.europa.eu/gas/network-codes/monitoring/balancing"
MAX_BYTES=2*1024*1024
MAX_ROWS=10000
NUM=re.compile(r"[+-]?\d{1,15}(?:\.\d{1,8})?")
ZERO=D(0)


@dataclass(frozen=True)
class Day:
    day:date
    scope:str
    complete:bool
    buy:D
    sell:D
    cost:D
    revenue:D
    reference:D|None

    @property
    def gross(self):
        return self.buy+self.sell

    @property
    def net_cost(self):
        return self.cost-self.revenue

    @property
    def differential(self):
        if not self.complete or self.reference is None:return None
        # Positive = higher cost relative to identical gross volumes at reference.
        return self.net_cost-(self.buy-self.sell)*self.reference


def number(raw,optional=False):
    if optional and raw=="":return None
    if not NUM.fullmatch(raw):raise ValueError("Valore numerico non valido: usare punto decimale.")
    return D(raw)


def parse(raw,closed_day):
    if not raw or len(raw)>MAX_BYTES:raise ValueError("CSV vuoto o oltre 2 MiB.")
    out={}
    try:
        reader=csv.DictReader(io.StringIO(raw.decode("utf-8-sig")),strict=True)
        if tuple(reader.fieldnames or ())!=FIELDS:raise ValueError("Usa le intestazioni del modello CSV.")
        for i,r in enumerate(reader,1):
            if i>MAX_ROWS or None in r or any(v is None for v in r.values()):
                raise ValueError("Righe o colonne non valide.")
            day=date.fromisoformat(r["gas_day"])
            if day.isoformat()!=r["gas_day"] or day<date(2016,10,1) or day>closed_day:
                raise ValueError("Giorno gas non concluso o fuori periodo.")
            scope=r["scope"]
            if scope not in SCOPES or r["coverage"] not in ("complete","partial"):
                raise ValueError("Perimetro o copertura non validi.")
            buy,sell,cost,revenue=[number(r[k]) for k in FIELDS[3:7]]
            ref=number(r["reference_eur_mwh"],True)
            if buy<0 or sell<0 or (buy==0 and cost!=0) or (sell==0 and revenue!=0):
                raise ValueError("Volumi o controvalori incoerenti.")
            if scope!="title" and ref is not None:
                raise ValueError("Benchmark title non applicabile a locational/stoccaggio.")
            item=Day(day,scope,r["coverage"]=="complete",buy,sell,cost,revenue,ref)
            key=day,scope
            if key in out and out[key]!=item:raise ValueError("Giorno/perimetro discordante.")
            out[key]=item
    except (UnicodeError,csv.Error,InvalidOperation,OverflowError):
        raise ValueError("CSV non leggibile.") from None
    if not out:raise ValueError("Nessun giorno gas.")
    return {"rows":tuple(out[k] for k in sorted(out)),"sha256":sha256(raw).hexdigest()}


def evaluate(rows,year,month,scope,closed_day):
    if scope not in SCOPES:raise ValueError("Perimetro non valido.")
    expected=[date(year,month,i) for i in range(1,monthrange(year,month)[1]+1)
              if date(year,month,i)<=closed_day]
    by={}
    for r in rows:
        if r.scope!=scope or r.day not in expected:continue
        if r.day in by and by[r.day]!=r:raise ValueError("Giorno/perimetro discordante.")
        by[r.day]=r
    complete=[r for r in by.values() if r.complete]
    active=[r for r in complete if r.gross>0]
    comparable=[r for r in active if r.differential is not None]
    def total(attr,items=complete):
        return sum((getattr(r,attr) for r in items),ZERO) if items else None
    buy,sell,cost,revenue=[total(k) for k in ("buy","sell","cost","revenue")]
    gross=total("gross")
    buy_price=cost/buy if buy else None
    sell_price=revenue/sell if sell else None
    diff=total("differential",comparable)
    comparable_volume=total("gross",comparable)
    result={"expected_days":len(expected),"complete_days":len(complete),
            "partial_days":len(by)-len(complete),"missing_days":len(expected)-len(by),
            "action_days":len(active),"complete_period":bool(expected) and len(complete)==len(expected),
            "buy_mwh":buy,"sell_mwh":sell,"gross_mwh":gross,"net_buy_mwh":buy-sell if complete else None,
            "buy_eur":cost,"sell_eur":revenue,"net_cost_eur":total("net_cost"),
            "buy_vwap":buy_price,"sell_vwap":sell_price,
            "spread":buy_price-sell_price if buy_price is not None and sell_price is not None else None,
            "buy_share_pct":100*buy/gross if gross else None,
            "comparable_days":len(comparable),"comparable_mwh":comparable_volume,
            "differential_eur":diff,"differential_eur_mwh":diff/comparable_volume if comparable_volume else None}
    detail=[]
    for d in expected:
        r=by.get(d)
        detail.append({"gas_day":d.isoformat(),"scope":scope,
                       "coverage":"missing" if r is None else "complete" if r.complete else "partial",
                       "buy_mwh":r.buy if r else None,"sell_mwh":r.sell if r else None,
                       "buy_eur":r.cost if r else None,"sell_eur":r.revenue if r else None,
                       "net_cost_eur":r.net_cost if r and r.complete else None,
                       "reference_eur_mwh":r.reference if r else None,
                       "differential_eur":r.differential if r and r.gross>0 else None})
    return result,detail


def template():
    return ",".join(FIELDS)+"\n"


def export(detail,digest):
    output=io.StringIO()
    fields=["sha256",*detail[0]] if detail else ["sha256","gas_day","scope","coverage"]
    w=csv.DictWriter(output,fieldnames=fields,lineterminator="\n")
    w.writeheader()
    for r in detail:w.writerow({"sha256":digest,**r})
    return output.getvalue()
