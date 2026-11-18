"""An optional weather check in the existing market page; no default network I/O."""
import streamlit as st

from .italiano import numero
from .models import Kind
from .public_data import SourceUnavailable
from .session import database
from .weather import analyse


def weather_panel(context):
    origin=context.bundle.origin
    if not (origin.grain=="daily" and origin.kind==Kind.HISTORICAL
            and not origin.archive and origin.name.startswith("ENTSOG")):
        return
    with st.expander("Meteo e domanda · approfondimento facoltativo"):
        st.caption("Open-Meteo, uso dimostrativo non commerciale. Proxy climatica Milano/Roma/Napoli, pesi uguali; "
                   "HDD base 18 °C. Giorni civili associati alle etichette giorno-gas, non misura oraria allineata.")
        consent=st.checkbox("Attiva l’analisi meteo gratuita per questa demo",key="weather_demo_consent")
        if not consent:
            return
        fingerprint=context.bundle.fingerprint
        if st.button("Verifica utilità del meteo",key="weather_run",type="secondary"):
            st.session_state.pop("weather_result",None)
            try:
                with st.spinner("Acquisizione meteo e confronto statistico…"):
                    result=analyse(database(),context.inspection.usable["demand_gwh"])
                st.session_state["weather_result"]=(fingerprint,result)
            except (ValueError,SourceUnavailable) as error:
                st.warning(str(error))
        saved=st.session_state.get("weather_result")
        if not saved or saved[0]!=fingerprint:
            return
        result=saved[1]
        from datetime import datetime,timedelta,timezone
        if datetime.now(timezone.utc)-datetime.fromisoformat(result["forecast_acquired"])>timedelta(hours=12):
            st.warning("Scenario meteo scaduto. Esegui nuovamente la verifica.")
            return
        a,b=st.columns(2)
        a.metric("MAE solo calendario (GWh)",numero(result["mae"]["calendar"]))
        b.metric("MAE calendario + HDD (GWh)",numero(result["mae"]["weather"]))
        st.caption(f'{result["observations"]} osservazioni complete · ultimi {result["holdout"]} come verifica cronologica. '
                   "Il confronto usa meteo storico realizzato: è condizionale, non confrontabile con il backtest operativo "
                   "dei modelli automatici e non dimostra un miglioramento delle previsioni live.")
        if result["improved"]:
            st.write("**Scenario condizionale dei prossimi sette giorni**")
            st.dataframe([{"Giorno":p["period"],"Temperatura media proxy (°C)":round(p["temperature_c"],1),
                           "HDD":round(p["hdd"],1),"Prelievi SRG stimati (GWh)":round(p["estimate_gwh"],1)}
                          for p in result["points"]],hide_index=True,width="stretch")
        else:
            st.info("Il meteo non migliora questo confronto condizionale: nessuno scenario alternativo pubblicato.")
        if result["refresh_failed"]:
            st.warning("Una fonte non si è aggiornata; utilizzata cache valida.")
        st.caption("Meteo storico fino al "+result["historical_end"]+" · dati Open-Meteo (CC BY 4.0).")
        st.markdown("[Fonte e condizioni](https://open-meteo.com/en/terms)")
        st.caption("Non modifica SARIMAX, la selezione automatica, il settlement o il Monte Carlo.")
