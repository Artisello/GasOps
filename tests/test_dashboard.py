from pathlib import Path
import pytest

from streamlit.testing.v1 import AppTest

from gasops_app.forecast import AUTOMATIC, MODELS
from gasops_app.models import Agent
from gasops_app.public_data import SourceUnavailable
from gasops_app.session import ARCHIVE, DEMO


@pytest.fixture(autouse=True)
def workbench_mode(monkeypatch):
    monkeypatch.setenv("GASOPS_APP_MODE", "workbench")


def _market_app(*args, **kwargs):
    app=AppTest.from_file(*args, **kwargs)
    app.session_state["overview_workspace"]="Mercato in sintesi"
    return app


def test_overview_button_completes_offline_run(monkeypatch, tmp_path):
    monkeypatch.setenv("GASOPS_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("GASOPS_PDF_DIR", str(tmp_path))
    monkeypatch.setenv("GASOPS_LLM_MODEL", "")
    monkeypatch.delenv("GROQ_API_KEY",raising=False)
    app = _market_app(Path(__file__).resolve().parents[1] / "app.py", default_timeout=30)
    app.session_state["selected_source"] = DEMO
    app.run()
    assert not app.exception
    assert app.title[0].value == "I.G.O.R. - Sistema Gas Italiano"
    assert app.button(key="analysis_launch").label == "Genera bollettino di mercato"
    assert sum(b.key=="analysis_launch" for b in app.button)==1
    assert app.checkbox(key="briefing_gie").value is True
    assert any("Nessun bollettino generato" in e.value for e in app.caption)
    assert app.selectbox(key="overview_model").value == AUTOMATIC
    app.button(key="analysis_launch").click().run()
    assert not app.exception
    report = app.session_state["last_run"]
    from gasops_app.session import database
    from gasops_app.store import Store
    assert Store(database().path).recent()==[]  # Public UI must not persist visitor runs.
    with pytest.raises(PermissionError):database().recent()
    assert report.finished_at and len(report.results) == 6
    assert app.session_state["last_briefing"].id == report.id
    assert any("Ultimo bollettino generato" in e.value for e in app.markdown)
    assert report.mode == "Deterministic" and report.interpretation is None
    assert any(e.value.endswith(" · Calcoli locali") and report.source.name in e.value for e in app.caption)
    completed = sum(r.status in ("completed", "review") for r in report.results.values())
    issues = sum(f.severity in ("high", "medium") for f in report.findings)
    assert any(e.value == f"Analisi eseguite: {completed}/{len(report.steps)} · Da verificare: {issues}" for e in app.caption)
    assert any("Consumi" in e.proto.body and "Previsione di esempio" in e.proto.body for e in app.get("html"))
    assert any("Scarica bollettino"==b.proto.label for b in app.get("download_button"))
    projection = report.results[Agent.FORECAST].values["forecast"]
    assert projection["model"] in MODELS
    assert projection["interval_kind"] in ("posterior", "empirical", "model_based")


def test_unavailable_public_feed_can_open_the_real_offline_archive(monkeypatch, tmp_path):
    monkeypatch.setenv("GASOPS_STATE_DIR", str(tmp_path))

    def unavailable(*args, **kwargs):
        raise SourceUnavailable("Eurostat non disponibile")

    monkeypatch.setattr("gasops_app.session.load_monthly", unavailable)
    app = _market_app(Path(__file__).resolve().parents[1] / "app.py", default_timeout=30).run()
    assert any("Eurostat non disponibile" in x.value for x in app.text)
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
    assert any("ENTSOG non disponibile" in x.value for x in app.text)
    assert any("Security of supply" in el.value for el in app.markdown)
    sources=AppTest.from_string("from gasops_app.operational_sources_page import operational_context\noperational_context()",default_timeout=30).run()
    assert not sources.exception
    assert sources.radio(key="operational_platform").value=="AGSI+"


def test_agsi_is_default_and_loads_independently(monkeypatch,tmp_path):
    import json
    from gasops_app.gas_calendar import closed_gas_day
    from gasops_app.models import utc_now
    from gasops_app.operational_sources import parse_agsi
    from gasops_app import operational_acquisition as acquisition, operational_sources_page as op
    monkeypatch.setenv("GASOPS_STATE_DIR",str(tmp_path))
    monkeypatch.setattr(op,"configured_key",lambda:"fixture-key")
    calls=[]
    def fake(store,key,scope,*,first=None,last=None,now=None,**kwargs):
        calls.append(scope)
        now = now or utc_now()
        day = last or closed_gas_day(now)
        payload={"last_page":1,"total":1,"data":[{"code":scope,"gasDayStart":day.isoformat(),
                 "gasInStorage":"90,5","workingGasVolume":"100","full":"90,5","withdrawal":"40","status":"C"}]}
        body = json.dumps(payload)
        if first is not None:
            store.cache(f"agsi-public-range-v1:{scope}:{first}:{last}",now.isoformat(),body)
        return parse_agsi(body,now,scope=scope)

    def run_inline(store,network,now,*,api_key,**options):
        work = acquisition.plan(network,acquisition.journal(store),now,api_key=api_key,**options)
        acquisition.synchronize(store,network,work,now,api_key=api_key,pause=0)

    monkeypatch.setattr(acquisition,"schedule",run_inline)
    monkeypatch.setattr(acquisition,"load_agsi",fake)
    monkeypatch.setattr(op,"load_agsi",fake)
    app=AppTest.from_string("from gasops_app.operational_sources_page import operational_context\noperational_context()",default_timeout=30).run()
    assert not app.exception and calls==["IT"]
    assert app.radio(key="operational_platform").value=="AGSI+"
    assert any("Giacenza" in e.proto.body for e in app.get("html"))
    assert any("Gas Infrastructure Europe" in el.value for el in app.markdown)
    app.run()
    assert calls==["IT"] and not app.exception
    app.selectbox(key="AGSI+_scope").select("EU").run()
    assert calls==["IT"] and not app.exception
    app.button(key="AGSI+_EU_load").click().run()
    assert calls==["IT","EU"] and not app.exception


def test_entsog_notice_does_not_hide_other_warnings():
    from gasops_app.session import source_notices, ENTSOG_METADATA_NOTE
    assert source_notices(None)==("","")
    assert source_notices(ENTSOG_METADATA_NOTE)==("",ENTSOG_METADATA_NOTE)
    stale="Ultimo giorno completo non recente: verifica pubblicazione e disponibilità."
    assert source_notices(ENTSOG_METADATA_NOTE+" "+stale)==(stale,ENTSOG_METADATA_NOTE)
    assert source_notices(stale)==(stale,"")


def test_overview_compact_model_controls(monkeypatch,tmp_path):
    monkeypatch.setenv("GASOPS_STATE_DIR",str(tmp_path))
    app=_market_app(Path(__file__).resolve().parents[1]/"app.py",default_timeout=30)
    app.session_state["selected_source"]=DEMO
    app.run()
    assert not app.exception
    assert not any("modello previsionale" in e.label for e in app.expander)
    assert not any("[Mercato e previsioni](/market) ·" in el.value for el in app.markdown)
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
    assert not calls
    app.button(key="gie_iip_load").click().run()
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
    app=_market_app(Path(__file__).resolve().parents[1]/"app.py",default_timeout=30)
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
    app=_market_app(Path(__file__).resolve().parents[1]/"app.py",default_timeout=30)
    app.session_state["selected_source"]=DEMO
    app.run()
    assert not app.exception
    assert any("Prototipo per Snam · creato da Igor" in e.proto.body for e in app.get("html"))
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
    app=_market_app(Path(__file__).resolve().parents[1]/"app.py",default_timeout=30)
    app.session_state["selected_source"]=DEMO
    app.run()
    assert not app.exception
    assert not any(e.value=="Il mercato in breve" for e in app.subheader)
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
    assert any("Fonte non disponibile" in x.value for x in app.text)


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
    assert app.radio(key="market_section").options==["Andamento","Consumi e prezzi","Meteo","Dati e metodo"]
    assert app.radio(key="market_section").value=="Consumi e previsioni"
    assert any("Variazione dei consumi" in e.proto.body for e in app.get("html"))
    assert not any("Dati osservati e previsioni"==e.label for e in app.expander)
    app.radio(key="market_section").set_value("Composizione e prezzi").run()
    assert not app.exception
    app.radio(key="market_section").set_value("Meteo").run()
    assert not app.exception
    app.radio(key="market_section").set_value("Modelli e dati").run()
    assert not app.exception
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
    assert app.radio(key="balancing_view").options==["Sistema e utenti","Bilanci e rettifiche","Dati Snam","Calcola saldo utente","Simula scenario"]
    assert app.radio(key="balancing_view").value=="Cockpit"
    assert not any("Saldo energetico" in e.proto.body for e in app.get("html"))
    app.radio(key="balancing_view").set_value("Sbilanciamento del partecipante").run()
    assert not app.exception
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
    app.session_state["balancing_view"]="Scenario di mercato"
    app.session_state["scenario_model"]="Scenario aggregato esistente"
    app.session_state["scenario_aggregate_source"]="Demo · dati fittizi"
    app.session_state["active_bundle"]=data
    app.session_state["scenario_case_"+data.fingerprint]={"demand_gwh":"100","supply_gwh":"120","storage_gwh":None,"price_eur_mwh":"42"}
    ass=Assumptions()
    app.session_state["assumptions"]=ass.model_copy(update={"stress":type(ass.stress).model_validate({**ass.stress.model_dump(), "storage_pct":10})}).model_dump(mode="json")
    app.run()
    assert not app.exception
    assert any("variazione stoccaggio è sospesa" in e.value for e in app.warning)



def test_commercial_workspace_only_renders_selected_task(monkeypatch,tmp_path):
    from datetime import date
    monkeypatch.setenv("GASOPS_STATE_DIR",str(tmp_path))
    app=AppTest.from_string("from gasops_app.operations_page import operations_ledger\noperations_ledger()",default_timeout=30).run()
    assert not app.exception
    assert app.radio(key="commercial_view").options==["Fatture","Garanzie","Scadenze","Prezzi","Calcolo GNL"]
    assert not app.number_input
    assert not app.dataframe
    assert any("importa prima i bilanci" in e.value for e in app.info)
    app.toggle(key="commercial_example").set_value(True).run()
    assert not app.exception
    assert not any(n.key=="credit_g" for n in app.number_input)
    app.number_input(key="invoice_amount_short").set_value(172200.).run()
    app.checkbox(key="invoice_present_long").set_value(False).run()
    app.date_input(key="invoice_date_short").set_value(date(2026,11,8)).run()
    assert not app.exception
    app.radio(key="commercial_view").set_value("Scadenze").run()
    assert not app.exception
    calendar=next(d.value for d in app.dataframe if "Adempimento" in d.value.columns)
    assert "Pagamento DEMO-FT-01" in calendar["Adempimento"].tolist()
    assert "Pagamento DEMO-FT-02" not in calendar["Adempimento"].tolist()
    assert str(calendar.loc[calendar["Adempimento"]=="Pagamento DEMO-FT-01","Data"].iloc[0])[:10]=="2026-11-23"
    app.radio(key="commercial_view").set_value("Garanzie").run()
    assert not app.exception
    assert not any(n.key=="invoice_amount_short" for n in app.number_input)
    app.number_input(key="credit_g").set_value(1020000.).run()
    assert not app.exception and any("EPSu ≥ MEPSu" in e.value for e in app.error)
    app.radio(key="commercial_view").set_value("Bilanci e GNL").run()
    assert not app.exception
    assert not any("Delta DS" in d.value.columns for d in app.dataframe)
    assert any("Allocazione illustrativa MWh" in d.value.columns for d in app.dataframe)



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
    assert app.radio(key="risk_result_view").options==["Carenza di gas","Impatto economico","Ipotesi e metodo"]
    assert app.radio(key="risk_result_view").value=="Carenza di gas"
    assert any("Probabilità di carenza" in e.proto.body for e in app.get("html"))
    first=saved["result"].summary["executed_at"]
    app.radio(key="risk_confidence").set_value("99").run()
    assert not app.exception
    assert app.session_state["risk_workspace_v2"]["result"].summary["executed_at"]==first
    assert any("Carenza al percentile 99" in e.proto.body for e in app.get("html"))
    for view in ("Impatto economico","Ipotesi e metodo","Carenza di gas"):
        app.radio(key="risk_result_view").set_value(view).run()
        assert not app.exception
        assert app.session_state["risk_workspace_v2"]["result"].summary["executed_at"]==first
    assert app.radio(key="risk_confidence").value=="99"
    app.selectbox(key="risk_preset").set_value("Base").run()
    assert not app.exception
    assert any("Fonte, previsione o scenario cambiati" in e.value for e in app.warning)



def test_document_desk_empty_state_has_no_precompiled_findings(monkeypatch,tmp_path):
    monkeypatch.setenv("GASOPS_PDF_DIR",str(tmp_path))
    app=AppTest.from_string("from gasops_app.document_page import document_page\ndocument_page()").run()
    assert not app.exception
    assert any("Aggiungi almeno un PDF" in e.value for e in app.info)
    assert not any("Piombino · Mancata discarica" in e.value for e in app.markdown)


def test_document_desk_pdf_search_and_rag_without_model(monkeypatch,tmp_path):
    import pymupdf
    from gasops_app import document_page
    monkeypatch.setattr(document_page,"document_directory",lambda root:(tmp_path,True))
    monkeypatch.setenv("GASOPS_PDF_DIR",str(tmp_path))
    monkeypatch.setattr(document_page,"reasoner",lambda:None)
    with pymupdf.open() as doc:
        doc.new_page().insert_text((80,80),"Garanzia economica con deposito cauzionale.")
        doc.save(tmp_path/"fixture.pdf")
    app=AppTest.from_string("from gasops_app.document_page import document_page\ndocument_page()").run()
    assert not app.exception
    app.button(key="document_local_open").click().run()
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
    monkeypatch.setattr(assistant_page,"ai_configured",lambda:False)
    db=session.database()
    from gasops_app.store import Store
    db=Store(db.path)  # Seed legacy private history outside the public UI boundary.
    data=synthetic()
    foreign=Run(question="DOMANDA_DI_UN_ALTRO_VISITATORE",source=data.origin,input_sha256=data.fingerprint,assumptions={})
    db.save(foreign)
    app=AppTest.from_string("from gasops_app.assistant_page import assistant_page\nassistant_page()",default_timeout=30)
    app.session_state["selected_source"]=DEMO
    app.run()
    assert not app.exception
    assert app.radio(key="assistant_view").value=="Assistente operativo"
    assert app.chat_input(key="assistant_question").disabled
    app.radio(key="assistant_view").set_value("Report locali").run()
    assert not app.exception and not app.chat_input
    assert app.button(key="assistant_starter_Consumi")
    assert not any(foreign.question in e.value for e in app.text)
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
        app.button(key="document_remote_refresh").click().run()
        assert not app.exception
        assert any(e.value=="garanzie.pdf" for e in app.text)
        assert search(app.session_state[desk.STATE]["docs"],"garanzia economica")
        assert not any(b.label=="Pubblica documenti" for b in app.button)
    first.session_state[desk.STATE]["reference_list"].append({"local":True})
    assert not second.session_state[desk.STATE]["reference_list"]


def test_document_archive_unconfigured_offers_session_uploads(monkeypatch,tmp_path):
    from gasops_app import document_page as desk
    monkeypatch.setenv("GASOPS_PDF_DIR",str(tmp_path))
    monkeypatch.setattr(desk,"_archive_config",lambda:None)
    app=AppTest.from_string("from gasops_app.document_page import document_page\ndocument_page()").run()
    assert not app.exception
    assert any("Archivio remoto non configurato" in e.value for e in app.caption)
    assert any(b.label=="Aggiungi ai miei PDF" for b in app.button)
    assert not any(b.label=="Pubblica documenti" for b in app.button)



def test_repository_document_import_instructions_and_bundled_pdf(monkeypatch,tmp_path):
    import pymupdf
    from gasops_app import document_page as desk
    from gasops_app.document_desk import search
    monkeypatch.delenv("GASOPS_PDF_DIR",raising=False)
    monkeypatch.setattr(desk,"ROOT",tmp_path)
    monkeypatch.setattr(desk,"_archive_config",lambda:None)
    public=tmp_path/"data"/"public-regulatory"
    public.mkdir(parents=True)
    private=tmp_path/"data"/"regulatory"
    private.mkdir()
    for directory,name,phrase in [(public,"public.pdf","Garanzia autorizzata"),(private,"private.pdf","Documento riservato")]:
        with pymupdf.open() as pdf:
            pdf.new_page().insert_text((80,80),phrase)
            pdf.save(directory/name)
    app=AppTest.from_string("from gasops_app.document_page import document_page\ndocument_page()").run()
    assert not app.exception
    assert any(e.label=="Carica PDF" for e in app.expander)
    app.button(key="document_local_open").click().run()
    assert any(e.value=="public.pdf" for e in app.text)
    assert not any(e.value=="private.pdf" for e in app.text)
    assert search(app.session_state[desk.STATE]["docs"],"garanzia autorizzata")



def test_visitor_pdf_survives_rerun_but_is_not_shared(monkeypatch,tmp_path):
    import pymupdf
    from gasops_app import document_page as desk
    from gasops_app.document_desk import search
    monkeypatch.setenv("GASOPS_PDF_DIR",str(tmp_path))
    monkeypatch.setattr(desk,"_archive_config",lambda:None)
    with pymupdf.open() as doc:
        doc.new_page().insert_text((80,80),"Deposito cauzionale personale.")
        raw=doc.tobytes()
    script="from gasops_app.document_page import document_page\ndocument_page()"
    first=AppTest.from_string(script)
    first.session_state[desk.VISITOR_UPLOADS]=(("test.pdf",raw),)
    first.session_state[desk.SCOPE]="I miei PDF"
    first.run()
    assert not first.exception
    assert search(first.session_state[desk.VISITOR_STATE]["docs"],"deposito cauzionale")
    first.run()
    assert not first.exception and first.session_state[desk.VISITOR_UPLOADS][0][1]==raw
    assert desk.STATE not in first.session_state
    second=AppTest.from_string(script).run()
    assert not second.exception and desk.VISITOR_UPLOADS not in second.session_state
    assert not second.session_state[desk.STATE]["docs"].documents
    first.radio(key=desk.SCOPE).set_value("Archivio pubblico").run()
    assert not first.exception and first.session_state[desk.VISITOR_UPLOADS][0][1]==raw



def test_visitor_upload_button_indexes_and_removes_pdf(monkeypatch,tmp_path):
    import pymupdf
    from types import SimpleNamespace
    from gasops_app import document_page as desk
    from gasops_app.document_desk import search
    monkeypatch.setenv("GASOPS_PDF_DIR",str(tmp_path))
    monkeypatch.setattr(desk,"_archive_config",lambda:None)
    with pymupdf.open() as doc:
        doc.new_page().insert_text((80,80),"Deposito cauzionale di prova.")
        raw=doc.tobytes()
    file=SimpleNamespace(name="prova.pdf",size=len(raw),getvalue=lambda:raw)
    monkeypatch.setattr(desk.st,"file_uploader",lambda *a,**kw:[file])
    app=AppTest.from_string("from gasops_app.document_page import document_page\ndocument_page()").run()
    assert not app.exception
    next(b for b in app.button if b.label=="Aggiungi ai miei PDF").click().run()
    assert not app.exception
    assert app.radio(key=desk.SCOPE).value=="I miei PDF"
    assert search(app.session_state[desk.VISITOR_STATE]["docs"],"deposito cauzionale")
    assert app.session_state[desk.VISITOR_UPLOADS]==(("prova.pdf",raw),)
    next(b for b in app.button if b.label=="Rimuovi").click().run()
    assert not app.exception and not app.session_state[desk.VISITOR_UPLOADS]
    assert not app.session_state[desk.VISITOR_STATE]["docs"].documents



def test_daily_settlement_desk_and_jarvis_no_implicit_fetch():
    from streamlit.testing.v1 import AppTest
    app=AppTest.from_string("from gasops_app.settlement_desk_page import panel\npanel()",default_timeout=30).run()
    assert not app.exception
    assert not app.get("html") or not any("172.200,00" in x.proto.body for x in app.get("html"))
    app.radio(key="daily_desk_data_mode").set_value("Esempio guidato").run()
    assert any("30/30 giorni conclusi utilizzabili" in x.proto.body for x in app.get("html"))
    assert any("172.200,00" in x.proto.body for x in app.get("html"))
    app.radio(key="daily_desk_filter").set_value("Rettifiche").run()
    assert not app.exception
    rows=next(d.value for d in app.dataframe if "Rettifica (€)" in d.value.columns)
    assert len(rows)==1
    assert float(rows["Rettifica (€)"].iloc[0])==-4200
    app.radio(key="daily_desk_filter").set_value("Eccezioni").run()
    assert not app.exception
    assert any("Nessuna giornata" in c.value for c in app.caption)


def test_jarvis_snapshot_reused_between_panels():
    from datetime import datetime,timezone,timedelta
    from gasops_app.data import ROME
    from gasops_app.operational_sources import parse_jarvis
    from gasops_app.operational_sources_page import utc_now
    from streamlit.testing.v1 import AppTest
    now=utc_now().astimezone(ROME)
    day=now.date() if now.hour>=6 else now.date()-timedelta(days=1)
    first=datetime(day.year,day.month,day.day,6,tzinfo=ROME)
    # Use a historical day so both publications are guaranteed to be in the past.
    day=day-timedelta(days=1)
    first=datetime(day.year,day.month,day.day,7,tzinfo=ROME)
    second=first+timedelta(hours=1)
    raw=("gas_day,published_at,expected_withdrawal_gwh,sas_gwh,expected_linepack_gwh\n"
         f"{day},{first.isoformat()},1000,-20,800\n"
         f"{day},{second.isoformat()},1010,-10,805\n").encode()
    snapshot=parse_jarvis(raw)
    app=AppTest.from_string("from gasops_app.operational_sources_page import _jarvis_panel\n_jarvis_panel(prefix='balancing')",default_timeout=30)
    app.session_state["jarvis_public_snapshot_v1"]=snapshot
    app.run()
    assert not app.exception
    assert any("SAS pubblicato" in e.proto.body for e in app.get("html"))
    # Historical selection is intentionally informational, not a warning.
    assert any("consultazione storica" in e.value.casefold() for e in app.caption)
    assert not any("consultazione storica" in e.value.casefold() for e in app.warning)
    assert len(app.session_state["jarvis_public_snapshot_v1"]["versions"]) == 2


def test_briefing_period_prefers_observed_and_fallback_is_not_monolithic(monkeypatch):
    from datetime import date
    from gasops_app import dashboard, session
    from gasops_app.models import Agent, Result, Run, Finding
    from gasops_app.data import synthetic
    data=synthetic()
    run=Run(question="briefing",source=data.origin.model_copy(update={"latest_period":None}),
            input_sha256=data.fingerprint,assumptions={"model":session.MODEL_CHOICES[0],"source_period":"2026-10-01"},
            mode="Deterministic fallback",warnings=["Fixture AI failure","Fixture AI failure"],summary="MONOLITHIC_FIXTURE")
    run.results[Agent.MARKET]=Result(agent=Agent.MARKET,summary="Mercato",values={"period":"2026-10-01","demand_gwh":100})
    run.findings=[Finding(id="fixture",title="Verifica fixture",severity="medium",detail="Dettaglio",category="Test")]
    assert dashboard._briefing_period(run)==dashboard.data_it(date(2026,10,1),day=data.origin.grain=="daily")
    monkeypatch.setattr(dashboard,"briefing_run",lambda:run)
    monkeypatch.setattr(dashboard,"analysis_label",lambda:"Genera bollettino di mercato")
    app=AppTest.from_string("from gasops_app import dashboard,session\nfrom gasops_app.data import synthetic\ndashboard._briefing_panel(session.Selection(session.DEMO,session.MODEL_CHOICES[0],30,synthetic()))").run()
    assert not app.exception
    assert sum(w.value=="Fixture AI failure" for w in app.warning)==1
    assert not any("MONOLITHIC_FIXTURE" in t.value for t in app.text)
    assert any("Verifica fixture" in m.value for m in app.markdown)


def test_briefing_context_keeps_missing_gie_and_umm_separate():
    app=AppTest.from_string("""from gasops_app.dashboard import _briefing_operational_context
_briefing_operational_context({
    "AGSI+":{"status":"available","gas_day":"2026-11-17","values":{"fill_pct":75.0,"stock_twh":100.0}},
    "ALSI":{"status":"unavailable","reason":"Chiave non configurata"},
    "IIP":{"status":"available","received_records":4,"coverage":"Completa"},
    "Open-Meteo":{"status":"available","points":[{"day":"2026-11-19","hdd":10.0,"temperature_c":8.0}]}
})
""").run()
    assert not app.exception
    assert any("Stoccaggi Italia" in e.proto.body and "75,0" in e.proto.body and "record, non eventi" in e.proto.body for e in app.get("html"))
    assert any("Copertura incompleta" in e.value and "ALSI" in e.value for e in app.caption)
    assert any("picco HDD" in e.value for e in app.caption)


def test_unverified_iip_not_shown_as_kpi():
    for source in ({"status":"stale","received_records":None,"coverage":"Completa"},
                   {"status":"available","received_records":4,"coverage":"Parziale"}):
        app=AppTest.from_string("from gasops_app.dashboard import _briefing_operational_context\n_briefing_operational_context("+repr({"IIP":source,"AGSI+":{"status":"available","values":{"fill_pct":75.0}}})+")").run()
        assert not app.exception
        assert not any("Record UMM ricevuti" in e.proto.body for e in app.get("html"))
        assert any("Copertura incompleta" in e.value and "IIP" in e.value for e in app.caption)


def test_briefing_regulatory_finding_cta_selects_exact_case(monkeypatch):
    from gasops_app import dashboard
    from gasops_app.regulatory import registered_case
    opened=[]
    monkeypatch.setattr(dashboard.st,"switch_page",lambda page:opened.append(page.url_path))
    app=AppTest.from_string("from gasops_app.dashboard import _registered_finding\nfrom gasops_app.regulatory import registered_case\n_registered_finding(registered_case('notice-7').finding)").run()
    assert not app.exception
    assert any("Piombino" in m.value and "7 giorni" in m.value for m in app.markdown)
    assert any("PDF p. 103" in c.value for c in app.caption)
    assert any("PDF p. 104" in c.value for c in app.caption)
    app.button(key="overview_finding_notice-7").click().run()
    assert not app.exception
    assert opened==["regulatory"]
    assert app.session_state["desk_finding_target"]=="notice-7"


def test_regulatory_cta_opens_historical_register_even_without_pdf(monkeypatch,tmp_path):
    from gasops_app import document_page
    monkeypatch.setenv("GASOPS_PDF_DIR",str(tmp_path))
    monkeypatch.setattr(document_page,"_archive_config",lambda:None)
    app=AppTest.from_string("from gasops_app.document_page import document_page\ndocument_page()")
    app.session_state["desk_finding_target"]="notice-7"
    app.session_state["document_archive_scope"]="I miei PDF"
    app.run()
    assert not app.exception
    assert app.radio(key="desk_mode").value=="Registro rilievi"
    assert app.radio(key="desk_register_origin").value=="Edizioni esaminate"
    assert app.radio(key="document_archive_scope").value=="Archivio pubblico"
    assert app.selectbox(key="desk_historical_case").value=="notice-7"
    assert any("Copia esatta dell’edizione non disponibile" in c.value for c in app.caption)
    assert not any(c.label=="Mostra pagina originale" for c in app.checkbox)
    app.radio(key="desk_register_origin").set_value("Rilievi di sessione").run()
    assert not app.exception
    assert any("Nessun rilievo nel registro" in e.value for e in app.info)


def test_registered_citation_resolves_by_revision_digest_not_filename():
    from types import SimpleNamespace
    from gasops_app.regulatory import EDITIONS, PIOMBINO, matching_edition, registered_case
    cite=registered_case("notice-7").finding.citations[0]
    fake=SimpleNamespace(digest="wrong-edition",pages=200)
    digest=next(key for key,name in EDITIONS.items() if name==PIOMBINO)
    exact=SimpleNamespace(digest=digest,pages=200)
    assert matching_edition(SimpleNamespace(documents={PIOMBINO:fake}),cite) is None
    assert matching_edition(SimpleNamespace(documents={"renamed.pdf":exact}),cite) is exact


def test_briefing_shows_dated_market_signals_and_stale_inventory():
    app=AppTest.from_string("""from gasops_app.dashboard import _briefing_market_context,_briefing_operational_context
_briefing_market_context({
    "ENTSOG · SRG":{"status":"available","period":"2026-11-17","values":{"demand_gwh":2260.7},"changes_pct":{"demand_gwh":-12}},
    "ACER · GNL":{"status":"available","values":{
        "eu":{"status":"available","period":"2026-11-18","value":86.09},
        "benchmark":{"status":"available","period":"2026-11-18","value":5.24}}}
})
_briefing_operational_context({"AGSI+":{"status":"stale","gas_day":"2026-11-16","last_observed_values":{"fill_pct":86.8,"stock_twh":176.6}}})
""").run()
    assert not app.exception
    assert any("Prelievi dei tre aggregati SRG" in c.value and "medie delle due finestre" in c.value for c in app.caption)
    assert any("Prezzo GNL UE" in c.value and "Differenziale" in c.value for c in app.caption)
    assert any("ultimo dato non recente" in h.proto.body and "86,8" in h.proto.body for h in app.get("html"))


def test_overview_compact_chart_hides_only_exact_duplicate_accounting_series():
    import pandas as pd
    from types import SimpleNamespace
    from gasops_app.visuals import demand_chart
    frame=pd.DataFrame({"demand_gwh":[10.,20.],"supply_gwh":[10.,20.]},
                       index=pd.to_datetime(["2026-09-01","2026-10-01"]))
    projection=SimpleNamespace(points=[])
    compact=demand_chart(frame,projection,"monthly",compact=True)
    assert compact.layout.meta=="coincident_accounting"
    assert [trace.name for trace in compact.data]==["Consumi osservati"]
    assert len(demand_chart(frame,projection,"monthly").data)==2
    frame.loc[frame.index[-1],"supply_gwh"]=None
    assert len(demand_chart(frame,projection,"monthly",compact=True).data)==2


def test_ai_readout_can_show_sections_without_repeating_usage():
    from gasops_app.data import synthetic
    from gasops_app.models import Run
    data=synthetic()
    run=Run(question="briefing",source=data.origin,input_sha256=data.fingerprint,assumptions={},
            ai_sections=[{"id":"summary","text":"Executive fixture","references":[]},
                         {"id":"market","text":"Market fixture","references":[]}],
            ai_usage={"calls":1})
    app=AppTest.from_string("from gasops_app.visuals import ai_readout\nimport streamlit as st\nai_readout(st.session_state['fixture'],section_ids={'summary'},usage=False)")
    app.session_state["fixture"]=run
    app.run()
    assert not app.exception
    assert any(t.value=="Executive fixture" for t in app.text)
    assert not any(t.value=="Market fixture" for t in app.text)


def test_document_workspace_precedes_management_and_keeps_tools(monkeypatch,tmp_path):
    import pymupdf
    from gasops_app import document_page as desk
    monkeypatch.setattr(desk,"document_directory",lambda root:(tmp_path,True))
    monkeypatch.setenv("GASOPS_PDF_DIR",str(tmp_path))
    monkeypatch.setattr(desk,"_archive_config",lambda:None)
    monkeypatch.setattr(desk,"reasoner",lambda:None)
    with pymupdf.open() as pdf:
        for phrase in ("Garanzia economica deposito cauzionale.", "Garanzia economica pagamento."):
            pdf.new_page().insert_text((70,80),phrase)
        pdf.save(tmp_path/"regole.pdf")
    app=AppTest.from_string("from gasops_app.document_page import document_page\ndocument_page()").run()
    assert not app.exception
    app.button(key="document_local_open").click().run()
    assert app.radio(key="desk_mode").value=="Cerca"
    assert len(app.radio(key="desk_mode").options)==8
    assert any("1 PDF · 2/2 pagine con testo" in c.value for c in app.caption)
    search=next(e for e in app.text_input if e.label=="Cosa vuoi cercare?")
    upload=next(e for e in app.expander if e.label=="Carica PDF")
    assert search and upload
    search.set_value("Garanzia economica")
    next(b for b in app.button if b.label=="Cerca nei PDF").click().run()
    assert not app.exception
    assert len(app.selectbox(key="desk_search_hit").options)==2
    assert any(e.label=="Altri passaggi · 1" for e in app.expander)
    app.button(key="desk_search_save").click().run()
    assert not app.exception
    assert len(app.session_state[desk.STATE]["reference_list"])==1
    app.radio(key="desk_mode").set_value("Riferimenti salvati").run()
    assert not app.exception
    assert any("1 riferimenti" in c.value for c in app.caption)
    app.radio(key=desk.SCOPE).set_value("I miei PDF").run()
    assert not app.exception
    assert any("Aggiungi almeno un PDF" in e.value for e in app.info)
    assert len(app.session_state[desk.STATE]["reference_list"])==1


def test_assistant_retains_last_result_when_launch_fails(monkeypatch,tmp_path):
    from gasops_app import session, assistant_page as assistant
    monkeypatch.setenv("GASOPS_STATE_DIR",str(tmp_path))
    monkeypatch.setenv("GASOPS_PDF_DIR",str(tmp_path))
    monkeypatch.setattr(session,"reasoner",lambda:None)
    monkeypatch.setattr(assistant,"reasoner",lambda:None)
    monkeypatch.setattr(assistant,"ai_configured",lambda:False)
    app=AppTest.from_string("from gasops_app.assistant_page import assistant_page\nassistant_page()",default_timeout=30)
    app.session_state["selected_source"]=DEMO
    app.session_state["assistant_view"]="Report locali"
    app.run()
    app.button(key="assistant_starter_Consumi").click().run()
    assert not app.exception
    prior=app.session_state[assistant.HISTORY][0]
    def fail(*args,**kwargs):raise RuntimeError("fixture")
    monkeypatch.setattr(assistant,"launch",fail)
    app.button(key="assistant_starter_Stress +10%").click().run()
    assert not app.exception
    assert app.session_state[assistant.HISTORY][0].id==prior.id
    assert any("Ultimo risultato conservato" in c.value for c in app.caption)
    assert any(e.value==prior.question for e in app.text)


def test_public_source_choices_hide_only_redundant_synthetic_series():
    from dataclasses import replace
    from gasops_app import session
    from gasops_app.data import synthetic, jrc_archive
    from gasops_app.live_sources import BUNDLES
    from gasops_app.models import Kind
    example=synthetic()
    archive=jrc_archive()
    assert session.DEMO in session.available_source_choices({})
    assert session.DEMO in session.available_source_choices({"active_bundle":example})
    assert session.DEMO in session.available_source_choices({"active_bundle":archive})
    # Synthetic test fixture representing the shape of an acquired public series.
    acquired=replace(example,origin=example.origin.model_copy(update={"kind":Kind.LIVE,"archive":False}))
    state={BUNDLES:{"daily":acquired},"active_bundle":example}
    assert session.public_series(state)["daily"] is acquired
    assert session.available_source_choices(state)==(session.PUBLIC,session.DAILY,session.ARCHIVE)
    empty=replace(acquired,rows=acquired.rows.iloc[:0])
    assert session.DEMO in session.available_source_choices({BUNDLES:{"daily":empty}})
