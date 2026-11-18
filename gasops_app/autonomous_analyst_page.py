"""One planning call and one evidence-based interpretation, explicit consent."""
import json
from datetime import date
import streamlit as st
import pandas as pd
from .analyst_planner import manifest,validate_plan,execute_plan
from .data_analyst import reference_facts,forecast_facts,evidence_ids
from .data import ROME

STATE="autonomous_analyst_v1"


def panel(items,model,now):
    st.caption("Scrivi una domanda: I.G.O.R. sceglie fonti, periodo e strumenti tra quelli disponibili.")
    remote=not model.config.local
    question=st.text_area("Domanda per l’AI",placeholder="Es. Qual è il legame tra generazione termoelettrica e riconsegna gas negli ultimi 90 giorni?",max_chars=600,key="auto_analyst_question")
    consent=True
    if remote:
        consent=st.checkbox("Autorizzo l’invio al modello della domanda, del catalogo pubblico consentito e degli aggregati risultanti. Ho verificato i diritti; nessun dato riservato.",key="auto_analyst_consent")
    today=now.astimezone(ROME).date()
    if st.button("Analizza con AI",type="primary",key="auto_analyst_run",disabled=not question.strip() or not consent):
        st.session_state.pop(STATE,None)
        try:
            facts=reference_facts()
            forecasts=forecast_facts(st.session_state)
            available=manifest(items,facts,forecasts,question,today,remote=remote)
            with st.spinner("Selezione delle fonti e degli strumenti…"):
                draft=model.plan_dataset(question.strip(),available)
                plan=validate_plan(draft,available,today)
            if not plan["tools"]:
                st.session_state[STATE]={"question":question,"plan":plan,"payload":None,"answer":None,
                    "warning":"Nessuna analisi pertinente selezionata. Verifica copertura, permessi e fonti disponibili.",
                    "model":model.config.model,"at":now.isoformat(),"omitted":available["omitted_eligible"],"refs":[]}
            else:
                with st.spinner("Calcoli locali e verifica delle evidenze…"):
                    evidence=execute_plan(plan,items,facts,forecasts)
                answer=None;refs=[];warning=None
                if evidence_ids(evidence):
                    try:
                        with st.spinner("Interpretazione AI dei risultati…"):
                            answer,refs=model.interpret_dataset(question.strip(),evidence,evidence_ids(evidence))
                    except Exception:
                        warning="Interpretazione AI non disponibile. Sono conservati soltanto i calcoli locali."
                else:
                    warning="Nessuna evidenza numerica per il piano selezionato. Nessuna risposta AI generata."
                st.session_state[STATE]={"question":question,"plan":plan,"payload":evidence,"answer":answer,
                    "warning":warning,"model":model.config.model,"at":now.isoformat(),
                    "omitted":available["omitted_eligible"],"refs":refs}
        except Exception:
            st.error("Pianificazione o calcolo non riusciti. Nessuna risposta AI generata. Verifica disponibilità del modello e delle fonti.")
    saved=st.session_state.get(STATE)
    if not saved:return
    st.caption("Ultima analisi · "+saved["at"]+" · "+saved["model"]+" · riesegui per aggiornare dati o domanda.")
    st.text(saved["question"])
    if saved["warning"]:st.warning(saved["warning"])
    if saved["answer"]:
        st.markdown("**Risposta AI**")
        st.text(saved["answer"])
        st.caption("Evidenze citate: "+", ".join(saved["refs"]))
    plan=saved["plan"]
    payload=saved["payload"]
    with st.expander("Piano scelto dall’AI",expanded=True):
        st.caption(plan["from"]+" – "+plan["to"]+" · "+", ".join(plan["tools"]))
        st.text(", ".join(plan["series"]+plan["benchmarks"]+plan["forecasts"]) or "Nessuna fonte selezionata")
        if saved["omitted"]:st.caption(f'{saved["omitted"]} serie ammissibili escluse dal catalogo compatto; usa la selezione manuale per consultarle.')
        st.caption("Il catalogo remoto esclude le serie riservate alla sola elaborazione locale.")
    if payload:
        if payload["series"]:
            st.dataframe([{"ID":r["id"],"Serie":r["label"],"Unità":r["unit"],"Da":r["first"],"A":r["last"],
                "N":r["n"],"Ultimo":r["last_value"],"Media":r["mean"]} for r in payload["series"]],hide_index=True,width="stretch")
        if payload["statistics"] or payload["correlations"]:
            st.markdown("**Risultati statistici**")
            st.dataframe(payload["statistics"]+payload["correlations"],hide_index=True,width="stretch")
        if payload["unavailable"] or payload["missing"]:
            with st.expander("Analisi non calcolabili",expanded=True):
                st.json({"strumenti":payload["unavailable"],"serie_senza_dati":payload["missing"]},expanded=False)
        with st.expander("Evidenze, fonti e limiti"):
            st.json(payload,expanded=False)
    st.caption("Piano vincolato e calcoli Python; nessuna esecuzione di codice AI, nessun download automatico. Le citazioni non certificano ogni affermazione.")
    st.download_button("Esporta analisi JSON",json.dumps(saved,ensure_ascii=False,indent=2,allow_nan=False),
        "igor-autonomous-analysis.json","application/json",key="auto_analyst_export")
    if st.button("Rimuovi analisi",key="auto_analyst_clear"):
        st.session_state.pop(STATE,None)
        st.rerun()
