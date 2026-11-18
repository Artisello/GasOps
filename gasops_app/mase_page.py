"""Public historical production; separate from operational supply and forecasting."""
import pandas as pd
import streamlit as st

from .mase_archive import MASE_SOURCE, LICENSE_URL, observations, as_bcm, NATIONAL
from .warehouse import MASE_CSV


def panel():
    st.subheader("Produzione nazionale di gas")
    st.caption("Italia · MASE–UNMIG · archivio storico, non aggiornato in tempo reale")
    try:
        frame = pd.DataFrame(observations())
    except (ValueError, OSError):
        st.error("Archivio UNMIG non disponibile o non valido.")
        return
    frame["bcm"] = [float(as_bcm(v, u)) for v, u in zip(frame.value, frame.unit, strict=True)]
    annual = frame[(frame.grain == "year") & frame.geography.isin(NATIONAL)].copy()
    national = annual[annual.geography == "IT"].sort_values("period")
    month = frame[frame.grain == "month"]
    national_month = month[month.geography == "IT"].sort_values("period")
    latest = national.iloc[-1]
    prev = national.iloc[-2]
    c1, c2, c3 = st.columns(3)
    c1.metric("Produzione 2025", f"{latest.bcm:.2f} mld Sm³")
    c2.metric("Variazione 2025/2024", f"{(latest.bcm / prev.bcm - 1) * 100:+.1f}%")
    c3.metric("Ultimo mese in archivio", national_month.iloc[-1].period)
    st.caption("2024 arrotondato nel databook; 2025 da report annuale. Variazione indicativa. Il 2026 è parziale.")
    st.subheader("Storico annuale")
    labels = {"IT":"Italia", "IT:onshore":"Terra", "IT:offshore":"Mare"}
    trend = annual.pivot(index="period", columns="geography", values="bcm").rename(columns=labels)
    st.line_chart(trend[["Italia","Terra","Mare"]], y_label="mld Sm³")
    st.subheader("Produzione mensile")
    monthly = month.pivot(index="period", columns="geography", values="bcm").rename(columns=labels)
    st.line_chart(monthly[["Italia","Terra","Mare"]] * 1000, y_label="milioni Sm³")
    st.caption("2025 completo; gennaio–febbraio 2026 (edizione 22/05/2026). Mesi successivi assenti dall'archivio, non zero.")
    st.subheader("Ripartizione 2025")
    kind = st.radio("Area", ["Regioni", "Zone marine"], horizontal=True, key="mase_area_kind")
    prefix = "region:" if kind == "Regioni" else "zone:"
    areas = frame[(frame.period == "2025") & frame.geography.str.startswith(prefix)].copy()
    areas["Area"] = areas.geography.str.removeprefix(prefix)
    areas["Milioni Sm³"] = areas.bcm * 1000
    st.bar_chart(areas.sort_values("Milioni Sm³", ascending=False), x="Area", y="Milioni Sm³", horizontal=True)
    st.caption("Produzione attribuita alla regione prevalente; non consumi regionali. Totali pubblicati separati dai dettagli.")
    with st.expander("Fonti, dati e altri archivi MASE"):
        st.markdown(f"[UNMIG: produzione nazionale]({MASE_SOURCE}) · [CSV nativo 2004–2026]({MASE_CSV}) · [Licenza CC BY 4.0]({LICENSE_URL})")
        for edition, url in frame[["edition","source_url"]].drop_duplicates().itertuples(index=False, name=None):
            st.markdown(f"[{edition}]({url})")
        st.caption("Trascrizioni delle tabelle ufficiali, non file CSV originali. Differenze di arrotondamento e incongruenze nei totali non corrette. Nessun uso per settlement o previsione.")
        st.dataframe(frame.drop(columns="bcm"), hide_index=True, width="stretch")
        st.download_button("Scarica estratto con provenienza", frame.drop(columns="bcm").to_csv(index=False), "igor-unmig.csv", "text/csv")
        st.markdown("[Bilancio gas (Excel)](https://sisen.mase.gov.it/dgsaie/bilancio-gas-naturale) · [Consumi regionali](https://sisen.mase.gov.it/dgsaie/consumi-regionali-gas-naturale) · [Consumi provinciali](https://sisen.mase.gov.it/dgsaie/consumi-provinciali-gas-naturale)")
        st.caption("SISEN: collegamenti ai file ufficiali. Formati nativi non ancora verificati, nessun dato di consumo importato.")
