"""Session-only, PDF-grounded document workspace."""
import json
import os
from pathlib import Path

import streamlit as st

from .data import ROOT
from .document_desk import build, identity, search, searchable_pages, bookmark, page_text, extend_uploads, MAX_RESULTS, MAX_TOTAL_BYTES
from .regulatory import read_local_pdfs, MAX_DOCUMENTS, MAX_PDF_BYTES
from .visuals import info
from .session import reasoner
from .document_rag import answer, MAX_PASSAGES
from .supervisor import ModelUnavailable

STATE="document_desk_v1"
UPLOADS="document_archive_uploads_v2"
UPLOAD_EPOCH="document_archive_uploader_epoch"
UPLOAD_NOTICE="document_archive_notice"


def _remove_upload(digest):
    st.session_state[UPLOADS]=tuple((name,data) for name,data in st.session_state.get(UPLOADS,())
                                    if identity(((name,data),))[0][1]!=digest)
    st.session_state[UPLOAD_EPOCH]=st.session_state.get(UPLOAD_EPOCH,0)+1
    st.session_state[UPLOAD_NOTICE]=("Documento rimosso dall’archivio.",[],[])


def _update_index(inputs,docs=None):
    key=identity(inputs)
    cached=st.session_state.get(STATE)
    if cached and cached["identity"]==key:
        return cached
    if docs is None:
        with st.spinner("Lettura e indicizzazione dei PDF…"):
            docs=build(inputs)
    # Preserve bookmarks for unchanged document editions only. Search/RAG
    # results and previews must be regenerated against the updated index.
    editions={(name,pdf.digest) for name,pdf in docs.documents.items()}
    refs=[item for item in (cached or {}).get("reference_list",[])
          if (item["document"],item["sha256"]) in editions]
    cached={"identity":key,"docs":docs,"reference_list":refs}
    st.session_state[STATE]=cached
    return cached


def _archive():
    directory=Path(os.environ.get("GASOPS_PDF_DIR") or ROOT/"data"/"regulatory")
    try:
        local=read_local_pdfs(directory)
    except OSError:
        local=()
        st.warning("Archivio predisposto sul server non leggibile.")
    if UPLOADS not in st.session_state:
        # Recover still-available PDFs from the earlier session index, if any.
        # The uploader is not the source of truth and is never rehydrated.
        previous=st.session_state.get(STATE,{})
        docs=previous.get("docs")
        local_hashes={digest for _,digest in identity(local)}
        st.session_state[UPLOADS]=tuple((pdf.name,pdf.data) for pdf in docs.documents.values()
                                       if pdf.digest not in local_hashes) if docs else ()
    existing=st.session_state[UPLOADS]
    st.subheader("I tuoi documenti")
    st.caption("I PDF caricati restano disponibili mentre navighi nell’app. La raccolta è privata alla sessione, non un archivio permanente.")
    epoch=st.session_state.get(UPLOAD_EPOCH,0)
    uploaded=st.file_uploader("Aggiungi PDF",type=["pdf"],accept_multiple_files=True,key=f"desk_pdf_upload_{epoch}",
                              help="PDF con testo selezionabile, fino a 24 MB per file. Solo documenti pubblici o autorizzati.")
    if uploaded:
        additions=[]
        rejected=[]
        size=0
        for item in uploaded:
            if item.size>MAX_PDF_BYTES or size+item.size>MAX_TOTAL_BYTES or len(additions)>=MAX_DOCUMENTS:
                rejected.append(f"{item.name} · limite di caricamento superato.")
                continue
            additions.append((item.name,item.getvalue()))
            size+=item.size
        try:
            with st.spinner("Aggiunta dei documenti all’archivio…"):
                retained,docs,notices=extend_uploads(existing,tuple(additions),local)
            cached=_update_index((*retained,*local),docs)
            st.session_state[UPLOADS]=retained
            count=len(retained)-len(existing)
            st.session_state[UPLOAD_NOTICE]=(f"{count} PDF aggiunti all’archivio." if count else "",
                                             rejected+notices,docs.errors if cached["docs"] is not docs else [])
        except (ValueError,RuntimeError):
            st.session_state[UPLOAD_NOTICE]=("",rejected+["Caricamento non completato. I PDF precedenti sono conservati."],[])
        # A fresh uploader accepts incremental additions and cannot re-add a
        # removed file. Only the independent archive survives navigation.
        st.session_state[UPLOAD_EPOCH]=epoch+1
        st.rerun()
    cached=_update_index((*st.session_state[UPLOADS],*local))
    docs=cached["docs"]
    message,notices,errors=st.session_state.pop(UPLOAD_NOTICE,("",[],[]))
    if message:
        st.success(message)
    for warning in dict.fromkeys([*notices,*errors,*docs.errors]):
        st.warning(warning)
    if docs.documents:
        coverage=searchable_pages(docs)
        own={digest for _,digest in identity(st.session_state[UPLOADS])}
        st.caption(f"{len(docs.documents)} PDF · {sum(coverage.values())} / {sum(p.pages for p in docs.documents.values())} pagine con testo")
        with st.container(border=True,key="panel_document_archive"):
            for name,pdf in docs.documents.items():
                label,actions=st.columns([3,1.45],vertical_alignment="center")
                with label:
                    st.text(pdf.name)
                    st.caption(f"{pdf.pages} pagine · {len(pdf.data)/1024/1024:.2f} MB · "+
                               ("Caricato nella sessione" if pdf.digest in own else "Predisposto sul server"))
                    if coverage[name]<pdf.pages:
                        st.caption(f"Testo estraibile in {coverage[name]} pagine.")
                with actions:
                    with st.popover("Azioni",icon=":material/more_horiz:"):
                        st.download_button("Scarica PDF",pdf.data,pdf.name,"application/pdf",key="desk_download_"+pdf.digest,
                                           icon=":material/download:",on_click="ignore")
                        st.caption("SHA-256")
                        st.text(pdf.digest)
                        if pdf.digest in own:
                            st.button("Rimuovi PDF",key="desk_remove_"+pdf.digest,
                                      icon=":material/delete:",on_click=_remove_upload,args=(pdf.digest,))
                        else:
                            st.caption("Documento predisposto sul server.")
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


def _ask(cached):
    docs=cached["docs"]
    model=reasoner()
    st.caption("Risposta basata sui soli PDF selezionati, con citazioni testuali controllate.")
    if model is None:
        st.info("AI non selezionata. Scegli il modello nel menu laterale; la ricerca nei PDF funziona comunque.")
    else:
        st.caption("Modello: "+model.config.model+(" · locale sul server" if model.config.local else " · provider remoto"))
    with st.form("desk_rag",border=False):
        question=st.text_area("Fai una domanda ai documenti",placeholder="Quali sono le condizioni per il calcolo del corrispettivo di sbilanciamento?",max_chars=600,height=95)
        scope=st.selectbox("Documento",["Tutti i PDF",*docs.documents],key="desk_rag_doc")
        consent=False
        if model and not model.config.local:
            st.warning("Non usare documenti riservati. La domanda e fino a sei estratti pertinenti saranno inviati al provider AI, non il PDF completo.")
            consent=st.checkbox("Autorizzo l’invio della domanda e degli estratti di documenti pubblici o autorizzati.",key="desk_rag_consent")
        submit=st.form_submit_button("Chiedi ai documenti",type="primary",width="stretch",disabled=model is None)
    if submit:
        cached.pop("rag",None)
        cached.pop("desk_rag_preview",None)
        st.session_state.pop("desk_rag_hit",None)
        if not question.strip():
            st.warning("Scrivi una domanda.")
        elif model and not model.config.local and not consent:
            st.warning("Autorizzazione necessaria per usare un provider remoto. Puoi usare Cerca senza inviare dati.")
        elif model:
            hits=search(docs,question,document=None if scope=="Tutti i PDF" else scope,limit=MAX_PASSAGES)
            claims,notice=[],None
            if hits:
                with st.spinner("Lettura degli estratti e verifica delle citazioni…"):
                    try:
                        claims=answer(model,question,hits,authorized_remote=consent)
                    except ModelUnavailable as error:
                        notice=str(error)
                    except Exception:
                        notice="Risposta AI non disponibile o citazioni non verificabili. Consulta gli estratti."
            cached["rag"]={"question":question,"scope":scope,"model":model.config.model,
                           "hits":hits,"claims":claims,"notice":notice}
    saved=cached.get("rag")
    if not saved:
        return
    st.caption("Ultima domanda · "+saved["model"]+" · "+saved["scope"])
    st.text(saved["question"])
    if saved["notice"]:
        st.warning(saved["notice"])
    if saved["claims"]:
        st.subheader("Risposta AI")
        for item in saved["claims"]:
            citation=item["citation"]
            with st.container(border=True):
                st.text(item["text"])
                st.caption(citation.document+f" · PDF p. {citation.page}")
                st.text("«"+citation.evidence+"»")
        st.caption("Citazioni testuali controllate; interpretazione e pertinenza da verificare sulla pagina originale.")
    elif not saved["notice"]:
        st.info("Riscontri insufficienti per una risposta AI. Nessuna conclusione generata.")
    st.subheader("Passaggi consultati")
    _results(cached,saved["hits"],"desk_rag")


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
    st.caption("Cerca, interroga e confronta i tuoi PDF.")
    info("Info archivio","La ricerca mostra testo estratto dalle pagine dei PDF presenti, non note precompilate. Le corrispondenze per parole chiave non sono un parere legale.",
         "Usa solo copie pubbliche o autorizzate. I PDF restano disponibili durante la navigazione nella stessa sessione; una nuova sessione o un riavvio possono azzerare la raccolta. Scarica gli originali per conservarli. I PDF non entrano nel bollettino; la ricerca è sul server. Con Chiedi all’AI, soltanto la domanda e gli estratti sono inviati al modello selezionato, previo consenso per provider remoti. Non caricare documenti riservati su un deployment pubblico. Nessun OCR. La vigenza delle edizioni non è verificata.")
    cached=_archive()
    if not cached["docs"].documents:
        st.info("Aggiungi almeno un PDF per iniziare. Non vengono mostrati rilievi o citazioni in assenza di documenti.")
        return
    action=st.radio("Strumento",["Cerca","Chiedi all’AI","Leggi PDF","Confronta","Riferimenti salvati"],
                    horizontal=True,label_visibility="collapsed",key="desk_mode")
    if action=="Cerca":
        _search(cached)
    elif action=="Chiedi all’AI":
        _ask(cached)
    elif action=="Leggi PDF":
        _read(cached)
    elif action=="Confronta":
        _compare(cached)
    else:
        _references(cached)
