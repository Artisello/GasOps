from datetime import datetime,timezone,timedelta
from concurrent.futures import ThreadPoolExecutor
import pytest
from gasops_app.llm import configuration, CompatibleReasoner, LLMConfig
from gasops_app.store import Store
from gasops_app.supervisor import ModelUnavailable

NOW=datetime(2026,11,18,tzinfo=timezone.utc)

def test_groq_secrets_and_paid_guard():
    c=configuration({"GROQ_API_KEY":"fixture","GASOPS_LLM_MODEL":"","GASOPS_LLM_URL":""})
    assert c.groq and c.model=="openai/gpt-oss-120b"
    assert "fixture" not in repr(c)
    with pytest.raises(ValueError,match="costi"):
        configuration({"GASOPS_LLM_MODEL":"grok","GASOPS_LLM_URL":"https://api.x.ai/v1",
                       "GASOPS_LLM_API_KEY":"fixture","GASOPS_ALLOW_PAID_LLM":"false"})

def test_shared_budget_atomic(tmp_path):
    db=Store(tmp_path/"budget.sqlite3")
    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes=list(pool.map(lambda _:db.reserve_llm(now=NOW),range(10)))
    assert sum(outcomes)==4 and db.llm_usage(now=NOW)==4
    assert db.reserve_llm(now=NOW+timedelta(seconds=61))
    assert db.llm_usage(now=NOW+timedelta(hours=24,seconds=62))==0

def test_llm_budget_denies_before_http(monkeypatch):
    def fail(*args,**kwargs):
        raise AssertionError("Network must not be called")
    monkeypatch.setattr("gasops_app.llm.requests.post",fail)
    model=CompatibleReasoner(LLMConfig("openai/gpt-oss-120b","https://api.groq.com/openai/v1","fixture"),
                             reserve=lambda:False)
    with pytest.raises(ModelUnavailable,match="Quota interna"):
        model.probe()

def test_external_evidence_excludes_private_tools():
    from gasops_app.llm import _evidence
    from gasops_app.models import Agent, Result
    results={a:Result(agent=a,summary="fixture") for a in Agent}
    safe=_evidence(results,external=True)
    assert Agent.REGULATORY.value not in safe and Agent.SETTLEMENT.value not in safe
    assert Agent.MARKET.value in safe


def test_generic_groq_secret_detected():
    c=configuration({"GASOPS_LLM_API_KEY":"gsk_fixture","GASOPS_LLM_MODEL":"",
                     "GASOPS_LLM_URL":"https://api.groq.com/openai/v1","GROQ_API_KEY":""})
    assert c.groq and c.model=="openai/gpt-oss-120b"


def test_unknown_key_not_guessed():
    with pytest.raises(ValueError,match="modello non configurato"):
        configuration({"GASOPS_LLM_API_KEY":"unknown","GASOPS_LLM_MODEL":"","GROQ_API_KEY":""})
