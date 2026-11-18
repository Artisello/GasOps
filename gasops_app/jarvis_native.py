"""Native public Jarvis spreadsheets; bounded, read-only, no formula evaluation."""
from datetime import datetime,date,timedelta
from decimal import Decimal,InvalidOperation
from hashlib import sha256
from io import BytesIO,StringIO
import csv,re,zipfile,posixpath
from xml.etree import ElementTree as ET

N='{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
REL='{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id'
MAX_BYTES=16*1024*1024
MAX_EXPANDED=160*1024*1024
MAX_ROWS=500000
MISSING={'','N.D.','N.A.','N.D','N.A','-','#N/A','#VALUE!','#DIV/0!'}
COLUMNS=("family","gas_day","edition","metric","unit","value","sheet","row","slot","sha256","file")
BALANCE_COLS=("B","N","O","T","U","V","W","X","Y","AH","AI","AJ")
BALANCE_SHEETS=("kWh","Sm3 PCS 10,57275 kWhSm3")
PCS=Decimal("10.57275")
TOLERANCE=Decimal("0.00002")
MONTHS=("Gennaio","Febbraio","Marzo","Aprile","Maggio","Giugno","Luglio","Agosto","Settembre","Ottobre","Novembre","Dicembre")


def safezip(raw):
    if len(raw)>MAX_BYTES: raise ValueError("File superiore a 16 MiB")
    z=zipfile.ZipFile(BytesIO(raw))
    members=z.infolist()
    if len(members)>500 or sum(x.file_size for x in members)>MAX_EXPANDED or len({x.filename for x in members})!=len(members):
        z.close()
        raise ValueError("Archivio eccede i limiti")
    return z


def xml(z,path):
    raw=z.read(path)
    # Reject DTD/entity declarations and non-UTF8 XML; no external resolution.
    text=raw.decode("utf-8-sig")
    if "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper() or "\x00" in text:
        raise ValueError("XML non supportato")
    return ET.fromstring(raw)


def workbook(raw):
    with safezip(raw) as z:
        if "xl/workbook.xml" not in z.namelist(): raise ValueError("Non XLSX")
        sheets=xml(z,"xl/workbook.xml")
        rel={x.get("Id"):x.get("Target") for x in xml(z,"xl/_rels/workbook.xml.rels") if x.get("TargetMode")!="External"}
        strings=["".join(t.text or "" for t in x.iter(N+"t")) for x in xml(z,"xl/sharedStrings.xml")] if "xl/sharedStrings.xml" in z.namelist() else []
        if any("confidential" in x.casefold() for x in strings):
            raise ValueError("Indicatore Confidential nel workbook")
        for sh in sheets.iter(N+"sheet"):
            name=sh.get("name")
            if name not in ("Storico_G",*BALANCE_SHEETS,"Stogit Adriatica") and not re.fullmatch(r"(?:\d{2}|(?:MY|G) - (?:WD|DA)|(?:Consuntivo|Previsionale|Previsione|Intraday).*|AT_\d{4}-\d{4}_IT)",name): continue
            path=rel[sh.get(REL)]
            path=path.lstrip("/") if path.startswith("/") else posixpath.normpath(posixpath.join("xl",path))
            if not re.fullmatch(r"xl/worksheets/sheet\d+\.xml",path):raise ValueError("Percorso foglio non supportato")
            root=xml(z,path)
            rows={}
            for r in root.iter(N+"row"):
                cells={}
                for c in r.iter(N+"c"):
                    v=c.find(N+"v")
                    val=v.text if v is not None else "".join(t.text or "" for t in c.iter(N+"t"))
                    if c.get("t")=="s" and val is not None: val=strings[int(val)]
                    if val and "confidential" in val.casefold():raise ValueError("Indicatore Confidential nel foglio")
                    if val is not None and val!="":cells[re.sub(r"\d","",c.get("r",""))]=val
                if cells:rows[int(r.get("r"))]=cells
            yield name,rows


def number(value):
    if value is None or str(value).strip().upper() in MISSING:return None
    try:n=Decimal(str(value).strip().replace(",","."))
    except InvalidOperation:return None
    if not n.is_finite() or abs(n)>Decimal("1e18"):return None
    return str(n)


def dmy(v):
    return datetime.strptime(v,"%d/%m/%Y").date().isoformat()


def balance_pair(sheets,name):
    """Require phase, date, labels and every selected numeric pair to reconcile."""
    a,b=(sheets[k] for k in BALANCE_SHEETS)
    m=re.fullmatch(r"bilancio_(\d{4})(\d{2})-IT\.xlsx",name,re.I)
    if not m:raise ValueError("Nome bilancio non riconosciuto")
    year,month=map(int,m.groups())
    for sh in (a,b):
        h=sh.get(14,{})
        if h.get("A")!="GG" or h.get("T")!="Totale Immesso" or h.get("AJ")!="Totale Prelevato":
            raise ValueError("Schema bilancio inatteso")
        if any(c not in h for c in BALANCE_COLS):raise ValueError("Colonne bilancio assenti")
    if any(a[14][c]!=b[14][c] for c in BALANCE_COLS):raise ValueError("Colonne incoerenti")
    title=a.get(8,{}).get("A","")
    if title!=b.get(8,{}).get("A") or f"{MONTHS[month-1]} {year}" not in title:raise ValueError("Periodo bilancio incoerente")
    stage="definitivo" if "definitivo" in title.lower() else "provvisorio" if "provvisorio" in title.lower() else None
    if not stage:raise ValueError("Fase bilancio assente")
    def days(sh):
        out={}
        for row,r in sh.items():
            if row<=14 or not re.fullmatch(r"\d{1,2}",r.get("A","")):continue
            d=date(year,month,int(r["A"])).isoformat()
            if d in out:raise ValueError("Giorno bilancio duplicato")
            out[d]=(row,r)
        return out
    aa,bb=days(a),days(b)
    if not aa or aa.keys()!=bb.keys():raise ValueError("Giorni non riconciliabili")
    checks=0
    for day,(_,r) in aa.items():
        for c in BALANCE_COLS:
            v,w=number(r.get(c)),number(bb[day][1].get(c))
            if (v is None)!=(w is None) or v is not None and abs(Decimal(v)-Decimal(w)*PCS)>TOLERANCE:
                raise ValueError("Unità non riconciliabili con PCS 10,57275")
            checks+=v is not None
    if not checks:raise ValueError("Nessuna coppia numerica")
    inconsistent=("milioni di kwh" not in a.get(9,{}).get("A","").lower() or
                  "milioni di sm3" not in b.get(9,{}).get("A","").lower())
    return stage,aa,bb,checks,inconsistent


def parse_xlsx(raw,name):
    digest=sha256(raw).hexdigest()
    out=[]; warnings=[]
    def emit(family,period,edition,metric,unit,value,sheet,row,slot=""):
        v=number(value)
        if v is not None:
            out.append((family,period,edition,metric,unit,v,sheet,row,slot,digest,name))
        if len(out)>MAX_ROWS:raise ValueError("Troppe osservazioni")
    balances={}
    for sheet,rows in workbook(raw):
        if sheet in BALANCE_SHEETS:
            balances[sheet]=rows
        elif sheet=="Storico_G":
            h=rows.get(1,{})
            if not(h.get("A")=="pubblicazione" and h.get("B")=="aggiornato il" and "SAS" in h.get("P","")):
                raise ValueError("Schema Storico_G inatteso")
            warnings.append("Storico_G: unità energetica non esplicita nel foglio; riportata come da verificare. Stime, non misure.")
            for i,r in rows.items():
                if i<=1 or not re.fullmatch(r"\d{4}_\d{2}_\d{2}_\d{2}(?:_\d+)?",r.get("A","")):continue
                day=datetime.strptime(r["A"][:10],"%Y_%m_%d").date().isoformat()
                for c in ("C","E","G","P","R","T","AA"):
                    if c in h:emit("operativi_annuali",day,sheet,h[c].strip(),"gradi giorno" if c=="AA" else "unità da verificare",r.get(c),sheet,i,r["A"]+" | "+r.get("B",""))
        elif re.fullmatch(r"\d{2}",sheet):
            stamp=rows.get(2,{}).get("A","")
            header=rows.get(47,{})
            units=rows.get(49,{})
            if not stamp.startswith("AGGIORNAMENTO ore:"):continue
            for dcol,vcol,edition in (("B","D","G-1 · consuntivo"),("E","G","G · stima"),("H","J","G+1 · previsione"),("K","M","G+2 · previsione")):
                label=header.get(dcol,"")
                if not label.startswith("GIORNO GAS (") or units.get(vcol)!="MWh":continue
                day=dmy(label.split(": ",1)[1])
                for i,r in rows.items():
                    if not 50<=i<=88:continue
                    metric=r.get("A","")
                    if metric in ("IMMESSO","RICONSEGNATO (1)","RICONSEGNATO","ESPORTAZIONI") or metric.startswith(("SBILANCIAMENTO ATTESO DEL SISTEMA","Line Pack di rete effettivo/dichiarato","BILANCIAMENTO RESIDUALE")):
                        emit("operativi_giornalieri",day,edition,metric,"MWh",r.get(vcol),sheet,i,sheet+" | "+stamp)
        elif re.fullmatch(r"(?:MY|G) - (?:WD|DA)",sheet) or re.match(r"^(Consuntivo|Previsionale|Previsione|Intraday)",sheet):
            h=rows.get(7,{})
            if rows.get(6,{}).get("A")!="Giorno di Riferimento":continue
            family="qk" if " - WD" in sheet or " - DA" in sheet else "wkr"
            for i,r in rows.items():
                if i<8 or not re.fullmatch(r"\d{2}/\d{2}/\d{4}",r.get("A","")):continue
                day=dmy(r["A"])
                for c,metric in h.items():
                    if c!="A":emit(family,day,sheet,metric,"coefficiente (come pubblicato)",r.get(c),sheet,i)
        elif sheet.startswith("AT_"):
            h=rows.get(13,{})
            if rows.get(8,{}).get("B","").lower()!="valori espressi in kwh" or h.get("B")!="DATA" or not h.get("E","").startswith("GIACENZA"):continue
            for i,r in rows.items():
                if i<14 or not re.fullmatch(r"\d{2}/\d{2}/\d{4}",r.get("B","")):continue
                day=dmy(r["B"])
                for c in ("C","D","E","F","G"):
                    emit("gas_stock",day,"pubblicato · include proiezioni",h[c],"frazione" if c=="F" else "kWh",r.get(c),sheet,i)
        elif sheet=="Stogit Adriatica":
            if rows.get(6,{}).get("A")!="Gas Day" or rows.get(7,{}).get("D")!="[MWh]":continue
            # Excel 1900 date system, require explicit plausible range.
            for i,r in rows.items():
                if i<8 or not re.fullmatch(r"\d{5}",r.get("A","")):continue
                day=(date(1899,12,30)+timedelta(days=int(r["A"])))
                if not 2020<=day.year<=2100:raise ValueError("Data HS2 non valida")
                for c,label,unit in (("B","Movimentato hub","MWh/d"),("C","Nomine utenti","MWh/d"),("D","Giacenza utenti","MWh"),("N","Spazio offerto","MWh"),("O","Spazio conferito","MWh")):
                    emit("gas_stock_hs2",day.isoformat(),"Stogit Adriatica · HS2",label,unit,r.get(c),sheet,i)
    if balances:
        if set(balances)!=set(BALANCE_SHEETS):raise ValueError("Servono i due fogli per riconciliare le unità")
        stage,aa,bb,checks,inconsistent=balance_pair(balances,name)
        if inconsistent:
            warnings.append(f"Intestazione unità incoerente in {name}; {checks} coppie riconciliate con PCS 10,57275. Unità inferita dal rapporto e nome foglio, non confermata da Snam.")
        for idx,(table,unit) in enumerate(((aa,"GWh"),(bb,"milioni di Sm3"))):
            sh=BALANCE_SHEETS[idx]
            h=balances[sh][14]
            for day,(i,r) in table.items():
                for c in BALANCE_COLS:emit("bilanci",day,stage,h[c],unit,r.get(c),sh,i)
    if not out:raise ValueError("Nessun foglio supportato")
    return out,warnings


def parse_wkr_csv(raw,name):
    reader=csv.DictReader(StringIO(raw.decode("utf-8-sig")),delimiter=";")
    cols=("ZONA_CLIMATICA","GIORNO","DATA_WKR","Wkr","TIPO","DATA_HDD")
    if tuple(reader.fieldnames or ())!=cols:raise ValueError("Schema CSV WKR non riconosciuto")
    digest=sha256(raw).hexdigest()
    out=[]
    for i,r in enumerate(reader,2):
        if i>10000 or None in r or any(v is None for v in r.values()):raise ValueError("CSV WKR non valido")
        if not re.fullmatch(r"\d{1,3}",r["ZONA_CLIMATICA"]) or not re.fullmatch(r"[A-Z0-9]{1,4}",r["TIPO"]):raise ValueError("Zona/tipo WKR non valido")
        day=datetime.strptime(r["GIORNO"],"%Y%m%d").date().isoformat()
        stamp=datetime.strptime(r["DATA_WKR"],"%Y%m%d %H:%M:%S").isoformat()
        hdd=datetime.strptime(r["DATA_HDD"],"%Y%m%d %H:%M:%S").isoformat()
        value=number(r["Wkr"])
        if value is not None:out.append(("wkr_csv",day,r["TIPO"],"Zona "+r["ZONA_CLIMATICA"],"coefficiente (come pubblicato)",value,"CSV",i,stamp+" | HDD "+hdd,digest,name))
    if not out:raise ValueError("CSV WKR vuoto")
    return out,[]


def parse_upload(raw,name):
    """Read one native file or ZIP (one nested ZIP level). PDFs never ingested."""
    out=[]; warnings=[]; seen=set()
    def dispatch(data,label,depth):
        suffix=posixpath.splitext(label.lower())[1]
        if suffix==".pdf":
            warnings.append("PDF escluso; nessuna estrazione.")
            return
        if suffix==".zip":
            if depth>1:raise ValueError("ZIP annidato oltre il limite")
            with safezip(data) as z:
                for item in z.infolist():
                    if item.is_dir():continue
                    basename=posixpath.basename(item.filename)
                    if not basename or item.file_size>MAX_BYTES:raise ValueError("Allegato ZIP fuori limite")
                    dispatch(z.read(item),basename,depth+1)
            return
        if suffix not in (".xlsx",".csv"):
            warnings.append("Formato non supportato escluso.")
            return
        key=sha256(data).hexdigest()
        if key in seen:return
        seen.add(key)
        rows,notes=(parse_xlsx(data,label) if suffix==".xlsx" else parse_wkr_csv(data,label))
        out.extend(rows);warnings.extend(notes)
        if len(out)>MAX_ROWS:raise ValueError("Troppe osservazioni")
    try:dispatch(raw,posixpath.basename(name),0)
    except (zipfile.BadZipFile,ET.ParseError,KeyError,IndexError,UnicodeError,OverflowError,InvalidOperation) as exc:
        raise ValueError("Formato nativo non valido") from exc
    if not out:raise ValueError("Nessuna osservazione numerica supportata")
    return out,warnings


def compare_balances(frame):
    """Only unique values per phase/day; no invented publication timestamps."""
    if frame.empty:return []
    results=[]
    for day,group in frame.groupby("gas_day",sort=True):
        by={edition:{Decimal(v) for v in part.value} for edition,part in group.groupby("edition")}
        p=by.get("provvisorio",set());d=by.get("definitivo",set())
        a=next(iter(p)) if len(p)==1 else None
        b=next(iter(d)) if len(d)==1 else None
        results.append({"gas_day":day,"provvisorio":float(a) if a is not None else None,
                        "definitivo":float(b) if b is not None else None,
                        "delta":float(b-a) if a is not None and b is not None else None,
                        "conflict":len(p)>1 or len(d)>1})
    return results
