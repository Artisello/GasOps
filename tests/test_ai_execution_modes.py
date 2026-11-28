from types import SimpleNamespace
from streamlit.testing.v1 import AppTest
from gasops_app import session,assistant_page
from gasops_app.llm import LLMConfig
from gasops_app.models import Run
from gasops_app.data import synthetic
from gasops_app.supervisor import ModelUnavailable
import pytest


def test_configured_ai_requires_explicit_activation_and_local_choice_persists(monkeypatch,tmp_path):
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
    assert app.chat_input(key="assistant_question").disabled
    app.selectbox(key="execution_mode").set_value("Deterministic").run()
    assert not app.exception and app.chat_input(key="assistant_question").disabled
    app.run()
    assert app.selectbox(key="execution_mode").value=="Deterministic"
    app.button(key="assistant_activate_ai").click().run()
    assert not app.exception
    assert app.selectbox(key="execution_mode").value=="fixture-local"
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
    monkeypatch.setattr(assistant_page,"reasoner",lambda:model)
    def fake(sel,question,**kwargs):
        assert kwargs["ai_policy"]=="required"
        return Run(question=question,source=sel.bundle.origin,input_sha256=sel.bundle.fingerprint,
                   assumptions={"model":sel.model},mode="Deterministic fallback",model="fixture-local",
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
    monkeypatch.setattr(assistant_page,"reasoner",lambda:None)
    monkeypatch.setattr(assistant_page,"source_filters",lambda *a,**k:pytest.fail("No source acquisition on inactive chat"))
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
    monkeypatch.setattr(assistant_page,"reasoner",lambda:model)
    monkeypatch.setattr(assistant_page,"source_filters",lambda *a,**k:session.Selection(session.PUBLIC,"Automatico",24,None))
    calls=[]
    def fake(selection,question,**kwargs):
        calls.append((question,kwargs))
        return Run(question=question,source=synthetic().origin,input_sha256="fixture",
                   assumptions={"source_lookup":True},summary="Dato non disponibile.")
    monkeypatch.setattr(assistant_page,"launch",fake)
    app=AppTest.from_string("from gasops_app.assistant_page import assistant_page\nassistant_page()")
    app.run()
    assert not app.exception and not calls
    assert app.button(key="assistant_starter_Consumi").disabled
    assert not app.chat_input(key="assistant_question").disabled
    app.chat_input(key="assistant_question").set_value("Quanto gas c’è negli stoccaggi?").run()
    assert not app.exception and len(calls)==1
    assert calls[0][1]["ai_policy"]=="required"
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
