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
    assert any("Nessun bollettino generato" in e.value for e in app.info)
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
    assert any(m.label=="Giacenza" for m in app.metric)
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
