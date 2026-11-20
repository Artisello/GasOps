from datetime import date, datetime, timezone
from hashlib import sha256
from pathlib import Path
import re

import pymupdf
from streamlit.testing.v1 import AppTest

from gasops_app.bso_reference import SOURCES, TERMS, NETWORK, STORAGE
from gasops_app.gas_calendar import closed_gas_day
from gasops_app.regulatory import Pdf
from gasops_app.storage_balancing import closed_hs1_day

ROOT=Path(__file__).resolve().parents[1]


def test_cited_bundled_editions_and_pages_match_original_documents():
    checked=set()
    for document, (_,digest,pages) in SOURCES.items():
        path=ROOT/"data"/"public-regulatory"/document
        if not path.exists():
            continue  # The separately supplied glossary is not a bundled PDF.
        raw=path.read_bytes()
        assert sha256(raw).hexdigest()==digest
        with pymupdf.open(stream=raw,filetype="pdf") as pdf:
            assert len(pdf)==pages
            assert Pdf("renamed.pdf",digest,raw,len(pdf)).title==document
            for term in TERMS.values():
                for source,_,number in term.references:
                    if source==document:
                        assert pdf[number-1].get_text().strip()
        checked.add(document)
    assert len(checked)==3
    with pymupdf.open(ROOT/"data"/"public-regulatory"/NETWORK) as pdf:
        sas=re.sub(r"\s+","",pdf[361].get_text()).lower()
        assert "sbilanciamentoattesodelsistema" in sas
    with pymupdf.open(ROOT/"data"/"public-regulatory"/STORAGE) as pdf:
        flow=re.sub(r"\s+","",pdf[180].get_text()).lower()
        assert "positivoseiniettato,negativoseerogato" in flow


def test_contextual_guide_changes_reference_without_requesting_sources(monkeypatch):
    import requests
    def forbidden(*args,**kwargs):raise AssertionError("La guida è locale.")
    monkeypatch.setattr(requests.Session,"request",forbidden)
    app=AppTest.from_string("from gasops_app.bso_reference import render_terms\nrender_terms('settlement','term')").run()
    assert not app.exception
    assert any("PDF p. 370" in caption.value for caption in app.caption)
    app.selectbox(key="term").set_value("storage").run()
    assert not app.exception
    assert any("HS1" in caption.value and "181" in caption.value for caption in app.caption)
    assert any("iniezione è positiva" in text.value for text in app.markdown)


def test_hs1_standard_time_is_distinct_from_transport_local_time():
    at=datetime(2026,7,12,4,30,tzinfo=timezone.utc)
    assert closed_gas_day(at)==date(2026,7,11)
    assert closed_hs1_day(at)==date(2026,7,10)
