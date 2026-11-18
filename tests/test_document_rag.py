import json
import pytest
from gasops_app.document_rag import answer
from gasops_app.models import Citation
from gasops_app.llm import CompatibleReasoner, LLMConfig


def test_remote_requires_consent_and_budget(monkeypatch):
    hit=Citation(document="private.pdf",page=2,evidence="La garanzia vale fino al termine.")
    model=CompatibleReasoner(LLMConfig("fixture","https://api.groq.com/openai/v1","key"))
    monkeypatch.setattr(model,"_chat",lambda *a,**k:pytest.fail("No call allowed"))
    with pytest.raises(ValueError,match="Consenso"):
        answer(model,"garanzia",[hit])
    with pytest.raises(ValueError,match="Quota"):
        answer(model,"garanzia",[hit],authorized_remote=True)


def test_verified_quote_and_no_filename_sent(monkeypatch):
    hit=Citation(document="private.pdf",page=2,evidence="La garanzia vale fino al termine.")
    sent=[]
    model=CompatibleReasoner(LLMConfig("fixture","https://api.groq.com/openai/v1","key"),reserve=lambda:True)
    def respond(messages,*,structured):
        sent.append(messages)
        assert structured
        return {"content":json.dumps({"claims":[{"text":"La garanzia dura fino al termine.",
            "source":"D1","quote":"La garanzia vale fino al termine."}]})}
    monkeypatch.setattr(model,"_chat",respond)
    result=answer(model,"garanzia",[hit],authorized_remote=True)
    assert result[0]["citation"]==hit
    assert "private.pdf" not in json.dumps(sent)
    assert answer(model,"garanzia",[],authorized_remote=True)==[] and len(sent)==1
    monkeypatch.setattr(model,"_chat",lambda *a,**k:{"content":json.dumps({"claims":[{"text":"Inventato",
        "source":"D1","quote":"Citazione inventata."}]})})
    with pytest.raises(ValueError,match="Citazione"):
        answer(model,"garanzia",[hit],authorized_remote=True)


def test_local_without_remote_consent(monkeypatch):
    model=CompatibleReasoner(LLMConfig("fixture","http://localhost:11434/v1"))
    monkeypatch.setattr(model,"_chat",lambda *a,**k:{"content":'{"claims":[]}'})
    assert answer(model,"garanzia",[Citation(document="a",page=1,evidence="Testo documento")])==[]
