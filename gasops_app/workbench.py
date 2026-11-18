"""Bilanciamento, ricerca normativa e centro operativo AI."""

from datetime import datetime
from html import escape
import json
import logging
import sqlite3

import pandas as pd
from pydantic import ValidationError
import streamlit as st

from .agents import MarketContext, RegulationArguments, regulation_result
from .finance import CommercialInput, ScenarioCase, ScenarioInput, SettlementInput, scenario, settle, settle_commercial, settlement_sensitivity
from .italiano import ESITI, GRAVITA, MODALITA, numero
from .models import AGENT_LABELS, Agent, Kind, Run, utc_now
from .regulatory import MAX_DOCUMENTS, REGISTER, SETTLEMENT_NOTE
from .reports import markdown
from .session import analysis_label, assumptions, database, fixture, launch, library, reasoner, save_assumptions, source_filters
from .visuals import chip, evidence, header, heading, info, kind_tag, kpi, kpi_grid, local_time, rows, steps

LOG = logging.getLogger(__name__)
QUESTIONS = (
    "Quali fattori incidono sulla domanda di gas?",
    "Ci sono anomalie nelle ultime osservazioni?",
    "Come è cambiata la domanda rispetto alla settimana precedente?",
    "Cosa succede se la domanda aumenta del 10%?",
    "Qual è l’esposizione finanziaria nella simulazione di regolazione?",
    "Come definisce il Codice di Rete il bilanciamento commerciale?",
    "Quali incongruenze emergono nei documenti normativi?",
    "Prepara un bollettino sul mercato del gas.",
)


def _settlement_panel() -> None:
    state=assumptions()
    mode=st.radio("Tipo di calcolo",["Semplice","Completo"],horizontal=True,
                  key="balancing_mode",help="Completo: aggiunge stoccaggio e transazioni nette al PSV.")
    advanced=mode=="Completo"
    saved=st.session_state.get("commercial_settlement") if advanced else None
    inputs=(CommercialInput.model_validate(saved) if saved else CommercialInput(**state.settlement.model_dump())) if advanced else state.settlement
    st.caption("Partecipante ipotetico · volumi e prezzi inseriti dall’utente · importi prima delle imposte.")
    form,output=st.columns([1,1.2],gap="medium")
    with form,st.container(border=True,key="panel_settlement_input"):
        st.subheader("1. Inserisci i dati")
        with st.form("settlement_form_"+mode,border=False):
            unit=st.selectbox("Unità dei volumi",("kWh","MWh","GWh"),index=("kWh","MWh","GWh").index(inputs.unit))
            def field(label,value,help=None):
                return st.text_input(label,str(value) if value is not None else "",max_chars=25,help=help)
            st.caption("Volumi di gas")
            a,b=st.columns(2)
            with a:
                delivered=field("Immissioni",inputs.delivered,"Gas immesso in rete.")
            with b:
                withdrawn=field("Prelievi",inputs.withdrawn,"Gas prelevato dalla rete.")
            if advanced:
                a,b=st.columns(2)
                with a:
                    storage=field("Stoccaggio netto",inputs.storage_net,"Prelievo da stoccaggio positivo, iniezione negativa.")
                with b:
                    psv=field("Transazioni nette (PSV)",inputs.psv_net,"Acquisti positivi, vendite negative. Inserisci il termine netto completo.")
            st.caption("Prezzi di sbilanciamento (€/MWh)")
            a,b=st.columns(2)
            with a:
                buy=field("Prezzo di acquisto",inputs.buy_eur_mwh)
            with b:
                sell=field("Prezzo di vendita",inputs.sell_eur_mwh)
            submitted=st.form_submit_button("Calcola sbilanciamento",type="primary",width="stretch")
        invalid=False
        if submitted:
            try:
                values=dict(delivered=delivered,withdrawn=withdrawn,unit=unit,buy_eur_mwh=buy,sell_eur_mwh=sell)
                if advanced:
                    inputs=CommercialInput(**values,storage_net=storage,psv_net=psv)
                    st.session_state["commercial_settlement"]=inputs.model_dump(mode="json")
                else:
                    inputs=SettlementInput(**values)
                    save_assumptions(state.model_copy(update={"settlement":inputs}))
            except ValidationError as error:
                labels={"delivered":"immissioni","withdrawn":"prelievi","buy_eur_mwh":"prezzo di acquisto",
                        "sell_eur_mwh":"prezzo di vendita","storage_net":"stoccaggio","psv_net":"transazioni nette"}
                st.error("Controlla: "+", ".join(labels.get(e["loc"][0],"unità") for e in error.errors())+
                         ". Il risultato precedente resta visibile.")
                invalid=True
        if advanced:
            st.caption("Calcolo completo indipendente: il bollettino AI conserva le ipotesi del calcolo semplice.")
    with output,st.container(border=True,key="panel_settlement_output"):
        st.subheader("2. Risultato")
        if invalid:
            st.caption("Ultimo risultato valido, non i valori appena inseriti.")
        result=settle_commercial(inputs) if advanced else settle(inputs)
        ds=result.imbalance_mwh
        cash=result.cash_flow_eur
        position="Non disponibile" if ds is None else "Carenza di gas" if ds<0 else "Eccesso di gas" if ds>0 else "In equilibrio"
        money="Non disponibile" if cash is None else "Addebito" if cash<0 else "Credito" if cash>0 else "Nessun flusso"
        st.markdown("**"+position+"**")
        kpi_grid([
            ("Saldo energetico",ds,"MWh","Immissioni + saldi netti − prelievi" if advanced else "Immissioni − prelievi",2,""),
            ("Flusso economico",cash,"€",money,2,"rose" if cash is not None and cash<0 else "teal" if cash is not None and cash>0 else ""),
        ])
        if ds is not None:
            if ds==0:
                st.write("Le quantità di gas sono in equilibrio.")
            else:
                st.write("Per annullare lo sbilanciamento servirebbe un aggiustamento netto di "+
                         numero(abs(ds),2)+" MWh "+("in aumento." if ds<0 else "in diminuzione."))
        rows([("Operazione applicata",ESITI[result.side] if result.side else "Non disponibile"),
              ("Prezzo applicato",_readout(result.price_eur_mwh,"€/MWh"))])
        for issue in result.problems:
            st.warning(issue)
        if result.price_eur_mwh is not None and result.price_eur_mwh<0:
            st.warning("Prezzo negativo: carenza/eccesso e addebito/credito possono avere segni diversi. Verifica il caso prima di ogni uso operativo.")
        with st.expander("Quanto cambia il risultato se cambia il prezzo?"):
            sensitivity=settlement_sensitivity(result)
            if sensitivity:
                st.caption("Variazione ipotetica di ±10 €/MWh, con saldo energetico invariato.")
                st.dataframe([{"Prezzo (€/MWh)":float(p),"Flusso (€)":float(v)} for p,v in sensitivity],
                             hide_index=True,width="stretch",column_config={"Prezzo (€/MWh)":st.column_config.NumberColumn(format="%.2f"),
                                                                         "Flusso (€)":st.column_config.NumberColumn(format="%.2f")})
            else:
                st.caption("Servono uno sbilanciamento non nullo e il prezzo applicabile.")
        with st.expander("Formula, unità e riferimenti"):
            if advanced:
                st.latex(r"DS_k=I_k+S_k+T_k^N-P_k")
                st.caption("Edizione di studio: CdR XCII, cap. 9 §3.1.2. S e T sono saldi netti con segno.")
            else:
                st.latex(r"DS=I-P")
                st.caption("Esempio semplificato: stoccaggio e transazioni nette pari a zero.")
            st.write("Flusso economico = saldo in MWh × prezzo applicabile. Negativo: addebito; positivo: credito. Calcolo dimostrativo, non fattura ufficiale.")
            evidence([SETTLEMENT_NOTE])
        st.download_button("Scarica simulazione",json.dumps({"tipo":"SIMULAZIONE","modalita":mode,
                           "inputs":inputs.model_dump(mode="json"),"risultato":result.model_dump(mode="json")},ensure_ascii=False,indent=2),
                           "gasops-bilanciamento.json","application/json",key="balance_download",icon=":material/download:")


def _readout(number, unit: str) -> str:
    return "Non disponibile" if number is None else f"{numero(number, 2)} {unit}"


def _scenario_panel() -> None:
    state=assumptions()
    changes=state.stress
    selected=st.session_state.get("active_bundle")
    data=selected or fixture()
    facts=MarketContext(data,state.model,utc_now()).facts
    if not facts or facts.get("demand_gwh") is None or facts.get("supply_gwh") is None:
        data=fixture()
        facts=MarketContext(data,state.model,utc_now()).facts
        st.warning("La fonte selezionata non contiene domanda e offerta confrontabili. Scenario basato su dati di esempio.")
    saved_key=f"scenario_case_{data.fingerprint}"
    saved=st.session_state.get(saved_key)
    try:
        case=ScenarioCase.model_validate(saved or facts)
        scenario(case,ScenarioInput(demand_pct=0))
    except (ValueError,ArithmeticError):
        st.error("I valori di base non sono validi. Seleziona dati di esempio nella panoramica.")
        return
    if case.storage_gwh is None and changes.storage_pct:
        changes=changes.model_copy(update={"storage_pct":0})
        st.warning("Contributo stoccaggio non disponibile: la variazione stoccaggio è sospesa per questa simulazione.")
    grain="GWh/mese" if data.origin.grain=="monthly" else "GWh/giorno gas"
    st.markdown("**"+("Simulazione · dati fittizi" if data.origin.kind==Kind.SYNTHETIC else "Italia · bilancio nazionale mensile" if data.origin.grain=="monthly" else "Serie selezionata")+"**")
    st.caption(data.origin.name+" · "+facts.get("label","periodo non disponibile")+" · "+grain+
               (" · base modificata dall’utente" if saved else " · base di riferimento"))
    if data.origin.grain=="monthly":
        st.caption("Disponibilità contabile, non offerta fisica della rete.")
    st.caption("Scenario ipotetico, non previsione né sbilanciamento ufficiale del sistema.")
    form,output=st.columns([1,1.2],gap="medium")
    with form,st.container(border=True,key="panel_scenario_input"):
        st.subheader("1. Imposta lo scenario")
        with st.form(f"scenario_form_{data.fingerprint[:12]}",border=False):
            demand_pct=st.slider("Variazione della domanda (%)",-100.,300.,float(changes.demand_pct),1.)
            supply_pct=st.slider("Variazione dell’offerta escluso stoccaggio (%)",-100.,300.,float(changes.supply_pct),1.)
            with st.expander("Valori di base e altre ipotesi"):
                demand=st.number_input("Domanda di base (GWh)",min_value=0.0,value=float(case.demand_gwh),step=10.)
                supply=st.number_input("Offerta totale di base (GWh)",min_value=0.0,value=float(case.supply_gwh),step=10.)
                storage=st.number_input("Contributo dello stoccaggio (GWh)",min_value=0.0,value=float(case.storage_gwh) if case.storage_gwh is not None else None)
                storage_pct=st.number_input("Variazione stoccaggio (%)",-100.0,300.0,float(changes.storage_pct))
                price=st.number_input("Prezzo di riferimento (€/MWh)",value=float(case.price_eur_mwh) if case.price_eur_mwh is not None else None)
                price_delta=st.number_input("Variazione prezzo (€/MWh)",-1000.0,1000.0,float(changes.price_delta_eur_mwh))
            submitted=st.form_submit_button("Simula scenario",type="primary",width="stretch")
        if submitted:
            try:
                candidate=ScenarioCase(demand_gwh=demand,supply_gwh=supply,storage_gwh=storage,price_eur_mwh=price)
                updated=ScenarioInput(demand_pct=demand_pct,supply_pct=supply_pct,storage_pct=storage_pct,price_delta_eur_mwh=price_delta)
                scenario(candidate,updated)
                case,changes=candidate,updated
                st.session_state[saved_key]=case.model_dump(mode="json")
                save_assumptions(state.model_copy(update={"stress":changes}))
            except (ValueError,ArithmeticError) as error:
                st.error("Ipotesi non valide: "+str(error)+". Resta visibile lo scenario precedente.")
        info("Info scenario","Lo stoccaggio è già incluso nell’offerta totale. I cambiamenti si applicano separatamente alle altre fonti e allo stoccaggio.",
             "Il Centro operativo usa gli scostamenti salvati e la propria fonte di riferimento; la base personalizzata resta in questa pagina.")
    with output,st.container(border=True,key="panel_scenario_output"):
        st.subheader("2. Impatto dello scenario")
        base=scenario(case,ScenarioInput(demand_pct=0))
        stress=scenario(case,changes)
        balance_label="Carenza" if stress.imbalance_gwh<0 else "Eccesso" if stress.imbalance_gwh>0 else "Equilibrio"
        st.markdown("**"+balance_label+" nello scenario**")
        kpi_grid([
            ("Saldo semplificato",stress.imbalance_gwh,grain,"Offerta − domanda",1,""),
            ("Copertura della domanda",stress.coverage_pct,"%","Offerta / domanda",1,""),
        ])
        comparison=pd.DataFrame({"Domanda":[float(base.demand_gwh),float(stress.demand_gwh)],
                                 "Offerta":[float(base.supply_gwh),float(stress.supply_gwh)]},index=["Base","Scenario"])
        st.caption("Domanda e offerta · "+grain)
        st.bar_chart(comparison,stack=False)
        if stress.gap_value_eur is not None:
            kpi("Valore indicativo del saldo",stress.gap_value_eur,"€","Non è settlement né fattura",0)
        with st.expander("Confronto numerico"):
            st.dataframe([{"Indicatore":label,"Base":_readout(getattr(base,field),unit),
                           "Scenario":_readout(getattr(stress,field),unit)}
                for label,field,unit in (("Domanda","demand_gwh",grain),("Offerta","supply_gwh",grain),
                    ("Stoccaggio","storage_gwh",grain),("Copertura","coverage_pct","%"),
                    ("Saldo","imbalance_gwh",grain),("Prezzo","price_eur_mwh","€/MWh"),
                    ("Valore saldo","gap_value_eur","€"))],hide_index=True,width="stretch")
        if stress.gap_value_eur is not None and base.gap_value_eur is not None:
            st.caption("Variazione del valore del saldo: "+numero(stress.gap_value_eur-base.gap_value_eur,0,signed=True)+" €.")


def balancing() -> None:
    header("Bilanciamento", f'{kind_tag(Kind.SIMULATION)} <span>Calcoli illustrativi · nessuna operazione reale</span>')
    participant, aggregate = st.tabs(["Sbilanciamento del partecipante", "Scenario di mercato"])
    with participant:
        _settlement_panel()
    with aggregate:
        _scenario_panel()


def _sync_uploads() -> None:
    files = st.session_state.get("reg_upload") or []
    st.session_state["pdf_uploads"] = tuple((item.name, item.getvalue()) for item in files[:MAX_DOCUMENTS])


def _reg_register() -> None:
    filters = {"all": "Tutti i rilievi", **GRAVITA}
    severity = st.selectbox("Gravità", tuple(filters), format_func=filters.__getitem__, key="reg_severity")
    cases = [entry for entry in REGISTER if severity == "all" or entry.finding.severity == severity]
    st.dataframe(
        [{"Rilievo": case.finding.title, "Gravità": GRAVITA[case.finding.severity],
          "Classificazione": case.finding.category, "Verifica dell’edizione": case.review} for case in cases],
        hide_index=True, width="stretch", height=40 + 36 * len(cases),
    )
    title = st.selectbox("Esamina il rilievo", [case.finding.title for case in cases], key="reg_finding")
    case = next(entry for entry in cases if entry.finding.title == title)
    with st.container(border=True, key="panel_reg_finding"):
        heading(case.finding.title, chip(GRAVITA[case.finding.severity].upper(), case.finding.severity))
        st.write(case.finding.detail)
        st.caption(case.review)
        evidence(case.finding.citations)


def _reg_query(docs) -> None:
    kind = st.radio("Modalità di ricerca", ["Fai una domanda", "Cerca nei documenti"], horizontal=True)
    available = ["Tutti i materiali indicizzati", *docs.documents]
    with st.form("reg_ask_form"):
        document = st.selectbox("Documento", available, disabled=kind == "Fai una domanda")
        query = st.text_input("Domanda o parole da cercare", placeholder="Come definisce il Codice di Rete il bilanciamento commerciale?",
                              max_chars=600)
        submitted = st.form_submit_button("Interroga l’analista" if kind == "Fai una domanda" else "Trova i riferimenti", type="primary")
    if submitted and not query.strip():
        st.warning("Inserisci una domanda o un termine di ricerca.")
    if submitted and query.strip():
        if kind == "Cerca nei documenti":
            found = docs.search(query, document=None if document == available[0] else document)
            st.session_state["reg_answer"] = (query, None, [hit.citation for hit in found], None, None)
        else:
            result = regulation_result(docs, RegulationArguments(query=query))
            interpretation, warning = None, None
            model = reasoner()
            if model and model.config.local and result.evidence:
                try:
                    interpretation, _ = model.interpret(query, {Agent.REGULATORY: result})
                except Exception as error:
                    LOG.warning("Regulatory interpretation unavailable (%s)", type(error).__name__)
                    warning = "Modello non disponibile. Puoi consultare i riferimenti qui sotto."
            st.session_state["reg_answer"] = (query, result.summary, result.evidence, interpretation, warning)
    answer = st.session_state.get("reg_answer")
    if answer:
        objective, summary, citations, narrative, warning = answer
        with st.container(border=True, key="panel_reg_answer"):
            heading("Riscontri nei documenti", chip(f"{len(citations)} RIFERIMENTI"))
            st.text(objective)
            if summary:
                st.text(summary)
            if warning:
                st.warning(warning)
            if narrative:
                st.caption("Interpretazione del modello sulle edizioni citate, da rivedere")
                st.text(narrative)
            if citations:
                evidence(citations)
            else:
                st.info("Nessun passaggio pertinente. Prova una frase del documento o carica un’edizione con testo ricercabile.")


def _reg_explorer(docs) -> None:
    if not docs.documents:
        st.info("Carica un PDF con testo ricercabile per aprire le pagine originali. Il registro contiene le note sulle edizioni esaminate.")
        return
    selected = st.selectbox("Documento PDF", list(docs.documents), key="reg_doc")
    document = docs.documents[selected]
    # The document itself provides the page numbers, including covers and contents.
    page = st.number_input("Pagina PDF", min_value=1, max_value=document.pages, step=1, value=1,
                           key=f"reg_page_{document.digest[:10]}")
    st.download_button("Scarica il PDF locale", document.data, file_name=document.name, mime="application/pdf",
                       icon=":material/download:")
    if st.button("Apri la pagina", type="primary", key="reg_open_page"):
        st.session_state["opened_pdf"] = (document.digest, int(page))
    if st.session_state.get("opened_pdf") == (document.digest, int(page)):
        st.image(document.render(int(page)), caption=f"{selected} · PDF p. {page}", width=690)
    with st.expander("Impronta dell’edizione"):
        st.code(document.digest, language=None)


def regulatory() -> None:
    header("Norme e documenti", '<span>Edizioni esaminate · applicabilità attuale da verificare</span>')
    left, right = st.columns([1.65, 1], gap="medium")
    with left:
        st.file_uploader("Aggiungi PDF con testo ricercabile", type=["pdf"], accept_multiple_files=True, key="reg_upload",
                         on_change=_sync_uploads)
    docs = library()
    with right, st.container(border=True, key="panel_reg_library"):
        heading("Archivio documenti", chip(f"{len(docs.documents)} PDFS"))
        if docs.documents:
            rows((title, f"{pdf.pages} pagine") for title, pdf in docs.documents.items())
        else:
            st.caption("Le note sulle edizioni esaminate sono disponibili offline.")
        for warning in docs.errors:
            st.warning(warning)
    register, ask, explorer = st.tabs(["Punti da verificare", "Ricerca e domande", "Leggi i documenti"])
    with register:
        _reg_register()
    with ask:
        _reg_query(docs)
    with explorer:
        _reg_explorer(docs)


def _example_question() -> None:
    chosen = st.session_state.get("ops_example")
    if chosen in QUESTIONS:
        st.session_state["ops_question"] = chosen


def _review_queue(report: Run, reviewed: dict[str, str]) -> None:
    queue = sorted(
        (finding for finding in report.findings if finding.severity != "info"),
        key=lambda f: (f.id in reviewed, f.severity != "high"),
    )
    heading("Coda di revisione", chip(f"{sum(f.id not in reviewed for f in queue)} APERTI", "review"))
    if not queue:
        st.caption("Nessun rilievo da rivedere in questa esecuzione.")
        return
    labels = {f.id: f"{'In carico' if f.id in reviewed else GRAVITA[f.severity]} · {f.title}" for f in queue}
    key = st.selectbox("Rilievo", list(labels), format_func=labels.__getitem__, key=f"review_item_{report.id}")
    finding = next(f for f in queue if f.id == key)
    st.caption(finding.category)
    st.text(finding.detail)
    evidence(finding.citations)
    if finding.id in reviewed:
        st.caption(f"Preso in carico il {local_time(datetime.fromisoformat(reviewed[finding.id]))}")
    elif st.button("Prendi in carico", key=f"review_{report.id}_{finding.id}", icon=":material/check:"):
        try:
            database().acknowledge(report.id, finding.id)
            st.rerun()
        except sqlite3.Error:
            LOG.exception("Unable to acknowledge finding")
            st.error("Impossibile salvare il rilievo nello storico locale.")


def _report_panel(report: Run) -> None:
    reviewed = database().reviewed(report.id)
    main, side = st.columns([1.9, 1], gap="medium")
    with main, st.container(border=True, key="panel_ops_summary"):
        heading("Sintesi operativa", chip(MODALITA[report.mode], "ok" if report.mode == "LLM-assisted" else ""))
        rows([("Fonte dati", report.source.name), ("Fine analisi", local_time(report.finished_at)), ("ID analisi", report.id[:12])])
        if report.model:
            st.caption("Modello selezionato: "+report.model)
        for warning in report.warnings:
            st.warning(warning)
        if report.assumptions.get("public_operational_context"):
            with st.expander("Fonti operative del briefing"):
                st.json(report.assumptions["public_operational_context"],expanded=False)
        if report.interpretation:
            st.markdown("**Interpretazione AI · da verificare**")
            st.text(report.interpretation)
            st.caption("Strumenti consultati · " + ", ".join(AGENT_LABELS[agent] for agent in report.interpretation_sources))
        else:
            st.caption("Nessuna interpretazione AI generata: risultati dei calcoli locali.")
        for agent in Agent:
            if agent in report.results:
                result = report.results[agent]
                st.markdown(f"**{AGENT_LABELS[agent]}**")
                st.text(result.summary)
        a, b = st.columns(2)
        suffix = report.id[:10]
        with a:
            payload = {**report.model_dump(mode="json"), "acknowledged_findings": reviewed}
            st.download_button("Scarica JSON", json.dumps(payload, ensure_ascii=False, indent=2),
                               f"gasops-{suffix}.json", mime="application/json", icon=":material/download:", width="stretch")
        with b:
            st.download_button("Scarica Markdown", markdown(report, reviewed), f"gasops-{suffix}.md",
                               mime="text/markdown", icon=":material/download:", width="stretch")
    with side, st.container(border=True, key="panel_ops_review"):
        _review_queue(report, reviewed)

    with st.container(border=True, key="panel_ops_trace"):
        conflict = any(item.category == "Validazione indipendente" for item in report.findings)
        verification = chip("CONFLITTO RILEVATO", "high") if conflict else chip("VALIDAZIONE COMPLETATA", "ok")
        heading("Esecuzione degli agenti e riscontri", verification if report.validated_at else "")
        with st.expander("Dati di ingresso e impronta del dataset"):
            st.code(report.input_sha256, language=None)
            st.json(report.assumptions, expanded=False)
        for agent in Agent:
            if agent not in report.results:
                continue
            item = report.results[agent]
            step = report.steps[agent]
            with st.expander(f"{AGENT_LABELS[agent]} · {ESITI[step.status]}"):
                if step.started_at and step.finished_at:
                    elapsed = (step.finished_at - step.started_at).total_seconds()
                    st.caption(f"{local_time(step.started_at)} · {numero(elapsed * 1000, 0)} ms")
                st.text(item.summary)
                evidence(item.evidence)
                if item.values:
                    st.json(item.values, expanded=False)
                for finding in item.findings:
                    st.caption(f"{GRAVITA[finding.severity].upper()} · {finding.title}. {finding.detail}")


def operations() -> None:
    top, controls = st.container(), st.container()
    with controls:
        selection = source_filters("ops", lookback=False)
    with top:
        started = header("Assistente AI", selection.meta, analysis_label(), disabled=selection.bundle is None)
    st.caption("Genera un bollettino o chiedi un approfondimento. Il risultato appare qui sotto.")
    with st.container(border=True, key="panel_ops_query"):
        heading("Fai una domanda sul gas")
        st.caption("Usa solo domande e dati pubblici o sintetici; non inserire informazioni riservate.")
        st.selectbox("Domanda di esempio", ["Scegli un esempio", *QUESTIONS], key="ops_example", on_change=_example_question)
        with st.form("ops_question_form", border=False):
            question = st.text_area("Richiesta di analisi", height=84, key="ops_question", max_chars=600,
                                    placeholder="Prepara un bollettino sul mercato del gas.")
            asked = st.form_submit_button("Invia la domanda", type="primary", disabled=selection.bundle is None)
    report = None
    if started:
        report = launch(selection, full=True)
    elif asked and question.strip():
        report = launch(selection, question)
    elif asked:
        st.warning("Inserisci una richiesta di analisi.")
    if report:
        st.session_state["ops_history"] = report.id

    history = database().recent()
    current = st.session_state.get("last_run")
    if current and all(item.id != current.id for item in history):
        history.insert(0, current)
    selected = None
    if history:
        entries = {run.id: run for run in history}
        chosen = st.selectbox(
            "Storico delle analisi", list(entries), key="ops_history",
            format_func=lambda item: f"{local_time(entries[item].started_at)} · {entries[item].question[:65]}",
        )
        selected = entries[chosen]
        _report_panel(selected)
    with st.expander("Flusso del supervisore",icon=":material/info:"):
        st.html('<div class="gas-flow-track"><span>Qualità</span><b>→</b><span>Agenti</span><b>→</b><span>Validazione</span><b>→</b><span>Report</span></div>')
        st.html(steps(selected,grid=True))
