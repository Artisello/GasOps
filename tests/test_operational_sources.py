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
        assert kwargs["headers"]["x-key"]=="test-key"
        assert kwargs["headers"]["Accept"]=="application/json"
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


def test_gie_attribution_and_alsi_units():
    from gasops_app.operational_sources import parse_alsi,attributed_csv,attribution
    row={"code":"IT","gasDayStart":"2026-11-17","inventory":{"lng":"20","gwh":"130"},
         "dtmi":"50","sendOut":"40","dtrs":"100","status":"C"}
    r=parse_alsi(json.dumps({"last_page":1,"data":[row]}),NOW,scope="IT")
    assert r["frame"].iloc[0]["inventory_1000m3_lng"]==20
    assert r["frame"].iloc[0]["inventory_gwh"]==130
    assert r["frame"].iloc[0]["sendout_reference_pct"]==40
    assert attribution("ALSI")["source"] in attributed_csv(r)
    assert "https://alsi.gie.eu/" in attributed_csv(r)
    row["inventory"]="20"
    row["dtrs"]="0"
    r=parse_alsi(json.dumps({"last_page":1,"data":[row]}),NOW,scope="IT")
    assert r["frame"]["inventory_gwh"].isna().all()
    assert r["frame"]["sendout_reference_pct"].isna().all()


def test_agsi_export_has_credit():
    from gasops_app.operational_sources import attributed_csv,attribution
    r=parse_agsi(json.dumps({"last_page":1,"data":[arow()]}),NOW,scope="IT")
    assert attribution("AGSI+")["source"] in attributed_csv(r)
    assert "https://agsi.gie.eu/" in attributed_csv(r)


def test_iip_partial_and_attributed_json():
    from gasops_app.operational_sources import parse_iip,attributed_iip_json
    raw={"last_page":2,"data":[{"messageId":"test","message":"Example only"}]}
    result=parse_iip(json.dumps(raw),NOW)
    assert result["partial"] is True
    export=json.loads(attributed_iip_json(result))
    assert "GIE" in export["source"] and export["source_url"]=="https://iip.gie.eu/"
    assert export["messages"]==raw["data"]
    with pytest.raises(ValueError):
        parse_iip(json.dumps({"last_page":0,"error":"access denied","data":[]}),NOW)


def test_shared_gie_key(monkeypatch):
    from gasops_app.operational_sources import gie_key
    monkeypatch.delenv("GASOPS_GIE_API_KEY",raising=False)
    monkeypatch.setenv("GASOPS_AGSI_API_KEY","old")
    assert gie_key()=="old"
    monkeypatch.setenv("GASOPS_GIE_API_KEY","new")
    assert gie_key()=="new"


def test_gie_real_document_decimal_formats_and_single_record():
    from gasops_app.operational_sources import number
    data=arow(stock="63,9469")
    data.update({"workingGasVolume":"243,4311","injection":"563,62","withdrawal":"591,99","full":"26.27"})
    result=parse_agsi(json.dumps({"last_page":1,"total":1,"data":data}),NOW,scope="IT")
    assert result["frame"].iloc[0]["stock_twh"]==pytest.approx(63.9469)
    assert result["frame"].iloc[0]["injection_gwh_d"]==pytest.approx(563.62)
    with pytest.raises(ValueError):
        number("1.234,56")
    with pytest.raises(ValueError,match="Accesso GIE negato"):
        parse_agsi(json.dumps({"last_page":0,"error":"access denied","message":"Invalid or missing API key"}),NOW,scope="IT")


def test_optional_capacity_can_be_missing():
    data=arow()
    data["workingGasVolume"]=None
    data["full"]=None
    result=parse_agsi(json.dumps({"last_page":1,"data":[data]}),NOW,scope="IT")
    assert result["frame"]["capacity_twh"].isna().all()


def test_gie_secret_can_be_read_before_env_export(monkeypatch):
    from gasops_app.operational_sources import gie_key
    monkeypatch.delenv("GASOPS_GIE_API_KEY",raising=False)
    assert gie_key({"GASOPS_GIE_API_KEY":"  secret  "})=="secret"
