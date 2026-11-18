"""Native Jarvis source viewer. Files and parsed records remain in this session."""
import pandas as pd
import streamlit as st
from .jarvis_native import COLUMNS,MAX_BYTES,MAX_ROWS,parse_upload,compare_balances
from .jarvis_archive import SOURCE

STATE="jarvis_native_v1"


def panel():
    st.subheader("Importazione nativa Jarvis")
    st.caption("Pubblicazioni originali · estratti verificabili · nessun invio AI o salvataggio condiviso")
    with st.expander("Importa XLSX / ZIP / CSV WKR",expanded=STATE not in st.session_state):
        st.markdown(f"[Scarica pubblicazioni Jarvis]({SOURCE})")
        with st.form("jarvis_native_import"):
            f=st.file_uploader("File originale (uno alla volta)",type=["xlsx","zip","csv"],key="jarvis_native_file")
            st.caption("Dati pubblici · solo sessione, senza dati riservati.")
            submit=st.form_submit_button("Importa",type="primary")
        if submit:
            if f is None:
                st.warning("Seleziona un file.")
            elif f.size>MAX_BYTES:
                st.error("File superiore a 16 MiB.")
            else:
                try:
                    with st.spinner("Validazione dei fogli e riconciliazione delle unità…"):
                        rows,warnings=parse_upload(f.getvalue(),f.name)
                        incoming=pd.DataFrame.from_records(rows,columns=COLUMNS)
                        old=st.session_state.get(STATE,{}).get("frame")
                        if old is not None:
                            incoming=incoming[~incoming.sha256.isin(old.sha256.unique())]
                            if len(old)+len(incoming)>MAX_ROWS:raise ValueError("Limite sessione")
                            incoming=pd.concat([old,incoming],ignore_index=True)
                        prev=st.session_state.get(STATE,{}).get("warnings",[])
                        st.session_state[STATE]={"frame":incoming,"warnings":list(dict.fromkeys([*prev,*warnings]))}
                    st.success("Archivio aggiornato. File identici deduplicati per SHA-256.")
                except (ValueError,TypeError,RuntimeError,OSError):
                    st.error("File non valido, schema non supportato, unità non riconciliabili o limite raggiunto. Archivio precedente invariato.")
        if STATE in st.session_state and st.button("Rimuovi archivio nativo",key="jarvis_native_clear"):
            st.session_state.pop(STATE,None)
            st.rerun()
    saved=st.session_state.get(STATE)
    if not saved:
        st.info("Nessun file nativo importato. Puoi caricare i file annuali 2023–2026 e gli ZIP delle altre pubblicazioni.")
        return
    frame=saved["frame"]
    a,b,c=st.columns(3)
    a.metric("Valori numerici",len(frame))
    b.metric("File distinti",frame.sha256.nunique())
    c.metric("Famiglie",frame.family.nunique())
    with st.expander("Qualità e unità"):
        for w in saved["warnings"]:st.text(w)
        st.caption("Storicizzazione locale alla sessione, non archivio live. Le intestazioni incoerenti richiedono conferma della fonte. Nessun dato mancante è trattato come zero.")
    family=st.selectbox("Pubblicazione",sorted(frame.family.unique()),key="native_family")
    subset=frame[frame.family==family]
    metric=st.selectbox("Metrica / zona / cluster",sorted(subset.metric.unique()),key="native_metric_"+family)
    subset=subset[subset.metric==metric]
    unit=st.selectbox("Unità",sorted(subset.unit.unique()),key="native_unit_"+family)
    subset=subset[subset.unit==unit]
    if family=="bilanci":
        st.caption("Confronto aggregato per giorno gas · unità riconciliate numericamente · non cash flow o bilanci individuali. Timestamp di pubblicazione non disponibili.")
        comparison=pd.DataFrame(compare_balances(subset))
        if not comparison.empty:
            valid=comparison.delta.notna()
            st.metric("Giorni confrontabili",int(valid.sum()))
            st.line_chart(comparison,x="gas_day",y=["provvisorio","definitivo"],y_label=unit)
            if valid.any():
                st.bar_chart(comparison,x="gas_day",y="delta",y_label=unit)
            st.dataframe(comparison,hide_index=True,width="stretch")
    else:
        edition=st.selectbox("Fase / edizione",sorted(subset.edition.unique()),key="native_edition_"+family)
        subset=subset[subset.edition==edition]
        filehash=st.selectbox("File / versione",sorted(subset.sha256.unique()),
            format_func=lambda h:subset.loc[subset.sha256==h,"file"].iloc[0]+" · "+h[:8],key="native_version_"+family)
        subset=subset[subset.sha256==filehash]
        if family in ("operativi_annuali","operativi_giornalieri"):
            day=st.selectbox("Giorno gas",sorted(subset.gas_day.unique(),reverse=True),key="native_day_"+family)
            subset=subset[subset.gas_day==day]
            chart=subset.sort_values("row").assign(numeric=pd.to_numeric(subset.sort_values("row").value))
            # Original row order in annual source; daily tab ordering 06–23 for G.
            if family=="operativi_giornalieri":chart=chart.sort_values("sheet")
            chart=chart.reset_index(drop=True)
            st.line_chart(chart,y="numeric",y_label=unit)
            st.caption("Sequenza di pubblicazioni: valori di fine giorno, non volumi orari da sommare. Timestamp riportati come nel file, senza offset inventati.")
        else:
            if not subset.gas_day.duplicated().any():
                st.line_chart(subset.assign(numeric=pd.to_numeric(subset.value)).sort_values("gas_day"),x="gas_day",y="numeric",y_label=unit)
            else:st.caption("Più versioni per giorno; nessuna aggregazione automatica.")
    st.dataframe(subset.head(2000),hide_index=True,width="stretch")
    st.caption("Vista tabellare limitata a 2.000 record; esportazione del filtro completo.")
    st.download_button("Esporta selezione CSV",subset.to_csv(index=False),"igor-jarvis-native.csv","text/csv",key="native_export")
