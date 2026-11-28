from datetime import datetime,timedelta,timezone
from pathlib import Path
from gasops_app.readiness import verify
from gasops_app import session
from gasops_app.monitoring import Archive,run,result,obs


def test_release_gate_offline(monkeypatch,tmp_path):
    monkeypatch.setenv("GASOPS_STATE_DIR",str(tmp_path/"real"))
    r=verify()
    assert r["passed"],r
    assert len(r["checks"])==8
    assert {c["check"] for c in r["checks"]}>={"jrc_public_archive","throwaway_sqlite_backup_restore"}
    assert not (tmp_path/"real").exists()
    assert "live APIs and terms" in r["not_verified"]


def test_visitor_pdf_does_not_enter_shared_cache(monkeypatch,tmp_path):
    class State(dict): pass
    monkeypatch.setattr(session.st,"session_state",State(pdf_uploads=(("private.pdf",b"fixture"),)))
    monkeypatch.setattr(session,"read_local_pdfs",lambda d:())
    monkeypatch.setattr(session,"Library",lambda docs:docs)
    def forbidden(*args):
        raise AssertionError("Visitor data reached shared cache")
    monkeypatch.setattr(session,"indexed_library",forbidden)
    assert session.library()==(("private.pdf",b"fixture"),)


def test_monitor_vintage_is_after_acquisition(tmp_path):
    t=datetime(2026,11,18,8,tzinfo=timezone.utc)
    end=t+timedelta(seconds=45)
    times=iter([t,end,end])
    a=Archive(tmp_path/"monitor.sqlite3")
    def fake(source,when):
        assert when==t
        return result(b"data","original_csv",[obs("2026-11-16","IT","flow","GWh",10)],1,1,"2026-11-16")
    r=run(["entsog"],t,a,collector=fake,clock=lambda:next(times))
    assert a.as_of("entsog",t)==[]
    assert a.as_of("entsog",end)[0][4]=="10"
    assert r["checked_at"]==end.isoformat()


def test_public_library_cache_and_mixed_upload_isolation(monkeypatch,tmp_path):
    public=(("public.pdf",b"public fixture"),)
    private=(("private.pdf",b"private fixture"),)
    state={}
    calls=[]
    monkeypatch.setattr(session.st,"session_state",state)
    monkeypatch.setattr(session,"read_local_pdfs",lambda d:public)
    monkeypatch.setattr(session,"Library",lambda documents:documents)
    def cached(documents):
        calls.append(documents)
        return documents
    monkeypatch.setattr(session,"indexed_library",cached)
    assert session.library()==public
    state["pdf_uploads"]=private
    assert session.library()==public+private
    state["pdf_uploads"]=(("another.pdf",b"another fixture"),)
    assert session.library()==public+state["pdf_uploads"]
    state.clear()
    assert session.library()==public
    assert calls==[public,public]
