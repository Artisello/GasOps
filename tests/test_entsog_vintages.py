from datetime import date,datetime,timedelta,timezone
from decimal import Decimal
import pandas as pd
import pytest
from gasops_app.entsog_network import NetworkResult,load_programmes
from gasops_app.entsog_vintages import capture,merge,join_programmes,outlook,STATE,SELECT
from gasops_app.session import source_notices

NOW=datetime(2026,11,18,12,tzinfo=timezone.utc)
DAY=date(2026,11,19)
POINT="IT-TSO-0001ITP-00093entry"

def test_notice_only_demoted():
    note="ENTSOG: totale dichiarato discordante; verificati i singoli valori ricevuti. Completezza delle eventuali revisioni non certificata."
    assert source_notices(note)==("",note)
    assert source_notices("Copertura parziale. "+note)==("Copertura parziale.",note)

def test_archive_and_cutoff():
    row={"gas_day":str(DAY),"indicator":"Nomination","quality":"valido","value_gwh_d":Decimal("120"),"timestamp_assumed":False}
    r=NetworkResult(POINT,(("Snam Rete Gas","Mazara"),),DAY,DAY,(row,),NOW,False,False,False)
    b=capture(r,NOW)
    assert merge([], [b,b], NOW)==[b]
    assert outlook({STATE:[b],SELECT:POINT},NOW)["n"]==1
    d=pd.DataFrame({"origin":[pd.Timestamp("2026-11-18")]},index=[pd.Timestamp(DAY)])
    f,cols=join_programmes(d,[b],POINT,"Nomination",pd.Timestamp("2026-11-20"))
    assert f[cols].iloc[0,0]==120
    late={**b,"acquired":"2026-11-18T15:01:00+00:00"}
    f,cols=join_programmes(d,[late],POINT,"Nomination",pd.Timestamp("2026-11-20"))
    assert pd.isna(f[cols].iloc[0,0])
    with pytest.raises(ValueError):merge([], [{**b,"rows":[{**b["rows"][0],"indicator":"Physical Flow"}]}],NOW)
    assert not outlook({STATE:[b],SELECT:POINT},NOW+timedelta(hours=13))
