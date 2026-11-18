"""Explicit quantitative evidence selection, optional bounded AI interpretation."""
from datetime import date
import json
import streamlit as st
import pandas as pd

from .data import ROME
from .models import utc_now
from .session import reasoner, ai_activation_panel
from .data_analyst import catalog,analyse,reference_facts,forecast_facts,can_share,MAX_SELECTED,evidence_ids

STATE="data_analyst_result_v1"


def panel():
    st.subheader("Analista dati integrato")
    st.caption("Serie pubbliche e dati già acquisiti · calcoli locali · fonti e periodo verificabili")
    from .live_sources_page import controls
    controls("analyst")
    now=utc_now()
    items,issues=catalog(st.session_state,now)
    if issues:
        with st.expander("Qualità delle fonti"):
            for issue in issues:st.text(issue)
    if not items:
        st.info("Nessuna serie disponibile.")
        return
    model=reasoner()
    if model:
        mode=st.radio("Selezione fonti e strumenti",["Automatica (AI)","Manuale"],horizontal=True,key="analyst_strategy")
        if mode=="Automatica (AI)":
            from .autonomous_analyst_page import panel as autonomous_panel
            from .weather_source import enabled,refresh
            from .session import database
            def acquire_weather():
                if enabled(st.session_state):refresh(st.session_state,database(),utc_now())
                return catalog(st.session_state,utc_now())[0]
            autonomous_panel(items,model,now,refresh_catalog=acquire_weather)
            return
    defaults=[k for k in ("snam_demand","terna_Thermal","terna_load","jarvis_withdrawal_definitivo") if k in items]
    if not defaults:
        recent=[k for k in items if k.startswith("market_")]
        defaults=recent[:3] if recent else ["jrc_demand_gwh"] if "jrc_demand_gwh" in items else [next(iter(items))]
    keys=st.multiselect("Serie da interrogare",list(items),default=defaults,
        format_func=lambda k:items[k].source+" · "+items[k].label,max_selections=MAX_SELECTED,key="analyst_series")
    with st.expander("Catalogo e copertura"):
        st.dataframe([{"Fonte":v.source,"Serie":v.label,"Unità":v.unit,"Perimetro":v.scope,
                      "Da":v.values.index[0],"A":v.values.index[-1],"Osservazioni":len(v.values),"Stato":v.status}
                      for v in items.values()],hide_index=True,width="stretch")
        st.markdown("[Carica Jarvis, ENTSOG e stoccaggi](/security-of-supply) · [Terna, ACER e backtest Snam](/market)")
    a,b=st.columns(2)
    first=a.date_input("Dal",value=date(2000,1,1),min_value=date(1990,1,1),max_value=now.astimezone(ROME).date(),key="analyst_from")
    last=b.date_input("Al",value=now.astimezone(ROME).date(),min_value=date(1990,1,1),max_value=now.astimezone(ROME).date(),key="analyst_to")
    include=st.checkbox("Includi benchmark pubblici e ultimi backtest compatibili",value=True,key="analyst_context")
    if model:
        st.caption("AI attiva · "+model.config.model)
    else:
        ai_activation_panel(prefix="analyst")
    question=st.text_area("Domanda per l’AI",placeholder="Es. Come si muovono termoelettrico e riconsegna gas? Il forecast migliora?",max_chars=600,key="analyst_question",disabled=model is None)
    if model is None:
        question=""
    remote=bool(model and not model.config.local)
    consent=False
    if remote:
        consent=st.checkbox("Autorizzo l'invio al modello esterno della domanda e dei soli aggregati pubblici selezionati; ho verificato le condizioni di utilizzo. Senza dati riservati.",key="analyst_consent")
        if keys and not can_share(items,keys):
            st.caption("GIE, flussi di interconnessione ENTSOG e coefficienti/stock Jarvis selezionati: solo elaborazione locale.")
    elif model:st.caption("Modello locale selezionato.")
    else:st.caption("Modalità senza AI: calcoli disponibili; attiva un modello dalla barra laterale per la risposta testuale.")
    if st.button("Calcola e interroga AI" if model and question.strip() else "Calcola statistiche",type="primary",key="analyst_run",disabled=not keys):
        st.session_state.pop(STATE,None)
        try:
            payload=analyse(items,keys,first.isoformat(),last.isoformat())
            if include:
                payload["benchmarks"]=reference_facts()
                payload["forecasts"]=forecast_facts(st.session_state,now,include_restricted=not remote)
            answer=None;refs=[];warning=None
            if model and question.strip() and (not remote or consent and can_share(items,keys)) and evidence_ids(payload):
                try:
                    answer,refs=model.interpret_dataset(question.strip(),payload,evidence_ids(payload))
                except Exception:
                    warning="Risposta AI non disponibile; calcoli locali conservati."
            elif model and remote and question.strip():
                warning="Invio al modello esterno non autorizzato per le serie selezionate."
            st.session_state[STATE]={"payload":payload,"answer":answer,"references":refs,"warning":warning,
                "question":question,"at":now.isoformat(),"model":model.config.model if answer else None,
                "mode":"AI" if answer else "Calcoli locali · nessuna risposta AI"}
        except (ValueError,TypeError,KeyError,ArithmeticError) as e:
            st.error("Analisi non disponibile: verifica intervallo, serie e copertura.")
    saved=st.session_state.get(STATE)
    if not saved:return
    payload=saved["payload"]
    st.caption("Ultima analisi eseguita: "+saved["at"]+" · riesegui dopo ogni modifica a fonti, filtri o domanda.")
    st.caption(saved.get("mode","AI" if saved.get("answer") else "Calcoli locali · nessuna risposta AI"))
    if saved["question"] and (model or not saved["answer"]):st.text(saved["question"])
    if saved["warning"]:st.warning(saved["warning"])
    if saved["answer"] and model:
        st.markdown("**Risposta AI precedente · "+str(saved.get("model") or "modello non registrato")+"**")
        st.text(saved["answer"])
        st.caption("Evidenze citate: "+", ".join(saved["references"])+" · interpretazione da verificare.")
    if saved["answer"] and not model:
        st.info("L’analisi precedente contiene una risposta AI; riattiva il modello per consultarla. Le statistiche rimangono disponibili.")
    if not payload["series"]:
        st.info("Nessuna osservazione nel periodo richiesto.")
    else:
        st.markdown("**Risultati verificabili**")
        st.dataframe([{ "ID":r["id"],"Serie":r["label"],"Unità":r["unit"],"Da":r["first"],"A":r["last"],"N":r["n"],
                        "Ultimo":r["last_value"],"Media":r["mean"],"Min":r["min"],"Max":r["max"],
                        "Variazione %":r["change_pct"]} for r in payload["series"]],hide_index=True,width="stretch")
    if payload["missing"]:st.caption("Serie senza osservazioni nel periodo: "+", ".join(payload["missing"]))
    if payload["correlations"]:
        st.markdown("**Correlazioni su giorni gas comuni**")
        st.dataframe(payload["correlations"],hide_index=True,width="stretch")
        st.caption("Pearson descrittivo, almeno 14 coppie; nessuna prova causale.")
    elif len(payload["series"])>1:st.caption("Nessuna correlazione calcolabile con frequenza e copertura compatibili.")
    with st.expander("Fonti, benchmark, backtest e dati dell'analisi"):
        st.json(payload,expanded=False)
        st.caption("Benchmark e backtest mantengono i loro periodi; non sono filtrati come le serie storiche.")
        st.download_button("Esporta evidenze JSON",json.dumps(saved if model else {**saved,"answer":None,"references":[],"question":"","model":None,"mode":"Calcoli locali"},ensure_ascii=False,indent=2,allow_nan=False),
                            "igor-data-analysis.json","application/json",key="analyst_export")
    if st.button("Rimuovi ultima analisi",key="analyst_clear"):
        st.session_state.pop(STATE,None)
        st.rerun()
