from datetime import datetime,timezone
from hashlib import sha256
import json
import pymupdf
import pytest
from gasops_app.document_desk import build
from gasops_app.compliance import add_reference,assess,case_links,export_register

NOW=datetime(2026,11,18,tzinfo=timezone.utc)
CASE={"id":"a"*64,"agent":"Settlement"}
QUOTE="Il termine di esempio vale sette giorni."


def fixture(text=QUOTE):
    with pymupdf.open() as pdf:
        page=pdf.new_page()
        page.insert_text((72,72),text)
        data=pdf.tobytes()
    return build((("fixture.pdf",data),))


def test_literal_binding_and_review():
    docs=fixture()
    refs,added=add_reference([],CASE,docs,"fixture.pdf",1,QUOTE,"Cap. esempio",NOW)
    assert added and refs[0]["sha256"]==sha256(docs.documents["fixture.pdf"].data).hexdigest()
    same,added=add_reference(refs,CASE,docs,"fixture.pdf",1,QUOTE,"Cap. esempio",NOW)
    assert not added and same==refs
    with pytest.raises(ValueError):
        add_reference(refs,CASE,docs,"fixture.pdf",1,"Il termine di esempio vale cinque giorni.","",NOW)
    with pytest.raises(ValueError):
        add_reference(refs,CASE,docs,"fixture.pdf",2,QUOTE,"",NOW)
    with pytest.raises(ValueError):
        assess(refs[0],"Pertinente per la revisione","",docs,NOW)
    assessed=assess(refs[0],"Pertinente per la revisione","Confronto manuale",docs,NOW)
    assert assessed["history"][0]["note"]=="Confronto manuale"
    assert case_links([assessed],"b"*64,docs)==[]


def test_changed_edition_preserved_but_not_assessable():
    docs=fixture()
    refs,_=add_reference([],CASE,docs,"fixture.pdf",1,QUOTE,"",NOW)
    newer=fixture("Un altro testo di esempio per la revisione.")
    assert case_links(refs,CASE["id"],newer)[0]["edition_status"]=="Edizione assente o cambiata"
    with pytest.raises(ValueError):
        assess(refs[0],"Non pertinente","Edizione cambiata",newer,NOW)
    export=json.loads(export_register(refs,[],newer))
    assert len(export["links"])==1 and not export["links"][0]["case_present"]
    assert "non certificate" in export["notice"]


def test_documentary_panel_empty_and_personal_no_link():
    from streamlit.testing.v1 import AppTest
    app=AppTest.from_string("import streamlit as st\nfrom gasops_app.compliance_page import panel\npanel(st.session_state['fixture'],public=True)")
    app.session_state["fixture"]={"docs":fixture()}
    app.run()
    assert not app.exception
    assert any("Esegui prima" in x.value for x in app.info)
    app=AppTest.from_string("from gasops_app.compliance_page import panel\npanel({},public=False)").run()
    assert not app.exception
    assert any("Archivio pubblico" in x.value for x in app.info)


def test_ui_attach_requires_confirm_and_preserves_case():
    from streamlit.testing.v1 import AppTest
    from gasops_app.compliance import STATE
    app=AppTest.from_string("import streamlit as st\nfrom gasops_app.compliance_page import panel\npanel(st.session_state['fixture'],public=True)")
    case={**CASE,"title":"Rilievo di esempio","period":"2026-11-01","evidence":"Dati di test"}
    app.session_state["fixture"]={"docs":fixture()}
    app.session_state["bso_agentic_v1_session"]={"cases":[case],"current":[case["id"]]}
    app.run()
    assert not app.exception
    next(t for t in app.text_area if t.label.startswith("Estratto letterale")).set_value(QUOTE)
    next(b for b in app.button if b.label=="Collega evidenza").click().run()
    assert not app.exception
    assert STATE not in app.session_state
    next(t for t in app.text_area if t.label.startswith("Estratto letterale")).set_value(QUOTE)
    next(c for c in app.checkbox if c.label.startswith("Confermo di voler associare")).check()
    next(b for b in app.button if b.label=="Collega evidenza").click().run()
    assert not app.exception
    assert len(app.session_state[STATE])==1
    assert app.session_state[STATE][0]["case_id"]==case["id"]
    assert app.session_state["bso_agentic_v1_session"]["cases"]==[case]
