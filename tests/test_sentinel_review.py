import json
from types import SimpleNamespace

import pandas as pd
import pytest

from gasops_app.document_review import compare_evidence
from gasops_app.models import Citation, Finding, Kind
from gasops_app.sentinel import snapshot


def test_review_only_publishes_two_verified_distinct_references():
    a=Citation(document="private-a.pdf",page=3,evidence="Il termine previsto è di sette giorni.")
    b=Citation(document="private-b.pdf",page=8,evidence="Il termine previsto è di cinque giorni.")
    item={"title":"Termini diversi","detail":"Possibile divergenza da verificare.",
          "check":"Verificare se il perimetro coincide.","a":"A1","quote_a":a.evidence,
          "b":"B1","quote_b":b.evidence}
    calls=[]
    def respond(messages,*,structured):
        calls.append(messages)
        assert structured
        return {"content":json.dumps({"findings":[item]})}
    model=SimpleNamespace(config=SimpleNamespace(local=False),reserve=lambda:True,_chat=respond)
    with pytest.raises(ValueError,match="Consenso"):
        compare_evidence(model,"termini",[a],[b])
    assert not calls
    assert compare_evidence(model,"termini",[a],[],authorized_remote=True)==[]
    assert not calls
    result=compare_evidence(model,"termini",[a],[b],authorized_remote=True)
    assert result[0]["citations"]==[a,b]
    assert "private-a.pdf" not in json.dumps(calls)
    item["quote_b"]="Citazione inventata."
    with pytest.raises(ValueError,match="Citazioni"):
        compare_evidence(model,"termini",[a],[b],authorized_remote=True)
    item["quote_b"]=b.evidence
    item["b"]="A1"
    with pytest.raises(ValueError,match="Citazioni"):
        compare_evidence(model,"termini",[a],[b],authorized_remote=True)
    assert compare_evidence(model,"termini",[a],[a],authorized_remote=True)==[]


def test_sentinel_counts_missing_values_and_labels_demo():
    series=pd.Series([100.,None,115.,None,110.,120.,None])
    context=SimpleNamespace(
        bundle=SimpleNamespace(origin=SimpleNamespace(grain="daily",archive=False,kind=Kind.SYNTHETIC)),
        inspection=SimpleNamespace(usable=pd.DataFrame({"demand_gwh":series}),findings=[
            Finding(id="stale",title="Fonte non recente",severity="medium",detail="Controllare",category="Dati")]),
        facts={"demand_gwh_change_pct":16.},
        projection=SimpleNamespace(points=[]))
    result=snapshot(context)
    assert result["observed"]==4 and result["expected"]==7
    assert result["trend"] and result["demo"]
    assert len(result["findings"])==1 and len(result["actions"])==4
