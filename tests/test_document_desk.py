import pymupdf
from gasops_app.document_desk import build,search,searchable_pages,bookmark,page_text


def pdf(*texts):
    with pymupdf.open() as doc:
        for text in texts:
            page=doc.new_page()
            page.insert_textbox(pymupdf.Rect(40,40,550,790),text,fontsize=10)
        return doc.tobytes()


def test_empty_desk_never_returns_preloaded_notes():
    library=build(())
    assert not library.documents and not library.passages
    assert search(library,"sette giorni mancata discarica")==[]


def test_search_pdf_only_and_scope():
    a=pdf("Il corrispettivo giornaliero di trasporto.", "Garanzia economica e deposito cauzionale.")
    b=pdf("Il corrispettivo mensile di trasporto.")
    library=build((("a.pdf",a),("b.pdf",b),("duplicato.pdf",a)))
    assert len(library.documents)==2
    names=list(library.documents)
    assert searchable_pages(library)=={names[0]:2,names[1]:1}
    results=search(library,"corrispettivo giornaliero",mode="exact")
    assert len(results)==1 and results[0].page==1 and results[0].document==names[0]
    assert search(library,"corrispettivo giornaliero",mode="exact",document=names[1])==[]
    assert search(library,"Quale garanzia economica?",document=names[0])[0].page==2
    saved=bookmark(library,results[0])
    assert saved["sha256"]==library.documents[names[0]].digest
    assert "giornaliero" in page_text(library.documents[names[0]],1)


def test_invalid_pdf_and_exact_boundary():
    words=" ".join(["termine"]*118+["frase","di","prova"]+["termine"]*30)
    raw=pdf(words)
    library=build((("bad.pdf",b"not pdf"),("test.pdf",raw)))
    assert library.errors and len(library.documents)==1
    assert search(library,"frase di prova",mode="exact")[0].page==1
    assert search(library,"termine assente impossibile",mode="exact")==[]



def test_archive_appends_uploads_and_deduplicates_by_bytes():
    from gasops_app.document_desk import extend_uploads
    a=pdf("Garanzia economica con deposito cauzionale.")
    b=pdf("Prezzo di sbilanciamento determinato dal mercato.")
    saved,library,notices=extend_uploads((),(("norme.pdf",a),))
    assert saved==(("norme.pdf",a),)
    assert len(library.documents)==1
    saved,library,notices=extend_uploads(saved,(("copia.pdf",a),("norme.pdf",b),("bad.pdf",b"bad")))
    assert saved==(("norme.pdf",a),("norme.pdf",b))
    assert len(library.documents)==2
    assert any("già presente" in n for n in notices)
    assert any("non valido" in n for n in notices)
    assert search(library,"garanzia economica")
    assert search(library,"prezzo di sbilanciamento")


def test_archive_invalid_second_upload_retains_first_and_server_file():
    from gasops_app.document_desk import extend_uploads
    a=pdf("Regole delle garanzie economiche.")
    b=pdf("Il prezzo del gas naturale.")
    saved,library,_=extend_uploads((("a.pdf",a),),(("bad.pdf",b"%PDF-broken"),),(("b.pdf",b),))
    assert saved==(("a.pdf",a),)
    assert len(library.documents)==2
    assert library.errors
