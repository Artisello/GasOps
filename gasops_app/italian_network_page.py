"""Italian network explorer, usable offline before any optional API refresh."""
from dataclasses import asdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from html import escape
from functools import partial
from inspect import signature
from pathlib import Path
import json

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from streamlit.components.v1 import declare_component

from .data import ROME
from .entsog import _last_completed, _start
from .entsog_network import INDICATORS
from .italiano import numero, data_it
from .italian_network import (ASSETS, CATEGORIES, applicable, filter_infrastructure,
                              load_network_assets, map_kpis, merge_observations, selected_id,
                              kpi_status, point_metrics)
from .italian_network_events import iip_events, relevant_events, parse_interruptions
from .italian_network_map import deck, display_name, legend_symbol
from .italian_network_refresh import STATE, refresh_network
from .italian_network_sources import decode_snapshot
from .models import utc_now
from .session import database
from .visuals import chip, local_time, plot, kpi_grid

LABELS = dict(zip(INDICATORS, ("Flusso fisico", "Nomina", "Rinomina", "Allocazione",
                              "Capacità tecnica", "Capacità prenotata", "Capacità disponibile")))
FILTER_KEYS = ("net_layers", "net_operators", "net_regions", "net_statuses", "net_period",
               "net_events", "net_only_events", "net_labels", "net_infrastructure", "net_direction", "net_indicator")
SELECTED = "italian_network_selected_v1"
FOCUS = "italian_network_focus_v1"
_viewport_width = declare_component("network_viewport_width",path=str(Path(__file__).with_name("map_viewport")))


@st.cache_data(show_spinner=False)
def assets():
    network = load_network_assets()
    boundary = json.loads((ASSETS/"italy.geojson").read_text())
    payload = json.loads((ASSETS/"operational.json").read_text())
    return network, boundary, tuple(decode_snapshot(p) for p in payload["snapshots"])


@st.cache_data(show_spinner=False)
def bundled_interruptions():
    network, _, _ = assets()
    p = json.loads((ASSETS/"interruptions.json").read_text())
    binding = next(b for b in network.bindings if b.point_direction == p["point_direction"])
    return parse_interruptions(json.dumps(p["raw_response"]),datetime.fromisoformat(p["retrieved_at"]),binding,
                               date.fromisoformat(p["first"]),date.fromisoformat(p["last"]))


def reset_filters():
    for key in FILTER_KEYS:
        st.session_state.pop(key, None)
    st.session_state.pop("net_pending_selection", None)
    st.session_state.pop(SELECTED,None)
    st.session_state["net_map_epoch"] = st.session_state.get("net_map_epoch", 0)+1


def _accept_pick(chart_key, visible_ids, mode, event=None):
    identifier = selected_id(event if event is not None else st.session_state.get(chart_key,{}), set(visible_ids))
    if identifier:
        st.session_state[SELECTED] = identifier
        if mode == "full":
            st.session_state["net_pending_selection"] = identifier


def _widget_selection(key):
    if st.session_state.get(key):
        st.session_state[SELECTED] = st.session_state[key]


def _reset_view(mode):
    key = "net_view_epoch_"+mode
    st.session_state[key] = st.session_state.get(key,0)+1


def render_map(network, boundary, visible, identifier, *, mode, observations, day, direction="entry", events=(), show_labels=True):
    """Native selection callback runs before the single Streamlit rerun."""
    key = f"italian_network_{mode}_deck_{st.session_state.get('net_map_epoch',0)}_{st.session_state.get('net_view_epoch_'+mode,0)}"
    description = "Mappa del sistema gas italiano. Gasdotti storici schematici e impianti; seleziona con il mouse o usa la ricerca infrastruttura per leggere gli stessi dettagli."
    # Native alt was added after our minimum supported Streamlit version.
    accessible = {"alt":description} if "alt" in signature(st.pydeck_chart).parameters else {}
    if not accessible:
        st.html('<p class="gas-map-description">'+escape(description)+'</p>')
    with st.container(key="network_map_frame_"+mode):
        width = _viewport_width(default=600,key="network_map_width_"+mode)
        width = width if isinstance(width,(int,float)) and not isinstance(width,bool) and 200 <= width <= 4000 else 600
        st.pydeck_chart(deck(network,boundary,visible,identifier,events,observations=observations,
            day=day,direction=direction,show_labels=show_labels,mode=mode,viewport_width=width-2),key=key,
            height=500 if mode == "overview" else 650,selection_mode="single-object",
            on_select=partial(_accept_pick,key,tuple(i.id for i in visible),mode),**accessible)
        st.button("Vista Italia",key="net_view_reset_"+mode,on_click=_reset_view,args=(mode,),
                  help="Ripristina l’inquadratura italiana, mantenendo l’infrastruttura selezionata.")


def render_legend(categories):
    labels = "".join(f'<span><img src="{legend_symbol(c)}" width="14" height="14" alt="" aria-hidden="true">{escape(CATEGORIES[c])}</span>' for c in categories)
    st.html('<div class="gas-map-legend" aria-label="Legenda della mappa">'+labels+'</div>')


def _age(value):
    hours = max(0,int(value.total_seconds()//3600))
    return f"{hours//24} g {hours%24} h" if hours >= 24 else f"{hours} h"


def _source_status(status, day, *, expanded=False):
    style = {"Storico":"historical","Aggiornato":"ok","Parziale":"review","Non disponibile":""}[status["status"]]
    st.html('<div class="gas-map-status">'+chip(status["status"],style)+f'<span>ENTSOG · giorno gas {escape(data_it(day))}</span></div>')
    if status["oldest"]:
        st.caption(f"Copia più vecchia: {_age(status['age'])}"+(" · acquisizioni diverse" if status["oldest"] != status["newest"] else ""))
    if status["failed"]:
        st.caption("Aggiornamento non riuscito · ultima copia valida")
    with st.expander("Date e copertura della fonte", expanded=expanded):
        st.caption("Giorno gas: "+data_it(day)+" · 06:00–06:00 Europe/Rome")
        st.caption("Pubblicazione fonte: "+local_time(status["published_oldest"]))
        if status["published_newest"] != status["published_oldest"]:
            st.caption("Ultima pubblicazione contribuente: "+local_time(status["published_newest"]))
        st.caption("Prima acquisizione contribuente: "+local_time(status["oldest"]))
        if status["newest"] != status["oldest"]:
            st.caption("Ultima acquisizione contribuente: "+local_time(status["newest"]))
        st.caption("Età della copia in cache: "+(_age(status["age"]) if status["age"] is not None else "Non disponibile"))
        st.caption("Copertura completa nel perimetro osservato." if status["complete"] else
                   "Copertura parziale o non certificata. N/A e conflitti esclusi; capacità confrontate sullo stesso giorno gas.")


def _operational_summary(network, item, observations, snapshots, direction, first, last, saved, *, compact=False, show_source=True):
    binding = next((b for b in network.bindings_for(item.id,"ENTSOG") if b.direction == direction),None)
    if not binding:
        if item.category == "pipeline":
            st.caption("Collegamento storico schematico · nessuna misura di flusso sul segmento")
        elif not network.bindings_for(item.id,"ALSI") and not network.bindings_for(item.id,"AGSI+"):
            st.caption("Geografia storica · dati operativi non associati")
        return
    metrics = point_metrics(observations,binding.point_direction,first,last)
    values = metrics["values"]
    if not values:
        st.caption("Nessun dato operativo confrontabile nel periodo.")
        return
    day = metrics["day"]
    flow = values.get("Physical Flow")
    if flow is not None:
        delta = metrics["change_gwh_d"]
        st.metric("Ultimo flusso pubblicato",numero(flow,1)+" GWh/d",
                  delta=(f"{numero(delta,1)} GWh/d sul giorno precedente" if delta is not None else None),delta_color="off")
    st.caption("Giorno gas "+data_it(day)+" · "+("Ingresso" if direction == "entry" else "Uscita"))
    if metrics["utilization_pct"] is not None:
        st.caption(f"Utilizzo capacità: {numero(metrics['utilization_pct'],1)}% · intervalli confrontabili")
    if not compact:
        measures = [(LABELS[k],v,"GWh/d","",1) for k,v in values.items() if k != "Physical Flow"]
        if measures:
            kpi_grid(measures)
        m = {"observations":metrics["observations"],"valid_points":int(flow is not None),"mapped_points":1}
        status = kpi_status(m,snapshots,day,utc_now(),current_day=_last_completed(utc_now()),failures=saved.get("failures",()))
        if show_source:
            _source_status(status,day)


def _open_full(identifier, first, last, direction=None):
    snapshots = (*assets()[2], *st.session_state.get(STATE,{}).get("snapshots",{}).values())
    earliest = min(s.first for s in snapshots)
    last = max(earliest, min(last, _last_completed(utc_now())))
    first = max(earliest, min(first, last))
    st.session_state[FOCUS] = {"id":identifier,"period":(first,last),"direction":direction}
    st.session_state["operational_platform"] = "MAP"
    from .operational_sources_page import operational_context
    st.switch_page(st.Page(operational_context,title="Security of Supply",icon=":material/shield:",url_path="security-of-supply"))


def overview_panel():
    from .system_status import build_status
    from . import system_status_page as system
    network,boundary,bundled = assets()
    saved = st.session_state.get(STATE,{})
    snapshots = (*bundled,*saved.get("snapshots",{}).values())
    observations = merge_observations(snapshots)
    now = utc_now()
    status = build_status(network,snapshots,st.session_state,now,
                          gas_day=st.session_state.get(system.SELECTED_DAY,st.session_state.get(system.DAY_KEY)),
                          interruptions=(bundled_interruptions(),),policy=system.policy())
    day = status.gas_day
    first = day-timedelta(days=6)
    identifier = st.session_state.get(SELECTED,st.session_state.get("net_infrastructure","INET_BP_65"))
    all_items = {i.id:i for i in network.infrastructure}
    if identifier not in all_items:
        identifier = "INET_BP_65"
    st.session_state[SELECTED] = identifier
    visible = tuple(i for i in network.infrastructure if i.category in ("pipeline","entry","lng","storage") or i.id == identifier)
    item = all_items[identifier]
    bindings = network.bindings_for(identifier,"ENTSOG")
    directions = sorted({b.direction for b in bindings})
    if st.session_state.get("net_overview_direction") not in directions:
        st.session_state["net_overview_direction"] = "entry" if "entry" in directions else directions[0] if directions else None
    direction = st.session_state.get("net_overview_direction")
    system.header(status)
    with st.container(key="network_overview"):
        map_col, detail = st.columns([1,1.3],gap="small")
        with map_col:
            render_map(network,boundary,visible,identifier,mode="overview",observations=observations,day=day,direction=direction)
            render_legend(c for c in CATEGORIES if any(i.category == c for i in visible))
            st.caption("SciGRID 2021 · collegamenti storici schematici · CC BY 4.0 · Natural Earth, pubblico dominio")
        with detail.container(key="network_home_detail"):
            st.subheader(display_name(item.name))
            st.caption(" · ".join(filter(None,[CATEGORIES[item.category],item.operator,*item.regions])))
            if len(directions)>1:
                direction = st.radio("Direzione",directions,key="net_overview_direction",horizontal=True,
                    format_func=lambda d:"Ingresso" if d == "entry" else "Uscita",label_visibility="collapsed")
            if bindings or any(saved.get("facilities",{}).get((b.provider,b.external_id)) for b in network.bindings_for(identifier)):
                data_tab, history_tab = st.tabs(["Dati","Storico"])
                with data_tab:
                    with st.container(key="network_home_point_data"):
                        _operational_summary(network,item,observations,snapshots,direction,first,day,saved,show_source=False)
                        _gie_detail(saved,identifier,network,first,day,mode="overview")
                with history_tab:
                    binding = next((b for b in bindings if b.direction == direction),None)
                    if binding:
                        _history(observations,binding.point_direction,first,day,mode="overview")
                    else:
                        st.caption("Storico GIE disponibile nella scheda Dati del singolo impianto.")
            else:
                _operational_summary(network,item,observations,snapshots,direction,first,day,saved,compact=True)
            with st.popover("Cerca infrastruttura",width="stretch"):
                st.session_state["net_overview_infrastructure"] = identifier
                st.selectbox("Infrastruttura",[i.id for i in sorted(network.infrastructure,key=lambda i:i.name)],
                    key="net_overview_infrastructure",format_func=lambda key:display_name(all_items[key].name),
                    on_change=_widget_selection,args=("net_overview_infrastructure",))
    system.balance(status)
    system.attention(status,network,_open_full)
    st.button("Esplora la rete",icon=":material/arrow_forward:",key="net_overview_open",
              width="stretch",on_click=_open_full,args=(identifier,first,day,direction))


def _plain(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError("Unsupported export value")


def export(network, visible, observations, events, first, last):
    ids = {i.id for i in visible}
    return json.dumps({"scope":"Italia · selezione corrente · nessuna stima di copertura nazionale",
        "first_gas_day":first, "last_gas_day":last,
        "infrastructure":[asdict(i) for i in visible],
        "geography":[asdict(g) for g in network.geography if g.infrastructure_id in ids],
        "bindings":[asdict(b) for b in network.bindings if b.infrastructure_id in ids],
        "observations":[asdict(o) for o in observations if o.infrastructure_id in ids
            and o.period_from < _start(last+timedelta(days=1)) and o.period_to > _start(first)],
        "events":[e for e in events if e["infrastructure_id"] in ids]},
        ensure_ascii=False, indent=2, default=_plain)


def _daily(observations, point, first, last, indicator):
    days = [first+timedelta(days=i) for i in range((last-first).days+1)]
    return days, [applicable(observations, point, d, indicator) for d in days]


def _history(observations, point, first, last, *, mode="full"):
    available = [name for name in INDICATORS if any(o.point_direction == point and o.indicator == name for o in observations)]
    if not available:
        st.caption("Nessuna serie storica disponibile per questa direzione nel periodo.")
        return
    key = "net_indicator" if mode == "full" else "net_overview_indicator"
    if st.session_state.get(key) not in available:
        st.session_state[key] = available[0]
    indicator = st.selectbox("Storico", available, format_func=LABELS.__getitem__, key=key)
    days, values = _daily(observations, point, first, last, indicator)
    usable = [v for v in values if v is not None]
    if not usable:
        st.caption("Nessun valore confrontabile sull’intero giorno gas nel periodo.")
        return
    figure = go.Figure(go.Scatter(x=days, y=[float(v) if v is not None else None for v in values],
        mode="lines+markers", connectgaps=False, line={"color":"#65dfbf", "width":2.5},
        marker={"size":5}, hovertemplate="%{x|%d/%m/%Y}<br>%{y:.2f} GWh/d<extra></extra>"))
    figure.update_layout(template="plotly_dark",height=250, margin={"l":42,"r":14,"t":12,"b":52},
                         paper_bgcolor="rgba(0,0,0,0)",plot_bgcolor="rgba(0,0,0,0)",
                         font={"color":"#b0bed0","family":"Arial, sans-serif","size":11},
                         yaxis={"title":"GWh/d","automargin":True},
                         xaxis={"tickformat":"%d/%m","nticks":4,"tickangle":0,"automargin":True},showlegend=False)
    plot(figure, key="net_entsog_history" if mode == "full" else "net_overview_entsog_history")
    st.caption(f"{len(usable)}/{len(days)} giorni gas · 06:00–06:00 Europe/Rome")
    if len(usable) >= 2:
        st.caption(f"Min {numero(min(usable),1)} · Max {numero(max(usable),1)} · Media {numero(sum(usable)/len(usable),1)} GWh/d")
        length = len(days)
        _, prior = _daily(observations, point, first-timedelta(days=length), first-timedelta(days=1), indicator)
        if len(usable) == length and all(v is not None for v in prior):
            delta = sum(usable)/length-sum(prior)/length
            st.caption(f"Media vs {length} giorni precedenti: {numero(delta,1)} GWh/d · periodi completi")


def _gie_detail(saved, identifier, network, first, last, *, mode="full"):
    for binding in network.bindings_for(identifier):
        result = saved.get("facilities", {}).get((binding.provider, binding.external_id))
        if not result:
            continue
        frame = result["frame"]
        frame = frame.loc[frame.gas_day.between(first,last)]
        if frame.empty:
            continue
        labels = {"stock_twh":("Gas in stoccaggio","TWh"), "capacity_twh":("Capacità stoccaggio","TWh"),
            "fill_pct":("Riempimento","%"), "injection_gwh_d":("Iniezione","GWh/d"),
            "withdrawal_gwh_d":("Prelievo","GWh/d"), "inventory_1000m3_lng":("Giacenza GNL","10³ m³ GNL"),
            "inventory_gwh":("Giacenza GNL","GWh"), "sendout_gwh_d":("Send-out","GWh/d"),
            "dtrs_gwh_d":("Capacità send-out dichiarata","GWh/d"),
            "dtmi_1000m3_lng":("Capacità inventario GNL dichiarata","10³ m³ GNL")}
        st.markdown("**"+binding.provider+" · singolo impianto**")
        latest = frame.iloc[-1]
        measures = [{"Misura":label,"Valore":numero(latest[key],2),"Unità":unit}
                    for key,(label,unit) in labels.items() if key in latest and pd.notna(latest[key])]
        st.caption(f"Giorno gas {data_it(latest.gas_day)} · acquisito {local_time(result['acquired'])}")
        if result["failed"] or binding.provider+":"+binding.external_id in saved.get("failures",{}):
            st.caption("Aggiornamento non riuscito · ultima copia valida")
        if latest.get("review",False):
            st.caption("Verifica GIE: giacenza, capacità e percentuale non riconciliate.")
        if measures:
            st.dataframe(measures, hide_index=True, width="stretch")
        numeric = [c for c in labels if c in frame and frame[c].notna().any()]
        if len(frame) > 1 and numeric:
            prefix = "net_gie_" if mode == "full" else "net_overview_gie_"
            series = st.selectbox("Storico GIE", numeric, format_func=lambda c:labels[c][0], key=prefix+"series_"+binding.provider)
            fig=go.Figure(go.Scatter(x=frame.gas_day, y=frame[series], mode="lines+markers", connectgaps=False))
            fig.update_layout(height=190,margin={"l":0,"r":0,"t":5,"b":5},yaxis_title=labels[series][1])
            plot(fig, key=prefix+"history_"+binding.provider)
        st.caption(f"Fonte: {result['source']} · stato {latest.status}")
        st.link_button("Apri fonte GIE", result["source_url"])


def _detail(network, item, observations, snapshots, direction, events, first, last, saved):
    geo = next(g for g in network.geography if g.infrastructure_id == item.id)
    st.subheader(display_name(item.name))
    st.caption(" · ".join(filter(None,[CATEGORIES[item.category],item.operator,*item.regions])))
    _operational_summary(network,item,observations,snapshots,direction,first,last,saved)
    bindings = network.bindings_for(item.id, "ENTSOG")
    binding = next((b for b in bindings if b.direction == direction), None)
    if binding:
        rows = [o for o in observations if o.point_direction == binding.point_direction
                and o.period_from < _start(last+timedelta(days=1)) and o.period_to > _start(first)]
        if rows:
            _history(observations, binding.point_direction, first, last)
            with st.expander("Valori e qualità"):
                latest = [max((o for o in rows if o.indicator == indicator), key=lambda o:(o.period_to,o.period_from))
                          for indicator in INDICATORS if any(o.indicator == indicator for o in rows)]
                st.dataframe([{"Misura":LABELS[o.indicator],"GWh/d":numero(o.value,2),
                    "Da":o.source_period_from or o.period_from.isoformat(),"A":o.source_period_to or o.period_to.isoformat(),
                    "Qualità":o.quality_status,"Stato fonte":o.publication_status,"Versioni":len(o.revisions),
                    "Pubblicato":o.observed_at or "Non disponibile","Acquisito":local_time(o.retrieved_at)} for o in latest],
                    hide_index=True, width="stretch")
                st.caption("Intervalli originali. N/A e conflitti esclusi dai calcoli; le capacità devono coprire lo stesso giorno gas.")
                for s in snapshots:
                    if s.point_direction == binding.point_direction and s.first <= last and s.last >= first:
                        if s.partial:
                            st.caption("Copertura parziale: conteggi API non riconciliati o pubblicazioni non confrontabili.")
                        if s.failed:
                            st.caption("Aggiornamento non riuscito · cache del "+local_time(s.acquired))
                        for warning in s.warnings:
                            st.caption(warning)
                st.link_button("ENTSOG · dati di trasporto", "https://transparency.entsog.eu/")
        else:
            st.caption("Nessuna pubblicazione disponibile per questa direzione e questo periodo.")
    _gie_detail(saved, item.id, network, first, last)
    matching = [e for e in events if e["infrastructure_id"] == item.id]
    if matching:
        with st.expander(f"Avvisi associati · {len(matching)}", expanded=True):
            for event in matching:
                st.write(event["kind"])
                st.caption(f"{local_time(event['period_from'])} → {local_time(event['period_to'])}")
                if event["value"] is not None:
                    st.caption(numero(event["value"],2)+" "+event["unit"]+" · "+event.get("capacity_type", ""))
                elif event.get("impact_label"):
                    st.caption(event["impact_label"])
                st.caption(event["source"]+" · "+event["status"])
                st.link_button("Fonte avviso", event["source_url"])
    with st.expander("Identità e geografia"):
        st.caption(item.status)
        st.caption(geo.geometry_accuracy)
        st.write("Fonte: "+geo.source)
        st.caption(f"Edizione {geo.dataset_version} · {geo.observed_at} · acquisita {geo.retrieved_at}")
        st.caption("ID geografico: "+item.source_id)
        for b in network.bindings_for(item.id):
            st.caption(f"{b.provider}: {b.external_id} · operatore {b.operator_id} · mapping confermato")
        details = {"diameter_mm":"Diametro storico · mm", "max_pressure_bar":"Pressione massima storica · bar",
                   "length_km":"Lunghezza originale storica · km"}
        for name,label in details.items():
            if item.metadata.get(name) is not None:
                st.caption(label+": "+numero(item.metadata[name],1))
        if item.metadata.get("length_note"):
            st.caption(item.metadata["length_note"])
        st.caption(geo.license)
        st.link_button("Fonte geografica", geo.source_url)


def panel(mode="full"):
    if mode == "overview":
        try:
            return overview_panel()
        except (OSError,ValueError,KeyError):
            st.info("Mappa temporaneamente non disponibile. Le analisi restano accessibili qui sotto.")
            return
    if mode != "full":
        raise ValueError("Modalità cartografica non riconosciuta")
    network, boundary, bundled = assets()
    focus = st.session_state.pop(FOCUS,None)
    if focus and focus["id"] in {i.id for i in network.infrastructure}:
        st.session_state["net_pending_selection"] = focus["id"]
        st.session_state["net_period"] = focus["period"]
        item = next(i for i in network.infrastructure if i.id == focus["id"])
        if focus.get("direction") in {b.direction for b in network.bindings_for(item.id,"ENTSOG")}:
            st.session_state["net_direction"] = focus["direction"]
        st.session_state["net_layers"] = sorted(set(st.session_state.get("net_layers",["pipeline","entry","lng","storage","compressor"]))|{item.category})
        for key in ("net_operators","net_regions","net_statuses","net_only_events"):
            st.session_state.pop(key,None)
    saved = st.session_state.get(STATE, {})
    snapshots = (*bundled, *saved.get("snapshots", {}).values())
    observations = merge_observations(snapshots)
    now = utc_now()
    default_last = min(max(s.last for s in bundled), _last_completed(now))
    meta, period_col, actions = st.columns([3,2,2], vertical_alignment="bottom")
    with meta:
        st.caption("Italia · dati pubblici · cartografia storica e aggiornamenti su richiesta")
        data_status = st.empty()
        if saved.get("attempted"):
            st.caption("Ultimo tentativo: "+local_time(saved["attempted"]))
            if saved.get("notices"):
                with st.expander("Esito aggiornamento", expanded=bool(saved.get("failures"))):
                    for notice in saved["notices"]:
                        st.caption(notice)
    period = period_col.date_input("Periodo · giorni gas", value=(default_last-timedelta(days=6),default_last),
        min_value=min(s.first for s in snapshots), max_value=_last_completed(now), key="net_period", format="DD/MM/YYYY")
    with actions:
        refresh_col, reset_col = st.columns(2)
        refresh_clicked = refresh_col.button("Aggiorna", icon=":material/refresh:", key="net_refresh", width="stretch",
            help="Aggiorna il punto e la direzione selezionati, gli avvisi ENTSOG e il contesto GIE se configurato. Nessuna chiamata durante la navigazione.")
        reset_col.button("Reset filtri", on_click=reset_filters, key="net_reset", width="stretch")
    layer_col, event_col, filter_col = st.columns([5,1,1], vertical_alignment="bottom")
    layer_col.multiselect("Livelli", list(CATEGORIES), default=["pipeline","entry","lng","storage","compressor"],
        format_func=CATEGORIES.__getitem__, key="net_layers", placeholder="Scegli i livelli")
    show_events = event_col.toggle("Interruzioni", key="net_events", help="Avvisi associati con codici verificati; uno zero pubblicato non è un’interruzione.")
    with filter_col.popover("Filtri", width="stretch"):
        st.multiselect("Operatore", sorted({i.operator or "Non indicato" for i in network.infrastructure}), key="net_operators")
        st.multiselect("Regione", sorted({r for i in network.infrastructure for r in i.regions}), key="net_regions")
        st.multiselect("Stato", sorted({i.status for i in network.infrastructure}), key="net_statuses")
        show_labels = st.toggle("Nomi sulla mappa", value=True, key="net_labels")
        st.checkbox("Solo con avvisi associati", key="net_only_events", disabled=not show_events)
    if len(period) != 2 or not 0 <= (period[1]-period[0]).days < 31:
        st.info("Seleziona un periodo da 1 a 31 giorni gas conclusi.")
        return
    first, last = period
    iip_result = st.session_state.get("gie_iip", {}).get("result")
    iip, unresolved = iip_events(network, iip_result, first, last)
    interruptions = {bundled_interruptions()["point_direction"]:bundled_interruptions(), **saved.get("interruptions", {})}
    interruption_sets = interruptions.values()
    events = relevant_events((*iip, *(e for s in interruption_sets for e in s["records"])), first, last)
    event_ids = {e["infrastructure_id"] for e in events}
    visible = filter_infrastructure(network, st.session_state.net_layers,
        operators=[None if v == "Non indicato" else v for v in st.session_state.get("net_operators",[])],
        regions=st.session_state.get("net_regions",[]), statuses=st.session_state.get("net_statuses",[]),
        event_ids=event_ids if show_events and st.session_state.get("net_only_events") else None)
    options = [i.id for i in sorted(visible, key=lambda i:(i.category != "entry",i.name))]
    lookup = {i.id:i for i in visible}
    visible_events = [e for e in events if e["infrastructure_id"] in lookup]
    pending = st.session_state.pop("net_pending_selection", st.session_state.get(SELECTED))
    if pending in options:
        st.session_state["net_infrastructure"] = pending
    if st.session_state.get("net_infrastructure") not in options:
        st.session_state["net_infrastructure"] = "INET_BP_65" if "INET_BP_65" in options else options[0] if options else None
    st.session_state[SELECTED] = st.session_state.get("net_infrastructure")
    summary = st.container(key="network_summary")
    with st.container(key="network_explorer"):
        map_col, detail = st.columns([1,1], gap="small")
    detail_content = detail.container(key="network_detail", border=True)
    with detail_content:
        identifier = st.selectbox("Infrastruttura", options, format_func=lambda k:display_name(lookup[k].name), key="net_infrastructure",
                                 placeholder="Nessuna infrastruttura nei filtri", disabled=not options,
                                 on_change=_widget_selection,args=("net_infrastructure",))
        points = network.bindings_for(identifier, "ENTSOG")
        directions = sorted({b.direction for b in points})
        if st.session_state.get("net_direction") not in directions:
            st.session_state["net_direction"] = directions[0] if directions else None
        direction = st.selectbox("Direzione", directions, key="net_direction", disabled=not directions,
            format_func=lambda d:"Ingresso" if d == "entry" else "Uscita", placeholder="—") if directions else None
    if refresh_clicked:
        if identifier:
            from .operational_sources_page import configured_key
            with st.spinner("Aggiornamento delle fonti per la selezione…"):
                refresh_network(st.session_state, database(), network, identifier, direction, first, last, now,
                                api_key=configured_key())
            st.rerun()
        else:
            st.caption("Seleziona un’infrastruttura per aggiornare i dati.")
    metrics = map_kpis(network, visible, observations, last)
    status = kpi_status(metrics,snapshots,last,now,current_day=_last_completed(now),failures=saved.get("failures",()))
    with data_status.container():
        st.caption(f"{status['status']} · ENTSOG · giorno gas {data_it(last)}"+
                   (f" · copia più vecchia {_age(status['age'])}" if status["age"] is not None else ""))
    with summary:
        items = [("Infrastrutture",metrics["mapped"],"", "Nei livelli selezionati",0)]
        if metrics["mapped_points"]:
            items.append(("Punti con dati",metrics["valid_points"],"",f"Su {metrics['mapped_points']} punti ENTSOG",0))
        if metrics["entry_flow_gwh_d"] is not None:
            items.append(("Ingressi di frontiera",metrics["entry_flow_gwh_d"],"GWh/d",f"{metrics['valid_entry_points']}/{metrics['mapped_entry_points']} ingressi coperti",1))
        if metrics["utilization_pct"] is not None:
            items.append(("Utilizzo capacità",metrics["utilization_pct"],"%",f"{metrics['comparable_points']} ingressi confrontabili",1))
        kpi_grid(items)
        if metrics["mapped_points"]:
            st.caption(f"Giorno gas: {data_it(last)} · flussi aggregati dei soli ingressi di frontiera; GNL separato.")
    with map_col:
        render_map(network,boundary,visible,identifier,mode="full",observations=observations,day=last,
                   direction=direction,events=event_ids if show_events else (),show_labels=show_labels)
        render_legend(c for c in st.session_state.net_layers if metrics["categories"][c])
        st.caption("Collegamenti schematici SciGRID 2021: non tracciati certificati né flussi sui gasdotti. Posizioni storiche indicative, salvo fonte del gestore.")
        st.caption("© SciGRID_gas / DLR-VE · CC BY 4.0 · INET_Raw 1.4 · confini Natural Earth, pubblico dominio")
        if not options:
            st.info("Nessuna infrastruttura nei filtri. Modifica i livelli o usa Reset filtri.")
        if "production" in st.session_state.net_layers:
            st.caption("Produzione: nessuna localizzazione verificata inclusa. I dati MASE restano nella vista Produzione.")
    with detail_content:
        if identifier:
            _detail(network,lookup[identifier],observations,snapshots,direction,events,first,last,saved)
    with st.expander("Copertura e fonti"):
        _source_status(status,last)
        st.dataframe([{"Livello":CATEGORIES[c],"Mappate":metrics["categories"][c]} for c in CATEGORIES],hide_index=True)
        relevant = [s for s in snapshots if s.first <= last and s.last >= first
                    and any(o.infrastructure_id in lookup for o in s.records)]
        if relevant:
            st.caption(f"{sum(s.partial for s in relevant)} risposte con copertura parziale. Le revisioni e gli intervalli restano nel dettaglio e nell’export.")
        st.caption("Cataloghi: ENTSOG e GIE acquisiti il 22/11/2026. Un punto pubblicante o un impianto nel catalogo non certificano disponibilità istantanea.")
        queried = [s for s in interruption_sets if s["first"] <= last and s["last"] >= first
                   and any(b.point_direction == s["point_direction"] and b.infrastructure_id in lookup for b in network.bindings)]
        if queried or iip_result:
            st.caption(f"Avvisi associati alla selezione: {len(visible_events)} · ENTSOG interrogato su {len(queried)} punti/direzioni, copertura non nazionale.")
        else:
            st.caption("Avvisi non verificati per questa selezione e questo periodo.")
        st.caption(f"IIP: {unresolved} messaggi non localizzati con certezza; restano nella vista Avvisi di mercato." if iip_result
                   else "IIP non interrogato: nessuna conclusione sull’assenza di indisponibilità.")
        if iip_result:
            st.caption("IIP · acquisito "+local_time(iip_result["acquired"])+(" · risposta parziale" if iip_result["partial"] else ""))
            if iip_result["failed"] or st.session_state.get("gie_iip",{}).get("error"):
                st.caption("IIP: aggiornamento non riuscito; ultima copia valida.")
        for notice in saved.get("notices", ()):
            st.caption(notice)
        st.link_button("SciGRID · dataset e licenza", "https://zenodo.org/records/4750979")
        st.download_button("Esporta selezione e provenienza",export(network,visible,observations,events,first,last),
                           "igor-rete-italiana.json","application/json",key="net_export")
    national = st.session_state.get("AGSI+_IT", {}).get("result")
    if national and not national["frame"].empty:
        latest = national["frame"].iloc[-1]
        st.caption(f"Contesto nazionale GIE AGSI+ · {data_it(latest.gas_day)} · {numero(latest.stock_twh,2)} TWh · {numero(latest.fill_pct,1)}% · indipendente dai filtri geografici")
        failed = national["failed"] or st.session_state.get("AGSI+_IT",{}).get("error")
        st.caption("Acquisito "+local_time(national["acquired"])+(" · ultima cache, aggiornamento non riuscito" if failed else ""))
