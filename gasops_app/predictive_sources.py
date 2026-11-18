"""Session-only feature adapters. Never silently mix sources, points or units."""
from datetime import timedelta
import pandas as pd
from .predictive import Covariate,series_from_rows
from .weather_gas import fetch
from .weather import SOURCE as WEATHER
from .entsog import SOURCE as ENTSOG
from .data import ROME
from .terna_power import PORTAL
from .operational_sources import GIE_LINKS


def session_features(state):
    result={}
    saved=state.get("AGSI+_IT",{})
    agsi=saved.get("result")
    if agsi and agsi.get("scope")=="IT":
        data=agsi["frame"]
        result["storage"]=Covariate("Giacenze AGSI+ Italia",series_from_rows(data.to_dict("records"),"gas_day","stock_twh"),
          "TWh","Italia",GIE_LINKS["AGSI+"],
          "Valori pubblicati, possibili revisioni · acquisizione "+agsi["acquired"].isoformat())
    network=state.get("entsog_network_result_v1")
    if network:
        rows=[r for r in network.rows if r["indicator"]=="Physical Flow" and r["quality"]=="valido"]
        result["flow"]=Covariate("Flusso interconnessione "+network.point,series_from_rows(rows,"gas_day","value_gwh_d"),
               "GWh/d",network.point,ENTSOG,"Singolo punto/direzione · acquisizione "+network.acquired.isoformat())
    terna=state.get("terna_power_v1")
    if terna and terna.get("power"):
        power=terna["power"]
        for metric,label in (("Thermal","Termoelettrico Terna (tutti i combustibili)"),("Wind","Eolico Terna"),("Photovoltaic","Fotovoltaico Terna"),("load","Fabbisogno Terna")):
            rows=[r for r in power["rows"] if r["metric"]==metric and r["gwh"] is not None]
            if rows:
                result["terna_"+metric]=Covariate(label,series_from_rows(rows,"gas_day","gwh"),"GWh elettrici","Italia",PORTAL,
                    "Agg. gas day sperimentale, timestamp assunto inizio intervallo · "+power["acquired"])
    return result


def historical_weather(store,frame,now,*,snapshot=None):
    last=min(frame.index.max().date(),now.astimezone(ROME).date()-timedelta(days=7))
    first=max(frame.index.min().date(),last-timedelta(days=364))
    if (last-first).days<70:
        raise ValueError("Storico insufficiente per il meteo.")
    if snapshot and snapshot["frame"].index.min()<=pd.Timestamp(first) and snapshot["frame"].index.max()>=pd.Timestamp(last):
        weather=snapshot["frame"].loc[str(first):str(last)]
        at,cached,failed=snapshot["acquired"],snapshot["cached"],snapshot["failed"]
    else:
        weather,at,cached,failed=fetch(store,first,last,"era5")
    if weather.empty:
        raise ValueError("Archivio meteo assente.")
    return Covariate("HDD base 18 °C",weather["hdd"],"°C · giorno","Milano/Roma/Napoli, pesi uguali",WEATHER,
                    "ERA5 storico realizzato; ritardo modellistico di 7 giorni · "+at.isoformat()+
                    (" · cache dopo errore" if failed else " · cache" if cached else ""))
