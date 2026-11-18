from datetime import datetime,timezone
import json
import pytest
from gasops_app.operational_sources import parse_agsi,parse_jarvis,jarvis_template,load_agsi

NOW=datetime(2026,11,18,12,tzinfo=timezone.utc)

def arow(day="2026-11-17",status="C",stock="90"):
    return {"code":"IT","gasDayStart":day,"status":status,"gasInStorage":stock,
            "workingGasVolume":"100","full":"90","injection":"8","withdrawal":"7"}

def test_storage_missing_and_country_and_conflicts():
    payload={"last_page":1,"data":[arow(),arow("2026-11-16","N",None)]}
    r=parse_agsi(json.dumps(payload),NOW,scope="IT")
    assert r["frame"]["stock_twh"].isna().sum()==1
    assert r["frame"].iloc[-1]["stock_twh"]==90
    assert r["frame"].iloc[-1]["withdrawal_gwh_d"]==7
    with pytest.raises(ValueError,match="Perimetro"):
        parse_agsi(json.dumps(payload),NOW,scope="EU")
    payload["data"].append(arow(stock="91"))
    with pytest.raises(ValueError,match="conflitto"):
        parse_agsi(json.dumps(payload),NOW,scope="IT")
    payload["last_page"]=2
    with pytest.raises(ValueError,match="paginata"):
        parse_agsi(json.dumps(payload),NOW,scope="IT")

def test_agsi_bounded_call(monkeypatch):
    import gasops_app.operational_sources as op
    def fake(store,**kwargs):
        assert kwargs["headers"]=={"x-key":"test-key"}
        assert kwargs["params"]["country"]=="IT"
        assert kwargs["params"]["size"]==100
        assert kwargs["attempts"]==1
        assert kwargs["ttl"].total_seconds()==86400
        return kwargs["parse"](json.dumps({"last_page":1,"data":[arow()]}),NOW)
    monkeypatch.setattr(op,"retrieve",fake)
    assert load_agsi(None,"test-key",now=NOW)["scope"]=="IT"
    with pytest.raises(ValueError):
        load_agsi(None,"",now=NOW)

def j(*lines):
    return (jarvis_template()+"\n".join(lines)+"\n").encode()

def test_jarvis_preserves_versions_and_signed_sas():
    r=parse_jarvis(j("2026-11-17,2026-11-17T06:30:00+01:00,2200,-40,1000",
                     "2026-11-17,2026-11-18T02:00:00+01:00,2300,-20,1010"),now=NOW)
    assert len(r["versions"])==2 and len(r["latest"])==1
    assert r["latest"].iloc[0]["sas_gwh"]==-20
    assert len(r["sha256"])==64

def test_jarvis_missing_and_conflicting():
    r=parse_jarvis(j("2026-11-17,2026-11-17T07:00:00+01:00,2200,,"),now=NOW)
    assert r["latest"]["sas_gwh"].isna().all()
    with pytest.raises(ValueError,match="conflitto"):
        parse_jarvis(j("2026-11-17,2026-11-17T07:00:00+01:00,2200,-1,",
                       "2026-11-17,2026-11-17T07:00:00+01:00,2200,-2,"),now=NOW)
    with pytest.raises(ValueError,match="giorno-gas"):
        parse_jarvis(j("2026-11-17,2026-11-18T07:00:00+01:00,2200,-1,"),now=NOW)
    with pytest.raises(ValueError,match="offset"):
        parse_jarvis(j("2026-11-17,2026-11-17T07:00:00,2200,-1,"),now=NOW)
