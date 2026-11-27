import ast
from pathlib import Path

import requests
from streamlit.testing.v1 import AppTest

from gasops_app.system_status_page import ARCHIVE_KEY
from gasops_app import demo_application,session
from gasops_app.llm import LLMConfig
from gasops_app.operations_ledger import sample_rows

ROOT=Path(__file__).resolve().parents[1]
PATHS=("","market","security-of-supply","balancing","ledger","risk","regulatory","operations","kpi","connections","demo")


def test_home_works_with_presentation_module_loaded_before_sidebar_release(monkeypatch):
    from gasops_app import presentation
    # Cloud can retain the presentation module from the preceding release,
    # which has the overview renderer but not the newer `home` convenience alias.
    monkeypatch.delattr(presentation,"home")
    monkeypatch.delenv("GASOPS_APP_MODE",raising=False)
    app=AppTest.from_file(ROOT/"app.py",default_timeout=30)
    app.session_state[ARCHIVE_KEY] = True
    app.run()
    assert not app.exception
    assert app.title[0].value=="I.G.O.R. - Sistema Gas Italiano"
    assert len(app.get("page_link"))==11
    assert {chart.key for chart in app.get("plotly_chart")}=={"net_overview_entsog_history"}


def test_home_does_not_call_a_cached_callback_from_the_previous_release(monkeypatch):
    def stale_home():
        raise ImportError("cannot import name 'home' from 'gasops_app.presentation'")
    monkeypatch.setattr(demo_application,"home",stale_home,raising=False)
    monkeypatch.delenv("GASOPS_APP_MODE",raising=False)
    app=AppTest.from_file(ROOT/"app.py",default_timeout=30).run()
    assert not app.exception
    assert app.title[0].value=="I.G.O.R. - Sistema Gas Italiano"
    assert len(app.get("page_link"))==11


def test_ready_assistant_respects_local_mode_and_does_not_regenerate_after_clear(monkeypatch):
    monkeypatch.setattr(session,"_configuration",lambda:LLMConfig("fixture-model","https://api.example.com/v1","fixture"))
    def forbidden(*args,**kwargs):raise AssertionError("Local mode must not activate a model")
    monkeypatch.setattr(session,"CompatibleReasoner",forbidden)
    app=AppTest.from_string("from gasops_app.demo_application import prepare\nprepare('operations')",default_timeout=30)
    app.session_state["execution_mode"]="Deterministic"
    app.run()
    assert not app.exception
    assert app.session_state["execution_mode"]=="Deterministic"
    assert app.session_state["assistant_history_v1"]==[]
    app.session_state["assistant_history_v1"]=[]
    app.run()
    assert not app.exception and app.session_state["assistant_history_v1"]==[]


def test_every_feature_route_is_reachable_offline_and_preserves_imports(monkeypatch,tmp_path):
    monkeypatch.delenv("GASOPS_APP_MODE",raising=False)
    monkeypatch.setenv("GASOPS_STATE_DIR",str(tmp_path))
    monkeypatch.setattr(session,"_configuration",lambda:None)
    monkeypatch.setattr("gasops_app.operational_sources_page.configured_key",lambda:None)
    monkeypatch.setattr("gasops_app.terna_power.credentials",lambda *a:(None,None))
    monkeypatch.setattr("gasops_app.document_page._archive_config",lambda:None)
    def forbid(*a,**k):raise AssertionError("Unexpected provider call while exploring ready cases")
    monkeypatch.setattr(requests.Session,"request",forbid)
    monkeypatch.setattr(requests,"request",forbid)
    rows=sample_rows()
    saved={"sha":"existing-evidence","rows":rows,"name":"session.csv"}
    app=AppTest.from_file(ROOT/"app.py",default_timeout=60)
    app.session_state["settlement_desk_csv_v1"]=saved
    app.run()
    assert not app.exception
    links={x.proto.page:x.proto.page_script_hash for x in app.get("page_link")}
    assert set(links)==set(PATHS)
    assert "sidebar_state" not in app.session_state
    for path in ("balancing","operations","security-of-supply","risk","ledger","regulatory","kpi","connections","market","demo",""):
        # Streamlit AppTest.switch_page only supports file pages; these are callable
        # pages. Use the actual hash exposed by each rendered native page link.
        app._page_hash=links[path]
        app.run()
        assert not app.exception,(path,[e.message for e in app.exception])
        assert len(app.get("page_link"))==11
        assert app.session_state["settlement_desk_csv_v1"]["sha"]==saved["sha"]
        assert app.session_state["settlement_desk_csv_v1"]["rows"]==rows
        if path=="balancing":
            assert app.radio(key="balancing_view").value=="Cockpit"
            app.radio(key="balancing_view").set_value("Controllo giornaliero").run()
            assert app.radio(key="daily_desk_data_mode").value=="Esempio guidato"
        if path=="operations":
            assert app.session_state["assistant_history_v1"]==[]
            assert app.radio(key="assistant_view").value=="Report locali"
        if path=="risk":
            assert "risk_workspace_v2" in app.session_state
        if path=="security-of-supply":
            assert app.radio(key="operational_platform").value=="MAP"


def test_all_page_modules_have_a_dependency_path_from_the_application():
    paths={p.stem:p for p in (ROOT/"gasops_app").glob("*.py")}
    paths["app"]=ROOT/"app.py"
    graph={name:set() for name in paths}
    for name,path in paths.items():
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id=="lazy":
                if node.args and isinstance(node.args[0],ast.Constant) and node.args[0].value in paths:
                    graph[name].add(node.args[0].value)
            if isinstance(node,ast.ImportFrom):
                module=(node.module or "").split(".")[-1]
                if module in paths:graph[name].add(module)
                if node.module in (None,"gasops_app"):
                    graph[name].update(x.name for x in node.names if x.name in paths)
    reached=set()
    pending=["app"]
    while pending:
        name=pending.pop()
        if name in reached:continue
        reached.add(name)
        pending.extend(graph[name]-reached)
    assert {name for name in paths if name.endswith("_page")}<=reached
