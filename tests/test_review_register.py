from datetime import datetime,timezone
from types import SimpleNamespace
import json
import pytest
from gasops_app.models import Citation
from gasops_app.review_register import register,decide,valid_cases,export_json,export_markdown


def sample():
    docs=SimpleNamespace(documents={"a":SimpleNamespace(digest="a"*64),"b":SimpleNamespace(digest="b"*64)})
    item={"title":"Termine diverso","detail":"Possibile divergenza.","check":"Verificare il perimetro.",
          "citations":[Citation(document="a",page=1,evidence="Il termine è sette giorni."),
                       Citation(document="b",page=2,evidence="Il termine è cinque giorni.")]}
    return docs,item


def test_case_register_preserves_history_and_versions():
    docs,item=sample()
    now=datetime(2026,11,18,tzinfo=timezone.utc)
    cases,added,omitted=register([], [item],docs,theme="termini",model="fixture",now=now)
    assert added==1 and omitted==0
    case=decide(cases[0],"Archiviato","Perimetri differenti.",now=now)
    again,added,_=register([case],[item],docs,theme="termini",model="fixture",now=now)
    assert added==0 and again==[case]
    payload=json.loads(export_json(again))
    assert payload["cases"][0]["history"][0]["note"]=="Perimetri differenti."
    markdown=export_markdown(again)
    assert "PDF p. 1" in markdown and "a"*64 in markdown and "Perimetri differenti." in markdown
    docs.documents["a"].digest="c"*64
    assert valid_cases(again,docs)==[]


def test_note_and_limits():
    docs,item=sample()
    cases,_,_=register([], [item],docs,theme="x",model="fixture")
    with pytest.raises(ValueError):
        decide(cases[0],"Archiviato","")
    with pytest.raises(ValueError):
        decide(cases[0],"Conformità verificata","note")
    items=[{**item,"title":str(i)} for i in range(41)]
    cases,added,omitted=register([],items,docs,theme="x",model="fixture")
    assert len(cases)==added==40 and omitted==1



def test_register_ui_can_record_human_review_without_model(monkeypatch):
    from streamlit.testing.v1 import AppTest
    from gasops_app import document_page as desk
    import streamlit as st
    from gasops_app.review_register import KEY
    docs,item=sample()
    cases,_,_=register([], [item],docs,theme="termini",model="fixture")
    monkeypatch.setattr(desk,"reasoner",lambda:pytest.fail("Register must not invoke AI"))
    app=AppTest.from_string("import streamlit as st\nfrom gasops_app.document_page import _review_register\n_review_register(st.session_state['fixture_register'])")
    app.session_state["fixture_register"]={"docs":docs,KEY:cases}
    app.run()
    assert not app.exception
    next(x for x in app.selectbox if x.label=="Stato della verifica").set_value("Archiviato")
    next(x for x in app.text_area if x.label=="Motivazione della decisione").set_value("Perimetri differenti.")
    next(b for b in app.button if b.label=="Registra verifica").click().run()
    assert not app.exception
    case=app.session_state["fixture_register"][KEY][0]
    assert case["status"]=="Archiviato"
    assert case["history"][0]["note"]=="Perimetri differenti."
