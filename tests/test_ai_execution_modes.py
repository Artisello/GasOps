from types import SimpleNamespace
from streamlit.testing.v1 import AppTest
from gasops_app import session,assistant_page
from gasops_app.llm import LLMConfig
from gasops_app.models import Run
from gasops_app.data import synthetic
from gasops_app.supervisor import ModelUnavailable
import pytest


def test_configured_assistant_is_ready_without_changing_other_pages_mode(monkeypatch,tmp_path):
    config=LLMConfig("fixture-local","http://localhost:11434/v1")
    monkeypatch.setattr(session,"_configuration",lambda:config)
    monkeypatch.setenv("GASOPS_STATE_DIR",str(tmp_path))
    monkeypatch.setenv("GASOPS_PDF_DIR",str(tmp_path))
    def no_request(*args,**kwargs):
        pytest.fail("No automatic AI request during rendering")
    monkeypatch.setattr("gasops_app.llm.requests.post",no_request)
    app=AppTest.from_string("from gasops_app import session,assistant_page\nsession.sidebar()\nassistant_page.assistant_page()",default_timeout=30)
    app.session_state["selected_source"]=session.DEMO
    app.run()
    assert not app.exception
    assert app.selectbox(key="execution_mode").value=="Deterministic"
    assert not app.chat_input(key="assistant_question").disabled
    assert not any(b.key=="assistant_activate_ai" for b in app.button)
    assert not any(x.label=="Fonte dati" for x in app.selectbox)
    assert not any(x.label=="Fonti e impostazioni" for x in app.expander)
    app.run()
    assert not app.exception
    assert app.selectbox(key="execution_mode").value=="Deterministic"
    assert not app.chat_input(key="assistant_question").disabled
    assert assistant_page.HISTORY not in app.session_state


def test_required_ai_policy_blocks_workflow_before_execution(monkeypatch):
    monkeypatch.setattr(session,"reasoner",lambda:None)
    monkeypatch.setattr(session,"MarketContext",lambda *a,**k:pytest.fail("Workflow should not start"))
    sel=session.Selection(session.DEMO,"Seasonal regression",30,synthetic())
    with pytest.raises(ModelUnavailable):
        session.launch(sel,"test",ai_policy="required")


def test_ai_failure_is_not_rendered_as_ai_response(monkeypatch,tmp_path):
    monkeypatch.setenv("GASOPS_STATE_DIR",str(tmp_path))
    monkeypatch.setenv("GASOPS_PDF_DIR",str(tmp_path))
    model=SimpleNamespace(config=LLMConfig("fixture-local","http://localhost:11434/v1"))
    monkeypatch.setattr(assistant_page,"assistant_reasoner",lambda:model)
    def fake(sel,question,**kwargs):
        assert kwargs["ai_policy"]=="automatic" and sel is None
        data=synthetic()
        return Run(question=question,source=data.origin,input_sha256=data.fingerprint,
                   assumptions={"model":"Automatic"},mode="Deterministic fallback",model="fixture-local",
                   summary="Calcolo di riserva")
    monkeypatch.setattr(assistant_page,"launch",fake)
    app=AppTest.from_string("from gasops_app.assistant_page import assistant_page\nassistant_page()",default_timeout=30)
    app.session_state["selected_source"]=session.DEMO
    app.run()
    app.button(key="assistant_starter_Consumi").click().run()
    assert not app.exception
    assert any("Nessuna risposta AI generata" in w.value for w in app.warning)
    assert not any("**Risposta AI**"==m.value for m in app.markdown)


def test_assistant_import_compatible_with_previous_session_module(monkeypatch):
    import importlib

    # Simulate a running Streamlit worker retaining the pre-UX session module.
    monkeypatch.delattr(session,"ai_configured",raising=False)
    monkeypatch.setattr(session,"_configuration",lambda:None)
    module=importlib.reload(assistant_page)
    assert not module.ai_configured()
    config=LLMConfig("fixture-local","http://localhost:11434/v1")
    monkeypatch.setattr(session,"_configuration",lambda:config)
    assert module.ai_configured()

    def invalid_config():
        raise ValueError("Invalid configuration")
    monkeypatch.setattr(session,"_configuration",invalid_config)
    assert not module.ai_configured()


@pytest.mark.parametrize("old_view",[None,"Indicatori GME"])
def test_assistant_starts_in_chat_even_without_ai_configuration(monkeypatch,old_view):
    monkeypatch.setattr(session,"_configuration",lambda:None)
    monkeypatch.setattr(assistant_page,"assistant_reasoner",lambda:None)
    monkeypatch.setattr(session,"source_filters",lambda *a,**k:pytest.fail("No source acquisition on inactive chat"))
    monkeypatch.setattr(assistant_page,"launch",lambda *a,**k:pytest.fail("No automatic analysis"))
    app=AppTest.from_string("from gasops_app.assistant_page import assistant_page\nassistant_page()")
    if old_view is not None:
        app.session_state["assistant_view"]=old_view
    app.run()
    assert not app.exception
    assert app.radio(key="assistant_view").value=="Assistente operativo"
    assert app.radio(key="assistant_view").options==["Chiedi all’AI","Esplora dati","Report"]
    assert app.chat_input(key="assistant_question").disabled


def test_free_question_can_use_independent_sources_without_market_bundle(monkeypatch):
    model=SimpleNamespace(config=LLMConfig("fixture-local","http://localhost:11434/v1"))
    monkeypatch.setattr(assistant_page,"assistant_reasoner",lambda:model)
    monkeypatch.setattr(session,"source_filters",lambda *a,**k:pytest.fail("No source selector in assistant"))
    calls=[]
    def fake(selection,question,**kwargs):
        calls.append((question,kwargs))
        return Run(question=question,source=synthetic().origin,input_sha256="fixture",
                   assumptions={"source_lookup":True},summary="Dato non disponibile.")
    monkeypatch.setattr(assistant_page,"launch",fake)
    app=AppTest.from_string("from gasops_app.assistant_page import assistant_page\nassistant_page()")
    app.run()
    assert not app.exception and not calls
    assert not app.button(key="assistant_starter_Consumi").disabled
    assert not app.chat_input(key="assistant_question").disabled
    app.chat_input(key="assistant_question").set_value("Quanto gas c’è negli stoccaggi?").run()
    assert not app.exception and len(calls)==1
    assert calls[0][1]["ai_policy"]=="automatic"
    app.run()
    assert not app.exception and len(calls)==1


def test_gme_readouts_do_not_reacquire_when_reading_history(monkeypatch):
    from gasops_app import gme_market_page as gme
    state={}
    monkeypatch.setattr(gme.st,"session_state",state)
    calls=[]
    result={"cards":[],"message":"Prezzo non disponibile"}
    monkeypatch.setattr(gme,"_assistant_price_readout",lambda *a:(calls.append(1) or result))
    monkeypatch.setattr(gme.st,"markdown",lambda *a,**k:None)
    monkeypatch.setattr(gme.st,"caption",lambda *a,**k:None)
    request={"kinds":["igi"],"day":"2026-11-20"}
    gme.assistant_prices(request,None,report_id="one")
    assert not calls
    gme.assistant_prices(request,None,report_id="one",refresh=True)
    gme.assistant_prices(request,None,report_id="one")
    gme.assistant_prices(request,None,report_id="one",refresh=True)
    assert len(calls)==1
    assert state["assistant_gme_readouts_v1"]["one"]==result


def test_gme_question_without_cached_prices_does_not_start_market_acquisition(monkeypatch):
    from gasops_app import gme_market_page as gme
    from datetime import datetime, timezone
    now=datetime(2026,11,28,12,tzinfo=timezone.utc)
    monkeypatch.setattr(gme,"utc_now",lambda:now)
    monkeypatch.setattr(gme.g,"api_configured",lambda:True)
    monkeypatch.setattr(gme,"_automatic_sources",lambda *a,**k:pytest.fail("GME acquisition belongs to market"))
    monkeypatch.setattr(gme,"snapshot",lambda *a,**k:None)
    result=gme._assistant_price_readout({"kinds":["igi"],"day":"2026-11-20"},now)
    assert result["cards"]==[]
    assert "Mercato e previsioni" in result["message"]


def test_followup_chat_keeps_latest_turn_separate_from_selected_history(monkeypatch):
    from datetime import datetime, timezone
    from gasops_app.assistant_sources import query_day
    model=SimpleNamespace(config=LLMConfig("fixture-local","http://localhost:11434/v1"))
    monkeypatch.setattr(assistant_page,"assistant_reasoner",lambda:model)
    monkeypatch.setattr(session,"source_filters",lambda *a,**k:pytest.fail("No source selector in assistant"))
    monkeypatch.setattr(assistant_page,"utc_now",lambda:datetime(2026,11,22,12,tzinfo=timezone.utc))
    monkeypatch.setattr(assistant_page,"_report",lambda *a,**k:None)
    calls=[]
    def fake(selection,question,**kwargs):
        calls.append(question)
        day=query_day(question).isoformat()
        return Run(question=question,source=synthetic().origin,input_sha256="fixture",
                   assumptions={"source_lookup":True,"requested_day":day,"requested_country":"IT",
                       "public_operational_context":{"AGSI+":{"source":"GIE AGSI+","scope":"IT","gas_day":day,
                           "status":"available","kind":"observed","values":{"stock_twh":70}}}})
    monkeypatch.setattr(assistant_page,"launch",fake)
    app=AppTest.from_string("from gasops_app.assistant_page import assistant_page\nassistant_page()").run()
    app.chat_input(key="assistant_question").set_value("Scorte AGSI+ in Italia del 21/11/2026?").run()
    assert not app.exception and len(calls)==1
    original=app.session_state[assistant_page.CONTEXT]
    app.chat_input(key="assistant_question").set_value("E rispetto al giorno precedente?").run()
    assert not app.exception and len(calls)==2 and "2026-11-20" in calls[-1]
    result=app.session_state[assistant_page.HISTORY][0]
    assert result.assumptions["assistant_user_question"]=="E rispetto al giorno precedente?"
    assert result.assumptions["assistant_comparison"][0]["delta"]==0
    app.selectbox(key=assistant_page.SELECTED).set_value(original).run()
    assert not app.exception and len(calls)==2
    app.chat_input(key="assistant_question").set_value("E il giorno precedente?").run()
    assert not app.exception and len(calls)==3 and "2026-11-19" in calls[-1]
    app.button(key="assistant_clear").click().run()
    assert not app.exception and assistant_page.CONTEXT not in app.session_state
    app.chat_input(key="assistant_question").set_value("E ieri?").run()
    assert not app.exception and len(calls)==3
    assert any("A quale dato" in x.value for x in app.info)
