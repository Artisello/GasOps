"""Visible entry points for existing providers; credentials never enter UI state."""
from datetime import timedelta

import streamlit as st

from . import session
from .live_sources import LABELS,STATUS,refresh
from .models import utc_now

EXTRA="connections_checks_v1"
CATALOG=(
    ("monthly","Eurostat + ARERA","Consumi e prezzi mensili","/market"),
    ("daily","ENTSOG · SRG","Prelievi giornalieri","/market"),
    ("acer","ACER","Prezzi GNL e benchmark","/market"),
    ("agsi","GIE · AGSI+","Stoccaggi","/security-of-supply"),
    ("alsi","GIE · ALSI","Terminali GNL","/security-of-supply"),
    ("iip","GIE · IIP","Avvisi degli operatori","/security-of-supply"),
    ("terna","Terna · consuntivi","Generazione e carico elettrico","/market"),
    ("terna_forward","Terna · MSD1","Previsioni elettriche","/market"),
    ("terna_capacity","Terna · capacità","Contesto termoelettrico","/market"),
    ("terna_industry","Terna · IMCEI","Contesto industriale","/market"),
    ("weather","Open-Meteo","Temperature e HDD","/market"),
    ("ai","Modello AI","Analisi e risposte con evidenze","/operations"),
    ("documents","Archivio documentale","PDF pubblici approvati","/regulatory"),
)


def access():
    from .operational_sources_page import configured_key
    from .terna_power import credentials
    from .weather_source import enabled
    from .document_page import _archive_config
    def safely(fn,default):
        try:return fn()
        except (ValueError,KeyError,FileNotFoundError):return default
    gie=safely(configured_key,None)
    terna=safely(lambda:credentials(st.secrets),None)
    if not terna:terna=credentials()
    if not all(terna):terna=None
    ai=safely(session._configuration,None)
    documents=safely(_archive_config,None)
    available=["monthly","daily","acer"]
    if gie:available.extend(("agsi","alsi"))
    if terna:available.extend(("terna","terna_forward","terna_capacity","terna_industry"))
    if enabled(st.session_state):available.append("weather")
    return {"gie":gie,"terna":terna,"ai":ai,"documents":documents,"available":available}


def provider_rows(state,configuration):
    acquired=state.get(STATUS,{}).get("sources",{})
    extra=state.get(EXTRA,{})
    available=set(configuration["available"])
    if configuration["gie"]:available.add("iip")
    if configuration["ai"]:available.add("ai")
    if configuration["documents"]:available.add("documents")
    rows=[]
    for key,name,purpose,path in CATALOG:
        checked=extra.get(key) if key in ("iip","ai","documents") else acquired.get(key)
        status=("Non configurata" if key not in available else
                checked["status"] if checked else "Disponibile · da verificare")
        rows.append({"Fonte":name,"Funzione":purpose,"Stato":status,
                     "Ultimo controllo":checked["at"] if checked else "—",
                     "Nota":checked.get("note","") if checked else "",
                     "Apri":path})
    rows.extend([
        {"Fonte":"JRC, MASE, ACER, Terna · archivi","Funzione":"Serie pubbliche datate incluse","Stato":"Archivio disponibile","Ultimo controllo":"—","Nota":"Periodi e fonti visibili nelle analisi","Apri":"/market"},
        {"Fonte":"Snam Jarvis","Funzione":"Import e versioni XLSX/CSV","Stato":"Importazione pubblica","Ultimo controllo":"—","Nota":"Nessun endpoint automatico nativo verificato","Apri":"/security-of-supply"},
        {"Fonte":"GME","Funzione":"Prezzi di sbilanciamento","Stato":"Consultazione e import","Ultimo controllo":"—","Nota":"Nessuna raccolta automatica senza autorizzazione prevista dai termini","Apri":"/market"},
    ])
    return rows


def refresh_all(state,store,configuration,now=None):
    now=now or utc_now()
    # Same per-session one-minute throttle as the existing provider coordinator.
    previous=state.get(STATUS,{}).get("attempted")
    if previous and now-previous<timedelta(seconds=60):return False
    ok=refresh(state,store,now,configuration["available"],gie=configuration["gie"],terna=configuration["terna"])
    if not ok:return False
    checks=dict(state.get(EXTRA,{}))
    def check(name,fn):
        try:
            note=fn()
            checks[name]={"status":"Da verificare" if note else "Verificata","at":utc_now().isoformat(),"note":note or ""}
        except Exception:
            checks[name]={"status":"Da verificare","at":utc_now().isoformat(),
                          "note":"Verifica non riuscita. Eventuali dati precedenti restano disponibili."}
    if configuration["gie"]:
        def iip():
            from .operational_sources import load_iip
            previous=state.get("gie_iip",{})
            state["gie_iip"]={**previous,"attempted":now}
            try:result=load_iip(store,configuration["gie"],now=now,refresh=True)
            except Exception:
                state["gie_iip"]={**previous,"attempted":now,"error":"Aggiornamento non disponibile"}
                raise
            state["gie_iip"]={"attempted":now,"result":result}
            return "Cache dopo mancato aggiornamento." if result.get("failed") else "Copertura parziale." if result.get("partial") else ""
        check("iip",iip)
    if configuration["ai"]:
        def ai():
            from .llm import CompatibleReasoner
            config=configuration["ai"]
            if not CompatibleReasoner(config,reserve=None if config.local else session._reserve_remote_request).probe():
                raise ValueError("Probe failed")
        check("ai",ai)
    if configuration["documents"]:
        def documents():
            from .document_archive import Archive
            Archive(configuration["documents"]).list_keys()
        check("documents",documents)
    state[EXTRA]=checks
    return True


def page():
    st.title("Fonti e API")
    st.caption("Le integrazioni del programma, con accesso diretto alle rispettive analisi.")
    configuration=access()
    if st.button("Aggiorna fonti connesse",type="primary",key="connections_refresh"):
        with st.spinner("Verifica e acquisizione delle fonti disponibili…"):
            changed=refresh_all(st.session_state,session.database(),configuration)
        if not changed:st.caption("Aggiornamento già richiesto nell’ultimo minuto.")
    rows=provider_rows(st.session_state,configuration)
    checked=sum(r["Ultimo controllo"]!="—" for r in rows)
    st.caption(f"{checked} connessioni controllate · configurazione e risposta sono distinte")
    st.dataframe([{k:r[k] for k in ("Fonte","Stato","Apri")} for r in rows],hide_index=True,width="stretch",column_config={
        "Apri":st.column_config.LinkColumn("Analisi",display_text="Apri"),
    })
    with st.expander("Dettagli delle verifiche"):
        st.dataframe(rows,hide_index=True,width="stretch")
        st.caption("Nessuna fonte non raggiungibile viene sostituita da dati simulati.")
    with st.expander("Catalogo delle funzionalità"):
        st.markdown(
            "- [Bilanciamento, settlement e rettifiche](/balancing)\n"
            "- [Fatture, garanzie, scadenze e GNL](/ledger)\n"
            "- [KPI, monitoraggio, incentivi e centro operativo](/kpi)\n"
            "- [Mercato, previsioni, Terna e analisi Snam](/market)\n"
            "- [Scorte, GNL, avvisi, HS1 e interconnessioni](/security-of-supply)\n"
            "- [Rischi e stress test](/risk)\n"
            "- [Assistente AI e analista dati](/operations)\n"
            "- [PDF, ricerca, verifiche e dossier](/regulatory)\n"
            "- [Esempi BSO e sviluppi del pilot](/demo)")
