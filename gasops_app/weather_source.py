"""Shared weather history and outlook; independent retrieval, labelled vintages."""
from datetime import timedelta,datetime
import os
import pandas as pd
from .data import ROME
from .weather_gas import fetch
from .weather import SOURCE
from .models import utc_now
from .public_data import SourceUnavailable

STATE="weather_public_v1"
SCOPE="Milano, Roma, Napoli · pesi uguali · giorno gas 06–06"
TTL=timedelta(hours=6)


def enabled(state):
    # Free endpoint is for this independent non-commercial demo only.
    return os.getenv("IGOR_WEATHER_ENABLED","1").lower() not in ("0","false","no","off") and bool(state.get("briefing_weather",True))


def refresh(state,store,now,*,force=False):
    if not enabled(state):return "Meteo disattivato"
    prior=state.get(STATE,{})
    attempted=prior.get("attempted")
    if attempted and now-attempted<(timedelta(minutes=1) if force else TTL):
        return prior.get("note","")
    today=now.astimezone(ROME).date()
    saved={**prior,"attempted":now}
    notes=[]
    for kind,first,last in (("era5",today-timedelta(days=365),today-timedelta(days=7)),
                            ("forecast",today+timedelta(days=1),today+timedelta(days=7))):
        try:
            frame,at,cached,failed=fetch(store,first,last,kind,refresh=force)
            if at.tzinfo is None or at>utc_now() or frame.empty or frame["hdd"].notna().sum()==0:
                raise ValueError("Dati meteo non validi")
            saved[kind]={"frame":frame,"acquired":at,"cached":cached,"failed":failed}
            if failed:notes.append(kind+" · cache dopo mancato aggiornamento")
        except (SourceUnavailable,ValueError,OSError,TypeError,KeyError):
            if kind in saved:saved[kind]={**saved[kind],"failed":True}
            notes.append(kind+" · ultimo dato valido conservato, se presente")
    saved["note"]="; ".join(notes)
    state[STATE]=saved
    return saved["note"]


def outlook(state,now):
    if not enabled(state):return None
    item=state.get(STATE,{}).get("forecast")
    if not item:return None
    at=item["acquired"]
    if at>now or now-at>timedelta(hours=12) or item["failed"]:
        return None
    today=now.astimezone(ROME).date()
    f=item["frame"].loc[str(today+timedelta(days=1)):str(today+timedelta(days=7))]
    f=f.dropna(subset=["temperature_c","hdd"])
    if f.empty:return None
    return {"source":"Open-Meteo (CC BY 4.0)","url":SOURCE,"scope":SCOPE,
        "acquired":at.isoformat(),"from":f.index[0].date().isoformat(),"to":f.index[-1].date().isoformat(),
        "n":len(f),"points":[{"day":d.date().isoformat(),"temperature_c":float(r.temperature_c),"hdd":float(r.hdd)} for d,r in f.iterrows()],
        "limitation":"Previsioni meteo, non misure; HDD base 18 °C; proxy territoriale non pesata per domanda."}


def archive(state,now):
    if not enabled(state):return None
    item=state.get(STATE,{}).get("era5")
    if not item or item["acquired"]>now:return None
    f=item["frame"].loc[:str(now.astimezone(ROME).date()-timedelta(days=7))]
    return {**item,"frame":f} if not f.empty else None
