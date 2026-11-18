from decimal import Decimal
import pandas as pd
import pytest
from gasops_app.jarvis_native import BALANCE_COLS,PCS,balance_pair,compare_balances,parse_upload,COLUMNS


def test_pair_reconciles_mislabeled_units():
    labels={c:c for c in BALANCE_COLS}|{"A":"GG","T":"Totale Immesso","AJ":"Totale Prelevato"}
    title={ "A":"Consuntivo definitivo del mese di Gennaio 2026"}
    left={8:title,9:{"A":"Valori espressi in milioni di Sm3"},14:labels,15:{"A":"1",**{c:str(PCS*Decimal("10")) for c in BALANCE_COLS}}}
    right={8:title,9:{"A":"Valori espressi in milioni di Sm3"},14:labels,15:{"A":"1",**{c:"10" for c in BALANCE_COLS}}}
    sheets={"kWh":left,"Sm3 PCS 10,57275 kWhSm3":right}
    stage,a,b,checks,inconsistent=balance_pair(sheets,"bilancio_202601-IT.xlsx")
    assert stage=="definitivo" and checks==12 and inconsistent
    right[15]["T"]="20"
    with pytest.raises(ValueError,match="riconciliabili"):
        balance_pair(sheets,"bilancio_202601-IT.xlsx")


def test_compare_conflicts_never_select_arbitrary_vintage():
    f=pd.DataFrame([{"gas_day":"2026-01-01","edition":"provvisorio","value":"10"},
                    {"gas_day":"2026-01-01","edition":"definitivo","value":"12"},
                    {"gas_day":"2026-01-02","edition":"provvisorio","value":"10"},
                    {"gas_day":"2026-01-02","edition":"provvisorio","value":"11"},
                    {"gas_day":"2026-01-02","edition":"definitivo","value":"13"}])
    rows=compare_balances(f)
    assert rows[0]["delta"]==2
    assert rows[1]["delta"] is None and rows[1]["conflict"]


def test_native_wkr_csv_and_pdf_exclusion():
    raw=b"ZONA_CLIMATICA;GIORNO;DATA_WKR;Wkr;TIPO;DATA_HDD\n11;20261117;20261118 10:41:07;1.1;C;20261118 11:00:00\n"
    rows,notes=parse_upload(raw,"wkr.csv")
    assert len(rows)==1 and rows[0][0]=="wkr_csv" and len(rows[0])==len(COLUMNS)
    with pytest.raises(ValueError):parse_upload(b"%PDF","report.pdf")


def test_native_empty_panel():
    from streamlit.testing.v1 import AppTest
    app=AppTest.from_string("from gasops_app.jarvis_native_page import panel\npanel()").run()
    assert not app.exception
    assert any("Nessun file nativo" in x.value for x in app.info)
