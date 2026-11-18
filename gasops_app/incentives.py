"""ARERA 6PI (482/2024/R/gas, Annex 1), calculation from declared daily inputs."""
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
import csv
import io
from hashlib import sha256

D=Decimal
ZERO=D(0)
RULE="482/2024/R/gas • Allegato 1 • 6PI"
SOURCE="https://www.arera.it/atti-e-provvedimenti/dettaglio/24/482-24"
ANNEX="https://www.arera.it/fileadmin/allegati/docs/24/482-2024-R-gas-ALLEGATO_1.pdf"
TIB="https://www.arera.it/fileadmin/allegati/docs/16/Allegato_A_-_TIB_aggiornato.pdf"
LABELS=("Errore previsioni G−1","Distanza prezzi di bilanciamento","Bilanciamento residuale",
        "Scarto gas di sistema","Volumi gas di sistema","Errore prelievi profilati")
UNITS=("%","%","GWh","GWh","GWh","Mmc")
HEADER=("gas_day","phase","p1_pct","p2_pct","p3_gwh","p4_gwh","p5_gwh","p6_mmc",
        "eex_status","wd_high","wd_low","da_high","da_low")
# a1, a2, m1, m2, m3, i1, i2, i3; Annex 1 p.1 (percentages as fractions).
PARAMS={ "1s":("0.0450","0.09581","1312727","1312727","2250000","72200","72200","162000"),
         "1w":("0.0350","0.10","1400000","1400000","2250000","70000","70000","155000"),
         "2":("0.04","0.20","250000","125000","31250","5000","0","-18750"),
         "3":("15","31.4","0","1220","422","20000","38293","13238"),
         "4s":("0","35","0","264.6","90.9","9260.3","9260.3","3181.8"),
         "4w":("0","50","0","555.6","100","27780.8","27780.8","5000"),
         "5":("5","10","0","800","0","4000","8000","0"),
         "6s":("0","1.00","0","0","6277","10000","10000","16277"),
         "6w":("0","3.50","0","0","5670","44000","44000","63847")}
PARAMS={k:tuple(map(D,v)) for k,v in PARAMS.items()}


def number(raw):
    if raw is None or str(raw).strip()=="":
        return None
    try:
        x=D(str(raw).strip())
    except InvalidOperation:
        raise ValueError("Numero non valido: usare il punto decimale.") from None
    if not x.is_finite() or abs(x)>D("1e9") or x.as_tuple().exponent < -12:
        raise ValueError("Numero fuori formato o intervallo.")
    return x


def parameters(k,day):
    if day.year not in range(2025,2029) or k not in range(1,7):
        raise ValueError("Indicatore o periodo fuori 6PI.")
    summer=(4<=day.month<=10) if k==1 else (5<=day.month<=9)
    return PARAMS[str(k)+("s" if summer else "w") if k in (1,4,6) else str(k)]


def incentive(k,day,value):
    if value is None:return None
    if value<0:raise ValueError("Indicatore negativo.")
    # CSV uses percentage points, not a fractional percentage.
    p=value/100 if k in (1,2) else value
    a,b,m1,m2,m3,i1,i2,i3=parameters(k,day)
    return i1-m1*p if p<=a else i2-m2*p if p<=b else i3-m3*p


def volatility_factor(i2,status,quotes):
    if i2 is None:return None
    if i2>=0 or status=="non_quotato":return D(1)
    if status!="quotato" or any(q is None for q in quotes):return None
    spans=[]
    for high,low in (quotes[:2],quotes[2:]):
        if high<low or high+low<=0:return None
        spans.append(2*(high-low)/(high+low))
    v=max(spans)
    return max(ZERO,min(D(1),(D(".22")-v)/D(".08")))


@dataclass(frozen=True)
class Day:
    day:date
    phase:str
    p:tuple
    status:str
    quotes:tuple

    @property
    def incentives(self):
        return tuple(incentive(k,self.day,p) for k,p in enumerate(self.p,1))

    @property
    def h(self):
        return volatility_factor(self.incentives[1],self.status,self.quotes)


def parse_csv(raw,cutoff):
    if not raw or len(raw)>2_000_000:raise ValueError("CSV vuoto o oltre 2 MB.")
    try:
        reader=csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
        if reader.fieldnames!=list(HEADER):raise ValueError("Usa il modello CSV 6PI.")
        out={}
        for row in reader:
            if None in row or any(v is None for v in row.values()):raise ValueError("Riga CSV incompleta.")
            day=date.fromisoformat(row["gas_day"])
            if day.isoformat()!=row["gas_day"] or day.year not in range(2025,2029) or day>cutoff:
                raise ValueError("Giorno gas fuori periodo 6PI o non concluso.")
            phase=row["phase"]
            status=row["eex_status"]
            if phase not in ("provvisorio","definitivo") or status not in ("quotato","non_quotato","ignoto"):
                raise ValueError("Fase o stato EEX non valido.")
            p=tuple(number(row[k]) for k in HEADER[2:8])
            if any(x is not None and x<0 for x in p):raise ValueError("Indicatore negativo.")
            q=tuple(number(row[k]) for k in HEADER[9:])
            if status!="quotato" and any(x is not None for x in q):
                raise ValueError("Quotazioni incompatibili con stato EEX.")
            for hi,lo in (q[:2],q[2:]):
                if hi is not None and lo is not None and hi<lo:raise ValueError("High inferiore a low.")
            item=Day(day,phase,p,status,q)
            if day in out and out[day]!=item:raise ValueError("Versioni discordanti: importa una sola versione per giorno gas.")
            out[day]=item
        if not out:raise ValueError("Nessun record.")
    except UnicodeError:
        raise ValueError("CSV UTF-8 richiesto.") from None
    return tuple(out[k] for k in sorted(out)),sha256(raw).hexdigest()


def annual_amount(rows,year):
    """Only a complete calendar with declared definitive observations; not certified IA."""
    if year not in range(2025,2029):raise ValueError("Anno fuori 6PI.")
    rows=tuple(rows)
    start,end=date(year,1,1),date(year+1,1,1)
    expected=(end-start).days
    if len(rows)!=expected or len({r.day for r in rows})!=expected or any(
        not start<=r.day<end or r.phase!="definitivo" or r.h is None or
        any(i is None for i in r.incentives) for r in rows):
        return None
    totals=[sum((r.incentives[k] for r in rows),ZERO) for k in range(6)]
    i1=totals[0]; threshold=D(3000000)
    shared=i1 if i1<threshold else threshold+(i1-threshold)/2
    adjusted_i2=sum((r.incentives[1]*r.h for r in rows),ZERO)
    gas=max(ZERO,totals[3]+totals[4])
    alpha=max(ZERO,totals[5]) if year<=2026 else totals[5]
    return max(D(-5000000),shared+adjusted_i2+totals[2]+gas+alpha)


def coverage(rows):
    rows=tuple(rows)
    results=[]
    for k in range(6):
        valid=[r for r in rows if r.incentives[k] is not None]
        vals=[r.incentives[k] for r in valid]
        results.append(dict(k=k+1,count=len(vals),raw=sum(vals,ZERO) if vals else None,
                            negative=sum(x<0 for x in vals)))
    return results


def template():
    return ",".join(HEADER)+"\n"


def demo_rows():
    # Explicit synthetic example, not measured values.
    return tuple(Day(date(2026,1,1)+timedelta(days=i),"provvisorio",
                    tuple(map(D,("4.5","3","20","40","6","3.8"))),"non_quotato",(None,)*4)
                 for i in range(7))


def export_rows(rows):
    buf=io.StringIO()
    w=csv.writer(buf)
    w.writerow([*HEADER,*[f"I{k}_eur" for k in range(1,7)],"h","I2_adjusted_eur","rule"])
    for r in rows:
        values=r.incentives
        w.writerow([r.day.isoformat(),r.phase,*r.p,r.status,*r.quotes,*values,r.h,
                    values[1]*r.h if r.h is not None and values[1] is not None else None,RULE])
    return buf.getvalue()
