from datetime import datetime,timedelta,timezone,date
import json
from pathlib import Path
import pytest
from gasops_app.monitoring import Archive,run,result,obs,parse_report,write_report

NOW=datetime(2026,11,18,8,tzinfo=timezone.utc)


def sample(value=10):
    return result(str(value).encode(),"original_csv",[obs("2026-11-16","IT","flow","GWh",value)],1,1,"2026-11-16")


def test_archive_vintages_and_dedup(tmp_path):
    a=Archive(tmp_path/"monitor.db")
    assert a.save("entsog",sample(),NOW)==(0,0)
    assert a.save("entsog",sample(),NOW+timedelta(hours=1))==(0,0)
    assert a.save("entsog",sample(12),NOW+timedelta(days=1))==(1,0)
    assert a.as_of("entsog",NOW)[0][4]=="10"
    assert a.as_of("entsog",NOW+timedelta(days=1))[0][4]=="12"
    with a.connect() as db:
        assert db.execute("select count(*) from snapshots").fetchone()[0]==2
        assert db.execute("select count(*) from acquisitions").fetchone()[0]==3


def test_missing_does_not_replace_previous(tmp_path):
    a=Archive(tmp_path/"monitor.db")
    a.save("entsog",sample(),NOW)
    a.save("entsog",result(b"missing","original_csv",[],0,1,None,"partial",["coverage"]),NOW+timedelta(days=1))
    assert a.as_of("entsog",NOW+timedelta(days=1))[0][4]=="10"


def test_robust_new_date_only(tmp_path):
    a=Archive(tmp_path/"monitor.db")
    rows=[obs(date(2026,11,1)+timedelta(days=i),"IT","flow","GWh",100) for i in range(15)]
    a.save("entsog",result(b"first","original_json",rows,15,15,"2026-11-15"),NOW)
    assert a.save("entsog",result(b"next","original_json",[obs("2026-11-16","IT","flow","GWh",200)],1,1,"2026-11-16"),NOW+timedelta(hours=1))==(0,1)


def test_failure_isolation_public_report_no_payload(tmp_path):
    def fake(source,now):
        if source=="acer":
            raise ValueError("private-token")
        if source=="mase":
            return result(b"raw","original_csv_pending",[],None,3,None,"raw_pending")
        return sample()
    r=run(["entsog","acer","mase"],NOW,collector=fake)
    assert [s["status"] for s in r["sources"]]==["ok","failed","raw_pending"]
    assert all(s["revisions"] is None for s in r["sources"])
    path=tmp_path/"report.json"
    write_report(r,path)
    assert "private-token" not in path.read_text()
    assert "payload" not in path.read_text()
    assert parse_report(path.read_bytes())==r
    r["sources"][0]["url"]="https://bad.example/"
    with pytest.raises(ValueError):
        parse_report(json.dumps(r).encode())


def test_optional_sources_skip():
    r=run(["gie","terna"],NOW,collector=lambda *_:None)
    assert all(s["status"]=="skipped" and s["valid"] is None for s in r["sources"])


def test_monitor_ui_empty(monkeypatch,tmp_path):
    from streamlit.testing.v1 import AppTest
    monkeypatch.setenv("GASOPS_STATE_DIR",str(tmp_path))
    app=AppTest.from_string("from gasops_app.bso_kpi_page import page\npage()",default_timeout=30).run()
    app.radio(key="bso_view").set_value("Monitoraggio fonti").run()
    assert not app.exception
    assert any("Nessun report disponibile" in x.value for x in app.info)
    write_report(run(["entsog"],NOW,collector=lambda *_:sample()),tmp_path/"monitor-report.json")
    app.run()
    assert not app.exception
    assert any("1 fonti nel report" in x.value for x in app.caption)
    _assert_monitor_cards(app,{"Acquisite":1,"Da verificare":0,"Non riuscite":0,"Non configurate":0})


def _assert_monitor_cards(app,expected):
    """Read rendered KPI values, not the removed native st.metric elements."""
    import re
    grids=[e.proto.body for e in app.get("html") if 'class="gas-kpi-grid"' in e.proto.body
           and '<span class="key">Acquisite</span>' in e.proto.body]
    assert len(grids)==1
    actual=dict(re.findall(r'<span class="key">([^<]+)</span><div class="readout">'
                           r'<span class="value [^"]*">([^<]+)</span>',grids[0]))
    assert actual=={label:str(value) for label,value in expected.items()}


def test_monitor_ui_distinguishes_source_statuses(monkeypatch,tmp_path):
    from streamlit.testing.v1 import AppTest
    monkeypatch.setenv("GASOPS_STATE_DIR",str(tmp_path))
    def collect(source,now):
        if source=="acer":raise ValueError("fixture")
        if source=="mase":return result(b"raw","original_csv_pending",[],None,3,None,"raw_pending")
        if source=="gie":return None
        if source=="terna":return result(b"partial","original_json",[],0,1,None,"partial",["coverage"])
        return sample()
    write_report(run(["entsog","acer","mase","gie","terna"],NOW,collector=collect),tmp_path/"monitor-report.json")
    app=AppTest.from_string("from gasops_app.monitoring_page import panel\npanel()",default_timeout=30).run()
    assert not app.exception
    _assert_monitor_cards(app,{"Acquisite":1,"Da verificare":2,"Non riuscite":1,"Non configurate":1})
    assert any("5 fonti nel report" in x.value for x in app.caption)


def test_report_rejects_impossible_counts_and_failed_observations():
    r=run(["entsog"],NOW,collector=lambda *_:sample())
    r["sources"][0]["valid"]=2
    with pytest.raises(ValueError):parse_report(json.dumps(r).encode())
    r["sources"][0]["valid"]=1
    r["sources"][0]["status"]="failed"
    with pytest.raises(ValueError):parse_report(json.dumps(r).encode())
