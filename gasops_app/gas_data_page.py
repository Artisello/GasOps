"""Unified Gas Data Explorer inside the existing Security of Supply page."""
from datetime import timedelta

import streamlit as st

from .gas_data import collect,select,series_frame,LABELS,MAX_DAYS,MAX_EXPORT_ROWS
from .italian_network_page import assets,bundled_interruptions,SELECTED
from .italian_network_map import display_name
from .italian_network import point_direction_labels, direction_name
from .models import utc_now
from .operational_sources import attributed_csv
from .session import database
from .source_health import gas_health,STATE_LABELS
from .source_health_page import render_rows
from .terna_charts import timeseries
from .visuals import plot
from .italiano import numero,data_it

FOCUS="gas_data_explorer_focus_v1"
PROVIDERS={"ENTSOG":"ENTSOG","AGSI+":"GIE · AGSI+","ALSI":"GIE · ALSI"}


def open_explorer(identifier,direction,first,last,*,navigate=False):
    st.session_state["operational_platform"]="EXPLORER"
    st.session_state[FOCUS]={"id":identifier,"direction":direction,"first":first,"last":last}
    if navigate:
        from .operational_sources_page import operational_context
        st.switch_page(st.Page(operational_context,title="Security of Supply",icon=":material/shield:",url_path="security-of-supply"))


def _choice(key,options,preferred=None):
    if st.session_state.get(key) not in options:
        st.session_state[key]=preferred if preferred in options else options[0]


def panel():
    st.caption("Dati pubblici già disponibili · confronto per punto e indicatore")
    now=utc_now()
    network,_,snapshots=assets()
    try:
        frame=collect(network,snapshots,st.session_state,now,store=database(),interruptions=(bundled_interruptions(),))
    except (OSError,ValueError,KeyError):
        st.info("Dati non disponibili per l’esplorazione. Le viste originali restano accessibili.")
        return
    menu=frame.loc[frame.value.notna()|frame.quality_status.eq("conflict")]
    if menu.empty:
        st.info("Nessuna osservazione validata disponibile. Le fonti si caricano dalle rispettive viste.")
        return
    focus=st.session_state.pop(FOCUS,None)
    if focus:
        targets=menu.loc[(menu.infrastructure_id==focus["id"])&
            ((menu.direction==focus["direction"]) if focus.get("direction") else True)]
        if not targets.empty:
            st.session_state["gas_explorer_provider"]=targets.provider.iloc[0]
            st.session_state["gas_explorer_entity"]=targets.entity_key.iloc[0]
        else:
            st.caption("Nessuna osservazione disponibile per il punto richiesto. Puoi esplorare le altre serie.")
        if focus.get("first") and focus.get("last"):
            st.session_state["gas_explorer_period"]=(focus["first"],focus["last"])
    a,b,c=st.columns([1,2.5,2])
    providers=[p for p in PROVIDERS if (menu.provider==p).any()]
    _choice("gas_explorer_provider",providers,"ENTSOG")
    provider=a.selectbox("Provider",providers,key="gas_explorer_provider",format_func=PROVIDERS.__getitem__)
    source=menu.loc[menu.provider==provider]
    direction_types=point_direction_labels(network)
    def entity_title(key,label):
        structural=direction_types.get(key)
        return display_name(label)+(" · "+structural if structural else "")
    entities=source.drop_duplicates("entity_key").set_index("entity_key")
    preferred=source.loc[source.infrastructure_id==st.session_state.get(SELECTED,"INET_BP_65"),"entity_key"]
    _choice("gas_explorer_entity",list(entities.index),preferred.iloc[0] if len(preferred) else None)
    entity=b.selectbox("Infrastruttura / punto",list(entities.index),key="gas_explorer_entity",
        format_func=lambda e:entity_title(e,entities.loc[e,"entity_label"]))
    primary=source.loc[source.entity_key==entity]
    if provider=="ENTSOG":
        structural=direction_types.get(entity)
        st.caption((structural or "Tipologia non verificata nel catalogo")+" · Dati: "+direction_name(primary.direction.iloc[0]))
        if structural=="Bidirezionale":
            other=entity[:-5]+"exit" if entity.endswith("entry") else entity[:-4]+"entry"
            st.caption("Direzione opposta: "+direction_name("exit" if entity.endswith("entry") else "entry")+
                (" · serie consultabile nel selettore" if other in entities.index else " · nessuna serie disponibile nel perimetro caricato"))
    options=list(dict.fromkeys(zip(primary.indicator,primary.unit,primary.time_basis)))
    _choice("gas_explorer_indicator",options,next((k for k in options if k[0]=="Physical Flow"),options[0]))
    indicator,unit,basis=c.selectbox("Indicatore",options,key="gas_explorer_indicator",
        format_func=lambda x:LABELS[x[0]]+" · "+x[1]+(" · intervalli fonte" if x[2]=="source_interval" else ""))
    compatible=frame.loc[(frame.provider==provider)&(frame.indicator==indicator)&(frame.unit==unit)&(frame.time_basis==basis)]
    labels=compatible.drop_duplicates("entity_key").set_index("entity_key").entity_label.to_dict()
    supported=source.loc[(source.indicator==indicator)&(source.unit==unit)&(source.time_basis==basis)]
    available_period=st.session_state.get("gas_explorer_period",(min(primary.query_first),max(primary.query_last)))
    candidates=set(supported.entity_key)
    if len(available_period)==2:
        candidates=set(select(supported,provider,list(candidates),indicator,unit,basis,*available_period).entity_key)
    alternatives=[e for e in labels if e!=entity and e in candidates]
    compared=[]
    if alternatives:
        with st.popover("Confronta punti"):
            previous=st.session_state.get("gas_explorer_comparison",[])
            st.session_state["gas_explorer_comparison"]=[e for e in previous if e in alternatives][:3]
            compared=st.multiselect("Stesso indicatore, unità e base temporale",alternatives,max_selections=3,
                key="gas_explorer_comparison",format_func=lambda e:entity_title(e,labels[e]))
    chosen=[entity,*compared]
    records=compatible.loc[compatible.entity_key.isin(chosen)]
    lower=min(records.query_first)
    upper=max(records.query_last)
    default_first=max(lower,upper-timedelta(days=6))
    current=st.session_state.get("gas_explorer_period",(default_first,upper))
    if len(current)==2:
        start=max(lower,min(current[0],upper))
        end=max(start,min(current[1],upper))
        if (end-start).days>=MAX_DAYS:start=end-timedelta(days=MAX_DAYS-1)
        st.session_state["gas_explorer_period"]=(start,end)
    period_col,view_col=st.columns([2,1])
    period=period_col.date_input("Periodo disponibile",value=(default_first,upper),min_value=lower,max_value=upper,
                               key="gas_explorer_period",format="DD/MM/YYYY")
    if len(period)!=2:
        st.caption("Completa l’intervallo di date.")
        return
    first,last=period
    if (last-first).days>=MAX_DAYS:
        st.info("Scegli al massimo 92 giorni.")
        return
    visible=select(frame,provider,chosen,indicator,unit,basis,first,last)
    if visible.empty:
        st.info("Nessuna osservazione nel periodo selezionato. Modifica il periodo o il punto.")
        return
    choices=["Serie temporale","Tabella"] if basis!="source_interval" and visible.usable.any() else ["Tabella"]
    _choice("gas_explorer_visualization",choices)
    view=view_col.radio("Visualizzazione",choices,horizontal=True,key="gas_explorer_visualization")
    health=gas_health(visible,first,last,now)
    states=" · ".join(dict.fromkeys(STATE_LABELS.get(r.get("state"),"Non disponibile") for r in health))
    st.caption(f"{PROVIDERS[provider]} · {unit} · {len(visible)} osservazioni · {states}")
    if compared:st.caption("Confronto visivo tra perimetri distinti; nessuna somma tra punti o aggregati.")
    if indicator=="Interruptions":st.caption("Capacità interrotta pubblicata: zero non indica un evento attivo; copertura limitata alla richiesta della fonte.")
    if basis=="source_interval":
        st.caption("Intervalli originali della fonte: tabella disponibile, senza trasformarli in una serie di giorni gas.")
    if view=="Serie temporale":
        chart=series_frame(visible,first,last)
        figure=timeseries(chart,unit,height=315)
        figure.update_layout(margin={"l":42,"r":14,"t":12,"b":52})
        ticks=list(chart.index[::max(1,(len(chart.index)+3)//4)])
        if ticks[-1]!=chart.index[-1]:ticks.append(chart.index[-1])
        figure.update_xaxes(tickmode="array",tickvals=ticks,tickformat="%d/%m",automargin=True)
        plot(figure,key="gas_explorer_series")
        counts=[f"{display_name(r['source'].split(' · ',1)[-1])}: {r['valid']}/{r['expected']} giorni" for r in health]
        st.caption(" · ".join(counts))
    latest=visible.loc[(visible.entity_key==entity)&(visible.gas_day==last)&visible.usable]
    if len(latest)==1:
        r=latest.iloc[0]
        st.metric(LABELS[indicator]+" · "+data_it(last),numero(r.value,2)+" "+unit,
            delta=numero(r.delta_d1,2)+" "+("p.p." if unit=="%" else unit)+" vs D-1" if r.delta_d1 is not None else None,delta_color="off")
        if r.delta_d1 is None:st.caption("D-1 non disponibile: nessun confronto con una data precedente sostitutiva.")
    columns=["gas_day","entity_label","indicator","value","unit","value_d1","delta_d1","quality_status",
             "revision_count","publication_status","period_from","period_to","observed_at","retrieved_at",
             *[c for c in visible.columns if c not in {"gas_day","entity_label","indicator","value","unit","value_d1","delta_d1",
                 "quality_status","revision_count","publication_status","period_from","period_to","observed_at","retrieved_at"}]]
    def table():
        display=visible[columns].copy()
        if provider=="ENTSOG":
            display.insert(2,"point_type",display.point_direction.map(direction_types).fillna("Non verificata"))
        st.dataframe(display,hide_index=True,width="stretch",key="gas_explorer_table",
            column_config={"value":st.column_config.NumberColumn("Valore"),"entity_label":"Punto / infrastruttura",
                "gas_day":"Giorno fonte","quality_status":"Qualità","observed_at":"Pubblicato",
                "point_type":"Tipologia punto","direction":"Direzione dati",
                "delta_d1":"Δ D-1 (p.p.)" if unit=="%" else "Δ D-1 ("+unit+")",
                "retrieved_at":"Acquisito","revisions":st.column_config.TextColumn("Revisioni · JSON")})
    if view=="Tabella":table()
    else:
        with st.expander("Osservazioni e revisioni"):table()
    try:
        csv=attributed_csv({"frame":visible},per_row_source=True,max_rows=MAX_EXPORT_ROWS)
        st.download_button("Scarica CSV selezionato",csv,"igor-gas-data.csv","text/csv",key="gas_explorer_csv")
    except ValueError as exc:st.info(str(exc))
    with st.expander("Fonte e qualità"):
        render_rows(health,key="gas_explorer_health",filterable=False,kpis=False,download=False)
        if visible.observed_at.isna().all():st.caption("Data di pubblicazione non disponibile; la data di acquisizione resta distinta.")
        if (~visible.usable.astype(bool)).any():st.caption("Grafico e D-1 escludono righe non confrontabili. Tabella e CSV ne conservano qualità e provenienza.")
        for note in dict.fromkeys(str(n) for n in visible.note if n):st.caption(note)
        for url in dict.fromkeys(visible.source_url):
            if url:st.link_button("Apri fonte",url)
        st.caption("Live: acquisizione diretta recente · Cached: copia recente · Historical: periodo passato · Partial: lacune o verifiche · Stale: TTL superato o refresh fallito. Gli stati non indicano telemetria in tempo reale.")
    for note in frame.attrs.get("notices",()):st.caption(note)
