"""Traceable BSO scorecard. No network calls, no fabricated observations or SLA."""
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from calendar import monthrange
from decimal import Decimal
from math import isfinite
import csv
import io

from .data import ROME
from .bso_kpis import operations_metrics, balancing_metrics, settlement_metrics, closed_gas_day
from .jarvis_archive import revision_rows, SOURCE as JARVIS
from .entsog_network import daily_metrics
from .entsog import SOURCE as ENTSOG
from .operational_sources import GIE_LINKS
from .acer_market import bundled_lng, TERMINAL, with_spreads, REPORT_2026
from .acer_baf_2026 import report_2026_rows
from .mase_archive import observations, as_bcm, MASE_SOURCE
from .terna_power import annual_rows, ANNUAL_URL, PORTAL, paired, correlation


@dataclass(frozen=True)
class Metric:
    area: str
    code: str
    label: str
    value: float | int | Decimal | None
    unit: str
    period: str
    scope: str
    source: str
    source_url: str
    status: str
    coverage: str
    definition: str


def finite(value):
    try:
        n=float(value)
        return n if isfinite(n) else None
    except (ValueError, TypeError, OverflowError):
        return None


def pct(n,d):
    return 100*n/d if d else None


def entry(area,code,label,value,unit,period,scope,source,url,status,coverage,definition):
    return Metric(area,code,label,finite(value),unit,period,scope,source,url,
                  status if finite(value) is not None else "Non disponibile",coverage,definition)


def month_label(year,month,cutoff):
    first=date(year,month,1)
    end=min(cutoff,date(year,month,monthrange(year,month)[1]))
    return f"{first:%Y-%m} · fino al {end.isoformat()}" if end>=first else f"{first:%Y-%m} · nessun giorno concluso"


def operations_scores(tasks,now,year,month):
    p=f"{year:04d}-{month:02d}"
    source="Registro attività importato"
    r=operations_metrics(tasks,now,year,month) if tasks is not None else None
    # Overdue backlog is an as-of stock, not the chosen monthly cohort.
    return [
        entry("Operations","on_time","Puntualità attività",r["on_time_pct"] if r else None,"%",p,"Tutte le aree",source,"","Dichiarato",
              f'{r["on_time"]}/{r["due"]} scadenze trascorse' if r else "Registro assente",
              "Attività completate entro il termine / attività con termine trascorso nel mese; include aperte in ritardo."),
        entry("Operations","overdue","Attività aperte in ritardo",len(r["overdue"]) if r else None,"",now.astimezone(ROME).isoformat(timespec="minutes"),
              "Tutte le date del registro",source,"","Dichiarato","Solo attività presenti" if r else "Registro assente",
              "Conteggio delle attività non completate oltre la scadenza, incluse quelle dei mesi precedenti."),
        entry("Operations","upcoming","Scadenze entro 7 giorni",r["next7"] if r else None,"",now.astimezone(ROME).isoformat(timespec="minutes"),
              "Tutte le date del registro",source,"","Dichiarato","Solo attività presenti" if r else "Registro assente",
              "Attività ancora aperte con termine non passato entro 168 ore; include le prossime 24 ore."),
    ]


def balancing_scores(imported,now,year,month):
    r=balancing_metrics(imported["versions"] if imported else None,year,month,now)
    p=month_label(year,month,closed_gas_day(now))
    status="Parziale · dichiarato" if r["observed"]<r["expected"] else "Dichiarato"
    cov=f'{r["observed"]}/{r["expected"]} giorni gas conclusi'
    def make(code,label,value,unit,definition):
        return entry("Balancing",code,label,value,unit,p,"Rete Snam · stime","Jarvis, import manuale",JARVIS,status,cov,definition)
    return [make("sas_mean","|SAS| medio",r["mean_abs_sas"],"GWh","Media dei valori assoluti dell'ultima stima disponibile per ciascun giorno gas concluso; non SAS misurato."),
            make("sas_peak","Picco |SAS|",r["peak_abs_sas"],"GWh","Massimo valore assoluto delle stime disponibili."),
            make("sas_coverage","Copertura stime SAS",pct(r["observed"],r["expected"]) if imported else None,"%",
                 "Giorni conclusi con ultima stima SAS numerica / giorni conclusi nel mese. Nessun import = non disponibile.")]


def archive_scores(records,now,year,month,metric,unit):
    p=f"{year:04d}-{month:02d}"
    subset=[r for r in (records or ()) if r.family=="balance" and r.metric==metric and r.unit==unit
            and (r.gas_day.year,r.gas_day.month)==(year,month) and r.gas_day<=closed_gas_day(now)
            and r.published_at<=now and r.scope=="SRG"]
    rows=revision_rows(subset)
    comparable=[r for r in rows if r["delta"] is not None]
    changed=sum(r["delta"]!=0 for r in comparable)
    cov=f"{len(comparable)}/{len(rows)} giorni presenti confrontabili"
    def make(code,label,value,u,definition):
        return entry("Settlement",code,label,value,u,p,"SRG · "+metric+" · "+unit,
                     "Jarvis, bilanci pubblici importati",JARVIS,"Dichiarato",cov,definition)
    return [make("revision_rate","Giorni con rettifica",pct(changed,len(comparable)),"%",
                 "Giorni con delta non nullo / giorni con provvisorio e definitivo confrontabili. Non copertura del mese."),
            make("revision_abs","Rettifiche assolute",sum(abs(r["delta"]) for r in comparable) if comparable else None,unit,
                 "Somma dei delta assoluti, stesso perimetro, indicatore e unità; non importi fatturati.")]


def participant_scores(rows,user,now,year,month):
    r=settlement_metrics(rows,user,year,month,closed_gas_day(now)) if rows and user else None
    cov=f'{r["eligible"]}/{r["expected"]} giorni gas' if r else "Registro o partecipante assente"
    p=month_label(year,month,closed_gas_day(now))
    def make(code,label,value,u,definition):
        return entry("Settlement",code,label,value,u,p,"Partecipante selezionato (ID non esportato)","Registro bilanci importato","",
                     "Parziale · dichiarato" if r and not r["complete"] else "Dichiarato",cov,definition)
    return [make("eligible","Definitivi utilizzabili",r["eligible_pct"] if r else None,"%","Giorni conclusi con definitivo valorizzabile e senza eccezioni implementate / giorni conclusi del mese."),
            make("exceptions","Giorni con eccezioni",r["exceptions"] if r else None,"","Giorni con almeno una eccezione, incluse le assenze; non conteggio di singole anomalie.")]


def network_scores(result,now):
    p="—"; scope="Punto/direzione non caricati"; status="Non disponibile"; cov="Nessuna estrazione"
    flow=util=gap=None
    if result is not None:
        days=daily_metrics(result)
        available=[r for r in days if r["Physical Flow"] is not None]
        latest=available[-1] if available else None
        p=latest["gas_day"] if latest else f"{result.first} – {result.last}"
        scope=result.point
        if result.labels and len(result.labels)==1:
            scope+=" · "+" / ".join(result.labels[0])
        valid=sum(r["quality"]=="valido" for r in result.rows)
        cov=f"{valid}/{len(result.rows)} slot richiesti · acquisito {result.acquired.isoformat(timespec='minutes')}"
        status="Da verificare" if result.metadata_warning or len(result.labels)!=1 or result.failed or now-result.acquired>timedelta(hours=12) else "Parziale" if valid<len(result.rows) else "Estratto"
        if latest:
            flow=latest["Physical Flow"]
            util=latest["technical_utilization_pct"]
            gap=latest["flow_minus_renomination"]
    def make(code,label,value,unit,definition):
        return entry("Contesto rete",code,label,value,unit,p,scope,"ENTSOG",ENTSOG,status,cov,definition)
    return [make("flow","Flusso fisico",flow,"GWh/d","Ultimo giorno con flusso numerico nell'estrazione; nessuna somma di punti."),
            make("util","Utilizzo capacità tecnica",util,"%","Flusso / capacità tecnica firm, stesso giorno e direzione; non congestione commerciale."),
            make("ren_gap","Flusso − rinomina",gap,"GWh/d","Differenza pubblicata sullo stesso giorno, non errore previsionale ex ante o DS.")]


def storage_scores(saved,now):
    result=saved.get("result") if saved else None
    value=stock=None
    period="—"; status="Non disponibile"; coverage="Caricare AGSI+ Italia"
    if result and result.get("scope")=="IT":
        frame=result["frame"].sort_values("gas_day")
        usable=frame[frame["stock_twh"].notna()]
        if not usable.empty:
            r=usable.iloc[-1]
            stock,value=r["stock_twh"],r["fill_pct"]
            day=r["gas_day"]
            period=str(day)
            coverage=f"Stato fonte {r['status']} · acquisito {result['acquired'].isoformat(timespec='minutes')}"
            status="Da verificare" if (saved.get("error") or result["failed"] or bool(r.get("review")) or
                (now.astimezone(ROME).date()-day).days>2 or now-result["acquired"]>timedelta(hours=24)) else "Stimato" if r["status"]=="E" else "Estratto"
    def make(code,label,v,u,definition):
        return entry("Contesto rete",code,label,v,u,period,"Italia · perimetro GIE","Gas Infrastructure Europe (GIE) – AGSI+",GIE_LINKS["AGSI+"],status,coverage,definition)
    return [make("stock","Gas in stoccaggio",stock,"TWh","Ultima giacenza pubblicata disponibile."),
            make("fill","Riempimento stoccaggi",value,"%","Percentuale pubblicata nello stesso giorno della giacenza; non soglia di sicurezza.")]


def historical_scores(lng,now):
    result=lng if lng is not None else bundled_lng()
    row=with_spreads(result.rows)[-1]
    p=row["date"]
    stat="Storico / non recente" if (now.astimezone(ROME).date()-date.fromisoformat(p)).days>4 else "Estratto"
    if result.failed or "utente" in result.provenance:
        stat="Da verificare"
    def market(code,label,value,definition):
        return entry("Contesto mercato",code,label,value,"€/MWh",p,"UE / regioni ACER","ACER TERMINAL",TERMINAL,stat,result.provenance,definition)
    return [market("lng","Prezzo GNL UE",row["eu"],"Valore spot DES UE pubblicato, non TTF."),
            market("lng_spread","Benchmark GNL − TTF",row["benchmark"],"Differenziale pubblicato rispetto a TTF front-month, non prezzo assoluto.")]


def benchmark_scores():
    rows=report_2026_rows()
    it={r["metric"]:r for r in rows if r["zone"]=="IT" and r["gas_year"]=="2024/2025"}
    metrics=(("imbalance_share","Sbilanciamenti / volume","%","Rapporto volumi sbilanciati / mercato fisico."),
             ("net_adjusted_neutrality","Neutralità netta rettificata","€/MWh","Surplus/costo unitario del regime, non profitto TSO."),
             ("tso_buy_share","Quota acquisti TSO","%","Quota degli acquisti sul volume delle azioni TSO."))
    result=[entry("Benchmark annuali","baf_"+key,label,it[key]["value"],unit,"GY 2024/2025","Italia · zona ACER",
                  "ACER report ottobre 2026",REPORT_2026,"Storico",f"p. {it[key]['page']} · arrotondato",definition)
            for key,label,unit,definition in metrics]
    prod=next(r for r in observations() if r["period"]=="2025" and r["geography"]=="IT")
    result.append(entry("Benchmark annuali","mase_prod","Produzione nazionale gas",as_bcm(prod["value"],prod["unit"]),"mld Sm³","2025","Italia",
                        "MASE – UNMIG",prod["source_url"],"Storico",prod["edition"],"Produzione gas nazionale pubblicata, non domanda o importazioni."))
    gas=next(r for r in annual_rows() if r["metric"]=="gas_gross")
    result.append(entry("Benchmark annuali","terna_gas","Elettricità da gas (lorda)",gas["value"],"TWh elettrici","2025","Italia",
                        "Terna, statistiche 2025",ANNUAL_URL,"Storico","Valore pubblicato arrotondato","Energia elettrica prodotta da gas, non energia del combustibile."))
    return result


def power_scores(saved):
    value=None; p="—"; cov="Caricare Terna + ENTSOG"; status="Non disponibile"
    if saved and saved.get("gas") and saved.get("power"):
        power,gas=saved["power"],saved["gas"]
        pairs=paired(power["rows"],gas["gas"])
        value=correlation(pairs)
        p=f"{power['first']} – {power['last']}"
        cov=f"{len(pairs)} coppie · Terna {power['acquired']} · ENTSOG {gas['acquired']}"
        status="Sperimentale · da verificare"
    return [entry("Contesto rete","power_corr","Correlazione power–gas",value,"r",p,"Italia elettrica / prelievi termoelettrici SRG",
                  "Terna + ENTSOG",PORTAL,status,cov,"Pearson su almeno 7 coppie complete; avvio intervallo Terna assunto, perimetri differenti, non causalità.")]


def export_csv(rows):
    # Export aggregates only; no underlying participant or task identifiers.
    out=io.StringIO()
    writer=csv.DictWriter(out,fieldnames=list(Metric.__dataclass_fields__),lineterminator="\n")
    writer.writeheader()
    for row in rows:
        d=asdict(row)
        for k,v in d.items():
            if isinstance(v,str) and v.lstrip().startswith(("=","+","-","@")):
                d[k]="'"+v
        writer.writerow(d)
    return out.getvalue()
