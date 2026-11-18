"""Session-local aggregate Jarvis workbench, isolated from participant settlement."""
import pandas as pd
import streamlit as st

from .jarvis_archive import (SOURCE,CATALOG,API_CATALOG,Q_NOTICE,DAILY,MAX_BYTES,
                            template,import_session,revision_rows,latest_records,record_dict,export_csv)

STATE = "jarvis_aggregate_archive_v1"
LABELS = {"balance":"Bilanci pubblici","wkr":"WKR","q":"Parametro q","gas_stock":"Gas Stock"}
METRICS = {"injections":"Immissioni","withdrawals":"Prelievi","balance_reported":"Saldo pubblicato",
           "wkr":"WKR","q":"Parametro q","gas_stock":"Gas Stock"}


def panel(prefix="supply"):
    st.subheader("Archivio pubblicazioni")
    st.caption("Rete SRG · estratti pubblici dichiarati dall'utente · non dati live")
    with st.expander("Fonti e importazione",expanded=STATE not in st.session_state):
        st.markdown(f"[Pubblicazioni Jarvis]({SOURCE}) · [Catalogo Snam]({CATALOG}) · [Dati giornalieri 2025]({DAILY})")
        st.markdown(f"[API Marketplace WKR]({API_CATALOG}) · [Pubblicazione parametro q]({Q_NOTICE})")
        st.download_button("Modello CSV vuoto",template(),"igor-jarvis-archive-template.csv","text/csv",key=prefix+"_ja_template")
        st.caption("Il modello I.G.O.R. non è un formato nativo Snam. Mapping manuale, stessa unità e perimetro tra revisioni; valori mancanti: omettere la riga, non inserire zero. Solo aggregati SRG, zone climatiche o cluster pubblici. Nessun cliente, operatore o PDR individuale.")
        with st.form(prefix+"_ja_import"):
            uploaded=st.file_uploader("Estratto CSV normalizzato",type=["csv"],key=prefix+"_ja_file")
            confirmed=st.checkbox("Confermo che i dati sono pubblici, autorizzati e non riservati.",key=prefix+"_ja_consent")
            submit=st.form_submit_button("Aggiungi pubblicazione")
        if submit:
            if not confirmed or uploaded is None:
                st.warning("Seleziona il file e conferma l'autorizzazione.")
            elif uploaded.size>MAX_BYTES:
                st.error("CSV superiore a 2 MiB.")
            else:
                try:
                    st.session_state[STATE]=import_session(st.session_state.get(STATE),uploaded.getvalue())
                    st.success("Pubblicazioni acquisite; versioni precedenti conservate.")
                except ValueError as exc:
                    # Some builtin parser errors contain arbitrary input; do not echo them.
                    msg=str(exc)
                    st.error(msg if msg.startswith(("CSV ","Conflitto ","Archivio ","Limite ","Usa ","Famiglia ","Fase,","Perimetro ","Riferimento ","Data ","Pubblicazione ","WKR ","Valore ","Nessuna ")) else "Estratto non valido. Archivio precedente invariato.")
        if STATE in st.session_state and st.button("Svuota archivio sessione",key=prefix+"_ja_clear"):
            st.session_state.pop(STATE,None)
            st.rerun()
    state=st.session_state.get(STATE)
    if not state:
        st.info("Nessuna pubblicazione numerica importata. Scarica un report pubblico dal portale e usa il modello.")
        return
    records=state["records"]
    family=st.radio("Pubblicazione",list(LABELS),format_func=LABELS.__getitem__,horizontal=True,key=prefix+"_ja_family")
    selected=[r for r in records if r.family==family]
    if not selected:
        st.info("Nessun dato per questa famiglia.")
        return
    st.caption(f"{len(selected)} osservazioni · {len(state['hashes'])} file distinti nell'archivio complessivo")
    metrics=sorted({r.metric for r in selected})
    metric=st.selectbox("Indicatore",metrics,format_func=METRICS.__getitem__,key=prefix+"_ja_metric")
    subset=[r for r in selected if r.metric==metric]
    unit=st.selectbox("Unità",sorted({r.unit for r in subset}),key=prefix+"_ja_unit")
    subset=[r for r in subset if r.unit==unit]
    scope=st.selectbox("Perimetro / cluster",sorted({r.scope for r in subset}),key=prefix+"_ja_scope")
    subset=[r for r in subset if r.scope==scope]
    if family=="balance":
        comparisons=revision_rows(subset)
        comparable=[r for r in comparisons if r["delta"] is not None]
        cols=st.columns(3)
        cols[0].metric("Giorni presenti",len(comparisons))
        cols[1].metric("Giorni confrontabili",len(comparable))
        cols[2].metric("Giorni con variazione",sum(r["delta"]!=0 for r in comparable))
        if comparable:
            frame=pd.DataFrame(comparable)
            frame[["provisional","definitive","delta"]]=frame[["provisional","definitive","delta"]].astype(float)
            st.line_chart(frame,x="gas_day",y=["provisional","definitive"],y_label=unit)
            st.bar_chart(frame,x="gas_day",y="delta",y_label=unit)
        else:
            st.info("Servono una versione provvisoria e una definitiva successiva per lo stesso giorno, metrica, unità e perimetro.")
        st.dataframe(comparisons,hide_index=True,width="stretch")
        st.caption("Delta = ultimo definitivo meno ultimo provvisorio precedente, solo coppie confrontabili. Non è il DS di un Utente del Bilanciamento né un importo fatturato.")
    else:
        latest=sorted(latest_records(subset),key=lambda r:r.gas_day)
        frame=pd.DataFrame([record_dict(r) for r in latest])
        frame["value"]=frame["value"].astype(float)
        st.line_chart(frame,x="gas_day",y="value",y_label=unit)
        st.dataframe(frame,hide_index=True,width="stretch")
        st.caption("Ultima pubblicazione importata per giorno; fase riportata, non effettività certificata. Nessuna conversione tra unità o formula di profilazione.")
    with st.expander("Versioni e provenienza"):
        st.dataframe([record_dict(r) for r in subset],hide_index=True,width="stretch")
        st.download_button("Esporta versioni selezionate",export_csv(subset),"igor-jarvis-versions.csv","text/csv",key=prefix+"_ja_export")
        for digest in state["hashes"]:
            st.text("SHA-256 estratto · "+digest)
        st.caption("Archivio solo in sessione, nessun salvataggio condiviso, nessun invio a LLM, nessun aggiornamento automatico.")
