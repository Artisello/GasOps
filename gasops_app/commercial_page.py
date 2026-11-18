"""Single commercial workbench; operational demo only, no confidential uploads."""
import csv
import io
from datetime import date
from decimal import Decimal as D

import streamlit as st

from .commercial_controls import (BILL_REF, EPS_REF, LNG_REF, PRICE_REF, demo_invoices,
                                  exposure, imbalance_prices, lng_deadlines, reconcile)
from .italiano import numero
from .operations_ledger import sample_rows


def money(value):
    return "—" if value is None else "€ "+numero(value,2)


def _csv(rows):
    output=io.StringIO()
    writer=csv.DictWriter(output,fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


def commercial_workbench(ledger_view):
    st.title("Operazioni commerciali")
    st.caption("Dati fittizi · Settembre 2026 · Edizioni normative di studio · Nessuna disposizione operativa o fattura reale")
    records = sample_rows()
    demo = reconcile(records,demo_invoices(),"DEMO-001",2026,9)
    eps = exposure(D(420000),D(280000),D(220000),D(1000000))
    issues = [r for r in demo if r["status"] not in ("QUADRA","NON DOVUTA")]
    st.subheader("Da verificare")
    a,b,c=st.columns(3)
    a.metric("Partite da riconciliare",len(issues))
    b.metric("Differenze note",money(sum((abs(r["delta"]) for r in issues if r["delta"] is not None),D(0))))
    c.metric("Utilizzo garanzie",numero(eps["ratio"],1)+"%")
    st.caption("I tre indicatori si riferiscono al caso demo fisso; gli strumenti sottostanti consentono simulazioni indipendenti.")
    tabs=st.tabs(["Fatture","Prezzi","Garanzie","Scadenze","Bilanci e GNL"])
    with tabs[0]:
        st.subheader("Confronta le partite economiche")
        st.caption("Esempio imponibile, un documento per gruppo DS; IVA, note di credito e fatture multiple richiedono verifica.")
        a,b=st.columns(2)
        short=a.number_input("Documento DS negativo (€)",min_value=0.,value=168000.,step=100.)
        long=b.number_input("Documento DS positivo (€)",min_value=0.,value=57000.,step=100.)
        from dataclasses import replace
        invoices=[replace(demo_invoices()[0],amount=D(str(short))),replace(demo_invoices()[1],amount=D(str(long)))]
        rows=reconcile(records,invoices,"DEMO-001",2026,9)
        st.dataframe([{"Partita":"DS negativo" if r["group"]=="short" else "DS positivo",
                       "Atteso":money(r["expected"]),"Documento":money(r["observed"]),
                       "Differenza":money(r["delta"]),"Esito":r["status"]} for r in rows],hide_index=True)
        st.download_button("Esporta riconciliazione CSV",_csv(rows),"gasops-riconciliazione.csv","text/csv",
                           key="commercial_reconcile_export")
        st.caption(BILL_REF+" · Una differenza non costituisce una nota di credito.")
    with tabs[1]:
        st.subheader("Verifica i prezzi di sbilanciamento")
        st.caption("Regime ordinario · volumi e prezzi ipotetici · inserire la percentuale semestrale pubblicata.")
        a,b=st.columns(2)
        volume=a.number_input("Volume STSP title (MWh)",0.,1e9,2500.,step=100.)
        mean=a.number_input("Prezzo medio GME (€/MWh)",0.,10000.,40.)
        rate=a.number_input("Small adjustment pubblicato (%)",0.,10.,1.)
        buy=b.number_input("Massimo acquisto TSO (€/MWh)",-10000.,10000.,42.)
        sell=b.number_input("Minimo vendita TSO (€/MWh)",-10000.,10000.,38.)
        ordinary=b.checkbox("Regime ordinario e dati TSO completi",value=True)
        day=date(2026,9,5)
        history=None
        if volume<2000:
            st.info("Sotto 2.000 MWh si usa lo storico dei 30 giorni precedenti. Per questa demo lo storico è sintetico.")
            historical=st.number_input("Prezzo medio ipotetico dei 30 giorni (€/MWh)",0.,10000.,39.)
            from datetime import timedelta
            history={day-timedelta(days=i):D(str(historical)) for i in range(1,31)}
        try:
            priced=imbalance_prices(day,D(str(volume)),D(str(mean)),D(str(buy)),D(str(sell)),
                                    D(str(rate)),history,ordinary=ordinary)
            a,b=st.columns(2)
            a.metric("Acquisto (€/MWh)",numero(priced["buy"],3))
            b.metric("Vendita (€/MWh)",numero(priced["sell"],3))
            st.caption(priced["method"]+" · SA "+numero(priced["adjustment"],3)+" €/MWh")
        except ValueError as error:
            st.warning(str(error))
        st.caption(PRICE_REF+" · Prezzi esposti a tre decimali; calcolo non arrotondato.")
    with tabs[2]:
        st.subheader("Controlla la capienza delle garanzie")
        st.caption("Inserire componenti EPSu già determinate e MEPSu disponibile; importi firmati, IVA inclusa ove prevista.")
        a,b=st.columns(2)
        pf=a.number_input("Pfat (€)",value=420000.,step=10000.)
        pd=a.number_input("Pdet (€)",value=280000.,step=10000.)
        pa=b.number_input("Patt (€)",value=220000.,step=10000.)
        limit=b.number_input("MEPSu (€)",min_value=0.,value=1000000.,step=10000.)
        try:
            risk=exposure(*(D(str(v)) for v in (pf,pd,pa,limit)))
            a,b=st.columns(2)
            a.metric("EPSu",money(risk["eps"]))
            b.metric("Capienza residua",money(risk["headroom"]))
            st.progress(float(max(D(0),min(D(100),risk["ratio"]))/100),text="Utilizzo "+numero(risk["ratio"],1)+"%")
            if risk["status"]=="LIMITE":
                st.error("EPSu ≥ MEPSu: verifica specialistica necessaria.")
            elif risk["status"]=="ATTENZIONE":
                st.warning("Soglia del 90% raggiunta.")
            else:
                st.success("Inferiore al 90%.")
        except ValueError as error:
            st.warning(str(error))
        st.caption(EPS_REF+" · Non calcola autonomamente Pfat, Pdet, Patt o MEPSu.")
    with tabs[3]:
        st.subheader("Scadenze commerciali")
        st.caption("Date dimostrative. Il calendario lavorativo deve essere verificato prima dell’uso.")
        a,b=st.columns(2)
        month=a.date_input("Mese di programmazione GNL",date(2026,12,1))
        acceptance=b.date_input("Accettazione programma",date(2026,11,20))
        raw=st.text_input("Festività da escludere (AAAA-MM-GG, separate da virgola)","2026-11-01, 2026-12-08, 2026-12-25, 2026-12-26")
        try:
            holidays={date.fromisoformat(v.strip()) for v in raw.split(",") if v.strip()}
            deadlines=lng_deadlines(month,acceptance,holidays)
            deadlines += [{"task":"Pagamento "+r["invoice"],"due":r["due"],"reference":BILL_REF} for r in demo if r["invoice"]]
            deadline_rows=sorted(deadlines,key=lambda d:d["due"] or date.max)
            st.dataframe([{"Adempimento":r["task"],"Data":r["due"],"Fonte":r["reference"]} for r in deadline_rows],hide_index=True)
            st.download_button("Esporta scadenze CSV",_csv(deadline_rows),"gasops-scadenze.csv","text/csv")
        except ValueError as error:
            st.warning(str(error))
        st.caption("Festività e convenzioni di pagamento non certificate. Nessun promemoria viene inviato.")
    with tabs[4]:
        ledger_view()
