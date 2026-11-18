"""Standalone demonstration; no file uploads, external writes or real counterparties."""
import csv
import io
from decimal import Decimal

import streamlit as st

from .operations_ledger import REFERENCE, allocate_lng_deviation, monthly_preview, revision_pairs, sample_rows
from .visuals import info, kpi_grid
from .italiano import numero


def _ledger_detail():
    st.subheader("Registro dei bilanci")
    st.caption("Demo sintetica · nessuna fatturazione ufficiale")
    info("Info registro","Codice di Rete XCII e Codice di Rigassificazione 2023-I: edizioni di studio. Vigenza, eccezioni e convenzioni contabili richiedono convalida specialistica.")
    rows = sample_rows()
    pairs = revision_pairs(rows)
    summary = monthly_preview(rows, "DEMO-001", 2026, 9)
    kpi_grid([("Partite DS negativo",summary["short_group_eur"],"€","Acquisto",2,""),
              ("Partite DS positivo",summary["long_group_eur"],"€","Vendita",2,""),
              ("Saldo simulato utente",summary["net_user_cash_eur"],"€","Non è una fattura",2,"")])
    st.caption("Settembre 2026 · imponibili illustrativi, IVA esclusa")
    st.subheader("Bilanci giornalieri e rettifiche")
    with st.popover("Info formula",icon=":material/info:"):
        st.latex(r"DS_k=I_k+S_k+T_k^N-P_k")
        st.caption(REFERENCE+" · PDF pp. 370–373, 394, 588.")
    data = []
    for prev, last in pairs:
        data.append({"Giorno-gas": last.day.isoformat(), "Versione": last.version,
                     "I (MWh)": str(last.injected), "S (MWh)": str(last.storage_net),
                     "T netto (MWh)": str(last.psv_net), "P (MWh)": str(last.withdrawn),
                     "DS provvisorio": str(prev.imbalance) if prev else "",
                     "DS definitivo": str(last.imbalance),
                     "Delta DS": str(last.imbalance-prev.imbalance) if prev else "",
                     "Flusso utente EUR": str(last.cash),
                     "Delta EUR": str(last.cash-prev.cash) if prev and prev.cash is not None else ""})
    revised=st.toggle("Mostra solo giornate con rettifiche",key="ledger_revisions_only")
    shown=[r for r in data if Decimal(r["Delta DS"] or "0")!=0 or Decimal(r["Delta EUR"] or "0")!=0] if revised else data
    st.caption(f"{len(shown)} di {len(data)} giorni del caso sintetico")
    st.dataframe(shown,hide_index=True,width="stretch")
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=list(data[0]))
    writer.writeheader()
    writer.writerows(data)
    st.download_button("Scarica registro completo CSV", output.getvalue(), "igor-registro-sintetico.csv", "text/csv")
    st.subheader("Riconciliazione GNL")
    info("Info GNL","Ripartizione pro-quota dello scostamento già al netto dei margini concordati (cap. 9 §3.2.1, PDF p. 96).")
    a,b=st.columns(2)
    first=a.number_input("Programma DEMO-A (MWh)",0,10000000,6000,step=100)
    second=b.number_input("Programma DEMO-B (MWh)",0,10000000,4000,step=100)
    net=st.number_input("Scostamento netto ipotetico (MWh)",-10000000,10000000,1000,step=100)
    programmed={"DEMO-A":Decimal(first),"DEMO-B":Decimal(second)}
    try:
        deltas = allocate_lng_deviation(programmed, Decimal(net))
        kpi_grid([("Programma totale",sum(programmed.values()),"MWh","Prima della rettifica",1,""),
                  ("Scostamento netto",Decimal(net),"MWh","Ipotesi",1,""),
                  ("Totale allocato",sum(programmed.values())+Decimal(net),"MWh","Dopo la rettifica",1,"")])
        st.dataframe([{"Utente fittizio":k,"Programma MWh":str(v),"Quota scostamento MWh":numero(deltas[k],3),
                      "Allocazione illustrativa MWh":numero(v+deltas[k],3)} for k,v in programmed.items()],hide_index=True,width="stretch")
        st.caption("Valori visualizzati arrotondati; il calcolo conserva lo scostamento totale.")
    except ValueError as exc:
        st.warning(str(exc))
    st.caption("Nessuna nomina, transazione o comunicazione operativa viene inviata.")


def operations_ledger():
    from .commercial_page import commercial_workbench
    commercial_workbench(_ledger_detail)
