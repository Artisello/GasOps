"""Weather scenario: consented, cached and independent from baseline forecast."""
from datetime import datetime,timedelta,timezone

import pandas as pd
import streamlit as st

from .italiano import numero
from .models import Kind, utc_now
from .public_data import SourceUnavailable
from .session import database
from .weather_gas import analyse_gas_day
from .visuals import info, local_time

LABELS={"calendar":"Calendario · aggregato","aggregate_weather":"Calendario + HDD · aggregato",
        "sector_calendar":"Calendario · tre settori","sector_weather":"Calendario + HDD · tre settori"}
SECTORS={"distribution_gwh":"Distribuzione","industry_gwh":"Industria","power_gwh":"Termoelettrico"}


def weather_panel(context):
    origin=context.bundle.origin
    if not (origin.grain=="daily" and origin.kind==Kind.HISTORICAL
            and not origin.archive and origin.name.startswith("ENTSOG")):
        return
    with st.container(border=True,key="panel_weather"):
        st.subheader("Meteo e consumi di gas")
        st.caption("Italia · Milano, Roma e Napoli · scenario dei prelievi SRG")
        info("Info meteo","Open-Meteo · temperature orarie allineate al giorno gas (06:00–06:00). Milano, Roma e Napoli a pesi uguali; HDD base 18 °C.","L’API gratuita è riservata all’uso non commerciale. Nessuna richiesta senza attivazione.")
        consent=st.checkbox("Attiva meteo automatico · demo non commerciale",key="weather_demo_consent")
        if not consent:
            return
        fingerprint=context.bundle.fingerprint
        now=utc_now()
        saved=st.session_state.get("weather_gas_result")
        clicked=st.button("Aggiorna meteo",key="weather_run",icon=":material/refresh:")
        # Update automatically once per dataset/6 hours after opt-in.
        # Failed requests are also throttled; regular widget edits do not retry.
        due=(not saved or saved["fingerprint"]!=fingerprint or now-saved["attempted"]>=timedelta(hours=6))
        if clicked and saved and now-saved["attempted"]<timedelta(seconds=60):
            st.caption("Aggiornamento disponibile dopo 60 secondi.")
            clicked=False
        if due or clicked:
            try:
                with st.spinner("Acquisizione oraria e confronto dei modelli…"):
                    result=analyse_gas_day(database(),context.inspection.usable,now,refresh=clicked)
                saved={"fingerprint":fingerprint,"attempted":now,"result":result}
            except (ValueError,SourceUnavailable) as error:
                saved={"fingerprint":fingerprint,"attempted":now,"error":str(error)}
            st.session_state["weather_gas_result"]=saved
        if saved.get("error"):
            st.warning(saved["error"])
            return
        result=saved["result"]
        acquired=datetime.fromisoformat(result["forecast_acquired"])
        if now-acquired>timedelta(hours=12):
            st.warning("Scenario meteo scaduto: aggiorna le fonti.")
            return
        if result["refresh_failed"]:
            st.warning("Una fonte non si è aggiornata; utilizzata cache valida.")
        if result["previous_note"]:
            st.warning(result["previous_note"])
        mode="Meteo archiviato a 24 ore" if result["evaluation"]=="archived_day1" else "Meteo storico realizzato"
        a,b,c=st.columns(3)
        a.metric("Errore senza meteo",numero(result["mae"]["calendar"])+" GWh")
        b.metric("Errore con meteo",numero(result["mae"]["sector_weather"])+" GWh")
        base=result["mae"]["calendar"]
        change=(result["mae"]["sector_weather"]/base-1)*100 if base>0 else None
        c.metric("Variazione errore",numero(change,signed=True)+"%" if change is not None else "—")
        st.caption(f'{mode} · {result["holdout"]} giorni di verifica · confronto non operativo a 7 giorni.')
        st.markdown("**Possibile andamento dei consumi · prossimi 7 giorni gas**")
        st.caption("Scenario condizionale, non previsione operativa principale.")
        frame=pd.DataFrame(result["points"]).set_index("period")
        st.line_chart(frame[["calendar_gwh","estimate_gwh"]].rename(columns={
            "calendar_gwh":"Calendario (GWh)","estimate_gwh":"Meteo settoriale (GWh)"}))
        with st.expander("Dettaglio per settore e temperature"):
            st.bar_chart(frame[list(SECTORS)].rename(columns=SECTORS),stack=True)
            st.dataframe(frame.reset_index().rename(columns={"period":"Giorno gas","temperature_c":"Temperatura (°C)",
                "hdd":"HDD","hours":"Ore","calendar_gwh":"Calendario (GWh)","estimate_gwh":"Totale meteo (GWh)",
                **{k:v+" (GWh)" for k,v in SECTORS.items()}}),hide_index=True,width="stretch")
        with st.expander("Validazione dei modelli e metodologia"):
            st.dataframe([{"Modello":LABELS[k],"MAE (GWh)":round(v,2)}
                          for k,v in result["mae"].items()],hide_index=True)
            st.dataframe([{"Settore":v,"MAE calendario":round(result["sector_mae"]["sector_calendar"][k],2),
                           "MAE con HDD":round(result["sector_mae"]["sector_weather"][k],2)}
                          for k,v in SECTORS.items()],hide_index=True)
            st.dataframe(result["folds"],hide_index=True)
            st.caption(f'Addestramento finale: {result["observations"]} giorni · due finestre cronologiche.')
            st.caption("Confronto a parità di osservazioni, gap di sette giorni prima di ogni verifica. "
                       "L’archivio previous_day1 è un lead fisso per ora, non un’unica emissione giornaliera. "
                       "Non certifica le versioni storiche dei prelievi. Pesi territoriali non calibrati. "
                       "Nessun modello promosso automaticamente; non modifica SARIMAX o Monte Carlo.")
        st.caption("Fonte: Open-Meteo (CC BY 4.0) · storico fino al "+result["historical_end"]+
                   " · previsione acquisita "+local_time(acquired))
        st.markdown("[Fonte e condizioni](https://open-meteo.com/en/terms)")
