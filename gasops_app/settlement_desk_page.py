"""Session-only daily balancing and settlement desk."""
import hashlib

import pandas as pd
import streamlit as st

from .settlement_desk import MAX_BYTES, csv_text, daily_controls, monthly_summary, parse_csv, template
from .operations_ledger import sample_rows
from .visuals import kpi_grid

STATE="settlement_desk_csv_v1"
JARVIS="https://jarvis.snam.it/public-data?lang=it"
GME="https://www.mercatoelettrico.org/Home/Esiti/Gas/PrezzoSbilanciamento/Esiti/PrezzoSbilanciamento"


def panel():
    st.subheader("Controllo giornaliero e chiusura mese")
    st.caption("Dati di esempio o CSV normalizzato autorizzato · MWh, €/MWh, importi prima delle imposte. Nessuna fattura o misura ufficiale.")
    with st.expander("Fonti e importazione"):
        st.markdown(f"[Snam · Jarvis: bilanci e dati operativi]({JARVIS}) · [GME · parametri dei prezzi di sbilanciamento]({GME})")
        st.caption("Riferimenti alle fonti, non download automatici. Il CSV è uno schema GasOps, non un formato Jarvis/GME: normalizza soltanto dati per i quali hai diritto d’uso. Prezzi forniti dall’utente, non stimati dal prezzo PSV.")
        st.download_button("Scarica modello CSV sintetico",template(),"gasops-modello-bilanci.csv","text/csv",key="desk_template")
        st.warning("Non caricare dati aziendali riservati o identificativi reali sul prototipo pubblico.")
        with st.form("desk_upload"):
            f=st.file_uploader("CSV bilanci e versioni",type=["csv"],help="UTF-8, virgola come separatore, decimali con punto, fino a 2 MiB.")
            consent=st.checkbox("Confermo che sto usando dati sintetici o autorizzati alla consultazione sul prototipo pubblico.")
            submitted=st.form_submit_button("Importa e valida CSV")
        if submitted:
            if not f or not consent:
                st.warning("Seleziona il file e conferma l’autorizzazione.")
            elif f.size>MAX_BYTES:
                st.warning("CSV superiore a 2 MiB.")
            else:
                try:
                    raw=f.getvalue()
                    rows=parse_csv(raw)
                    st.session_state[STATE]={"rows":rows,"name":f.name,"sha":hashlib.sha256(raw).hexdigest()}
                    st.success("CSV acquisito nella sessione.")
                except ValueError as exc:
                    st.error(str(exc)+" Il dataset precedente resta invariato.")
        if STATE in st.session_state and st.button("Rimuovi CSV dalla sessione",key="desk_clear"):
            st.session_state.pop(STATE,None)
            st.rerun()
    uploaded=st.session_state.get(STATE)
    rows=uploaded["rows"] if uploaded else sample_rows()
    st.caption("CSV utente · non verificato dalla fonte · sessione corrente" if uploaded else "Demo sintetica · settembre 2026")
    if uploaded:
        st.caption("SHA-256: "+uploaded["sha"])
    users=sorted({r.user for r in rows})
    user=st.selectbox("Partecipante (ID fittizio)",users,key="daily_desk_user")
    months=sorted({(r.day.year,r.day.month) for r in rows if r.user==user},reverse=True)
    year,month=st.selectbox("Mese di competenza",months,format_func=lambda x:f"{x[0]}-{x[1]:02d}",key="daily_desk_month")
    daily=daily_controls(rows,user,year,month)
    summary=monthly_summary(daily)
    st.caption(f"{summary['eligible']}/{summary['expected']} giorni definitivi senza le eccezioni controllate.")
    if not summary["complete"]:
        st.warning("Chiusura mensile non pronta per verifica: giorni mancanti o eccezioni. Importi sotto solo parziali, non totale del mese.")
    else:
        st.caption("Tutti i giorni superano i controlli implementati. Resta necessaria la validazione specialistica.")
    kpi_grid([("Addebiti utente",summary["debits"],"€","Solo giorni utilizzabili",2,""),
              ("Crediti utente",summary["credits"],"€","Solo giorni utilizzabili",2,""),
              ("Giorni con eccezioni",summary["exceptions"],"","Da verificare",0,""),
              ("Impatto assoluto rettifiche",summary["revision_abs"],"€",str(summary["comparable"])+" coppie valorizzabili",2,"")])
    a,b=st.columns(2)
    with a:
        st.caption("Sbilanciamento giornaliero più recente per giorno (MWh)")
        frame=pd.DataFrame({"Giorno":pd.to_datetime([r["day"] for r in daily]),
                            "DS":[float(r["ds_mwh"]) if r["ds_mwh"] is not None else None for r in daily]})
        st.bar_chart(frame,x="Giorno",y="DS")
    with b:
        st.caption("Effetti delle rettifiche provvisorio → definitivo (€)")
        bridge=pd.DataFrame({"Giorno":pd.to_datetime([r["day"] for r in daily]),
                            "Quantità":[float(r["quantity_effect_eur"]) if r["quantity_effect_eur"] is not None else None for r in daily],
                            "Prezzo":[float(r["price_effect_eur"]) if r["price_effect_eur"] is not None else None for r in daily]})
        if bridge[["Quantità","Prezzo"]].notna().any().any():
            st.bar_chart(bridge,x="Giorno",y=["Quantità","Prezzo"],stack=False)
        else:
            st.info("Nessuna coppia con scomposizione valorizzabile.")
    mode=st.radio("Mostra giornate",["Tutte","Eccezioni","Rettifiche"],horizontal=True,key="daily_desk_filter")
    shown=[r for r in daily if mode=="Tutte" or (mode=="Eccezioni" and r["issues"]) or
           (mode=="Rettifiche" and (r["delta_ds_mwh"] not in (None,0) or r["delta_cash_eur"] not in (None,0)))]
    def display(r):
        return {"Giorno gas":r["day"],"Fase":{"missing":"Assente","provisional":"Provvisorio","definitive":"Definitivo"}[r["stage"]],
                "DS (MWh)":r["ds_mwh"],"Flusso utente (€)":r["cash_eur"],"Δ DS (MWh)":r["delta_ds_mwh"],
                "Δ €":r["delta_cash_eur"],"Effetto quantità (€)":r["quantity_effect_eur"],
                "Effetto prezzo (€)":r["price_effect_eur"],"Eccezioni":"; ".join(r["issues"])}
    st.dataframe([display(r) for r in shown],hide_index=True,width="stretch")
    if not shown:
        st.caption("Nessuna giornata corrispondente al filtro.")
    export=[{"user":user,"period":f"{year}-{month:02d}","source":"CSV_NON_VERIFICATO" if uploaded else "SYNTHETIC",
             **r,"issues":"; ".join(r["issues"])} for r in daily]
    st.download_button("Esporta controllo giornaliero CSV",csv_text(export),"gasops-controllo-giornaliero.csv",
                       "text/csv",key="daily_desk_export")
    with st.expander("Metodo e limiti"):
        st.write("DS = immissioni + stoccaggio netto + transazioni nette PSV − prelievi. Calcolo dimostrativo con arrotondamento per giorno a centesimi. Rettifiche: confronto ultimo provvisorio e ultimo definitivo; effetto quantità valorizzato ai prezzi del provvisorio per il segno del DS finale, poi effetto prezzo residuo. Se manca il prezzo controfattuale, nessuna scomposizione. Gli importi escludono i giorni con eccezioni e non sono fatture. Le soglie e le eccezioni sono controlli di studio, non regole di accettazione Snam. Nessuna trasmissione AI o salvataggio persistente del CSV.")
