"""Shared persistent archive and independent visitor-only PDF workspaces."""
import json
import os
import re
from threading import Lock
from pathlib import Path

import streamlit as st

from .data import ROOT
from .document_desk import build, identity, search, searchable_pages, bookmark, page_text, extend_uploads, MAX_RESULTS, MAX_TOTAL_BYTES
from .regulatory import read_local_pdfs, MAX_DOCUMENTS, MAX_PDF_BYTES, REGISTER, registered_case, matching_edition
from .visuals import info, header
from .session import reasoner
from .document_rag import answer, MAX_PASSAGES
from .review_register import KEY as REVIEW_KEY, LIMIT as REVIEW_LIMIT, STATUSES, valid_cases, register, decide, export_json, export_markdown
from .supervisor import ModelUnavailable
from .document_archive import Archive, ArchiveConfig, ArchiveError, display_name
from .access import document_directory, private_access, require_private

STATE="document_desk_v1"
VISITOR_STATE="document_visitor_index_v1"
VISITOR_UPLOADS="document_visitor_uploads_v1"
VISITOR_NOTICE="document_visitor_notice_v1"
SCOPE="document_archive_scope"
NEXT_SCOPE="document_archive_next_scope"
ADMIN="gasops_document_admin"
NOTICE="gasops_document_notice"
WRITE_LOCK=Lock()


def _archive_config():
    def value(name):
        try:
            return str(st.secrets.get(name) or os.environ.get(name,"")).strip()
        except (FileNotFoundError,KeyError):
            return os.environ.get(name,"").strip()
    url,key,admin=(value(k) for k in ("GASOPS_DOCUMENTS_URL","GASOPS_DOCUMENTS_KEY","GASOPS_DOCUMENTS_ADMIN_ID"))
    contributors=tuple(v.strip() for v in value("GASOPS_DOCUMENTS_CONTRIBUTOR_IDS").split(",") if v.strip())
    if not any((url,key,admin,contributors)):
        return None
    return ArchiveConfig(url.rstrip("/"),key,admin,contributors)


@st.cache_resource(ttl=300,max_entries=8,show_spinner=False)
def _read_remote_pdf(config,key):
    # Immutable, content-addressed public object. Never cache admin tokens or visitor PDFs.
    return Archive(config).read_document(key)


@st.cache_resource(ttl=30,max_entries=1,show_spinner=False)
def _read_remote(config):
    # Refresh the manifest, not every unchanged PDF. Legacy names cannot be
    # assumed immutable and are fetched again. Removed keys are never returned.
    archive=Archive(config)
    return archive.read(reader=lambda key:_read_remote_pdf(config,key)
                        if re.fullmatch(r"[a-f0-9]{64}--.+\.pdf",key,re.I) and key[:64]==key[:64].lower()
                        else archive.read_document(key))


def _manifest(directory):
    """Cheap file identity; detect changes without reopening large PDFs."""
    entries=[]
    for path in sorted(directory.glob("*.pdf"))[:MAX_DOCUMENTS]:
        if not path.is_file():continue
        info=path.stat()
        if info.st_size<=MAX_PDF_BYTES:
            entries.append((path.name,info.st_size,info.st_mtime_ns,info.st_ctime_ns,info.st_ino,info.st_dev))
    return tuple(entries)


def _load_local(directory,manifest):
    result=read_local_pdfs(directory)
    if _manifest(directory)!=manifest:
        raise OSError("Archivio locale cambiato durante la lettura.")
    return result


@st.cache_resource(max_entries=1,show_spinner=False)
def _public_local(directory,manifest):
    return _load_local(directory,manifest)


def _local_inputs(directory,*,shared):
    if not shared:
        require_private()
    manifest=_manifest(directory)
    if shared:
        return _public_local(directory,manifest)
    # Explicit server override paths stay session-local.
    key=(directory,manifest)
    prior=st.session_state.get("document_local_snapshot_v2")
    if prior and prior[0]==key:return prior[1]
    inputs=_load_local(directory,manifest)
    st.session_state["document_local_snapshot_v2"]=(key,inputs)
    return inputs


@st.cache_resource(max_entries=1,show_spinner=False)
def _public_index(key,_inputs):
    # Library is read-only after construction: transform/search and rendering
    # open separate PDF handles; all mutable UI state stays in session_state.
    docs=build(_inputs)
    return docs,searchable_pages(docs)


def _public_snapshot(local,remote,*,shared):
    prior=st.session_state.get("document_public_snapshot_v2")
    if prior and prior[0] is local and prior[1] is remote:
        inputs,key=prior[2:]
    else:
        inputs=tuple((display_name(k),v) for k,v in remote)+local
        key=identity(inputs)
        st.session_state["document_public_snapshot_v2"]=(local,remote,inputs,key)
    return _update_index(inputs,key=key,shared=shared)


def _admin_panel(config,archive,local,remote):
    if not private_access() or not (config.admin_id or config.contributor_ids):
        return
    with st.expander("Pubblica nell’archivio condiviso"):
        saved=st.session_state.get(ADMIN)
        session=saved[1] if saved and saved[0]==config and saved[1].valid(config) else None
        if not session:
            st.session_state.pop(ADMIN,None)
            with st.form("document_admin_login",clear_on_submit=True):
                email=st.text_input("Email account autorizzato",max_chars=254)
                password=st.text_input("Password",type="password",max_chars=256)
                login=st.form_submit_button("Accedi")
                st.caption("Account I.G.O.R. autorizzato · nessun account GitHub richiesto.")
            if login:
                try:
                    st.session_state[ADMIN]=(config,archive.login(email,password))
                except ArchiveError as exc:
                    st.error(str(exc))
                else:
                    st.rerun()
            return
        if st.button("Esci dalla gestione",key="document_admin_logout"):
            st.session_state.pop(ADMIN,None)
            st.rerun()
        st.warning("I PDF pubblicati saranno accessibili a chiunque, anche tramite il loro URL. Solo documenti pubblici o con autorizzazione alla diffusione.")
        with st.form("document_publish",clear_on_submit=True):
            uploaded=st.file_uploader("Aggiungi PDF all’archivio pubblico",type=["pdf"],accept_multiple_files=True,
                                      help="Massimo 24 MB per file; 8 documenti, 64 MB e 2.000 pagine complessive.")
            authorized=st.checkbox("Confermo che tutti i PDF possono essere resi pubblici.")
            publish=st.form_submit_button("Pubblica documenti",type="primary")
        if publish:
            if not authorized or not uploaded:
                st.warning("Seleziona i PDF e conferma la pubblicazione.")
            elif len(uploaded)>MAX_DOCUMENTS or any(f.size>MAX_PDF_BYTES for f in uploaded) or sum(f.size for f in uploaded)>MAX_TOTAL_BYTES:
                st.warning("Limiti di caricamento superati.")
            else:
                try:
                    with WRITE_LOCK,st.spinner("Pubblicazione nell’archivio condiviso…"):
                        count,notes=archive.publish(session,tuple((f.name,f.getvalue()) for f in uploaded),local)
                    st.session_state[NOTICE]=(f"{count} PDF pubblicati.",notes)
                except (ArchiveError,ValueError,RuntimeError):
                    st.session_state[NOTICE]=("",["Pubblicazione non completata; verifica i PDF già salvati prima di riprovare."])
                finally:
                    _read_remote.clear()
                    _read_remote_pdf.clear()
                st.rerun()
        if remote and session.is_admin(config):
            labels={k:display_name(k) for k,_ in remote}
            with st.form("document_remove",clear_on_submit=True):
                key=st.selectbox("Documento da rimuovere",list(labels),format_func=labels.__getitem__)
                confirmation=st.checkbox("Confermo la rimozione dall’archivio pubblico.")
                remove=st.form_submit_button("Rimuovi documento")
            if remove:
                if not confirmation:
                    st.warning("Conferma la rimozione.")
                else:
                    try:
                        with WRITE_LOCK:
                            archive.remove(session,key)
                        st.session_state[NOTICE]=("Documento rimosso.",[])
                    except ArchiveError as exc:
                        st.session_state[NOTICE]=("",[str(exc)])
                    finally:
                        _read_remote.clear()
                        _read_remote_pdf.clear()
                    st.rerun()


def _update_index(inputs,docs=None,*,state_key=STATE,key=None,shared=False):
    key=identity(inputs) if key is None else key
    cached=st.session_state.get(state_key)
    if cached and cached["identity"]==key:
        if "coverage" not in cached:cached["coverage"]=searchable_pages(cached["docs"])
        return cached
    coverage=None
    if docs is None:
        with st.spinner("Lettura e indicizzazione dei PDF…"):
            if shared and state_key==STATE:
                docs,coverage=_public_index(key,inputs)
            else:
                docs=build(inputs)
    if coverage is None:coverage=searchable_pages(docs)
    # Preserve bookmarks for unchanged document editions only. Search/RAG
    # results and previews must be regenerated against the updated index.
    editions={(name,pdf.digest) for name,pdf in docs.documents.items()}
    refs=[item for item in (cached or {}).get("reference_list",[])
          if (item["document"],item["sha256"]) in editions]
    cases=valid_cases((cached or {}).get(REVIEW_KEY,[]),docs)
    cached={"identity":key,"docs":docs,"coverage":coverage,"reference_list":refs,REVIEW_KEY:cases}
    st.session_state[state_key]=cached
    return cached


def _visitor_upload_panel(*, has_public=False):
    """Never write visitor bytes to disk, shared cache, or the public bucket."""
    personal=st.session_state.get(VISITOR_UPLOADS,())
    message,notices=st.session_state.pop(VISITOR_NOTICE,("",[]))
    if message:
        st.success(message)
    for notice in notices:
        st.warning(notice)
    with st.expander("Carica PDF",expanded=not personal and not has_public):
        st.caption("Solo sessione · PDF pubblici o autorizzati, nessun dato riservato.")
        with st.form("document_visitor_add",clear_on_submit=True):
            files=st.file_uploader("Seleziona PDF",type=["pdf"],accept_multiple_files=True,
                help="8 PDF, massimo 24 MB per file, 64 MB e 2.000 pagine in totale; PDF con testo ricercabile.")
            submit=st.form_submit_button("Aggiungi ai miei PDF",type="primary")
        if submit:
            if not files:
                st.warning("Seleziona almeno un PDF.")
            elif len(files)>MAX_DOCUMENTS or any(f.size>MAX_PDF_BYTES for f in files) or sum(f.size for f in files)>MAX_TOTAL_BYTES:
                st.warning("Limiti di caricamento superati.")
            else:
                try:
                    with st.spinner("Indicizzazione dei PDF…"):
                        retained,docs,notes=extend_uploads(personal,tuple((f.name,f.getvalue()) for f in files))
                    added=len(retained)-len(personal)
                    st.session_state[VISITOR_UPLOADS]=retained
                    _update_index(retained,docs,state_key=VISITOR_STATE)
                    if retained:
                        st.session_state[NEXT_SCOPE]="I miei PDF"
                    st.session_state[VISITOR_NOTICE]=(f"{added} PDF aggiunti." if added else "",notes+docs.errors)
                    st.rerun()
                except (ValueError,RuntimeError):
                    st.warning("Importazione non completata. I PDF già caricati restano disponibili.")
        if personal:
            with st.form("document_visitor_remove",clear_on_submit=True):
                index=st.selectbox("Rimuovi dai miei PDF",range(len(personal)),format_func=lambda i:personal[i][0])
                remove=st.form_submit_button("Rimuovi")
            if remove:
                retained=tuple(item for i,item in enumerate(personal) if i!=index)
                st.session_state[VISITOR_UPLOADS]=retained
                _update_index(retained,state_key=VISITOR_STATE)
                st.session_state[VISITOR_NOTICE]=("PDF rimosso dalla sessione.",[])
                st.rerun()


def _archive(selected,scope_slot):
    # Keep the explicit public repository folder separate from ignored local PDFs.
    directory,shared=document_directory(ROOT)
    upload_slot=st.container()
    config=None
    try:
        config=_archive_config()
    except ValueError:
        st.warning("Configurazione archivio persistente non valida.")
    public_selected=selected=="Archivio pubblico"
    admin_saved=st.session_state.get(ADMIN)
    managing=bool(private_access() and config and admin_saved and admin_saved[0]==config and admin_saved[1].valid(config))
    local=remote=()
    if public_selected or managing:
        try:
            manifest=_manifest(directory)
            opened=st.session_state.get("document_local_opened_v1",False)
            if shared and manifest and not managing:
                if not opened:
                    st.caption(f"{len(manifest)} PDF pubblici disponibili · indicizzazione su richiesta")
                    opened=st.button("Apri PDF pubblici",key="document_local_open")
                    if opened:st.session_state["document_local_opened_v1"]=True
                if opened:local=_local_inputs(directory,shared=True)
            else:
                local=_local_inputs(directory,shared=shared)
        except OSError:
            st.warning("Archivio predisposto sul server non leggibile.")
    if config:
        archive=Archive(config)
        if public_selected or managing:
            prior=st.session_state.get("document_remote_snapshot_v1")
            remote=prior[1] if prior and prior[0]==config else ()
            if st.button("Aggiorna archivio pubblico",key="document_remote_refresh"):
                try:
                    clear=getattr(_read_remote,"clear",None)
                    if clear:clear()
                    remote=_read_remote(config)
                    st.session_state["document_remote_snapshot_v1"]=(config,remote)
                except ArchiveError as exc:
                    st.warning(str(exc)+" Ultima copia disponibile conservata.")
            if not prior:
                st.caption("Archivio remoto consultabile con Aggiorna archivio pubblico.")
            _admin_panel(config,archive,local,remote)
        else:
            # Login does not need any PDF. After authorization the management
            # path fetches the current archive before allowing mutation.
            _admin_panel(config,archive,(),())
    else:
        st.caption("Archivio remoto non configurato · caricamento personale disponibile.")
        with st.expander("Pubblicazione permanente · configurazione",expanded=False):
            st.write("Per rendere un PDF visibile a tutti anche dopo un riavvio serve l’archivio remoto. Gli utenti autorizzati potranno pubblicare qui senza accesso a GitHub.")
            st.markdown("[Configurazione archivio remoto](https://github.com/Artisello/GasOps#archivio-pubblico-persistente-supabase-storage)")
            st.caption("Solo per gestori del progetto: è ancora possibile predisporre PDF pubblici nel repository.")
            st.link_button("Apri cartella pubblica","https://github.com/Artisello/GasOps/tree/main/data/public-regulatory")
    with upload_slot:
        _visitor_upload_panel(has_public=bool(local or remote or (not public_selected and (config or directory.is_dir()))))
    message,notices=st.session_state.pop(NOTICE,("",[]))
    if message:
        st.success(message)
    for notice in notices:
        st.warning(notice)
    personal=st.session_state.get(VISITOR_UPLOADS,())
    with scope_slot:
        if selected=="I miei PDF":
            cached=_update_index(personal,state_key=VISITOR_STATE)
            description="Solo sessione · non pubblicati"
        else:
            cached=_public_snapshot(local,remote,shared=shared)
            description="Consultabili da tutti" if shared else "Archivio riservato · account autorizzato"
        docs=cached["docs"]
        count=len(docs.documents)
        pages=sum(p.pages for p in docs.documents.values())
        searchable=sum(cached["coverage"].values())
        st.caption(f"{count} PDF · {searchable}/{pages} pagine con testo · {description}")
        for warning in docs.errors:
            st.warning(warning)
    _render_documents(cached,show_errors=False)
    return cached


def _render_documents(cached, *, show_errors=True):
    docs=cached["docs"]
    if show_errors:
        for warning in docs.errors:
            st.warning(warning)
    if docs.documents:
        coverage=cached["coverage"]
        with st.expander(f"Documenti disponibili · {len(docs.documents)} PDF"):
            st.caption(f"{sum(coverage.values())} / {sum(p.pages for p in docs.documents.values())} pagine con testo")
            for name,pdf in docs.documents.items():
                label,actions=st.columns([3,1.45],vertical_alignment="center")
                with label:
                    st.text(pdf.name)
                    st.caption(f"{pdf.pages} pagine · {len(pdf.data)/1024/1024:.2f} MB")
                    if coverage[name]<pdf.pages:
                        st.caption(f"Testo estraibile in {coverage[name]} pagine.")
                with actions:
                    with st.popover("Azioni",icon=":material/more_horiz:"):
                        st.download_button("Scarica PDF",pdf.data,pdf.name,"application/pdf",key="desk_download_"+pdf.digest,
                                           icon=":material/download:",on_click="ignore")
                        st.caption("SHA-256")
                        st.text(pdf.digest)




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
    if not allow_preview:
        for hit in hits:
            with st.container(border=True):
                st.text(hit.document+f" · PDF p. {hit.page}")
                st.text(hit.evidence)
        return
    previous=st.session_state.get(prefix+"_hit")
    if previous is not None and previous not in range(len(hits)):
        st.session_state.pop(prefix+"_hit",None)
    index=st.selectbox("Passaggio da consultare",range(len(hits)),
                       format_func=lambda i:f"{hits[i].document} · p. {hits[i].page}",key=prefix+"_hit")
    hit=hits[index]
    with st.container(border=True,key=prefix+"_selected"):
        st.text(hit.document+f" · PDF p. {hit.page}")
        st.text(hit.evidence)
        a,b=st.columns(2)
        with a:
            if st.button("Apri pagina originale",key=prefix+"_open",icon=":material/description:",width="stretch"):
                cached[prefix+"_preview"]=(hit.document,hit.page)
        with b:
            if st.button("Salva riferimento",key=prefix+"_save",icon=":material/bookmark_add:",width="stretch"):
                _save(cached,hit)
        if cached.get(prefix+"_preview")== (hit.document,hit.page):
            _preview(cached["docs"].documents[hit.document],hit.page,prefix)
    if len(hits)>1:
        with st.expander(f"Altri passaggi · {len(hits)-1}"):
            for i,other in enumerate(hits):
                if i==index:continue
                st.text(other.document+f" · PDF p. {other.page}")
                st.text(other.evidence)


def _mode_label(mode):
    return "Parole chiave" if mode=="keywords" else "Frase esatta"


def _search(cached,*,ready_example=False):
    docs=cached["docs"]
    if ready_example and not cached.get("demo_search_prepared_v1"):
        cached["demo_search_prepared_v1"]=True
        if "desk_search_result" not in cached:
            query="corrispettivo di sbilanciamento"
            cached["desk_search_result"]=(query,"Tutti i PDF","keywords",search(docs,query,"keywords"))
    with st.form("desk_search",border=False):
        query=st.text_input("Cosa vuoi cercare?",placeholder="Es. corrispettivo di sbilanciamento",max_chars=600)
        a,b=st.columns([2,1])
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
        st.markdown("**Risultati della ricerca**")
        st.text(query+" · "+document+" · "+_mode_label(mode))
        _results(cached,hits,"desk_search")


def _ask(cached):
    docs=cached["docs"]
    model=reasoner()
    st.caption("Risposta dai PDF selezionati · citazioni controllate.")
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


def _review_documents(cached):
    from .document_review import compare_evidence
    docs=cached["docs"]
    names=list(docs.documents)
    model=reasoner()
    st.subheader("Revisore documentale")
    st.caption("Possibili incongruenze · non giudizio di conformità")
    info("Revisione","Due riscontri testuali obbligatori. Analisi limitata agli estratti recuperati; la corrispondenza letterale non prova l’interpretazione.")
    with st.form("desk_reviewer",border=False):
        a,b=st.columns(2)
        first=a.selectbox("Documento A",names,key="review_a")
        second=b.selectbox("Documento B",names,index=min(1,len(names)-1),key="review_b")
        theme=st.text_input("Tema da verificare",placeholder="Es. preavviso di cancellazione, scadenze, garanzie",max_chars=600)
        consent=False
        if model and not model.config.local:
            consent=st.checkbox("Autorizzo l'invio del tema e di massimo sei estratti pubblici o autorizzati al provider AI.")
        submit=st.form_submit_button("Avvia revisione",type="primary",disabled=model is None)
    if model is None:
        st.info("Seleziona un modello AI nella barra laterale. Cerca e Confronta restano disponibili senza AI.")
    if submit:
        cached.pop("document_review",None)
        if not theme.strip():
            st.warning("Indica un tema preciso.")
        elif model and not model.config.local and not consent:
            st.warning("Consenso necessario per la revisione con provider remoto.")
        elif model:
            first_hits=search(docs,theme,document=first,limit=6 if first==second else 3)
            if first==second:
                left,right=first_hits[::2][:3],first_hits[1::2][:3]
            else:
                left,right=first_hits,search(docs,theme,document=second,limit=3)
            saved={"theme":theme,"first":first,"second":second,"left":left,"right":right,
                   "model":model.config.model,"findings":[],"status":"insufficient"}
            if left and right:
                try:
                    with st.spinner("Revisione degli estratti e controllo delle citazioni…"):
                        saved["findings"]=compare_evidence(model,theme,left,right,authorized_remote=consent)
                    saved["status"]="completed"
                except ModelUnavailable as exc:
                    st.warning(str(exc))
                    saved["status"]="unavailable"
                except (ValueError,TypeError,RuntimeError,KeyError,OSError):
                    saved["status"]="invalid"
            cached["document_review"]=saved
    saved=cached.get("document_review")
    if not saved:
        return
    st.caption("Ultima revisione · "+saved["model"])
    st.text(saved["theme"]+" · "+saved["first"]+" / "+saved["second"])
    if saved["status"]=="insufficient":
        st.info("Riscontri insufficienti nei due insiemi di passaggi. Nessuna richiesta AI effettuata.")
    elif saved["status"] in ("invalid","unavailable"):
        st.warning("Revisione non disponibile o citazioni non verificabili. Consulta gli estratti.")
    elif not saved["findings"]:
        st.info("Nessun rilievo concreto restituito sugli estratti esaminati. Non esclude altri errori.")
    for item in saved["findings"]:
        with st.container(border=True):
            st.markdown("**Possibile incongruenza**")
            st.text(item["title"])
            st.text(item["detail"])
            for citation in item["citations"]:
                st.caption(citation.document+f" · PDF p. {citation.page}")
                st.text("«"+citation.evidence+"»")
            st.caption("Verifica suggerita")
            st.text(item["check"])
    if saved["findings"]:
        if st.button("Aggiungi rilievi al registro",key="review_register_add",icon=":material/bookmark_add:"):
            cases,added,omitted=register(cached.get(REVIEW_KEY,[]),saved["findings"],docs,
                                        theme=saved["theme"],model=saved["model"])
            cached[REVIEW_KEY]=cases
            st.success(f"{added} nuovi rilievi nel registro." if added else "Nessun nuovo rilievo aggiunto.")
            if omitted:
                st.warning("Registro pieno: esporta e svuota prima di aggiungerne altri.")

        payload={"theme":saved["theme"],"model":saved["model"],"status":"ipotesi da verificare",
                 "editions":{name:docs.documents[name].digest for name in {saved["first"],saved["second"]}},
                 "findings":[{**item,"citations":[c.model_dump(mode="json") for c in item["citations"]]} for item in saved["findings"]]}
        st.download_button("Esporta rilievi JSON",json.dumps(payload,ensure_ascii=False,indent=2),
                           "igor-revisione.json","application/json",key="desk_review_export")
    with st.expander("Estratti esaminati"):
        for hit in [*saved["left"],*saved["right"]]:
            st.caption(hit.document+f" · PDF p. {hit.page}")
            st.text(hit.evidence)



def _historical_register(cached):
    """Read-only prepared cases, distinct from AI-generated session hypotheses."""
    st.subheader("Rilievi documentali")
    st.caption("Edizioni esaminate · non rappresentano incidenti operativi del giorno.")
    cases={case.finding.id:case for case in REGISTER}
    selected=st.selectbox("Rilievo",list(cases),format_func=lambda key:cases[key].finding.title,
                          key="desk_historical_case")
    case=cases[selected]
    item=case.finding
    with st.container(border=True):
        st.markdown("**"+item.title+"**")
        st.caption(item.category+" · "+case.review)
        st.text(item.detail)
        st.caption("Vigenza e applicabilità alla singola operazione non certificate.")
        st.markdown("**Documenti e passaggi di riferimento**")
        for index,cite in enumerate(item.citations):
            st.text(f"{cite.document} · {cite.section} · PDF p. {cite.page}")
            st.text(cite.evidence)
            pdf=matching_edition(cached["docs"],cite)
            if pdf is None:
                st.caption("Copia esatta dell’edizione non disponibile nell’archivio selezionato. Riferimento storico, non estratto verificato in questa sessione.")
                continue
            key=f"desk_historical_preview_{item.id}_{index}"
            if st.checkbox("Mostra pagina originale",key=key):
                _preview(pdf,cite.page,"historical")
    if st.session_state.get(SCOPE)!="Archivio pubblico":
        st.caption("Puoi consultare le copie pubbliche scegliendo Archivio pubblico.")


def _review_register(cached):
    docs=cached["docs"]
    cases=valid_cases(cached.get(REVIEW_KEY,[]),docs)
    cached[REVIEW_KEY]=cases
    st.subheader("Registro rilievi")
    st.caption("Dossier della sessione · edizioni PDF correnti")
    info("Registro","Nessuna nuova richiesta AI. I rilievi legati a PDF rimossi o modificati vengono esclusi. Esporta prima di rimuovere PDF o chiudere la sessione.")
    if not cases:
        st.info("Nessun rilievo nel registro. Avvia il Revisore e aggiungi le ipotesi che vuoi approfondire.")
        return
    a,b,c=st.columns(3)
    a.metric("Rilievi",len(cases))
    b.metric("Da verificare",sum(x["status"]==STATUSES[0] for x in cases))
    c.metric("In approfondimento",sum(x["status"] in STATUSES[1:3] for x in cases))
    status=st.selectbox("Filtra stato",["Tutti",*STATUSES],key="review_register_filter")
    visible=[x for x in cases if status=="Tutti" or x["status"]==status]
    if visible:
        entries={x["id"]:x for x in visible}
        chosen=st.selectbox("Rilievo",list(entries),format_func=lambda k:entries[k]["status"]+" · "+entries[k]["title"],
                            key="review_register_selected")
        case=entries[chosen]
        with st.container(border=True):
            st.text(case["title"])
            st.caption(case["status"]+" · "+case["theme"]+" · "+case["model"])
            st.text(case["detail"])
            st.caption("Verifica suggerita")
            st.text(case["check"])
            st.caption("Citazioni letterali verificate · interpretazione da verificare")
            for i,hit in enumerate(case["citations"]):
                st.text(hit["document"]+f" · PDF p. {hit['page']}")
                st.text("«"+hit["evidence"]+"»")
                if st.button("Apri pagina originale",key=f"register_page_{chosen}_{i}"):
                    cached["register_preview"]=(chosen,i)
                if cached.get("register_preview")== (chosen,i):
                    _preview(docs.documents[hit["document"]],hit["page"],"register")
            with st.form("register_decision_"+chosen,clear_on_submit=True):
                new_status=st.selectbox("Stato della verifica",STATUSES,index=STATUSES.index(case["status"]))
                note=st.text_area("Motivazione della decisione",max_chars=600,
                                 placeholder="Es. le disposizioni riguardano perimetri diversi…")
                submitted=st.form_submit_button("Registra verifica",type="primary")
            if submitted:
                try:
                    updated=decide(case,new_status,note)
                    cached[REVIEW_KEY]=[updated if x["id"]==chosen else x for x in cases]
                    st.rerun()
                except ValueError as error:
                    st.warning(str(error))
            with st.expander("Storico decisioni"):
                st.caption("Annotazioni dell’utente, non risultati verificati automaticamente.")
                for event in case["history"]:
                    st.text(event["at"]+" · "+event["from"]+" → "+event["to"])
                    st.text(event["note"])
                if not case["history"]:
                    st.caption("Nessuna decisione registrata.")
    else:
        st.caption("Nessun rilievo con questo stato.")
    st.caption(f"{len(cases)}/{REVIEW_LIMIT} rilievi · esporta prima di chiudere la sessione o rimuovere PDF.")
    left,right=st.columns(2)
    left.download_button("Scarica dossier Markdown",export_markdown(cases),"igor-dossier.md",
                         "text/markdown",key="review_register_md",width="stretch")
    right.download_button("Scarica registro JSON",export_json(cases),"igor-registro.json",
                          "application/json",key="review_register_json",width="stretch")
    with st.expander("Svuota registro"):
        confirmed=st.checkbox("Confermo di voler eliminare il registro di questa sessione.",key="review_register_clear_confirm")
        if st.button("Svuota",disabled=not confirmed,key="review_register_clear"):
            cached[REVIEW_KEY]=[]
            cached.pop("register_preview",None)
            st.rerun()


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
                       "igor-riferimenti.json","application/json",key="desk_refs_export")
    if st.button("Svuota raccolta",key="desk_refs_clear"):
        items.clear()
        st.rerun()


def document_page(*,ready_example=False):
    header("Norme e documenti","")
    pending=st.session_state.pop(NEXT_SCOPE,None)
    if pending in ("Archivio pubblico","I miei PDF"):
        st.session_state[SCOPE]=pending
    target=st.session_state.pop("desk_finding_target",None)
    if isinstance(target,str) and registered_case(target):
        st.session_state[SCOPE]="Archivio pubblico"
        st.session_state["desk_mode"]="Registro rilievi"
        st.session_state["desk_register_origin"]="Edizioni esaminate"
        st.session_state["desk_historical_case"]=target
    # Emit navigation before disk/network/index work. Upload requests switch
    # scope on the next rerun via NEXT_SCOPE, not an instantiated widget.
    scope_slot=st.container(key="document_scope")
    with scope_slot:
        selected=st.radio("Archivio",["Archivio pubblico","I miei PDF"],horizontal=True,key=SCOPE,
                          label_visibility="collapsed")
    tool_slot=st.container(key="document_tools")
    with tool_slot:
        action=st.radio("Strumento",["Cerca","Chiedi all’AI","Leggi PDF","Confronta","Revisore","Registro rilievi","Riferimenti salvati","Compliance"],
                        horizontal=True,label_visibility="collapsed",key="desk_mode",
                        format_func={"Cerca":"Cerca","Chiedi all’AI":"Chiedi AI","Leggi PDF":"Leggi","Confronta":"Confronta",
                                     "Revisore":"Verifica","Registro rilievi":"Rilievi","Riferimenti salvati":"Salvati","Compliance":"Compliance"}.__getitem__)
    body=st.container(key="document_workspace")
    with st.container(key="document_management"):
        st.subheader("Archivio PDF")
        cached=_archive(selected,scope_slot)
        info("Archivio e privacy","Ricerca sul testo estratto, senza OCR; la vigenza non è certificata. Non caricare documenti riservati sul deployment pubblico.",
             "I PDF personali sono disponibili solo in sessione; i PDF pubblicati da account autorizzati sono condivisi. Solo l’amministratore può rimuovere documenti condivisi.",
             "Il bollettino non riceve i PDF. Chiedi AI invia solo domanda ed estratti al modello; per provider remoti occorre consenso.")
    with body:
        if not cached["docs"].documents and action!="Registro rilievi":
            st.info("Aggiungi almeno un PDF per iniziare a cercare. Usa Carica PDF nell’archivio qui sotto.")
            return
        if action=="Cerca":
            _search(cached,ready_example=ready_example)
        elif action=="Chiedi all’AI":
            _ask(cached)
        elif action=="Leggi PDF":
            _read(cached)
        elif action=="Confronta":
            _compare(cached)
        elif action=="Revisore":
            _review_documents(cached)
        elif action=="Registro rilievi":
            origin=st.radio("Origine dei rilievi",["Edizioni esaminate","Rilievi di sessione"],horizontal=True,
                            key="desk_register_origin",label_visibility="collapsed")
            if origin=="Edizioni esaminate":
                _historical_register(cached)
            else:
                _review_register(cached)
        elif action=="Compliance":
            from .compliance_page import panel as compliance_panel
            compliance_panel(cached,public=st.session_state.get(SCOPE)=="Archivio pubblico")
        else:
            _references(cached)
