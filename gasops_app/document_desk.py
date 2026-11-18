"""PDF-only retrieval for the document desk; no network or built-in findings."""
from hashlib import sha256
from pathlib import Path
import re

import pymupdf

from .models import Citation
from .regulatory import Library, MAX_DOCUMENTS, MAX_PDF_BYTES, MAX_PAGES, Pdf

MAX_TOTAL_BYTES=64*1024*1024
MAX_TOTAL_PAGES=2000
MAX_RESULTS=12
STOP=set("a ad al alla alle allo ai agli anche che chi come con cosa da dal dalla dei del della delle di e è ed gli i il in la le lo ne nel nella non o per quale quali quando quanto se si sono su sul tra un una uno the an and of is are what how".split())


def identity(inputs):
    return tuple((Path(name).name,sha256(data).hexdigest()) for name,data in inputs)


def build(inputs):
    """Check aggregate limits before extraction; deduplicate the same bytes."""
    accepted=[]
    errors=[]
    seen=set()
    size=pages=0
    for name,data in inputs:
        name=Path(name).name
        digest=sha256(data).hexdigest()
        if digest in seen:
            continue
        seen.add(digest)
        if len(accepted)>=MAX_DOCUMENTS:
            errors.append(f"{name} · limite di {MAX_DOCUMENTS} documenti raggiunto.")
            continue
        if len(data)>MAX_PDF_BYTES or not data.startswith(b"%PDF-"):
            errors.append(f"{name} · PDF non valido o superiore a 24 MB.")
            continue
        try:
            with pymupdf.open(stream=data,filetype="pdf") as doc:
                if doc.needs_pass or not 1<=len(doc)<=MAX_PAGES:
                    raise ValueError("PDF protetto o numero di pagine non supportato.")
                count=len(doc)
        except (ValueError,RuntimeError) as error:
            errors.append(f"{name} · PDF non leggibile o protetto.")
            continue
        if size+len(data)>MAX_TOTAL_BYTES or pages+count>MAX_TOTAL_PAGES:
            errors.append(f"{name} · limite complessivo (64 MB / 2.000 pagine) superato.")
            continue
        accepted.append((name,data))
        size+=len(data)
        pages+=count
    library=Library(tuple(accepted),include_notes=False)
    library.errors[:0]=errors
    return library


def extend_uploads(existing, additions, local=()):
    """Append validated uploads without replacing earlier documents.

    Uploads have priority over server-provided PDFs, as in the original desk.
    Invalid and duplicate files are never retained as session uploads.
    """
    candidates=list(existing)
    known={digest for _,digest in identity((*existing,*local))}
    total=sum(len(data) for _,data in existing)
    notices=[]
    for name,data in additions:
        name=Path(name).name
        digest=sha256(data).hexdigest()
        if digest in known:
            notices.append(f"{name} · già presente nell’archivio.")
            continue
        if len(data)>MAX_PDF_BYTES or not data.startswith(b"%PDF-"):
            notices.append(f"{name} · PDF non valido o superiore a 24 MB.")
            continue
        if len(candidates)>=MAX_DOCUMENTS or total+len(data)>MAX_TOTAL_BYTES:
            notices.append(f"{name} · spazio dell’archivio insufficiente. Rimuovi un documento e riprova.")
            continue
        candidates.append((name,data))
        known.add(digest)
        total+=len(data)
    library=build((*candidates,*local))
    accepted={pdf.digest for pdf in library.documents.values()}
    # Never commit an update that would lose a previously stored upload.
    if any(digest not in accepted for _,digest in identity(existing)):
        raise ValueError("Aggiornamento non completato. I documenti precedenti sono conservati.")
    retained=tuple((name,data) for name,data in candidates if sha256(data).hexdigest() in accepted)
    return retained,library,notices


def page_text(pdf:Pdf,page:int):
    if not 1<=page<=pdf.pages:
        raise ValueError("Pagina fuori intervallo.")
    with pymupdf.open(stream=pdf.data,filetype="pdf") as doc:
        return " ".join(doc[page-1].get_text(sort=True).split())


def searchable_pages(library):
    pages={name:set() for name in library.documents}
    for item in library.passages:
        if item.is_pdf and item.citation.document in pages:
            pages[item.citation.document].add(item.citation.page)
    return {name:len(found) for name,found in pages.items()}


def search(library,query,mode="keywords",document=None,limit=MAX_RESULTS):
    if document is not None and document not in library.documents:
        return []
    query=" ".join(query.strip().split())[:600]
    if not query:
        return []
    limit=max(1,min(int(limit),MAX_RESULTS))
    if mode=="keywords":
        # Avoid matches due entirely to question filler; never inject offline aliases.
        tokens=[t for t in re.findall(r"[\w-]+",query) if len(t)>=2 and t.casefold() not in STOP]
        if not tokens:
            return []
        return [hit.citation for hit in library.search(" ".join(tokens),limit=limit,
                    document=document,expand_aliases=False)
                if hit.is_pdf and hit.citation.document in library.documents]
    if mode!="exact":
        raise ValueError("Modalità di ricerca non valida.")
    # Search normalized full-page text, not individual chunks. No OCR or
    # cross-page match, preserves original extracted spelling in snippets.
    pattern=re.compile(re.escape(query),re.IGNORECASE)
    results=[]
    for name,pdf in library.documents.items():
        if document is not None and name!=document:
            continue
        with pymupdf.open(stream=pdf.data,filetype="pdf") as doc:
            for page in doc:
                source=" ".join(page.get_text(sort=True).split())
                match=pattern.search(source)
                if match:
                    begin=max(0,match.start()-230)
                    end=min(len(source),match.end()+350)
                    results.append(Citation(document=name,page=page.number+1,
                         evidence=("…" if begin else "")+source[begin:end]+("…" if end<len(source) else "")))
                    if len(results)>=limit:
                        return results
    return results


def bookmark(library,citation):
    pdf=library.documents.get(citation.document)
    if pdf is None or not citation.page or not 1<=citation.page<=pdf.pages:
        raise ValueError("Riferimento non presente nell’archivio.")
    return {"document":citation.document,"sha256":pdf.digest,"page":citation.page,
            "excerpt":citation.evidence}
