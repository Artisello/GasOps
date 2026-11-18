"""Standalone demonstration; no file uploads, external writes or real counterparties."""
import csv
import io
from decimal import Decimal

import streamlit as st

from .operations_ledger import REFERENCE, allocate_lng_deviation, monthly_preview, revision_pairs, sample_rows


def _ledger_detail():
    st.subheader("Registro dei bilanci")
    st.caption("Demo sintetica · Codice di Rete XCII e Codice di Rigassificazione 2023-I · Nessuna fatturazione ufficiale")
    st.info("Le edizioni sono fonti di studio. La vigenza, le eccezioni e le convenzioni contabili richiedono convalida specialistica.")
    rows = sample_rows()
    pairs = revision_pairs(rows)
    summary = monthly_preview(rows, "DEMO-001", 2026, 9)
    def eur(x):
        return f"€ {x:,.2f}"
    a, b, c = st.columns(3)
    a.metric("Partite DS negativo", eur(summary["short_group_eur"]))
    b.metric("Partite DS positivo", eur(summary["long_group_eur"]))
    c.metric("Saldo simulato utente", eur(summary["net_user_cash_eur"]))
    st.caption("Settembre 2026 · 30 giorni sintetici · imponibili illustrativi, esclusi IVA, altri corrispettivi e aggiustamenti. Il saldo non è una fattura.")
    st.subheader("Bilanci giornalieri e rettifiche")
    st.latex(r"DS_k=I_k+S_k+T_k^N-P_k")
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
    st.dataframe(data, hide_index=True, use_container_width=True)
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=list(data[0]))
    writer.writeheader()
    writer.writerows(data)
    st.download_button("Esporta registro CSV", output.getvalue(), "gasops-registro-sintetico.csv", "text/csv")
    st.caption(REFERENCE + " · PDF pp. 370–373, 394, 588.")
    st.subheader("Riconciliazione GNL")
    st.write("Ripartizione pro-quota dello scostamento già al netto dei margini concordati (cap. 9 §3.2.1, PDF p. 96).")
    net = st.number_input("Scostamento netto ipotetico (MWh)", min_value=-10000, max_value=10000, value=1000, step=100)
    programmed = {"DEMO-A": Decimal(6000), "DEMO-B": Decimal(4000)}
    try:
        deltas = allocate_lng_deviation(programmed, Decimal(net))
        st.dataframe([{"Utente fittizio": k, "Programma MWh": str(v),
                      "Quota scostamento MWh": str(deltas[k]),
                      "Allocazione illustrativa MWh": str(v+deltas[k])} for k,v in programmed.items()], hide_index=True)
    except ValueError as exc:
        st.warning(str(exc))
    st.caption("Nessuna nomina, transazione o comunicazione operativa viene inviata.")


def operations_ledger():
    from .commercial_page import commercial_workbench
    commercial_workbench(_ledger_detail)
