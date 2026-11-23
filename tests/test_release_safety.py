"""Negative access, session and temporal contracts for the public prototype."""
from datetime import datetime, timedelta, timezone, date
from types import SimpleNamespace
from pathlib import Path
import subprocess
import sys

import pytest
from streamlit.testing.v1 import AppTest
from gasops_app import access, session
from gasops_app.freshness import temporal_evidence
from gasops_app.gas_calendar import gas_day_bounds

NOW = datetime(2026, 11, 23, 10, tzinfo=timezone.utc)


class Identity(dict):
    is_logged_in = True


def authorize(monkeypatch):
    import streamlit as st
    monkeypatch.setenv("GASOPS_PROFILE", access.PRIVATE)
    monkeypatch.setenv("GASOPS_AUTH_ISSUER", "https://identity.example.test")
    monkeypatch.setenv("GASOPS_PRIVATE_SUBJECTS", "operator-1")
    monkeypatch.setattr(st, "user", Identity(iss="https://identity.example.test", sub="operator-1", exp=4102444800))


@pytest.mark.parametrize("profile", ["", "invalid", "public_demo", "test"])
def test_client_state_and_legacy_mode_never_grant_private_access(monkeypatch, profile):
    import streamlit as st
    monkeypatch.setenv("GASOPS_PROFILE", profile)
    monkeypatch.setenv("GASOPS_APP_MODE", "workbench")
    monkeypatch.setenv("IGOR_GME_PRIVATE_AUTHORIZED", "1")
    monkeypatch.setattr(st, "session_state", {"GASOPS_PROFILE":access.PRIVATE,"authenticated":True})
    assert not access.private_access()
    from gasops_app.gme_market import private_enabled
    assert not private_enabled()
    with pytest.raises(PermissionError):
        access.require_private()


def test_private_access_requires_verified_identity_issuer_subject_and_expiry(monkeypatch):
    authorize(monkeypatch)
    assert access.private_access()
    import streamlit as st
    for claim, value in (("iss","https://other.test"),("sub","unknown"),("exp",0),("exp","bad")):
        with monkeypatch.context() as m:
            user=Identity(st.user)
            user[claim]=value
            m.setattr(st,"user",user)
            assert not access.private_access()
    monkeypatch.setattr(st,"user",SimpleNamespace(is_logged_in=False))
    assert not access.private_access()


def test_private_entrypoint_blocks_direct_url_before_loading_application(monkeypatch,tmp_path):
    monkeypatch.setenv("GASOPS_PROFILE",access.PRIVATE)
    monkeypatch.setenv("GASOPS_STATE_DIR",str(tmp_path))
    app=AppTest.from_file(Path(__file__).resolve().parents[1]/"app.py")
    app.query_params.update(profile="private_workbench",authenticated="true",route="operations")
    app.session_state["authenticated"]=True
    app.run()
    assert not app.exception and app.title[0].value=="Accesso riservato"
    assert not app.get("page_link") and not app.get("file_uploader")
    assert not (tmp_path/"state.sqlite3").exists()


def test_legacy_server_pdf_override_is_never_public_or_globally_cached(monkeypatch,tmp_path):
    monkeypatch.setenv("GASOPS_PROFILE",access.PUBLIC)
    monkeypatch.setenv("GASOPS_PDF_DIR",str(tmp_path/"secret"))
    paths=[]
    monkeypatch.setattr(session,"ROOT",tmp_path)
    monkeypatch.setattr(session.st,"session_state",{})
    monkeypatch.setattr(session,"read_local_pdfs",lambda p: paths.append(p) or ())
    monkeypatch.setattr(session,"indexed_library",lambda docs: docs)
    assert session.library()==()
    assert paths==[tmp_path/"data"/"public-regulatory"]
    authorize(monkeypatch)
    monkeypatch.setattr(session,"Library",lambda docs: docs)
    monkeypatch.setattr(session,"indexed_library",lambda *a: pytest.fail("Private documents entered global cache"))
    assert session.library()==()
    assert paths[-1]==tmp_path/"secret"


def test_application_store_blocks_private_history_even_when_opted_in(monkeypatch,tmp_path):
    monkeypatch.setenv("GASOPS_PROFILE",access.PUBLIC)
    monkeypatch.setenv("GASOPS_STATE_DIR",str(tmp_path))
    monkeypatch.setenv("GASOPS_PRIVATE_RUN_HISTORY","1")
    db=session.database()
    for call in (lambda: db.recent(),lambda: db.save(None),lambda: db.reviewed("private"),lambda: db.acknowledge("private","finding")):
        with pytest.raises(PermissionError):call()
    db.cache("public",NOW.isoformat(),"public data")
    assert db.cached("public")[1]=="public data"


def test_public_supabase_mutations_fail_before_network(monkeypatch):
    from gasops_app.document_archive import Archive, ArchiveConfig, AdminSession, ArchiveError
    monkeypatch.setenv("GASOPS_PROFILE",access.PUBLIC)
    monkeypatch.setattr("requests.request",lambda *a,**k: pytest.fail("Unauthorized network request"))
    admin="00000000-0000-4000-8000-000000000001"
    archive=Archive(ArchiveConfig("https://fixture.supabase.co","sb_publishable_fixture",admin))
    fake=AdminSession("forged",4102444800,admin)
    for call in (lambda: archive.login("a@test","secret"),lambda: archive.publish(fake,()),lambda: archive.remove(fake,"example.pdf"),
                 lambda: archive._request("DELETE","/storage/v1/object/gasops-documents")):
        with pytest.raises(ArchiveError):call()


def test_two_sessions_isolate_reports_chat_uploads_and_filters(monkeypatch,tmp_path):
    monkeypatch.setenv("GASOPS_PROFILE",access.PUBLIC)
    monkeypatch.setenv("GASOPS_STATE_DIR",str(tmp_path))
    monkeypatch.setenv("GASOPS_PDF_DIR",str(tmp_path/"private"))
    script="""import streamlit as st
from gasops_app import session
st.text(str(st.session_state.get('last_run', 'no-report')))
st.text(str(st.session_state.get('chat_history', [])))
st.text(str(st.session_state.get('pdf_uploads', ())))
st.text_input('Filtro',key='isolated_filter')
"""
    a,b=AppTest.from_string(script),AppTest.from_string(script)
    for key,value in dict(last_run="A-REPORT",chat_history=["A-CHAT"],pdf_uploads=(("A-PDF",b"private"),),isolated_filter="A").items():
        a.session_state[key]=value
    a.run();b.run()
    assert not a.exception and not b.exception
    assert "A-REPORT" in a.text[0].value
    assert all("A-" not in t.value for t in b.text)
    assert b.text_input[0].value==""
    b.text_input[0].set_value("B").run()
    a.run()
    assert a.text_input[0].value=="A"


def test_recent_retrieval_cannot_promote_historical_observation():
    e=temporal_evidence(now=NOW,gas_day=date(2021,12,31),retrieved_at=NOW,
        current_day=date(2026,11,22),valid=1,expected=1,cached=True)
    assert e["data_status"]=="Historical" and e["historical"] and e["cached"]
    assert e["cache_age"]==0 and e["published_at"] is None and e["observed_at"] is None
    old=temporal_evidence(now=NOW,gas_day=date(2026,11,22),retrieved_at=NOW-timedelta(days=2),
        current_day=date(2026,11,22),valid=1,expected=1)
    assert old["data_status"]=="Stale" and not old["historical"]


@pytest.mark.parametrize("day,hours",[(date(2026,3,28),23),(date(2026,10,24),25)])
def test_temporal_contract_preserves_dst_observation_period(day,hours):
    start,stop=gas_day_bounds(day)
    e=temporal_evidence(now=NOW,gas_day=day,period_from=start,period_to=stop,retrieved_at=NOW,
        current_day=date(2026,11,22),valid=1,expected=1)
    assert (datetime.fromisoformat(e["observation_period"]["to"])-datetime.fromisoformat(e["observation_period"]["from"])).total_seconds()/3600==hours


def test_temporal_missing_future_partial_and_failed_are_separate():
    base=dict(now=NOW,gas_day=date(2026,11,22),current_day=date(2026,11,22),retrieved_at=NOW,expected=2)
    assert temporal_evidence(**base)["data_status"]=="Unavailable"
    assert temporal_evidence(**base,valid=1)["data_status"]=="Partial"
    assert temporal_evidence(**base,valid=2,failed=True)["data_status"]=="Failed refresh"
    base["retrieved_at"]=NOW+timedelta(hours=1)
    assert temporal_evidence(**base,valid=2)["data_status"]=="Partial"
    assert temporal_evidence(**base,valid=2)["cache_age"] is None


def test_cache_only_retains_original_age_and_never_attempts_network(monkeypatch,tmp_path):
    from gasops_app.public_data import cached_only,retrieve,SourceUnavailable
    from gasops_app.store import Store
    import gasops_app.public_data as m
    monkeypatch.setattr(m,"utc_now",lambda: NOW)
    monkeypatch.setattr(m.requests,"get",lambda *a,**k: pytest.fail("Network during rendering"))
    db=Store(tmp_path/"public.sqlite3")
    old=NOW-timedelta(days=2)
    db.cache("public",old.isoformat(),"valid")
    def parser(raw,at,**kwargs):return raw,at,kwargs
    with cached_only():
        assert retrieve(db,key="public",name="Source",url="https://example.test",parse=parser,ttl=timedelta(hours=1))==("valid",old,{"cached":True})
        with pytest.raises(SourceUnavailable):
            retrieve(db,key="missing",name="Source",url="https://example.test",parse=parser,ttl=timedelta(hours=1))


def test_forecast_models_are_imported_only_when_calculating():
    subprocess.run([sys.executable,"-c","import gasops_app.forecast,gasops_app.session,gasops_app.weather_source,sys; assert 'sklearn' not in sys.modules; assert 'statsmodels' not in sys.modules"],check=True)


def test_map_and_explorer_agree_on_recently_retrieved_historical_flow():
    from dataclasses import replace
    from gasops_app.italian_network_page import assets
    from gasops_app.italian_network import evidence_status
    from gasops_app.gas_data import collect
    from gasops_app.source_health import observation_health
    network,_,snapshots=assets()
    snap=next(s for s in snapshots if any(o.indicator=="Physical Flow" and o.value is not None for o in s.records))
    records=tuple(replace(o,retrieved_at=NOW,publication_status="Confirmed") for o in snap.records)
    snap=replace(snap,records=records,acquired=NOW,cached=False,failed=False,partial=False)
    flow=next(o for o in records if o.indicator=="Physical Flow" and o.value is not None)
    day=flow.gas_day
    map_status=evidence_status((flow,),day,NOW,complete=True,current_day=date(2026,11,22))
    frame=collect(network,(snap,),{},NOW,first=day,last=day)
    visible=frame.loc[(frame.indicator=="Physical Flow") & (frame.gas_day==day)]
    health=observation_health(visible,day,day,NOW)
    assert map_status["data_status"]==health["data_status"]=="Historical"
    assert map_status["retrieved_at"]==health["retrieved_at"]==NOW.isoformat()
    assert health["cache_age"]==0


def test_observation_age_allowance_does_not_extend_cache_freshness():
    from gasops_app.source_health import row
    day=date(2026,11,22)
    health=row("GIE · AGSI+","Italia","Osservato",{day:10},[day],NOW,
        acquired=NOW-timedelta(hours=30),period_limit=day,
        age_limit=timedelta(days=3),cache_ttl=timedelta(hours=24))
    assert health["data_status"]=="Stale" and health["cache_age"]==30*3600
    assert not health["historical"]
