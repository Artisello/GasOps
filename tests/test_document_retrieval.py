"""Offline hybrid retrieval regressions using real generated PDF pages."""
import pymupdf
import pytest

from gasops_app.document_desk import build,search,page_text,STOP
from gasops_app.document_retrieval import score,references
from gasops_app.assistant_lookup import ranked_document_hits
from gasops_app.models import Citation


def pdf(*texts):
    with pymupdf.open() as doc:
        for text in texts:
            page=doc.new_page()
            page.insert_textbox(pymupdf.Rect(40,40,550,790),text,fontsize=10)
        return doc.tobytes()


def test_synonym_retrieves_actual_original_excerpt():
    docs=build((("rules.pdf",pdf("The security deposit shall be returned within thirty days.",
                                 "The gas supply is measured in energy units.")),))
    hits=search(docs,"deposito cauzionale",mode="hybrid")
    assert hits and hits[0].page==1
    assert "security deposit" in hits[0].evidence
    assert hits[0].evidence in page_text(docs.documents[hits[0].document],1)
    assert search(docs,"deposito cauzionale",mode="exact")==[]


def test_literal_reference_restricts_results_and_does_not_infer_subsections():
    docs=build((("rules.pdf",pdf("Articolo 9. Il preavviso è richiesto.",
                                 "Articolo 9.1 Il preavviso è richiesto.",
                                 "Articolo 19. Il preavviso è richiesto.")),))
    hits=search(docs,"Articolo 9 preavviso",mode="hybrid")
    assert [h.page for h in hits]==[1]
    assert references("Articolo 9.1")=={("article","9.1")}
    assert references("Cap. 9 §4.4.2")=={("chapter","9"),("section","4.4.2")}


def test_page_and_document_filter_preserve_provenance():
    docs=build((("a.pdf",pdf("La cauzione è richiesta.","La cauzione è restituita.")),
                ("b.pdf",pdf("La cauzione è richiesta.","La cauzione resta valida."))))
    name=next(iter(docs.documents))
    hits=search(docs,"deposito cauzionale pagina 2",mode="hybrid",document=name)
    assert hits and all(h.document==name and h.page==2 for h in hits)
    assert search(docs,"deposito cauzionale pagina 99",mode="hybrid")==[]


def test_unknown_query_does_not_return_unrelated_title_or_notes():
    docs=build((("quasar.pdf",pdf("La fornitura di gas è misurata.")),))
    assert search(docs,"quasar",mode="hybrid")==[]
    assert search(docs,"quale come cosa",mode="hybrid")==[]
    assert search(docs,"neutrini cosmici",mode="hybrid")==[]


def test_cross_archive_results_deduplicate_copies_not_revisions():
    a=build((("rules.pdf",pdf("La cauzione è restituita.")),))
    b=build((("rules.pdf",pdf("La cauzione non è restituita.")),))
    hits=ranked_document_hits([a,a,b],"deposito cauzionale",6)
    assert len(hits)==2 and len({h.document for h in hits})==2
    assert all(h.page==1 for h in hits)


def test_reference_and_title_cannot_substitute_for_passage():
    hit=Citation(document="Articolo 9 preavviso.pdf",page=1,evidence="Articolo 19. Il preavviso è richiesto.")
    assert score("Articolo 9 preavviso",hit,STOP) is None
