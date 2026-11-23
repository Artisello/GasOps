from datetime import datetime,timezone,timedelta
from types import SimpleNamespace

from gasops_app import connections_page as page
from gasops_app.live_sources import STATUS

NOW=datetime(2026,11,21,12,tzinfo=timezone.utc)


def test_provider_catalog_never_calls_an_unchecked_configuration_connected():
    config={"available":["monthly","daily","acer"],"gie":None,"terna":None,"ai":None,"documents":None}
    rows={r["Fonte"]:r for r in page.provider_rows({},config)}
    assert "da verificare" in rows["Eurostat + ARERA"]["Stato"]
    assert rows["GIE · AGSI+"]["Stato"]=="Non configurata"
    assert rows["Modello AI"]["Stato"]=="Non configurata"
    assert rows["Eurostat + ARERA"]["Configurata"] is True
    assert rows["Eurostat + ARERA"]["Raggiungibile"] is None
    assert rows["Eurostat + ARERA"]["Risposta validata"] is None
    assert rows["Eurostat + ARERA"]["Dati nel periodo"] is False
    assert "live pendente" in rows["MASE"]["Stato"]
    # A past success does not turn a removed configuration into a connection.
    stale={page.EXTRA:{"ai":{"status":"Verificata","at":NOW.isoformat()}}}
    rows={r["Fonte"]:r for r in page.provider_rows(stale,config)}
    assert rows["Modello AI"]["Stato"]=="Non configurata"


def test_all_connected_adapters_are_used_and_failure_preserves_prior_results(monkeypatch):
    called=[]
    def refresh(state,store,now,available,**kwargs):
        called.extend(available)
        state[STATUS]={"attempted":now,"sources":{}}
        return True
    monkeypatch.setattr(page,"refresh",refresh)
    def iip(*a,**k):
        called.append("iip")
        raise ValueError("upstream failure")
    monkeypatch.setattr("gasops_app.operational_sources.load_iip",iip)
    class Reasoner:
        def __init__(self,*a,**k):pass
        def probe(self):called.append("ai");return True
    monkeypatch.setattr("gasops_app.llm.CompatibleReasoner",Reasoner)
    class Archive:
        def __init__(self,*a):pass
        def list_keys(self):called.append("documents");return []
    monkeypatch.setattr("gasops_app.document_archive.Archive",Archive)
    config={"available":["monthly","daily","acer","agsi","alsi","terna","terna_forward","terna_capacity","terna_industry","weather"],
            "gie":"fixture-key","terna":("id","secret"),"ai":SimpleNamespace(local=True),"documents":object()}
    prior={"messages":[{"id":"previous"}]}
    state={"gie_iip":{"result":prior}}
    assert page.refresh_all(state,None,config,NOW)
    assert called==[*config["available"],"iip","ai","documents"]
    assert state["gie_iip"]["result"]==prior
    assert state[page.EXTRA]["iip"]["status"]=="Da verificare"
    assert state[page.EXTRA]["ai"]["status"]=="Verificata"
    assert state[page.EXTRA]["documents"]["status"]=="Verificata"
    assert not page.refresh_all(state,None,config,NOW+timedelta(seconds=1))
