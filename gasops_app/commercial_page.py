"""Commercial desk for synthetic data; no external transactions or confidential files."""
import csv
import io
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal as D

import pandas as pd
import streamlit as st

from .commercial_controls import (BILL_REF, EPS_REF, LNG_REF, PRICE_REF, demo_invoices,
                                  exposure, imbalance_prices, lng_deadlines, reconcile)
from .commercial_view import reconciliation_summary, guarantee_scenario, calendar_rows
from .italiano import numero, data_it
from .visuals import info, kpi_grid
from .operations_ledger import sample_rows


def money(value):
    return "—" if value is None else "€ "+numero(value,2)


def _csv(rows):
    output=io.StringIO()
    writer=csv.DictWriter(output,fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


def _invoice_panel(records):
    st.subheader("Riconciliazione delle fatture")
    st.caption("Settembre 2026 · imponibili di esempio, IVA esclusa.")
    originals=demo_invoices()
    invoices=[]
    for original,label,col in zip(originals,("DS negativo · acquisto","DS positivo · vendita"),st.columns(2),strict=True):
        with col,st.container(border=True):
            st.markdown("**"+label+"**")
            present=st.checkbox("Documento presente",value=True,key="invoice_present_"+original.group)
            amount=st.number_input("Importo fattura (€)",min_value=0.,max_value=1e12,value=float(original.amount),
                                   step=100.,disabled=not present,key="invoice_amount_"+original.group)
            issue=st.date_input("Data emissione",original.issue_date,disabled=not present,key="invoice_date_"+original.group)
            if present and issue is not None:
                invoices.append(replace(original,amount=D(str(amount)),issue_date=issue))
    rows=reconcile(records,invoices,"DEMO-001",2026,9)
    summary=reconciliation_summary(rows)
    for r in rows:
        with st.container(border=True):
            label="Acquisto per DS negativo" if r["group"]=="short" else "Vendita per DS positivo"
            st.markdown("**"+label+" · "+r["status"]+"**")
            kpi_grid([("Importo atteso",r["expected"],"€","Da bilanci definitivi",2,""),
                      ("Importo documento",r["observed"],"€","Inserito nella demo",2,""),
                      ("Differenza",r["delta"],"€","Documento − atteso",2,"rose" if r["delta"] else "")])
            if r["status"]=="MANCANTE":
                st.warning("Documento non presente nella simulazione.")
            elif r["status"]=="DIFFERENZA":
                st.warning("Importo da riconciliare: "+money(abs(r["delta"]))+".")
            if r["due"]:
                st.caption("Data di pagamento indicativa: "+data_it(r["due"]))
    st.download_button("Scarica riconciliazione CSV",_csv([{**r,"mode":"SIMULAZIONE"} for r in rows]),
                       "igor-riconciliazione.csv","text/csv",key="commercial_reconcile_export")
    info("Info fatture",BILL_REF,"Le due partite sono separate. Una differenza non è una nota di credito. Fatture multiple, IVA e rettifiche richiedono verifica. Non vengono emesse fatture.")
    return rows,summary


def _price_panel():
    st.subheader("Prezzi di sbilanciamento")
    st.caption("Simulazione · regime ordinario · non prezzi GME effettivi")
    a,b=st.columns(2)
    with a:
        day=st.date_input("Giorno gas",date(2026,9,5),key="price_day")
        volume=st.number_input("Volume STSP title (MWh)",0.,1e9,2500.,step=100.)
        mean=st.number_input("Prezzo medio GME (€/MWh)",0.,10000.,40.,disabled=volume<2000)
        rate=st.number_input("Small adjustment pubblicato (%)",0.,10.,1.)
    with b:
        buy=st.number_input("Massimo acquisto TSO (€/MWh)",-10000.,10000.,42.)
        sell=st.number_input("Minimo vendita TSO (€/MWh)",-10000.,10000.,38.)
        ordinary=st.checkbox("Regime ordinario e dati TSO completi",value=True)
    history=None
    if volume<2000:
        st.info("Sotto 2.000 MWh: si usa la media dei 30 giorni precedenti. Esempio sintetico a prezzo costante.")
        historical=st.number_input("Prezzo medio ipotetico dei 30 giorni (€/MWh)",0.,10000.,39.)
        if day is not None:
            history={day-timedelta(days=i):D(str(historical)) for i in range(1,31)}
    try:
        if day is None:
            raise ValueError("Indica il giorno gas.")
        priced=imbalance_prices(day,D(str(volume)),D(str(mean)),D(str(buy)),D(str(sell)),
                                D(str(rate)),history,ordinary=ordinary)
        kpi_grid([("Prezzo acquisto",priced["buy"],"€/MWh","Per DS negativo",3,""),
                  ("Prezzo vendita",priced["sell"],"€/MWh","Per DS positivo",3,""),
                  ("Small adjustment",priced["adjustment"],"€/MWh","Percentuale × media",3,"")])
        st.caption(priced["method"])
        with st.expander("Dettaglio del calcolo"):
            st.dataframe([{"Prezzo":"Acquisto","Media + SA":float(priced["mean"]+priced["adjustment"]),
                           "Estremo TSO":buy,"Risultato":float(priced["buy"])},
                          {"Prezzo":"Vendita","Media − SA":float(priced["mean"]-priced["adjustment"]),
                           "Estremo TSO":sell,"Risultato":float(priced["sell"])}],hide_index=True,width="stretch")
    except (ValueError,OverflowError) as error:
        st.warning(str(error))
    info("Info prezzi",PRICE_REF,"Il calcolo usa la percentuale semestrale fornita dall’utente; nessun calcolo automatico Euribor. Prezzi esposti a tre decimali; confronto non arrotondato.")
    from .operational_sources_page import gme_reference
    gme_reference()


def _guarantee_panel():
    st.subheader("Controllo delle garanzie")
    st.caption("Componenti già determinate · IVA inclusa ove prevista")
    a,b=st.columns(2)
    with a:
        pf=st.number_input("Pfat · fatturato (€)",-1e12,1e12,420000.,step=10000.,key="guarantee_pfat")
        pd_=st.number_input("Pdet · determinato (€)",-1e12,1e12,280000.,step=10000.,key="guarantee_pdet")
    with b:
        pa=st.number_input("Patt · atteso (€)",-1e12,1e12,220000.,step=10000.,key="guarantee_patt")
        limit=st.number_input("MEPSu · limite (€)",min_value=0.,max_value=1e12,value=1000000.,step=10000.,key="guarantee_limit")
    with st.expander("Simula un aumento o una riduzione dell’esposizione"):
        shock=st.number_input("Variazione ipotetica di Patt (€)",-1e12,1e12,80000.,step=10000.,key="guarantee_shock")
    try:
        case=guarantee_scenario(*(D(str(v)) for v in (pf,pd_,pa,limit,shock)))
    except ValueError as error:
        st.warning(str(error))
        return None
    risk=case["current"]
    projected=case["projected"]
    with st.container(border=True,key="panel_guarantee_usage"):
        st.caption("Utilizzo del limite MEPSu")
        st.markdown("### "+numero(risk["ratio"],1)+"%")
        st.progress(float(max(D(0),min(D(100),risk["ratio"]))/100))
        info("Soglie","Soglie di studio: 90% attenzione, 100% limite. Barra limitata a 0–100%; valore effettivo sopra.")
        if risk["status"]=="LIMITE":
            st.error("Esposizione pari o superiore al limite. Verifica specialistica necessaria.")
        elif risk["status"]=="ATTENZIONE":
            st.warning("Soglia di attenzione del 90% raggiunta.")

    kpi_grid([("Esposizione EPSu",risk["eps"],"€","Pfat + Pdet + Patt",2,""),
              ("Margine residuo",risk["headroom"],"€","MEPSu − EPSu",2,"rose" if risk["headroom"]<0 else ""),
              ("Distanza dal 90%",case["to_90"],"€","Negativo = soglia superata",2,"")])
    with st.container(border=True):
        st.markdown("**Scenario ipotetico · "+numero(D(str(shock)),0,signed=True)+" € su Patt**")
        kpi_grid([("Utilizzo nello scenario",projected["ratio"],"%",projected["status"],1,""),
                  ("Margine nello scenario",projected["headroom"],"€","Limite invariato",2,""),
                  ("MEPS aggiuntivo teorico",case["additional_meps_90"],"€","Per utilizzo ≤ 90%",2,"")])
        info("Scenario","Indicazione matematica, non richiesta di garanzia né decisione di accesso.")
    info("Info garanzie",EPS_REF,"I componenti EPSu e MEPSu devono essere già validati. Non vengono calcolati automaticamente. Lo scenario varia solo Patt; non modifica l’esposizione attuale.")
    st.download_button("Scarica controllo garanzie CSV",_csv([
        {"scenario":name,"eps":r["eps"],"meps":r["meps"],"headroom":r["headroom"],"ratio":r["ratio"],"status":r["status"],"mode":"SIMULAZIONE","reference":EPS_REF}
        for name,r in (("base",risk),("ipotetico",projected))]),"igor-garanzie.csv","text/csv",key="guarantee_export")
    return risk


def _calendar_panel(invoice_rows):
    st.subheader("Scadenze commerciali")
    st.caption("Calendario demo · stato pagamenti non verificato")
    as_of=st.date_input("Data di riferimento",date(2026,11,18),key="commercial_as_of")
    with st.expander("Parametri calendario GNL"):
        a,b=st.columns(2)
        month=a.date_input("Primo giorno del mese di programmazione",date(2026,12,1))
        acceptance=b.date_input("Accettazione programma",date(2026,11,20))
        raw=st.text_input("Festività escluse (AAAA-MM-GG, separate da virgola)","2026-11-01, 2026-12-08, 2026-12-25, 2026-12-26")
    deadlines=[{"task":"Pagamento "+r["invoice"],"due":r["due"],"reference":BILL_REF} for r in invoice_rows if r["invoice"]]
    try:
        holidays={date.fromisoformat(v.strip()) for v in raw.split(",") if v.strip()}
        if month is None:
            raise ValueError("Indica il mese di programmazione.")
        deadlines+=lng_deadlines(month,acceptance,holidays)
    except (ValueError,OverflowError) as error:
        st.warning("Scadenze GNL non calcolate: "+str(error))
    if as_of is None:
        st.info("Indica la data di riferimento.")
        return []
    result=calendar_rows(deadlines,as_of)
    if not result:
        st.info("Nessuna data disponibile per i parametri inseriti.")
        return []
    urgent=[r for r in result if r["days_left"] is not None and 0<=r["days_left"]<=7]
    past=[r for r in result if r["days_left"] is not None and r["days_left"]<0]
    kpi_grid([("Entro 7 giorni",len(urgent),"","Da valutare nella demo",0,""),
              ("Date trascorse",len(past),"","Non implica mancato pagamento",0,"")])
    st.dataframe([{"Adempimento":r["task"],"Data":r["due"],"Giorni residui":r["days_left"],"Stato data":r["status"]}
                  for r in result],hide_index=True,width="stretch")
    st.download_button("Scarica scadenze CSV",_csv(result),"igor-scadenze.csv","text/csv",key="commercial_calendar_export")
    info("Info scadenze",BILL_REF,LNG_REF,"I pagamenti usano giorni di calendario; le scadenze GNL escludono weekend e festività inserite. Convenzioni ed effettiva vigenza da verificare. Nessun promemoria automatico.")
    return result


def commercial_workbench(ledger_view):
    st.title("Fatture e garanzie")
    st.caption("Simulazione · partecipante fittizio DEMO-001 · nessuna operazione reale")
    summary_slot=st.container()
    tabs=st.tabs(["Fatture","Garanzie","Scadenze","Prezzi","Bilanci e GNL"])
    with tabs[0]:
        invoice_rows,summary=_invoice_panel(sample_rows())
    with tabs[1]:
        risk=_guarantee_panel()
    with tabs[2]:
        calendar=_calendar_panel(invoice_rows)
    with tabs[3]:
        _price_panel()
    with tabs[4]:
        ledger_view()
    with summary_slot:
        kpi_grid([("Partite da verificare",summary["issues"],"",str(summary["unknown"])+" con importo non confrontabile",0,""),
                  ("Differenze note",summary["known_difference"],"€","Somma assoluta delle differenze note",2,""),
                  ("Utilizzo garanzie",risk["ratio"] if risk else None,"%",risk["status"] if risk else "Non calcolabile",1,""),
                  ("Date entro 7 giorni",sum(r["days_left"] is not None and 0<=r["days_left"]<=7 for r in calendar),"","Calendario dimostrativo",0,"")])

