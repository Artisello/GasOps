"""Session-only, PDF-grounded document workspace."""
import json
import os
from pathlib import Path

import streamlit as st

from .data import ROOT
from .document_desk import build, identity, search, searchable_pages, bookmark, page_text, MAX_RESULTS, MAX_TOTAL_BYTES
from .regulatory import read_local_pdfs, MAX_DOCUMENTS, MAX_PDF_BYTES
from .visuals import info

STATE="document_desk_v1"


def _archive():
    directory=Path(os.environ.get("GASOPS_PDF_DIR") or ROOT/"data"/"regulatory")
    try:
        local=read_local_pdfs(directory)
    except OSError:
        local=()
        st.warning("Archivio predisposto sul server non leggibile.")
    # Upload first, so shared files cannot silently crowd out the user's files.
    uploaded=st.file_uploader("Aggiungi PDF",type=["pdf"],accept_multiple_files=True,key="desk_pdf_upload",
                              help="PDF con testo selezionabile, fino a 24 MB per file. Solo documenti pubblici o autorizzati.")
    inputs=[]
    total=0
    for item in uploaded or []:
        if item.size>MAX_PDF_BYTES or total+item.size>MAX_TOTAL_BYTES or len(inputs)>=MAX_DOCUMENTS:
            st.warning("Alcuni PDF caricati superano i limiti dell’archivio; non sono stati indicizzati.")
            continue
        inputs.append((item.name,item.getvalue()))
        total+=item.size
    inputs=tuple(inputs)+local
    key=identity(inputs)
    cached=st.session_state.get(STATE)
    if not cached or cached["identity"]!=key:
        with st.spinner("Lettura e indicizzazione dei PDF…"):
            docs=build(inputs)
        # Prevent earlier search output being displayed for a different edition.
        cached={"identity":key,"docs":docs,"reference_list":[]}
        st.session_state[STATE]=cached
    docs=cached["docs"]
    for warning in docs.errors:
        st.warning(warning)
    if docs.documents:
        coverage=searchable_pages(docs)
        st.caption(f"{len(docs.documents)} PDF · {sum(coverage.values())} / {sum(p.pages for p in docs.documents.values())} pagine con testo")
        with st.expander("Archivio e versioni"):
            for name,pdf in docs.documents.items():
                st.text(name)
                st.caption(f"{coverage[name]}/{pdf.pages} pagine con testo · SHA-256 {pdf.digest[:12]}…")
                if coverage[name]<pdf.pages:
                    st.caption("Alcune pagine non contengono testo estraibile: potrebbero includere immagini o tabelle.")
                st.download_button("Scarica PDF",pdf.data,pdf.name,"application/pdf",key="desk_download_"+pdf.digest,
                                   icon=":material/download:")
    return cached


def _preview(pdf,page,label):
    try:
        image=pdf.render(page)
        st.image(image,caption=f"{pdf.name} · pagina PDF {page}",width=690)
        with st.expander("Testo estratto dalla pagina"):
            text=page_text(pdf,page)
            st.text(text or "Nessun testo estraibile in questa pagina.")
    except (ValueError,RuntimeError,IndexError) as error:
        st.warning("Impossibile visualizzare la pagina selezionata.")


def _save(cached,citation):
    item=bookmark(cached["docs"],citation)
    refs=cached["reference_list"]
    if any(x["sha256"]==item["sha256"] and x["page"]==item["page"] and x["excerpt"]==item["excerpt"] for x in refs):
        st.caption("Riferimento già salvato.")
    elif len(refs)>=100:
        st.warning("Limite di 100 riferimenti raggiunto. Esporta e svuota la raccolta.")
    else:
        refs.append(item)
        st.caption("Riferimento salvato nella sessione.")


def _results(cached,hits,prefix,*,allow_preview=True):
    if not hits:
        st.info("Nessun passaggio trovato. Prova parole diverse o la ricerca esatta.")
        return
    st.caption(f"{len(hits)} pagine pertinenti mostrate (massimo {MAX_RESULTS}).")
    for hit in hits:
        with st.container(border=True):
            st.text(hit.document+f" · PDF p. {hit.page}")
            st.text(hit.evidence)
    if allow_preview:
        index=st.selectbox("Seleziona un riferimento",range(len(hits)),
                           format_func=lambda i:f"{hits[i].document} · p. {hits[i].page}",key=prefix+"_hit")
        hit=hits[index]
        a,b=st.columns(2)
        with a:
            if st.button("Apri pagina originale",key=prefix+"_open",icon=":material/description:"):
                cached[prefix+"_preview"]=(hit.document,hit.page)
        with b:
            if st.button("Salva riferimento",key=prefix+"_save",icon=":material/bookmark_add:"):
                _save(cached,hit)
        if cached.get(prefix+"_preview")== (hit.document,hit.page):
            _preview(cached["docs"].documents[hit.document],hit.page,prefix)


def _mode_label(mode):
    return "Parole chiave" if mode=="keywords" else "Frase esatta"


def _search(cached):
    docs=cached["docs"]
    with st.form("desk_search",border=False):
        query=st.text_input("Cosa vuoi cercare?",placeholder="Es. corrispettivo di sbilanciamento",max_chars=600)
        a,b=st.columns(2)
        document=a.selectbox("Documento",["Tutti i PDF",*docs.documents])
        mode=b.selectbox("Tipo di ricerca",["keywords","exact"],format_func=_mode_label)
        submitted=st.form_submit_button("Cerca nei PDF",type="primary",width="stretch",icon=":material/search:")
    if submitted:
        cached.pop("desk_search_result",None)
        cached.pop("desk_search_preview",None)
        st.session_state.pop("desk_search_hit",None)
        if not query.strip():
            st.warning("Inserisci un termine o una frase.")
        else:
            with st.spinner("Ricerca nei documenti…"):
                hits=search(docs,query,mode,None if document=="Tutti i PDF" else document)
            cached["desk_search_result"]=(query,document,mode,hits)
    saved=cached.get("desk_search_result")
    if saved:
        query,document,mode,hits=saved
        st.caption("Ultima ricerca · "+_mode_label(mode))
        st.text(query+" · "+document)
        _results(cached,hits,"desk_search")


def _read(cached):
    docs=cached["docs"]
    selected=st.selectbox("Documento",list(docs.documents),key="desk_read_doc")
    pdf=docs.documents[selected]
    page=st.number_input("Pagina PDF",min_value=1,max_value=pdf.pages,
                         value=1,step=1,key="desk_read_page_"+pdf.digest)
    if st.button("Visualizza pagina",type="primary",key="desk_read_open",icon=":material/description:"):
        cached["read_page"]=(pdf.digest,int(page))
    if cached.get("read_page")== (pdf.digest,int(page)):
        _preview(pdf,int(page),"read")


def _compare(cached):
    docs=cached["docs"]
    names=list(docs.documents)
    if len(names)<2:
        st.info("Aggiungi almeno due PDF per confrontare la stessa materia in documenti diversi.")
        return
    with st.form("desk_compare",border=False):
        a,b=st.columns(2)
        first=a.selectbox("Documento A",names,index=0)
        second=b.selectbox("Documento B",names,index=1)
        query=st.text_input("Tema o frase da confrontare",placeholder="Es. garanzie",max_chars=600)
        mode=st.radio("Ricerca",["keywords","exact"],format_func=_mode_label,horizontal=True)
        submitted=st.form_submit_button("Confronta passaggi",type="primary",width="stretch")
    if submitted:
        cached.pop("comparison",None)
        for prefix in ("desk_cmp_a","desk_cmp_b"):
            cached.pop(prefix+"_preview",None)
            st.session_state.pop(prefix+"_hit",None)
        if first==second or not query.strip():
            st.warning("Scegli due documenti differenti e inserisci un tema.")
        else:
            with st.spinner("Ricerca nei due PDF…"):
                hits_a=search(docs,query,mode,first,limit=4)
                hits_b=search(docs,query,mode,second,limit=4)
            cached["comparison"]=(query,first,second,hits_a,hits_b)
    if "comparison" in cached:
        query,first,second,hits_a,hits_b=cached["comparison"]
        st.text("Confronto: "+query)
        st.caption("Passaggi affiancati, non verifica automatica delle modifiche normative.")
        a,b=st.columns(2)
        for col,name,hits,prefix in ((a,first,hits_a,"desk_cmp_a"),(b,second,hits_b,"desk_cmp_b")):
            with col:
                st.text(name)
                _results(cached,hits,prefix)


def _references(cached):
    items=cached["reference_list"]
    if not items:
        st.caption("Salva un passaggio dalla ricerca o dal confronto.")
        return
    st.caption(f"{len(items)} riferimenti · conservati soltanto in questa sessione.")
    for r in items:
        st.text(r["document"]+f" · PDF p. {r['page']}")
        st.text(r["excerpt"])
    st.download_button("Esporta riferimenti JSON",json.dumps(items,ensure_ascii=False,indent=2),
                       "gasops-riferimenti.json","application/json",key="desk_refs_export")
    if st.button("Svuota raccolta",key="desk_refs_clear"):
        items.clear()
        st.rerun()


def document_page():
    st.title("Norme e documenti")
    st.caption("Cerca, leggi e confronta i tuoi PDF. Nessuna ricerca web o risposta AI in questa vista.")
    info("Info archivio","La ricerca mostra testo estratto dalle pagine dei PDF presenti, non note precompilate. Le corrispondenze per parole chiave non sono un parere legale.",
         "Usa solo copie pubbliche o autorizzate. I PDF caricati qui rimangono nella memoria della sessione del server e non sono inviati a provider AI o al bollettino. Nessun OCR. La vigenza delle edizioni non è verificata.")
    cached=_archive()
    if not cached["docs"].documents:
        st.info("Aggiungi almeno un PDF per iniziare. Non vengono mostrati rilievi o citazioni in assenza di documenti.")
        return
    action=st.radio("Strumento",["Cerca","Leggi PDF","Confronta","Riferimenti salvati"],
                    horizontal=True,label_visibility="collapsed",key="desk_mode")
    if action=="Cerca":
        _search(cached)
    elif action=="Leggi PDF":
        _read(cached)
    elif action=="Confronta":
        _compare(cached)
    else:
        _references(cached)
