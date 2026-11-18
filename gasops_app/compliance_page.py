"""Link session operation proposals to exact quotes from the public PDF desk."""
import streamlit as st

from .compliance import (STATE,MAX_LINKS,TOPICS,OFFICIAL,OUTCOMES,add_reference,assess,
                         case_links,edition_status,export_register)
from .document_desk import page_text,search
from .models import utc_now

CASE_STATE="bso_agentic_v1_session"
INDEX_STATE="document_desk_v1"
HITS="compliance_search_v1"


def public_docs(state):
    cached=state.get(INDEX_STATE)
    return cached.get("docs") if cached else None


def references_panel(case):
    records=case_links(st.session_state.get(STATE,[]),case["id"],public_docs(st.session_state))
    with st.expander("Riferimenti normativi",expanded=False):
        st.caption("Solo riferimenti associati esplicitamente a questa versione del rilievo. Vigenza e conformità non certificate.")
        if not records:
            st.caption("Nessun collegamento documentale per questa versione.")
        for r in records:
            st.text(f'{r["document"]} · PDF p. {r["page"]}')
            st.text(r["quote"])
            st.caption(r["outcome"]+" · "+r["edition_status"])
        st.markdown("[Norme e documenti → Compliance](/regulatory)")


def official_links():
    with st.expander("Fonti ufficiali da consultare"):
        for label,url in OFFICIAL.items():
            st.markdown(f"[{label}]({url})")
        st.caption("Indici e provvedimenti di riferimento, non attestazione dell'edizione vigente o applicabile alla singola giornata.")


def panel(cached,*,public):
    st.subheader("Compliance operativa")
    st.caption("Rilievo BSO → evidenza documentale → verifica umana. Nessuna decisione automatica di conformità.")
    official_links()
    if not public:
        st.info("Seleziona Archivio pubblico per associare riferimenti alla coda operativa. I PDF personali restano separati.")
        return
    docs=cached["docs"]
    state=st.session_state
    cases=state.get(CASE_STATE,{}).get("cases",[])
    current=set(state.get(CASE_STATE,{}).get("current",[]))
    records=state.get(STATE,[])
    if not cases:
        st.info("Esegui prima i controlli sui dati di sessione in KPI operativi → Centro operativo. La demo non alimenta la compliance.")
        st.markdown("[Apri Centro operativo](/kpi)")
    else:
        lookup={r["id"]:r for r in cases}
        selected=st.selectbox("Rilievo operativo",[r["id"] for r in cases],
             format_func=lambda i:f'{lookup[i]["agent"]} · {lookup[i]["title"]} · {lookup[i]["period"]} · {i[:8]}',key="compliance_case")
        case=lookup[selected]
        st.text(case["evidence"])
        if selected not in current:
            st.warning("Rilievo storico: non presente nell'ultima scansione. Nessuna risoluzione implicita.")
        title,query=TOPICS.get(case["agent"],("Ricerca documentale",""))
        st.caption("Tema di ricerca suggerito: "+title+" · non attribuzione automatica di un obbligo.")
        name=st.selectbox("Documento pubblico",list(docs.documents),key="compliance_doc")
        pdf=docs.documents[name]
        q=st.text_input("Parole chiave",value=query,key="compliance_query_"+selected)
        if st.button("Cerca nel documento",key="compliance_search"):
            state[HITS]={"key":(selected,name,pdf.digest,q),"hits":search(docs,q,document=name,limit=6)}
        saved=state.get(HITS,{})
        if saved.get("key")== (selected,name,pdf.digest,q):
            for hit in saved["hits"]:
                st.markdown(f"**PDF p. {hit.page}**")
                st.text(hit.evidence)
            if not saved["hits"]:
                st.caption("Nessuna corrispondenza. Non dimostra assenza di un obbligo.")
        page=int(st.number_input("Pagina fisica del PDF",min_value=1,max_value=pdf.pages,value=1,key="compliance_page_"+pdf.digest))
        with st.expander("Testo della pagina selezionata"):
            st.text(page_text(pdf,page)[:20000] or "Nessun testo estraibile.")
        with st.form("compliance_attach_"+selected+"_"+pdf.digest):
            section=st.text_input("Capitolo / paragrafo (dichiarato)",max_chars=120)
            quote=st.text_area("Estratto letterale dalla pagina · 15–300 caratteri",max_chars=300)
            st.caption("Controllo letterale sul testo estratto; spazi normalizzati. Il paragrafo dichiarato non viene certificato.")
            confirm=st.checkbox("Confermo di voler associare questo estratto al rilievo, senza attestare conformità.")
            submit=st.form_submit_button("Collega evidenza")
        if submit and not confirm:
            st.warning("Conferma esplicitamente il collegamento prima di registrarlo.")
        if submit and confirm:
            try:
                updated,added=add_reference(records,case,docs,name,page,quote,section,utc_now())
                state[STATE]=updated
                records=updated
                st.success("Evidenza collegata." if added else "Evidenza già collegata.")
            except (ValueError,RuntimeError) as exc:
                st.error(str(exc))
        subset=case_links(records,selected,docs)
        if subset:
            refs={r["id"]:r for r in subset}
            chosen=st.selectbox("Evidenza da valutare",list(refs),
                format_func=lambda i:f'{refs[i]["document"]} · p. {refs[i]["page"]} · {i[:8]}',key="compliance_ref_"+selected)
            r=refs[chosen]
            st.text(r["quote"])
            st.caption(r["edition_status"]+" · "+r["outcome"])
            if r["edition_status"]=="Copia indicizzata corrispondente":
                with st.form("compliance_review_"+chosen):
                    outcome=st.selectbox("Pertinenza", [x for x in OUTCOMES if x!=r["outcome"]])
                    note=st.text_area("Motivazione · nessun dato riservato",max_chars=400)
                    review=st.form_submit_button("Registra valutazione")
                if review:
                    try:
                        changed=assess(r,outcome,note,docs,utc_now())
                        # Do not store a computed edition status in the immutable record.
                        changed.pop("edition_status",None)
                        state[STATE]=[changed if x["id"]==chosen else x for x in records]
                        st.rerun()
                    except ValueError as exc:
                        st.error(str(exc))
            if r["history"]:
                st.dataframe(r["history"],hide_index=True,width="stretch")
    st.divider()
    st.caption(f"{len(records)}/{MAX_LINKS} collegamenti · sessione corrente · storico conservato anche se edizione o rilievo cambiano.")
    st.download_button("Esporta matrice di tracciabilità JSON",export_register(records,cases,docs),
                       "igor-compliance.json","application/json",key="compliance_export")
    with st.expander("Gestione registro"):
        clear=st.checkbox("Ho esportato il registro e confermo la rimozione.",key="compliance_confirm_clear")
        if st.button("Svuota collegamenti",disabled=not clear,key="compliance_clear"):
            state.pop(STATE,None)
            st.rerun()
