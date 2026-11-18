from pathlib import Path

from streamlit.testing.v1 import AppTest

from gasops_app.forecast import AUTOMATIC, MODELS
from gasops_app.models import Agent
from gasops_app.public_data import SourceUnavailable
from gasops_app.session import ARCHIVE, DEMO


def test_overview_button_completes_offline_run(monkeypatch, tmp_path):
    monkeypatch.setenv("GASOPS_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("GASOPS_PDF_DIR", str(tmp_path))
    monkeypatch.setenv("GASOPS_LLM_MODEL", "")
    monkeypatch.delenv("GROQ_API_KEY",raising=False)
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / "app.py", default_timeout=30)
    app.session_state["selected_source"] = DEMO
    app.run()
    assert not app.exception
    assert app.title[0].value == "Panoramica del mercato"
    assert app.button(key="analysis_launch").label == "Genera bollettino di mercato"
    assert any("Nessun bollettino generato" in e.value for e in app.caption)
    assert app.selectbox(key="overview_model").value == AUTOMATIC
    app.button(key="analysis_launch").click().run()
    assert not app.exception
    report = app.session_state["last_run"]
    assert report.finished_at and len(report.results) == 6
    assert app.session_state["last_briefing"].id == report.id
    assert any("Ultimo bollettino generato" in e.value for e in app.markdown)
    assert any(m.label=="Modalità effettiva" and m.value=="Deterministica" for m in app.metric)
    assert any("Scarica bollettino"==b.proto.label for b in app.get("download_button"))
    projection = report.results[Agent.FORECAST].values["forecast"]
    assert projection["model"] in MODELS
    assert projection["interval_kind"] in ("posterior", "empirical", "model_based")


def test_unavailable_public_feed_can_open_the_real_offline_archive(monkeypatch, tmp_path):
    monkeypatch.setenv("GASOPS_STATE_DIR", str(tmp_path))

    def unavailable(*args, **kwargs):
        raise SourceUnavailable("Eurostat non disponibile")

    monkeypatch.setattr("gasops_app.session.load_monthly", unavailable)
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / "app.py", default_timeout=30).run()
    assert app.error[0].value == "Eurostat non disponibile"
    app.button(key="overview_archive").click().run()
    assert not app.exception
    assert app.selectbox(key="overview_dataset").value == ARCHIVE
    assert app.session_state["active_bundle"].origin.archive


def test_operational_sources_visible_when_entsog_unavailable(monkeypatch,tmp_path):
    from gasops_app.session import DAILY
    monkeypatch.setenv("GASOPS_STATE_DIR",str(tmp_path))
    monkeypatch.delenv("GASOPS_GIE_API_KEY",raising=False)
    monkeypatch.delenv("GASOPS_AGSI_API_KEY",raising=False)
    def unavailable(*args,**kwargs):
        raise SourceUnavailable("ENTSOG non disponibile")
    monkeypatch.setattr("gasops_app.session.load_daily",unavailable)
    app=AppTest.from_string("from gasops_app.dashboard import market\nmarket()",default_timeout=30)
    app.session_state["selected_source"]=DAILY
    app.run()
    assert not app.exception
    assert app.error[0].value=="ENTSOG non disponibile"
    assert any("Security of supply" in el.value for el in app.markdown)
    sources=AppTest.from_string("from gasops_app.operational_sources_page import operational_context\noperational_context()",default_timeout=30).run()
    assert not sources.exception
    assert sources.radio(key="operational_platform").value=="AGSI+"


def test_agsi_is_default_and_loads_independently(monkeypatch,tmp_path):
    from datetime import timedelta
    import json
    from gasops_app.models import utc_now
    from gasops_app.data import ROME
    from gasops_app.operational_sources import parse_agsi
    from gasops_app import operational_sources_page as op
    monkeypatch.setenv("GASOPS_STATE_DIR",str(tmp_path))
    monkeypatch.setenv("GASOPS_GIE_API_KEY","fixture-key")
    monkeypatch.setattr(op,"configured_key",lambda:"fixture-key")
    calls=[]
    def fake(store,key,scope,**kwargs):
        calls.append(scope)
        now=utc_now()
        day=now.astimezone(ROME).date()-timedelta(days=1)
        payload={"last_page":1,"total":1,"data":[{"code":scope,"gasDayStart":day.isoformat(),
                 "gasInStorage":"90,5","workingGasVolume":"100","full":"90,5","withdrawal":"40","status":"C"}]}
        return parse_agsi(json.dumps(payload),now,scope=scope)
    monkeypatch.setattr(op,"load_agsi",fake)
    app=AppTest.from_string("from gasops_app.operational_sources_page import operational_context\noperational_context()",default_timeout=30).run()
    assert not app.exception
    assert calls==["IT"] and app.radio(key="operational_platform").value=="AGSI+"
    assert any("Giacenza" in e.proto.body for e in app.get("html"))
    assert any("Gas Infrastructure Europe" in el.value for el in app.markdown)
    app.run()
    assert calls==["IT"] and not app.exception
    app.selectbox(key="AGSI+_scope").select("EU").run()
    assert calls==["IT","EU"] and not app.exception


def test_entsog_notice_does_not_hide_other_warnings():
    from gasops_app.session import source_notices, ENTSOG_METADATA_NOTE
    assert source_notices(None)==("","")
    assert source_notices(ENTSOG_METADATA_NOTE)==("",ENTSOG_METADATA_NOTE)
    stale="Ultimo giorno completo non recente: verifica pubblicazione e disponibilità."
    assert source_notices(ENTSOG_METADATA_NOTE+" "+stale)==(stale,ENTSOG_METADATA_NOTE)
    assert source_notices(stale)==(stale,"")


def test_overview_quick_links_and_advanced_model(monkeypatch,tmp_path):
    monkeypatch.setenv("GASOPS_STATE_DIR",str(tmp_path))
    app=AppTest.from_file(Path(__file__).resolve().parents[1]/"app.py",default_timeout=30)
    app.session_state["selected_source"]=DEMO
    app.run()
    assert not app.exception
    assert any("modello previsionale" in e.label for e in app.expander)
    assert any("/security-of-supply" in el.value for el in app.markdown)
    assert app.selectbox(key="overview_model").value==AUTOMATIC
    assert app.selectbox(key="overview_dataset").value==DEMO



def test_iip_market_desk_filters_and_detail_without_more_network(monkeypatch,tmp_path):
    from gasops_app import operational_sources_page as op
    from gasops_app.models import utc_now
    from gasops_app.operational_sources import parse_iip
    import json
    monkeypatch.setenv("GASOPS_STATE_DIR",str(tmp_path))
    monkeypatch.setattr(op,"configured_key",lambda:"fixture-key")
    calls=[]
    def fake(store,key,**kwargs):
        calls.append(key)
        payload={"data":[{"messageId":"a","assetName":"Example A","countryCode":"IT","eventStatus":"Active"},
                         {"messageId":"b","assetName":"Example B","countryCode":"DE","eventStatus":"Active"}],
                 "meta":{"current_page":1,"last_page":1,"per_page":50,"total":2}}
        return {**parse_iip(json.dumps(payload),utc_now()),"request_from":"2026-11-18","request_to":"2026-11-25"}
    monkeypatch.setattr(op,"load_iip",fake)
    app=AppTest.from_string("from gasops_app.operational_sources_page import operational_context\noperational_context()",default_timeout=30)
    app.session_state["operational_platform"]="IIP"
    app.run()
    assert not app.exception
    assert len(app.dataframe)==1 and len(app.dataframe[0].value)==2
    assert any("2 / 2" in m.value for m in app.markdown)
    app.text_input(key="iip_search").set_value("Example B").run()
    assert not app.exception and len(app.dataframe[0].value)==1
    assert app.dataframe[0].value.iloc[0]["Asset"]=="Example B"
    assert len(calls)==1



def test_ai_diagnostics_visible_without_key(monkeypatch,tmp_path):
    from gasops_app import session
    monkeypatch.setattr(session,"_configuration",lambda:None)
    app=AppTest.from_string("from gasops_app.session import sidebar\nsidebar()").run()
    assert not app.exception
    assert any(e.label=="Connessione e limiti AI" for e in app.expander)
    assert any("AI non configurata" in e.value for e in app.caption)


def test_ai_connection_test_visible_in_deterministic_mode(monkeypatch,tmp_path):
    from gasops_app import session
    from gasops_app.llm import LLMConfig
    monkeypatch.setenv("GASOPS_STATE_DIR",str(tmp_path))
    monkeypatch.setattr(session,"_configuration",lambda:LLMConfig("fixture","https://api.groq.com/openai/v1","secret"))
    probes=[]
    monkeypatch.setattr(session.CompatibleReasoner,"probe",lambda self:probes.append(self.config.model) or True)
    app=AppTest.from_string("from gasops_app.session import sidebar\nsidebar()")
    app.session_state["execution_mode"]="Deterministic"
    app.run()
    assert not app.exception
    assert any(e.label=="Connessione e limiti AI" for e in app.expander)
    app.button(key="sidebar_llm_probe").click().run()
    assert not app.exception and probes==["fixture"]
    assert any("verificate" in e.value for e in app.success)



def test_briefing_keeps_previous_report_when_source_changes(monkeypatch,tmp_path):
    from gasops_app import session
    from gasops_app.agents import Assumptions, MarketContext
    from gasops_app.data import synthetic
    from gasops_app.models import utc_now
    from gasops_app.regulatory import Library
    from gasops_app.workflow import run_workflow
    monkeypatch.setenv("GASOPS_STATE_DIR",str(tmp_path))
    monkeypatch.setattr(session,"_configuration",lambda:None)
    report=run_workflow(MarketContext(synthetic(),"Seasonal regression",utc_now()),Library(),Assumptions(),full=True)
    report.assumptions["model"]="Seasonal regression"
    app=AppTest.from_file(Path(__file__).resolve().parents[1]/"app.py",default_timeout=30)
    app.session_state["selected_source"]=DEMO
    app.session_state["last_briefing"]=report
    app.run()
    assert not app.exception
    assert any("Bollettino precedente" in e.value for e in app.warning)
    assert any("Ultimo bollettino generato" in e.value for e in app.markdown)
    assert app.session_state["last_briefing"].id==report.id



def test_lean_interface_preserves_diagnostics_and_author_credit(monkeypatch,tmp_path):
    from gasops_app import session
    monkeypatch.setenv("GASOPS_STATE_DIR",str(tmp_path))
    monkeypatch.setattr(session,"_configuration",lambda:None)
    app=AppTest.from_file(Path(__file__).resolve().parents[1]/"app.py",default_timeout=30)
    app.session_state["selected_source"]=DEMO
    app.run()
    assert not app.exception
    assert any("Prototipo per SNAM creato da Igor" in e.proto.body for e in app.get("html"))
    assert any(e.label=="Connessione e limiti AI" for e in app.expander)
    assert any("Dati sintetici" in e.value for e in app.caption)
    assert app.button(key="analysis_launch").label=="Genera bollettino di mercato"


def test_ai_sidebar_survives_stale_store_instance(monkeypatch):
    from gasops_app import session
    from gasops_app.llm import LLMConfig
    from gasops_app.supervisor import ModelUnavailable
    import pytest
    monkeypatch.setattr(session,"_configuration",lambda:LLMConfig("fixture","https://api.groq.com/openai/v1","secret"))
    monkeypatch.setattr(session,"database",lambda:object())
    app=AppTest.from_string("from gasops_app.session import sidebar\nsidebar()").run()
    assert not app.exception
    assert any("Contatore AI non disponibile" in e.value for e in app.warning)
    assert app.button(key="sidebar_llm_probe").disabled
    with pytest.raises(ModelUnavailable,match="richiesta bloccata"):
        session._reserve_remote_request()


def test_store_wrapper_is_fresh_without_resetting_persisted_budget(tmp_path):
    from gasops_app.session import store
    old=store(str(tmp_path))
    assert old.reserve_llm()
    new=store(str(tmp_path))
    assert old is not new
    assert new.llm_usage()==1
    assert old.path==new.path


def test_overview_has_plain_language_and_responsive_cards(monkeypatch,tmp_path):
    from gasops_app import session
    monkeypatch.setenv("GASOPS_STATE_DIR",str(tmp_path))
    monkeypatch.setattr(session,"_configuration",lambda:None)
    app=AppTest.from_file(Path(__file__).resolve().parents[1]/"app.py",default_timeout=30)
    app.session_state["selected_source"]=DEMO
    app.run()
    assert not app.exception
    assert any(e.value=="Il mercato in breve" for e in app.subheader)
    assert any("Nella simulazione, i consumi" in e.value or "Dati insufficienti" in e.value for e in app.markdown)
    assert any('gas-kpi-grid' in e.proto.body for e in app.get("html"))
    assert app.button(key="analysis_launch").label=="Genera bollettino di mercato"
    assert any(e.label=="Fonti e aggiornamento" for e in app.expander)


def test_market_scope_explicit_and_source_failure_preserves_scope(monkeypatch,tmp_path):
    from gasops_app.session import market_scope, PUBLIC, DAILY, ARCHIVE, DEMO
    assert market_scope(PUBLIC)==("Italia","Bilancio nazionale mensile")
    assert "non totale nazionale" in market_scope(DAILY)[1]
    assert "2015–2021" in market_scope(ARCHIVE)[1]
    assert market_scope(DEMO)[0]=="Simulazione"
    monkeypatch.setenv("GASOPS_STATE_DIR",str(tmp_path))
    def unavailable(*args,**kwargs):
        raise SourceUnavailable("Fonte non disponibile")
    monkeypatch.setattr("gasops_app.session.load_daily",unavailable)
    app=AppTest.from_string("from gasops_app.dashboard import market\nmarket()",default_timeout=30)
    app.session_state["selected_source"]=DAILY
    app.run()
    assert not app.exception
    assert any("Italia · rete Snam (SRG)" in e.value and "non totale nazionale" in e.value for e in app.markdown)
    assert app.error[0].value=="Fonte non disponibile"


def test_market_layout_and_no_weather_request_for_demo(monkeypatch,tmp_path):
    monkeypatch.setenv("GASOPS_STATE_DIR",str(tmp_path))
    def forbidden(*args,**kwargs):
        raise AssertionError("Weather unavailable for demo")
    monkeypatch.setattr("gasops_app.weather_page.analyse_gas_day",forbidden)
    app=AppTest.from_string("from gasops_app.dashboard import market\nmarket()",default_timeout=30)
    app.session_state["selected_source"]=DEMO
    app.run()
    assert not app.exception
    assert any("**Simulazione**" in e.value for e in app.markdown)
    assert [tab.label for tab in app.tabs]==["Consumi e previsioni","Composizione e prezzi","Meteo","Modelli e dati"]
    assert any("Variazione dei consumi" in e.proto.body for e in app.get("html"))
    assert any("Dati osservati e previsioni"==e.label for e in app.expander)
    assert any("Provenienza e metodologia"==e.label for e in app.expander)



def test_supply_snapshot_same_day_and_exact_week():
    from datetime import date,timedelta
    import pandas as pd
    from gasops_app.supply_view import inventory_snapshot,chart_window,scope_label
    day=date(2026,11,17)
    frame=pd.DataFrame([
        {"gas_day":day-timedelta(days=7),"stock_twh":80.,"fill_pct":80.,"withdrawal_gwh_d":3.},
        {"gas_day":day-timedelta(days=1),"stock_twh":79.,"fill_pct":79.,"withdrawal_gwh_d":4.},
        {"gas_day":day,"stock_twh":78.,"fill_pct":78.,"withdrawal_gwh_d":None}])
    latest,changes=inventory_snapshot(frame,"AGSI+")
    assert latest["gas_day"]==day and pd.isna(latest["withdrawal_gwh_d"])
    assert changes["fill_pct"]==-2 and "withdrawal_gwh_d" not in changes
    chart=chart_window(frame,30)
    assert len(chart)==30 and chart["stock_twh"].notna().sum()==3
    assert scope_label("IT")=="Italia" and "GIE" in scope_label("EU")


def test_supply_alsi_latest_day_with_energy_only():
    import pandas as pd
    from datetime import date
    from gasops_app.supply_view import inventory_snapshot
    frame=pd.DataFrame([{"gas_day":date(2026,11,16),"sendout_gwh_d":200.,"inventory_1000m3_lng":100.,"inventory_gwh":None},
                        {"gas_day":date(2026,11,17),"sendout_gwh_d":None,"inventory_1000m3_lng":None,"inventory_gwh":50.}])
    latest,changes=inventory_snapshot(frame,"ALSI")
    assert latest["gas_day"]==date(2026,11,17) and latest["inventory_gwh"]==50.
    assert pd.isna(latest["sendout_gwh_d"]) and changes=={}



def test_balancing_page_simple_and_complete(monkeypatch,tmp_path):
    monkeypatch.setenv("GASOPS_STATE_DIR",str(tmp_path))
    app=AppTest.from_string("from gasops_app.workbench import balancing\nbalancing()",default_timeout=30).run()
    assert not app.exception
    assert [tab.label for tab in app.tabs]==["Sbilanciamento del partecipante","Scenario di mercato"]
    assert any("Saldo energetico" in e.proto.body for e in app.get("html"))
    app.radio(key="balancing_mode").set_value("Completo").run()
    assert not app.exception
    assert any(e.label=="Stoccaggio netto" for e in app.text_input)
    assert any(e.label=="Transazioni nette (PSV)" for e in app.text_input)
    assert any("Calcolo completo indipendente" in e.value for e in app.caption)
    for widget in app.text_input:
        if widget.label=="Stoccaggio netto":
            widget.set_value("300")
        elif widget.label=="Transazioni nette (PSV)":
            widget.set_value("-200")
    next(b for b in app.button if b.label=="Calcola sbilanciamento").click().run()
    assert not app.exception
    assert app.session_state["commercial_settlement"]["storage_net"]=="300"
    assert any("1.100,00" in e.proto.body and "46.200,00" in e.proto.body for e in app.get("html"))


def test_balancing_missing_storage_shock_does_not_crash(monkeypatch,tmp_path):
    from gasops_app.data import synthetic
    from gasops_app.agents import Assumptions
    monkeypatch.setenv("GASOPS_STATE_DIR",str(tmp_path))
    app=AppTest.from_string("from gasops_app.workbench import balancing\nbalancing()",default_timeout=30)
    data=synthetic()
    app.session_state["active_bundle"]=data
    app.session_state["scenario_case_"+data.fingerprint]={"demand_gwh":"100","supply_gwh":"120","storage_gwh":None,"price_eur_mwh":"42"}
    ass=Assumptions()
    app.session_state["assumptions"]=ass.model_copy(update={"stress":ass.stress.model_copy(update={"storage_pct":10})}).model_dump(mode="json")
    app.run()
    assert not app.exception
    assert any("variazione stoccaggio è sospesa" in e.value for e in app.warning)



def test_commercial_workspace_updates_summary_and_calendar(monkeypatch,tmp_path):
    from datetime import date
    monkeypatch.setenv("GASOPS_STATE_DIR",str(tmp_path))
    app=AppTest.from_string("from gasops_app.operations_page import operations_ledger\noperations_ledger()",default_timeout=30).run()
    assert not app.exception
    assert [t.label for t in app.tabs]==["Fatture","Garanzie","Scadenze","Prezzi","Bilanci e GNL"]
    def summary():
        return next(e.proto.body for e in app.get("html") if "Partite da verificare" in e.proto.body)
    assert "4.200,00" in summary() and "92,0" in summary()
    app.number_input(key="invoice_amount_short").set_value(172200.).run()
    assert not app.exception and "4.200,00" not in summary()
    app.checkbox(key="invoice_present_long").set_value(False).run()
    assert not app.exception and "1 con importo non confrontabile" in summary()
    app.number_input(key="guarantee_limit").set_value(920000.).run()
    assert not app.exception and "100,0" in summary()
    app.date_input(key="invoice_date_short").set_value(date(2026,11,8)).run()
    assert not app.exception
    calendar=next(d.value for d in app.dataframe if "Adempimento" in d.value.columns)
    assert "Pagamento DEMO-FT-01" in calendar["Adempimento"].tolist()
    assert "Pagamento DEMO-FT-02" not in calendar["Adempimento"].tolist()
    assert str(calendar.loc[calendar["Adempimento"]=="Pagamento DEMO-FT-01","Data"].iloc[0])[:10]=="2026-11-23"
    app.toggle(key="ledger_revisions_only").set_value(True).run()
    assert not app.exception
    ledger=next(d.value for d in app.dataframe if "Delta DS" in d.value.columns)
    assert len(ledger)==1



def test_risk_workspace_stress_and_confidence_without_recompute(monkeypatch,tmp_path):
    monkeypatch.setenv("GASOPS_STATE_DIR",str(tmp_path))
    app=AppTest.from_string("from gasops_app.risk_page import risk_page\nrisk_page()",default_timeout=30).run()
    assert not app.exception
    app.selectbox(key="risk_preset").set_value("Stress combinato").run()
    assert not app.exception
    next(b for b in app.button if b.label=="Esegui simulazione").click().run()
    assert not app.exception
    saved=app.session_state["risk_workspace_v2"]
    assert saved["result"].summary["stress"]=={"demand_pct":10.,"supply_pct":-10.,"price_delta":10.}
    assert saved["result"].summary["probability_deficit"]>=saved["base"]["probability_deficit"]
    assert [tab.label for tab in app.tabs]==["Carenza di gas","Impatto economico","Ipotesi e metodo"]
    assert any("Probabilità di carenza" in e.proto.body for e in app.get("html"))
    first=saved["result"].summary["executed_at"]
    app.radio(key="risk_confidence").set_value("99").run()
    assert not app.exception
    assert app.session_state["risk_workspace_v2"]["result"].summary["executed_at"]==first
    assert any("Carenza al percentile 99" in e.proto.body for e in app.get("html"))
    app.selectbox(key="risk_preset").set_value("Base").run()
    assert not app.exception
    assert any("Fonte, previsione o scenario cambiati" in e.value for e in app.warning)



def test_document_desk_empty_state_has_no_precompiled_findings(monkeypatch,tmp_path):
    monkeypatch.setenv("GASOPS_PDF_DIR",str(tmp_path))
    app=AppTest.from_string("from gasops_app.document_page import document_page\ndocument_page()").run()
    assert not app.exception
    assert any("Aggiungi almeno un PDF" in e.value for e in app.info)
    assert not any("Preavviso di esattamente sette giorni" in e.value for e in app.markdown)


def test_document_desk_pdf_search_and_rag_without_model(monkeypatch,tmp_path):
    import pymupdf
    from gasops_app import document_page
    monkeypatch.setenv("GASOPS_PDF_DIR",str(tmp_path))
    monkeypatch.setattr(document_page,"reasoner",lambda:None)
    with pymupdf.open() as doc:
        doc.new_page().insert_text((80,80),"Garanzia economica con deposito cauzionale.")
        doc.save(tmp_path/"fixture.pdf")
    app=AppTest.from_string("from gasops_app.document_page import document_page\ndocument_page()").run()
    assert not app.exception
    next(e for e in app.text_input if e.label=="Cosa vuoi cercare?").set_value("garanzia economica")
    next(b for b in app.button if b.label=="Cerca nei PDF").click().run()
    assert not app.exception
    assert any("Garanzia economica" in e.value for e in app.text)
    app.radio(key="desk_mode").set_value("Chiedi all’AI").run()
    assert not app.exception
    assert next(b for b in app.button if b.label=="Chiedi ai documenti").disabled



def test_assistant_session_history_isolated_and_shortcut_works(monkeypatch,tmp_path):
    from gasops_app import session, assistant_page
    from gasops_app.models import Run
    from gasops_app.data import synthetic
    monkeypatch.setenv("GASOPS_STATE_DIR",str(tmp_path))
    monkeypatch.setenv("GASOPS_PDF_DIR",str(tmp_path))
    monkeypatch.setattr(session,"reasoner",lambda:None)
    monkeypatch.setattr(assistant_page,"reasoner",lambda:None)
    monkeypatch.setattr(assistant_page,"analysis_label",lambda:"Genera bollettino di mercato")
    db=session.database()
    data=synthetic()
    foreign=Run(question="DOMANDA_DI_UN_ALTRO_VISITATORE",source=data.origin,input_sha256=data.fingerprint,assumptions={})
    db.save(foreign)
    app=AppTest.from_string("from gasops_app.assistant_page import assistant_page\nassistant_page()",default_timeout=30)
    app.session_state["selected_source"]=DEMO
    app.run()
    assert not app.exception
    assert not any(foreign.question in e.value for e in app.text)
    assert any("Il risultato apparirà qui" in e.value for e in app.caption)
    app.button(key="assistant_starter_Consumi").click().run()
    assert not app.exception
    history=app.session_state[assistant_page.HISTORY]
    assert len(history)==1 and Agent.MARKET in history[0].results
    assert history[0].mode=="Deterministic"
    assert len(db.recent())==1 and db.recent()[0].id==foreign.id
    assert any("Calcoli locali · senza risposta AI" in e.value for e in app.caption)
    app.button(key="assistant_starter_Stress +10%").click().run()
    assert not app.exception
    history=app.session_state[assistant_page.HISTORY]
    assert len(history)==2 and Agent.SCENARIO in history[0].results
    assert history[0].results[Agent.SCENARIO].values["changes"]["demand_pct"]=="10"
    assert len(db.recent())==1
    app.selectbox(key=assistant_page.SELECTED).set_value(history[1].id).run()
    assert not app.exception
    assert any(e.value==history[1].question for e in app.text)
    app.button(key="assistant_clear").click().run()
    assert not app.exception and assistant_page.HISTORY not in app.session_state
    assert len(db.recent())==1



def test_shared_document_archive_visible_to_fresh_sessions(monkeypatch,tmp_path):
    import pymupdf
    from gasops_app import document_page as desk
    from gasops_app.document_archive import ArchiveConfig, object_name
    from gasops_app.document_desk import search
    monkeypatch.setenv("GASOPS_PDF_DIR",str(tmp_path))
    config=ArchiveConfig("https://fixture.supabase.co","sb_publishable_fixture")
    monkeypatch.setattr(desk,"_archive_config",lambda:config)
    monkeypatch.setattr(desk,"reasoner",lambda:None)
    with pymupdf.open() as doc:
        doc.new_page().insert_text((80,80),"Garanzia economica con deposito cauzionale.")
        raw=doc.tobytes()
    shared=((object_name("garanzie.pdf",raw),raw),)
    monkeypatch.setattr(desk,"_read_remote",lambda config:shared)
    script="from gasops_app.document_page import document_page\ndocument_page()"
    first=AppTest.from_string(script).run()
    second=AppTest.from_string(script).run()
    for app in (first,second):
        assert not app.exception
        assert any(e.value=="garanzie.pdf" for e in app.text)
        assert search(app.session_state[desk.STATE]["docs"],"garanzia economica")
        assert not any(b.label=="Pubblica documenti" for b in app.button)
    first.session_state[desk.STATE]["reference_list"].append({"local":True})
    assert not second.session_state[desk.STATE]["reference_list"]


def test_document_archive_unconfigured_does_not_offer_ephemeral_uploads(monkeypatch,tmp_path):
    from gasops_app import document_page as desk
    monkeypatch.setenv("GASOPS_PDF_DIR",str(tmp_path))
    monkeypatch.setattr(desk,"_archive_config",lambda:None)
    app=AppTest.from_string("from gasops_app.document_page import document_page\ndocument_page()").run()
    assert not app.exception
    assert any("Archivio remoto non configurato" in e.value for e in app.caption)
    assert not any(b.label=="Pubblica documenti" for b in app.button)
