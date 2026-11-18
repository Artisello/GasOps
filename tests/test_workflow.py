from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from threading import Barrier, Thread

import pytest
import requests

from gasops_app.agents import Assumptions, MarketContext
from gasops_app.data import synthetic
from gasops_app.llm import CompatibleReasoner, LLMConfig
from gasops_app.models import Agent, Result, Run
from gasops_app.regulatory import Library
from gasops_app.reports import markdown
from gasops_app.store import Store
from gasops_app.supervisor import Arguments, Call, Tool, execute
from gasops_app.workflow import run_workflow

NOW = datetime(2026, 11, 17, tzinfo=timezone.utc)


@pytest.fixture
def context():
    return MarketContext(synthetic(), "Seasonal regression", NOW)


def test_complete_offline_workflow_is_traceable(context, monkeypatch, tmp_path):
    def offline(*args, **kwargs):
        raise AssertionError("Offline execution attempted a network request")

    monkeypatch.setattr(requests, "post", offline)
    monkeypatch.setattr(requests, "get", offline)
    snapshots = []
    run = run_workflow(context, Library(), Assumptions(), full=True,
                       notify=lambda state: snapshots.append({k: step.status for k, step in state.steps.items()}))
    assert set(run.results) == set(Agent)
    assert run.mode == "Deterministic"
    assert run.steps[Agent.QUALITY].finished_at <= run.steps[Agent.MARKET].started_at
    assert any(snapshot[Agent.FORECAST] == "running" for snapshot in snapshots)
    assert any(f.id == "notice-7" for f in run.findings)
    assert not any(f.category == "Validazione indipendente" for f in run.findings)
    assert run.results[Agent.SETTLEMENT].values["cash_flow_eur"] == "-50400.00"
    stress = run.results[Agent.SCENARIO].values["stress"]
    assert float(stress["coverage_pct"]) == pytest.approx(87.82, abs=0.02)
    mc = run.results[Agent.SCENARIO].values["monte_carlo"]
    assert mc["settings"]["simulations"] == 10000
    assert 0 <= mc["probability_deficit"] <= 1
    assert mc["gross_cost_tail_eur"]["95"]["cvar"] >= mc["gross_cost_tail_eur"]["95"]["var"]

    store = Store(tmp_path / "state.sqlite3")
    store.save(run)
    store.save(run)
    store.acknowledge(run.id, "notice-7")
    assert store.recent()[0] == run
    assert len(store.recent()) == 1
    md = markdown(run, store.reviewed(run.id))
    assert "PDF p. 103" in md and "preso in carico" in md


def test_independent_tools_overlap(context):
    barrier = Barrier(2, timeout=4)
    agents = [Agent.SETTLEMENT, Agent.REGULATORY]

    def probe(agent):
        barrier.wait()
        return Result(agent=agent, summary="Completed")

    tools = {agent: Tool("Concurrent test", Arguments, lambda _, agent=agent: probe(agent)) for agent in agents}
    report = Run(question="Check concurrency", source=context.bundle.origin, input_sha256="fixture", assumptions={})
    report = execute(report, tools, [Call(a, Arguments()) for a in agents], set(agents), lambda _: [], lambda _: None)
    assert all(report.steps[agent].status == "completed" for agent in agents)


def test_deterministic_analysis_routes_question_and_assumptions(context):
    request = "Cosa succede se la domanda aumenta del 15% e l’offerta cala dell’8%?"
    run = run_workflow(context, Library(), Assumptions(), request)
    assert run.results[Agent.SCENARIO].values["changes"]["demand_pct"] == "15"
    assert run.results[Agent.SCENARIO].values["changes"]["supply_pct"] == "-8"
    assert Agent.SETTLEMENT not in run.results
    assert Agent.REGULATORY not in run.results


def test_model_timeout_uses_deterministic_tools(context, monkeypatch):
    def unavailable(*args, **kwargs):
        raise requests.Timeout()

    monkeypatch.setattr(requests, "post", unavailable)
    reasoner = CompatibleReasoner(LLMConfig("offline-model", "http://127.0.0.1:9999/v1"))
    run = run_workflow(context, Library(), Assumptions(), full=True, reasoner=reasoner)
    assert run.mode == "Deterministic fallback"
    assert len(run.results) == 6
    assert run.warnings and run.interpretation is None


def test_llm_tool_protocol_routes_and_retrieves_in_bounded_rounds(context):
    requests_seen = []

    def tool_call(name, args, identifier):
        return {"tool_calls": [{"id": identifier, "type": "function",
                                "function": {"name": name, "arguments": json.dumps(args)}}]}

    answers = [
        tool_call("scenario", {"demand_pct": "12"}, "scenario_call"),
        tool_call("regulatory_intelligence", {"query": "seven days of cancellation notice"}, "reg_call"),
        {"content": json.dumps({"interpretation": "The stress screen and the edition boundary both merit review.",
                                "references": ["scenario", "regulatory_intelligence"]})},
    ]

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            requests_seen.append((self.path, json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
            reply = json.dumps({"choices": [{"message": answers[len(requests_seen) - 1]}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(reply)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        model = CompatibleReasoner(LLMConfig("configured-test-model", f"http://127.0.0.1:{server.server_port}/v1"))
        run = run_workflow(context, Library(), Assumptions(),
                           "Check +12% demand and look up the cancellation boundary if needed.", reasoner=model)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert run.mode == "LLM-assisted"
    assert len(requests_seen) == 3
    assert requests_seen[0][0] == "/v1/chat/completions"
    assert any(msg.get("tool_call_id") == "scenario_call" for msg in requests_seen[1][1]["messages"])
    assert any(msg.get("tool_call_id") == "reg_call" for msg in requests_seen[2][1]["messages"])
    assert run.results[Agent.SCENARIO].values["changes"]["demand_pct"] == "12"
    assert run.interpretation_sources == [Agent.SCENARIO, Agent.REGULATORY]
    assert Agent.MARKET not in run.results


def test_cvar_routes_to_scenario(context):
    run = run_workflow(context, Library(), Assumptions(), "Calcola CVaR e Monte Carlo")
    assert "monte_carlo" in run.results[Agent.SCENARIO].values



def test_planned_assistant_shortcut_keeps_local_tools_and_single_model_call(context):
    class SummaryOnly:
        label="mock"
        calls=0
        def route(self,*args):
            pytest.fail("Shortcut must not call the model for routing")
        def review(self,*args):
            pytest.fail("Shortcut must not call the model for review")
        def summarize(self,run):
            self.calls+=1
            assert Agent.SCENARIO in run.results
            return "Sintesi dello scenario.",[Agent.SCENARIO]
    reasoner=SummaryOnly()
    run=run_workflow(context,Library(),Assumptions(),
                     "Simula uno scenario in cui la domanda aumenta del 10%.",
                     reasoner=reasoner,planned_only=True)
    assert reasoner.calls==1
    assert run.mode=="LLM-assisted"
    assert run.interpretation=="Sintesi dello scenario."
    assert run.results[Agent.SCENARIO].values["changes"]["demand_pct"]=="10"
