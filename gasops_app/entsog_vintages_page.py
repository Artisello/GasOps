"""Bounded access and portable archive."""
from datetime import timedelta
import json
import pandas as pd
import streamlit as st
from .data import ROME
from .models import utc_now
from .entsog_network import load_programmes,check_point
from .entsog_vintages import STATE,SELECT,MAX_BYTES,merge,capture,points,outlook
from .public_data import SourceUnavailable
from .session import database
from .italian_network import load_network_assets, verified_bindings, point_direction_labels, direction_name
from .italian_network_map import display_name


def panel():
    state=st.session_state;now=utc_now();today=now.astimezone(ROME).date()
    with st.expander("Nomine e rinomine · G / G+1 / G+2"):
        with st.form("entsog_programmes_query"):
            point=st.text_input("Punto e direzione",value=state.get(SELECT,""))
            click=st.form_submit_button("Aggiorna programmi")
        if click:
            last=state.get("entsog_programmes_attempt")
            if last and now-last<timedelta(minutes=1):st.caption("Aggiornamento recente.")
            else:
                try:
                    check_point(point)
                    state["entsog_programmes_attempt"]=now
                    with st.spinner("Acquisizione ENTSOG…"):
                        r=load_programmes(database(),point,today,today+timedelta(days=2),now=now,refresh=True)
                        state[STATE]=merge(state.get(STATE,[]),[capture(r,utc_now())],utc_now())
                    state[SELECT]=point
                except (ValueError,SourceUnavailable,TypeError,KeyError):st.caption("Programmi non disponibili; dati precedenti conservati.")
        known=points(state.get(STATE,[]))
        if known:
            network=load_network_assets()
            types=point_direction_labels(network)
            names={i.id:i.name for i in network.infrastructure}
            labels={b.point_direction:display_name(names[b.infrastructure_id])+" · "+types[b.point_direction]+
                    (" · "+direction_name(b.direction) if types[b.point_direction]=="Bidirezionale" else "")
                    for b in verified_bindings(network)}
            preferred=state.get(SELECT)
            state[SELECT]=st.selectbox("Punto e direzione dell’archivio",known,index=known.index(preferred) if preferred in known else 0,
                key="entsog_archive_point",format_func=lambda key:labels.get(key,key+" · Tipologia non verificata"))
        fact=outlook(state,utc_now())
        if fact:
            f=pd.DataFrame(fact["points"])
            st.line_chart(f.pivot(index="day",columns="indicator",values="gwh"),y_label="GWh/giorno gas")
            st.dataframe(f,hide_index=True,width="stretch")
        else:st.caption("Nessun programma recente con metadati validabili per il punto.")
        st.caption("Programmi, non consuntivi. ENTSOG TP Transport Data · https://transparency.entsog.eu/")
    with st.expander("Archivio versionato"):
        f=st.file_uploader("Ripristina JSON I.G.O.R.",type=["json"],key="entsog_vintage_file")
        st.caption("JSON pubblico · timestamp dichiarati, non autenticati.")
        if st.button("Unisci archivio",disabled=f is None,key="entsog_vintage_import"):
            try:
                if f.size>MAX_BYTES:raise ValueError("Limite")
                obj=json.loads(f.getvalue())
                if obj["version"]!=1:raise ValueError("Versione")
                state[STATE]=merge(state.get(STATE,[]),obj["batches"],now)
                st.rerun()
            except (ValueError,KeyError,TypeError,OverflowError):st.caption("Archivio non valido.")
        batches=state.get(STATE,[])
        if batches:
            st.caption(f"{len(batches)} acquisizioni · timestamp importati dichiarati, non autenticati.")
            st.download_button("Esporta archivio",json.dumps({"version":1,"batches":batches},allow_nan=False),"igor-entsog-vintages.json","application/json")
