"""Illustrative GNL allocation calculator and commercial entry point."""
from decimal import Decimal

import streamlit as st

from .operations_ledger import allocate_lng_deviation
from .visuals import info, kpi_grid
from .italiano import numero


def _ledger_detail():
    st.subheader("Ripartisci lo scostamento GNL")
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
        
    except ValueError as exc:
        st.warning(str(exc))
    st.caption("Calcolo illustrativo · nessuna operazione inviata.")


def operations_ledger():
    from .commercial_page import commercial_workbench
    commercial_workbench(_ledger_detail)
