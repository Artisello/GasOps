"""Commercial desk for synthetic data; no external transactions or confidential files."""
import csv
import io
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal as D

import pandas as pd
import streamlit as st

from .commercial_controls import (BILL_REF, LNG_REF, PRICE_REF, demo_invoices,
                                  imbalance_prices, lng_deadlines, reconcile)
from .commercial_view import calendar_rows
from .italiano import numero, data_it
from .visuals import info, kpi_grid, header
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
    st.subheader("Esempio fatture")
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
    return rows


def _price_panel():
    st.subheader("Prezzi di sbilanciamento")
    st.caption("Calcolo ipotetico · non prezzi GME effettivi")
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
    from .credit_risk_page import credit_risk_panel
    return credit_risk_panel()


def _calendar_panel(invoice_rows):
    st.subheader("Scadenze commerciali")
    st.caption("Scadenze calcolate · nessun pagamento verificato")
    if invoice_rows:
        st.caption("Fatture di esempio · dati sintetici")
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
    kpi_grid([("Entro 7 giorni",len(urgent),"","Date indicative",0,""),
              ("Date trascorse",len(past),"","Non implica mancato pagamento",0,"")])
    st.dataframe([{"Adempimento":r["task"],"Data":r["due"],"Giorni residui":r["days_left"],"Stato data":r["status"]}
                  for r in result],hide_index=True,width="stretch")
    st.download_button("Scarica scadenze CSV",_csv(result),"igor-scadenze.csv","text/csv",key="commercial_calendar_export")
    info("Info scadenze",BILL_REF,LNG_REF,"I pagamenti usano giorni di calendario; le scadenze GNL escludono weekend e festività inserite. Convenzioni ed effettiva vigenza da verificare. Nessun promemoria automatico.")
    return result


def commercial_workbench(ledger_view):
    from .workspace import picker
    from .reconciliation_page import documents_panel, BALANCE_STATE
    header("Fatture e garanzie", "")
    # Keep explicit draft fields when switching between tasks in the same session.
    for key in list(st.session_state):
        if key.startswith(("invoice_present_","invoice_amount_","invoice_date_")) or key in (
                "commercial_example","commercial_as_of","price_day","credit_g","credit_c",
                "credit_pfat","credit_pdet","credit_patt","credit_verified","credit_late_bal",
                "credit_late_tr","credit_daily","credit_price","credit_vat","credit_psv"):
            st.session_state[key]=st.session_state[key]
    view=picker("Strumento",("Fatture","Garanzie","Scadenze","Prezzi","Bilanci e GNL"),
                key="commercial_view",labels={"Bilanci e GNL":"Calcolo GNL"})
    if view=="Fatture":
        documents_panel()
        if not st.session_state.get(BALANCE_STATE):
            if st.toggle("Prova con dati di esempio",key="commercial_example"):
                st.session_state["commercial_example_rows"]=_invoice_panel(sample_rows())
            else:
                st.session_state.pop("commercial_example_rows",None)
    elif view=="Garanzie":
        _guarantee_panel()
    elif view=="Scadenze":
        # Example invoices are included only after an explicit demonstration.
        rows=[] if st.session_state.get(BALANCE_STATE) else st.session_state.get("commercial_example_rows",[])
        _calendar_panel(rows)
    elif view=="Prezzi":
        _price_panel()
    else:
        ledger_view()
