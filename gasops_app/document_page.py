"""Shared, persistent public PDF archive; personal research state stays session-only."""
import json
import os
from threading import Lock
from pathlib import Path

import streamlit as st

from .data import ROOT
from .document_desk import build, identity, search, searchable_pages, bookmark, page_text, MAX_RESULTS, MAX_TOTAL_BYTES
from .regulatory import read_local_pdfs, MAX_DOCUMENTS, MAX_PDF_BYTES
from .visuals import info
from .session import reasoner
from .document_rag import answer, MAX_PASSAGES
from .supervisor import ModelUnavailable
from .document_archive import Archive, ArchiveConfig, ArchiveError, display_name

STATE="document_desk_v1"
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
    if not any((url,key,admin)):
        return None
    return ArchiveConfig(url.rstrip("/"),key,admin)


@st.cache_data(ttl=30,max_entries=3,show_spinner=False)
def _read_remote(config):
    # Only public archives are cached across visitors; never credentials or chat.
    return Archive(config).read()


def _admin_panel(config,archive,local,remote):
    if not config.admin_id:
        return
    with st.expander("Gestisci archivio"):
        saved=st.session_state.get(ADMIN)
        session=saved[1] if saved and saved[0]==config and saved[1].valid(config) else None
        if not session:
            st.session_state.pop(ADMIN,None)
            with st.form("document_admin_login",clear_on_submit=True):
                email=st.text_input("Email amministratore",max_chars=254)
                password=st.text_input("Password",type="password",max_chars=256)
                login=st.form_submit_button("Accedi")
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
                st.rerun()
        if remote:
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
                    st.rerun()


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
    st.subheader("Archivio documentale pubblico")
    st.caption("Documenti consultabili da tutti. Le ricerche e i riferimenti salvati restano nella singola sessione.")
    config=None
    try:
        config=_archive_config()
    except ValueError:
        st.warning("Configurazione archivio persistente non valida.")
    remote=()
    if config:
        archive=Archive(config)
        try:
            with st.spinner("Aggiornamento archivio…"):
                remote=_read_remote(config)
        except ArchiveError as exc:
            st.warning(str(exc)+" Sono mostrati soltanto eventuali PDF predisposti sul server.")
        else:
            _admin_panel(config,archive,local,remote)
    else:
        st.caption("Archivio remoto non configurato · consultazione dei soli PDF predisposti nel progetto.")
    message,notices=st.session_state.pop(NOTICE,("",[]))
    if message:
        st.success(message)
    for notice in notices:
        st.warning(notice)
    cached=_update_index(tuple((display_name(k),v) for k,v in remote)+local)
    docs=cached["docs"]
    for warning in docs.errors:
        st.warning(warning)
    if docs.documents:
        coverage=searchable_pages(docs)
        st.caption(f"{len(docs.documents)} PDF · {sum(coverage.values())} / {sum(p.pages for p in docs.documents.values())} pagine con testo")
        with st.container(border=True,key="panel_document_archive"):
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
    st.caption("Cerca, interroga e confronta i documenti dell’archivio.")
    info("Info archivio","La ricerca mostra testo estratto dalle pagine dei PDF presenti, non note precompilate. Le corrispondenze per parole chiave non sono un parere legale.",
         "Usa solo copie pubbliche o autorizzate. I PDF pubblicati nell’archivio remoto sono condivisi tra tutti i visitatori e conservati indipendentemente dalla sessione Streamlit. Solo l’amministratore può pubblicare e rimuovere documenti. Non caricare dati riservati. I PDF non entrano nel bollettino; la ricerca è sul server. Con Chiedi all’AI, soltanto la domanda e gli estratti sono inviati al modello selezionato, previo consenso per provider remoti. Non caricare documenti riservati su un deployment pubblico. Nessun OCR. La vigenza delle edizioni non è verificata.")
    cached=_archive()
    if not cached["docs"].documents:
        st.info("Aggiungi almeno un PDF tramite la gestione amministratore per iniziare. Non vengono mostrati rilievi o citazioni in assenza di documenti.")
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
