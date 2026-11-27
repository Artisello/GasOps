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
from .entsog_network import INDICATORS, NAMES
from .italiano import numero, data_it
from .italian_network import (ASSETS, CATEGORIES, applicable, filter_infrastructure,
                              load_network_assets, map_kpis, merge_observations, selected_id,
                              kpi_status, point_intelligence, verified_bindings,
                              validated_observations, reading_infrastructure, READING_MODES)
from .italian_network_events import iip_events, verified_events, parse_interruptions
from .italian_network_map import deck, display_name, legend_symbol, nearby_points, NEARBY_METRES
from .italian_network_refresh import STATE
from .italian_network_sources import decode_snapshot, load_catalog
from .node_discovery import audit_nodes
from .direction_ui import arrow_text, direction_header, paired_flow_html, direction_chip
from .public_data import SourceUnavailable, SourceSchemaError
from .models import utc_now
from . import operational_acquisition as acquisition
from .balancing_cockpit import inventory_state
from .gas_data import source_context
from .operational_progress import connection_status, watch
from .system_status_page import ARCHIVE_KEY
from .session import database
from .visuals import chip, local_time, plot, kpi_grid

LABELS = NAMES
FILTER_KEYS = ("net_layers", "net_operators", "net_regions", "net_statuses", "net_period",
               "net_events", "net_only_events", "net_labels", "net_infrastructure", "net_direction", "net_indicator")
SELECTED = "italian_network_selected_v1"
FOCUS = "italian_network_focus_v1"
READING = "italian_network_reading_v1"
DETAIL_TABS = ("Dati", "Storico", "Eventi", "Fonti")


def _detail_tab_key(mode):
    return "net_detail_tab_" + mode
MODE_LABELS = {"SYSTEM":"Sistema","FLOW":"Flussi","ATTENTION":"Attenzione"}
MODE_HINTS = {"SYSTEM":"Categorie e disponibilità dei dati.",
    "FLOW":"Flussi dei punti verificati · gasdotti solo come contesto geografico.",
    "ATTENTION":"Eventi pubblicati, indicatori calcolati e qualità dei dati."}
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


def _accept_pick(chart_key, visible_ids, mode, event=None, *, point_directions=()):
    identifier = selected_id(event if event is not None else st.session_state.get(chart_key,{}), set(visible_ids))
    if identifier:
        previous = st.session_state.get(SELECTED)
        st.session_state[SELECTED] = identifier
        if mode in ("overview", "full"):
            st.session_state[_detail_tab_key(mode)] = (
                "Eventi" if st.session_state.get(READING) == "ATTENTION" else "Dati"
            )
        direction = dict(point_directions).get(identifier)
        direction_key = "net_direction" if mode == "full" else "net_overview_direction"
        if direction in ("entry","exit"):
            st.session_state[direction_key] = direction
        elif previous != identifier and mode in ("overview","full"):
            st.session_state.pop(direction_key,None)
        if mode == "full":
            st.session_state["net_pending_selection"] = identifier


def _widget_selection(key):
    if st.session_state.get(key):
        previous = st.session_state.get(SELECTED)
        st.session_state[SELECTED] = st.session_state[key]
        mode = "overview" if key == "net_overview_infrastructure" else "full"
        if previous != st.session_state[key]:
            st.session_state.pop("net_overview_direction" if mode == "overview" else "net_direction",None)
        st.session_state[_detail_tab_key(mode)] = (
            "Eventi" if st.session_state.get(READING) == "ATTENTION" else "Dati"
        )


def _infrastructure_label(item):
    return display_name(item.name)+" · "+CATEGORIES[item.category]


def _reading_selection(key):
    st.session_state[READING] = st.session_state[key]
    mode = "overview" if key == "net_reading_overview" else "full"
    st.session_state[_detail_tab_key(mode)] = "Eventi" if st.session_state[key] == "ATTENTION" else "Dati"
    st.session_state.pop("net_pending_selection",None)
    _reset_view(mode)


def _reading_items(perimeter, reading, intelligence, identifier, events, findings, *, include_nodes=True):
    return reading_infrastructure(perimeter,reading,intelligence,event_ids=events,finding_ids=findings,include_nodes=include_nodes)


def _selectable_items(displayed, reading):
    return tuple(i for i in displayed if reading not in ("FLOW","ATTENTION") or i.category != "pipeline")


def _resolve_selection(displayed, reading, previous, events=(), findings=()):
    choices = _selectable_items(displayed,reading)
    if previous in {i.id for i in choices}:
        return previous
    if not choices:
        return None
    if reading == "ATTENTION":
        return min(choices,key=lambda i:(i.id not in events,i.id not in findings,i.name,i.id)).id
    return min(choices,key=lambda i:(i.id!="INET_BP_65",i.category!="entry",i.name,i.id)).id


def _reconcile_map(network, perimeter, observations, snapshots, day, now, saved, previous,
                   direction, policy, reading, events, findings, mode):
    # Eligibility uses a verified direction with data, not a stale direction from another item.
    intelligence = _map_intelligence(network,perimeter,observations,snapshots,day,now,saved,None,None,policy)
    # Membership in Flow depends on any verified observed direction, not the
    # direction the user happens to inspect (which may legitimately be N/D).
    flow_displayed = _reading_items(perimeter,reading,intelligence,previous,events,findings) if reading=="FLOW" else None
    if previous in intelligence and direction in ("entry","exit"):
        candidate = point_intelligence(network,previous,observations,day,now,direction=direction,
            snapshots=snapshots,failures=saved.get("failures",()),ttl_hours=policy.network_ttl_hours)
        if candidate.get("binding"):
            intelligence[previous] = candidate
    displayed = flow_displayed if flow_displayed is not None else _reading_items(perimeter,reading,intelligence,previous,events,findings)
    identifier = _resolve_selection(displayed,reading,previous,events,findings)
    if identifier != previous:
        st.session_state[_detail_tab_key(mode)] = "Eventi" if reading=="ATTENTION" else "Dati"
        if st.session_state.get("net_camera_focus_"+mode):
            _reset_view(mode)
    binding = intelligence.get(identifier,{}).get("binding")
    directions = sorted({b.direction for b in verified_bindings(network,identifier)}) if identifier else []
    direction = binding.direction if binding else (directions[0] if directions else None)
    st.session_state[SELECTED] = identifier
    return displayed,identifier,directions,direction,intelligence


def _empty_selection(reading):
    st.info("Nessun punto pertinente per questa vista e il giorno selezionato." if reading in ("FLOW","ATTENTION")
            else "Nessuna infrastruttura nei filtri selezionati.")


def _select_related(mode, identifier):
    _accept_pick("related", (identifier,), mode,
        {"selection":{"objects":{"related":[{"infra_id":identifier}]}}})


def _nearby_selector(network, item, visible, mode):
    ids = nearby_points(network, visible).get(item.id, ())
    if not ids:
        return
    lookup = {i.id:i for i in visible}
    st.caption(f"Infrastrutture sovrapposte o vicine (entro {NEARBY_METRES} m) · scegli quale consultare.")
    with st.container(key="network_nearby_"+mode):
        for other in sorted((lookup[i] for i in ids), key=lambda i:(i.category,i.name,i.id)):
            st.button(_infrastructure_label(other), key=f"net_nearby_{mode}_{other.id}",
                on_click=_select_related,args=(mode,other.id),width="stretch")


def _attention_context(identifier, displayed, reading):
    if reading == "ATTENTION" and identifier not in {i.id for i in displayed}:
        st.info("Selezione fuori dalla vista Attenzione: nessun segnale associato nel perimetro disponibile. Scegli un punto evidenziato sulla mappa.")



def _mode_selector(layout):
    current = st.session_state.get(READING,"SYSTEM")
    current = current if current in READING_MODES else "SYSTEM"
    st.session_state[READING] = current
    key = "net_reading_"+layout
    st.session_state[key] = current
    with st.container(key="net_mode_"+layout):
        st.radio("Lettura della mappa",READING_MODES,key=key,horizontal=True,label_visibility="collapsed",
                 format_func=MODE_LABELS.__getitem__,on_change=_reading_selection,args=(key,))
        st.caption(MODE_HINTS[current])
    return current


def _initialize_layers():
    # Upgrade only the previous default, preserving deliberate user filters.
    if not st.session_state.get("net_layer_defaults_p1"):
        if set(st.session_state.get("net_layers",())) == {"pipeline","entry","lng","storage","compressor"}:
            st.session_state["net_layers"] = list(CATEGORIES)
        st.session_state["net_layer_defaults_p1"] = True
    # Restore the previous default without changing other custom layer subsets.
    if not st.session_state.get("net_layer_defaults_nodes_v1"):
        if set(st.session_state.get("net_layers",())) == set(CATEGORIES)-{"node"}:
            st.session_state["net_layers"] = list(CATEGORIES)
        st.session_state["net_layer_defaults_nodes_v1"] = True


def _map_intelligence(network, visible, observations, snapshots, day, now, saved, selected, direction, policy):
    return {i.id:point_intelligence(network,i.id,observations,day,now,
        direction=direction if i.id == selected else None,snapshots=snapshots,
        failures=saved.get("failures",()),ttl_hours=policy.network_ttl_hours)
        for i in visible if network.bindings_for(i.id,"ENTSOG")}


def _reset_view(mode):
    st.session_state.pop("net_camera_focus_"+mode,None)
    key = "net_view_epoch_"+mode
    st.session_state[key] = st.session_state.get(key,0)+1


def _focus_view(mode, identifier):
    _reset_view(mode)
    st.session_state["net_camera_focus_"+mode] = identifier


def render_map(network, boundary, visible, identifier, *, mode, observations, day, direction="entry", events=(), show_labels=True,
               reading_mode="SYSTEM", intelligence=None, findings=(), scenario_ids=()):
    """Native selection callback runs before the single Streamlit rerun."""
    key = f"italian_network_{mode}_deck_v2_{st.session_state.get('net_map_epoch',0)}_{st.session_state.get('net_view_epoch_'+mode,0)}"
    description = "Mappa del sistema gas italiano. Gasdotti storici schematici e impianti; seleziona con il mouse o usa la ricerca infrastruttura per leggere gli stessi dettagli."
    # Native alt was added after our minimum supported Streamlit version.
    accessible = {"alt":description} if "alt" in signature(st.pydeck_chart).parameters else {}
    if not accessible:
        st.html('<p class="gas-map-description">'+escape(description)+'</p>')
    with st.container(key="network_map_frame_"+mode):
        width = _viewport_width(default=600,key="network_map_width_"+mode)
        width = width if isinstance(width,(int,float)) and not isinstance(width,bool) and 200 <= width <= 4000 else 600
        focus = st.session_state.get("net_camera_focus_"+mode)
        st.pydeck_chart(deck(network,boundary,visible,identifier,events,observations=observations,
            day=day,direction=direction,show_labels=show_labels,mode=mode,viewport_width=width-2,
            reading_mode=reading_mode,intelligence=intelligence,finding_ids=findings,stable_picking=True,scenario_ids=scenario_ids,focus_id=focus),key=key,
            height=500 if mode in ("overview","scenario") else 650,selection_mode="single-object",
            on_select=partial(_accept_pick,key,tuple(i.id for i in _selectable_items(visible,reading_mode)),mode,
                point_directions=tuple((identifier,info["binding"].direction) for identifier,info in (intelligence or {}).items() if info.get("binding"))),**accessible)
        if mode in ("overview","full"):
            st.button("Centra selezione",key="net_view_focus_"+mode,icon=":material/my_location:",
                      disabled=identifier not in {i.id for i in visible},
                      on_click=_focus_view,args=(mode,identifier),
                      help="Inquadra l’infrastruttura selezionata senza modificare filtri o giorno gas.")
        st.button("Vista Italia",key="net_view_reset_"+mode,on_click=_reset_view,args=(mode,),
                  help="Ripristina l’inquadratura italiana, mantenendo l’infrastruttura selezionata.")


def render_legend(categories, reading_mode="SYSTEM", *, event_overlay=False):
    categories = tuple(categories)
    labels = "".join(f'<span><img src="{legend_symbol(c)}" width="14" height="14" alt="" aria-hidden="true">{escape(CATEGORIES[c])}</span>' for c in categories)
    st.html('<div class="gas-map-legend" aria-label="Legenda della mappa">'+labels+'</div>')
    if "entry" in categories:
        st.html('<div class="igor-direction-header" aria-label="Direzioni censite ENTSOG">'+
                "".join(direction_chip(t) for t in ("Solo ingresso","Solo uscita","Bidirezionale"))+'</div>')
    if reading_mode in ("SYSTEM","FLOW"):
        st.caption("Pieno: dati ENTSOG · contorno: dato assente o sola geografia.")
        if reading_mode == "FLOW":
            st.caption("Dimensione e numero accanto al punto: flusso fisico (GWh/d). Classi: 0 · fino a 100 · fino a 500 · oltre 500. Il numero è arrotondato; non è capacità.")
            st.caption("Gasdotti schematici: nessun flusso attribuito ai segmenti.")
    elif reading_mode == "ATTENTION":
        marks = "".join(f'<span><img src="{legend_symbol(c)}" alt="" aria-hidden="true">{label}</span>'
                        for c,label in (("ring","Evento pubblicato"),("finding","Indicatore I.G.O.R."),("quality","Dato assente / cache da aggiornare")))
        st.html('<div class="gas-map-legend" aria-label="Legenda attenzione">'+marks+'</div>')
    if event_overlay and reading_mode != "ATTENTION":
        st.html('<div class="gas-map-legend"><span><img src="'+legend_symbol("ring")+'" alt="" aria-hidden="true">Evento pubblicato</span></div>')


def _age(value):
    hours = max(0,int(value.total_seconds()//3600))
    return f"{hours//24} g {hours%24} h" if hours >= 24 else f"{hours} h"


def _source_status(status, day, *, expanded=False):
    from .freshness import label,style
    st.html('<div class="gas-map-status">'+chip(label(status),style(status))+f'<span>ENTSOG · giorno gas {escape(data_it(day))}</span></div>')
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


def _operational_summary(network, item, info, *, compact=False, paired=None):
    """Same sections and evidence in the overview and the full point card."""
    if not compact:st.caption("STATO")
    if not info.get("binding"):
        st.caption(item.status)
        if item.category == "pipeline":
            st.caption("Collegamento storico schematico · nessuna misura di flusso sul segmento")
        elif not network.bindings_for(item.id,"ALSI") and not network.bindings_for(item.id,"AGSI+"):
            st.caption("Geografia storica · dati operativi non associati")
        return
    binding, day = info["binding"], info["day"]
    status = info["status"]
    from .freshness import label,style
    st.html('<div class="gas-map-status">'+chip(label(status),style(status))+
        '<span>ENTSOG · '+escape(arrow_text(binding.direction))+' · '+escape(data_it(day))+'</span></div>')
    if status["age"] is not None:
        st.caption("Copia "+_age(status["age"])+(" · da aggiornare" if info["stale"] else ""))
    values, publications = info["values"], info["publications"]
    flow = values.get("Physical Flow")
    if paired is not None:
        st.caption("Flussi fisici · giorno gas selezionato")
        st.html(paired_flow_html(paired,active=binding.direction))
    if flow is not None and not compact and paired is None:st.caption("DATI FISICI")
    if flow is not None:
        delta = info["change_gwh_d"]
        if paired is None:
            flow_col,util_col=st.columns([1.3,1]) if compact else (st,None)
            flow_col.metric("Ultimo flusso pubblicato",numero(flow,1)+" GWh/d",
                      delta=(f"{numero(delta,1)} GWh/d vs D-1" if delta is not None else None),delta_color="off")
            if compact and info["utilization_pct"] is not None:
                util_col.metric("Utilizzo capacità",numero(info["utilization_pct"],1)+"%",
                    help="Flusso / capacità tecnica firm, con unità e intervalli confrontabili sul giorno gas.")
        else:
            details = []
            if info["utilization_pct"] is not None:
                details.append("Utilizzo capacità: "+numero(info["utilization_pct"],1)+"%")
            if delta is not None:
                details.append("Δ D-1: "+numero(delta,1)+" GWh/d")
            if details:
                st.caption(arrow_text(binding.direction)+" · "+" · ".join(details))
        row = publications["Physical Flow"][0]
        st.caption(_period_label(row))
    elif not values:
        st.caption("Nessun dato operativo confrontabile sul giorno selezionato.")
    if info["utilization_pct"] is not None and not compact and paired is None:
        st.caption(f"Utilizzo capacità: {numero(info['utilization_pct'],1)}% · intervalli confrontabili")
    for heading,names in (("DATI COMMERCIALI",("Nomination","Renomination","Allocation","Firm Technical","Firm Booked","Firm Available")),):
        measures = []
        for name in names:
            if name not in publications:
                continue
            row = publications[name][0]
            detail = _period_label(row)
            if name == "Firm Available":
                detail = "Pubblicata · "+detail
            if name not in values:
                detail += " · intervallo fonte, escluso dai confronti sul giorno"
            measures.append((LABELS[name],row.value,row.unit,detail,1))
        if measures:
            if compact:
                with st.expander("Capacità e dati commerciali"):
                    st.dataframe([{"Indicatore":label,"Valore":numero(value,1),"Unità":unit,"Periodo e validità":period}
                        for label,value,unit,period,*_ in measures],hide_index=True,width="stretch")
            else:
                if heading:st.caption(heading)
                kpi_grid(measures)


def _period_label(row):
    start, stop = row.period_from.astimezone(ROME), row.period_to.astimezone(ROME)
    return f"{start:%d/%m %H:%M %Z} → {stop:%d/%m %H:%M %Z}"


def _open_full(identifier, first, last, direction=None):
    snapshots = (*assets()[2], *st.session_state.get(STATE,{}).get("snapshots",{}).values())
    earliest = min(s.first for s in snapshots)
    last = max(earliest, min(last, _last_completed(utc_now())))
    first = max(earliest, min(first, last))
    st.session_state[FOCUS] = {"id":identifier,"period":(first,last),"direction":direction}
    st.session_state["operational_platform"] = "MAP"
    from .operational_sources_page import operational_context
    st.switch_page(st.Page(operational_context,title="Security of Supply",icon=":material/shield:",url_path="security-of-supply"))


def _open_stress(identifier,day):
    from .workbench import balancing
    closed=_last_completed(utc_now())
    st.session_state.update(balancing_view="Scenario di mercato",scenario_model="Stress Test Italia",
        sos_mode="Dati pubblici",sos_public_day=max(closed-timedelta(days=91),min(day,closed+timedelta(days=1))))
    st.session_state[SELECTED]=identifier
    st.session_state.pop("sos_seen_map",None)
    st.switch_page(st.Page(balancing,title="Bilanciamento",icon=":material/balance:",url_path="balancing"))


def _status_state(context, saved, now, day):
    state = inventory_state(context,saved,day,history=True)
    details = state.get("operational_acquisition",{})
    signals = acquisition.failures(details,day or _last_completed(now))
    old = state.get(STATE,{})
    facilities = dict(old.get("facilities",{}))
    for provider,identifier,eic,result,_ in context["inventory"]:
        if identifier and ((provider,eic) not in facilities or
                (result.get("acquired") and result["acquired"]>facilities[(provider,eic)]["acquired"])):
            facilities[provider,eic] = result
    state[STATE] = {**old,"facilities":facilities,"failures":{**old.get("failures",{}),**dict.fromkeys(signals,True)}}
    state["operational_connections"] = {"srg":{"failed":"srg" in signals}}
    for source,field in (("agsi","AGSI+_IT"),("alsi","ALSI_IT")):
        if source in signals and field in state:
            state[field] = {**state[field],"error":"Aggiornamento non riuscito"}
    return state


def _publish_details(result):
    if not result:
        return
    saved = dict(st.session_state.get(STATE,{}))
    for field in ("interruptions","facilities"):
        if field in result:
            saved[field] = {**saved.get(field,{}),**result[field]}
    st.session_state[STATE] = saved
    if "gie_iip" in result:
        st.session_state["gie_iip"] = result["gie_iip"]


def _window_context(network, bundled, state, now, store, first, last, archive):
    return source_context(network,bundled if archive else (),{} if archive else state,now,
        store=None if archive else store,first=first,last=last,
        interruptions=(bundled_interruptions(),) if archive else ())


def _automatic_day():
    from .system_status_page import REQUESTED_DAY
    st.session_state.pop(REQUESTED_DAY,None)


def _archive_changed(widget):
    st.session_state[ARCHIVE_KEY] = st.session_state[widget]
    _automatic_day()
    st.session_state.pop("net_period",None)


def _source_controls(connections, *, gie, overview=False):
    widget = ARCHIVE_KEY+("_overview" if overview else "_map")
    archive = st.session_state.get(ARCHIVE_KEY,False)
    if st.session_state.get(widget) != archive:
        st.session_state[widget] = archive
    with st.popover("Fonti operative"):
        connection_status(connections,gie=gie)
        st.checkbox("Consulta lo snapshot storico",key=widget,on_change=_archive_changed,args=(widget,))
        if overview:
            st.button("Ultimo giorno coperto",key="ops_default_day",on_click=_automatic_day)
            return st.button("Aggiorna fonti",key="ops_refresh_overview")
    return False


def overview_panel():
    """Render cache immediately; the shared worker refreshes sources outside Streamlit."""
    from .system_status import build_status
    from . import system_status_page as system
    from .operational_sources_page import configured_key
    network,boundary,bundled = assets()
    now,store = utc_now(),database()
    completed = _last_completed(now)
    chosen = st.session_state.get(system.REQUESTED_DAY)
    info = acquisition.journal(store)
    connections = info.get("connections",{})
    api_key = configured_key()
    map_slot = st.container()
    refresh = _source_controls(connections,gie=bool(api_key),overview=True)
    archive = st.session_state.get(ARCHIVE_KEY,False)
    anchor = min(chosen or (max(s.last for s in bundled) if archive else completed),completed)
    job = None
    if not archive:
        requested = (dict(first=anchor,last=anchor) if chosen else
                     dict(first=completed-timedelta(days=6),last=completed) if refresh else {})
        job = acquisition.schedule(store,network,now,api_key=api_key,force=refresh,**requested)
    watch(store,job,connections)
    if archive:
        st.caption("Snapshot storico incluso · acquisizioni statiche.")
    context = _window_context(network,bundled,st.session_state,now,store,anchor-timedelta(days=34),anchor,archive)
    data = {} if archive else dict(st.session_state,operational_acquisition=info)
    snapshots = context["snapshots"]
    policy = system.policy()
    state = _status_state(context,data,now,chosen)
    status = build_status(network,snapshots,state,now,gas_day=chosen,
                          interruptions=context["interruptions"],policy=policy)
    if chosen is None and not archive:
        state = _status_state(context,data,now,status.gas_day)
        status = build_status(network,snapshots,state,now,gas_day=status.gas_day,
                              interruptions=context["interruptions"],policy=policy)
    saved = state.get(STATE,{})
    observations = validated_observations(network,merge_observations(snapshots),now)
    day = status.gas_day
    first = day-timedelta(days=6)
    identifier = st.session_state.get(SELECTED,st.session_state.get("net_infrastructure","INET_BP_65"))
    all_items = {i.id:i for i in network.infrastructure}
    perimeter = network.infrastructure
    direction = st.session_state.get("net_overview_direction")
    with map_slot, st.container(key="network_overview"):
        system.header(status,include_metrics=False)
        reading = _mode_selector("overview")
        event_ids = {e["infrastructure_id"] for e in status.active_events}
        finding_ids = {f.infrastructure_id for f in status.attention if f.category not in ("quality","event") and f.infrastructure_id}
        visible,identifier,directions,direction,intelligence = _reconcile_map(network,perimeter,observations,
            snapshots,day,now,saved,identifier,direction,policy,reading,event_ids,finding_ids,"overview")
        st.session_state["net_overview_direction"] = direction
        choices = _selectable_items(visible,reading)
        map_col, detail = st.columns([1.25,1],gap="medium")
        with map_col:
            render_map(network,boundary,visible,identifier,mode="overview",observations=observations,day=day,direction=direction,
                reading_mode=reading,intelligence=intelligence,events=event_ids if reading == "ATTENTION" else (),findings=finding_ids)
            render_legend((c for c in CATEGORIES if any(i.category == c for i in visible)),reading)
            st.caption("SciGRID 2021 · collegamenti storici schematici · CC BY 4.0 · Natural Earth, pubblico dominio")
        with detail.container(key="network_home_detail"):
            if len(directions)>1:
                direction = st.radio("Direzione da consultare",directions,key="net_overview_direction",horizontal=True,
                    format_func=arrow_text)
            if identifier:
                _detail(network,all_items[identifier],observations,snapshots,direction,status.active_events,first,day,saved,
                        mode="overview",info=intelligence.get(identifier),attention=status.attention,
                        displayed=visible,reading=reading)
            else:
                _empty_selection(reading)
            with st.popover("Cerca infrastruttura",width="stretch"):
                st.session_state["net_overview_infrastructure"] = identifier
                st.selectbox("Infrastruttura",[i.id for i in sorted(choices,key=lambda i:i.name)],
                    key="net_overview_infrastructure",format_func=lambda key:_infrastructure_label(all_items[key]),
                    disabled=not choices,on_change=_widget_selection,args=("net_overview_infrastructure",))
    st.button("Esplora la rete",icon=":material/arrow_forward:",key="net_overview_open",
              width="stretch",on_click=_open_full,args=(identifier,first,day,direction))
    system.metrics(status)
    system.attention(status,network,_open_full,compact=True)
    system.balance(status,compact=True)


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
    first_valid = next(day for day,value in zip(days,values) if value is not None)
    figure.update_xaxes(range=[first_valid-timedelta(days=1),last+timedelta(days=1)])
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


def _point_provenance(network, item, observations, snapshots, binding, first, last):
    st.caption("DATI E PROVENIENZA")
    geo = next(g for g in network.geography if g.infrastructure_id == item.id)
    if binding:
        rows = [o for o in observations if o.point_direction == binding.point_direction
                and o.period_from < _start(last+timedelta(days=1)) and o.period_to > _start(first)]
        if rows:
            with st.expander("Valori e qualità"):
                latest = [max((o for o in rows if o.indicator == indicator), key=lambda o:(o.period_to,o.period_from))
                          for indicator in INDICATORS if any(o.indicator == indicator for o in rows)]
                st.dataframe([{"Misura":LABELS[o.indicator],"Valore":numero(o.value,2),"Unità":o.unit,
                    "Direzione":binding.direction,"Unità fonte":o.source_unit,"ID fonte":o.source_id,
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
                st.caption(binding.source+" · "+binding.dataset_version+" · "+binding.license)
    with st.expander("Identità e geografia",expanded=item.category not in ("entry","lng")):
        st.caption(item.status)
        st.caption(geo.geometry_accuracy)
        st.write("Fonte: "+geo.source)
        st.caption(f"Edizione {geo.dataset_version} · {geo.observed_at} · acquisita {geo.retrieved_at}")
        st.caption("ID geografico: "+item.source_id)
        for b in network.bindings_for(item.id):
            st.caption(f"{b.provider}: {b.external_id} · operatore {b.operator_id} · mapping {b.mapping_confidence}")
        details = {"diameter_mm":"Diametro storico · mm", "max_pressure_bar":"Pressione massima storica · bar",
                   "length_km":"Lunghezza originale storica · km"}
        for name,label in details.items():
            if item.metadata.get(name) is not None:
                st.caption(label+": "+numero(item.metadata[name],1))
        if item.metadata.get("length_note"):
            st.caption(item.metadata["length_note"])
        st.caption(geo.license)
        st.link_button("Fonte geografica", geo.source_url)


def _point_events(item, info, events, attention):
    st.caption("EVENTI")
    matching = [e for e in events if e["infrastructure_id"] == item.id]
    for event in matching:
        st.markdown("**Evento pubblicato · "+escape(event["kind"])+"**")
        st.caption(f"{local_time(event['period_from'])} → {local_time(event['period_to'])}")
        if event["value"] is not None:
            st.caption(numero(event["value"],2)+" "+event["unit"]+" · "+event.get("capacity_type",""))
        elif event.get("impact_label"):
            st.caption(event["impact_label"])
        st.caption(event["source"]+" · "+event["status"]+" · "+event["source_id"])
        st.caption("Pubblicato "+local_time(event.get("observed_at"))+" · acquisito "+local_time(event["retrieved_at"]))
        st.link_button("Fonte avviso",event["source_url"])
    findings = [f for f in attention if f.infrastructure_id == item.id and f.category != "event"]
    for finding in findings:
        st.markdown("**Indicatore I.G.O.R. · "+finding.description+"**")
        if finding.observed_value is not None:
            st.caption(numero(finding.observed_value,1)+" "+finding.unit+
                (" · soglia "+numero(finding.threshold,1) if finding.threshold is not None else ""))
        explanations = {
            "historical_median_deviation": "Il flusso fisico si discosta dalla mediana storica oltre la soglia configurata. Lo scarto è assoluto: non indica da solo un aumento o una riduzione.",
            "capacity_utilization": "Il rapporto tra flusso fisico e capacità tecnica pubblicata supera la soglia configurata.",
            "missing_expected_flow": "La copia consultata non contiene il flusso atteso. Non equivale a flusso nullo o indisponibilità fisica.",
            "stale_critical_source": "La copia disponibile non è recente o l’aggiornamento non è riuscito.",
        }
        if finding.rule in explanations:
            st.write(explanations[finding.rule])
        if finding.baseline is not None and finding.baseline_n:
            st.caption(f"Mediana storica: {numero(finding.baseline,1)} GWh/d · {finding.baseline_n} giorni validi")
        source = finding.source_id.split(":",1)[0]
        direction_label = {"entry":"Ingresso","exit":"Uscita"}.get(finding.direction)
        st.caption(" · ".join(filter(None, (source, direction_label,
            "Indicatore calcolato, non avviso del gestore"))))
        ids = tuple(dict.fromkeys(finding.evidence_ids))
        st.caption(f"Evidenze: {len(ids)} riferimenti" if ids else "Evidenze: dato atteso assente")
        with st.expander("Evidenze tecniche e metodologia"):
            st.text("Regola: " + finding.rule)
            st.text("Fonte: " + finding.source_id)
            if finding.observed_at:
                st.caption("Pubblicazione delle evidenze: " + local_time(finding.observed_at))
            if finding.retrieved_at:
                st.caption("Acquisizione delle evidenze: " + local_time(finding.retrieved_at))
            if ids:
                st.dataframe(pd.DataFrame({"ID osservazione": ids}), hide_index=True,
                             width="stretch", height=min(280, 38 + 35*len(ids)))
            else:
                st.caption("Nessun identificativo di osservazione disponibile.")
    if info.get("capacity_change_gwh_d") is not None:
        st.markdown("**Indicatore I.G.O.R. · capacità tecnica ridotta rispetto a D-1**")
        st.caption(numero(info["capacity_change_gwh_d"],1)+" GWh/d · confronto di capacità pubblicate su giorni compatibili")
    if not matching:
        st.caption("Nessun evento associato nella copia disponibile · copertura parziale, non certifica assenza di interruzioni.")
    if info.get("stale"):
        st.caption("Qualità dati · cache da aggiornare. Non indica un’indisponibilità fisica.")
    if info.get("binding") and not info.get("flow_available"):
        st.caption("Qualità dati · flusso fisico non disponibile per il giorno e la direzione selezionati. Non equivale a flusso nullo.")


NODE_CATALOG_KEY = "net_node_discovery_catalog"


def _node_report(network, saved):
    catalog = (None if st.session_state.get(ARCHIVE_KEY,False) else
               st.session_state.get(NODE_CATALOG_KEY) or saved.get("catalog"))
    return audit_nodes(network,catalog or network.sources["opd"])


def _node_detail(network,item,saved,events,attention):
    report = _node_report(network,saved)
    node = next(n for n in report["nodes"] if n["id"]==item.id)
    st.caption("Nodo geografico storico · nessuna serie operativa associata")
    if node["state"]=="already_mapped":
        st.caption("Punti ENTSOG omonimi già associati ad altre infrastrutture. Nessuna duplicazione dei flussi.")
    elif node["state"]=="review_required":
        st.caption("Possibile corrispondenza anagrafica da verificare; non costituisce un'associazione operativa.")
    else:
        st.caption("Nessuna corrispondenza nominale esatta nel catalogo ENTSOG esaminato.")
    if node["candidates"]:
        with st.expander("Corrispondenze ENTSOG da consultare"):
            st.dataframe([{"Punto":c["label"],"Direzione":"Ingresso" if c["direction"]=="entry" else "Uscita",
                "Dati censiti":"Sì" if c["has_data"] else "No",
                "Associazione":c["mapped_name"] or "Da verificare"} for c in node["candidates"]],hide_index=True,width="stretch")
    st.caption(f"Catalogo: {report['catalog_rows']} righe · {len(report['operators'])} operatori censiti · "
               +str(report["catalog_date"] or "data non disponibile")[:10]
               +(" · aggiornamento non riuscito" if report["failed"] else ""))
    st.caption("La verifica non dimostra l'assenza di dati presso altri operatori o portali riservati.")
    relevant = [e for e in events if e.get("infrastructure_id")==item.id]
    signals = [f for f in attention if f.infrastructure_id==item.id]
    if relevant or signals:
        with st.expander("Eventi e segnalazioni associati"):
            _point_events(item,{},relevant,signals)
    _point_provenance(network,item,(),(),None,None,None)


def _node_catalog_audit(network,saved,store,archive):
    with st.expander("Copertura API dei nodi"):
        st.caption("Verifica nominale del catalogo ENTSOG Snam Rete Gas (IT-TSO-0001). "
                   "Non è una verifica nazionale né una prova di identità fisica. "
                   "Nessuna associazione o misura viene importata automaticamente.")
        if st.button("Verifica catalogo ENTSOG",key="net_node_catalog_refresh",disabled=archive):
            try:
                st.session_state[NODE_CATALOG_KEY] = load_catalog(store,refresh=True)
                st.session_state.pop("net_node_catalog_error",None)
            except (SourceUnavailable,SourceSchemaError,ValueError,OSError):
                st.session_state["net_node_catalog_error"] = True
        if not archive and st.session_state.get("net_node_catalog_error"):
            st.warning("Catalogo non aggiornato: verifica basata sull'ultima copia disponibile.")
        report = _node_report(network,saved)
        if report["failed"]:
            st.warning("Aggiornamento non riuscito · ultima copia valida.")
        st.caption(f"{report['catalog_rows']} righe · {len(report['operators'])} operatori · "
                   f"{report['conflicts']} chiavi in conflitto escluse · "
                   +str(report["catalog_date"] or "data non disponibile")[:10])
        labels={"verified":"Associato","review_required":"Da revisionare","already_mapped":"Punto già associato altrove",
                "no_exact_match":"Nessuna corrispondenza esatta"}
        counts={key:sum(n["state"]==key for n in report["nodes"]) for key in labels}
        st.caption(" · ".join(f"{label}: {counts[key]}" for key,label in labels.items()))
        candidates=[{"Nodo":n["name"],"Esito":labels[n["state"]],"Punto ENTSOG":c["label"],
            "Operatore":c["operator"],"Direzione":c["direction"],"Associazione esistente":c["mapped_name"]}
            for n in report["nodes"] for c in n["candidates"]]
        if candidates:
            st.dataframe(candidates,hide_index=True,width="stretch")
        st.download_button("Esporta verifica di tutti i nodi",json.dumps(report,ensure_ascii=False,indent=2,default=str),
            "igor-node-discovery.json","application/json",key="net_node_catalog_export")


def _detail(network, item, observations, snapshots, direction, events, first, last, saved, *, mode="full", info=None, attention=(), displayed=None, reading="SYSTEM"):
    if mode!="overview":st.caption("IDENTITÀ")
    st.subheader(display_name(item.name))
    st.caption(" · ".join(filter(None,[CATEGORIES[item.category],item.operator,*item.regions])))
    from .italian_network_map import direction_label
    structural = direction_label(verified_bindings(network,item.id))
    if structural:
        st.html(direction_header(structural,direction))
        st.caption("Direzioni censite ENTSOG rispetto alla rete italiana")
    if displayed is not None:
        _attention_context(item.id,displayed,reading)
        _nearby_selector(network,item,displayed,mode)
    info = info if info is not None else point_intelligence(network,item.id,observations,last,utc_now(),
        direction=direction,snapshots=snapshots,failures=saved.get("failures",()))
    binding = info.get("binding")
    if item.category=="node" and not binding and not network.bindings_for(item.id):
        _node_detail(network,item,saved,events,attention)
        return
    # Tracked tabs permit native map callbacks to select the relevant view.
    # Older Streamlit versions do not support stateful tabs.
    tab_key = _detail_tab_key(mode)
    active = st.session_state.get(tab_key, "Dati")
    active = active if active in DETAIL_TABS else "Dati"
    if "on_change" in signature(st.tabs).parameters:
        st.session_state.setdefault(tab_key, active)
        data_tab, history_tab, events_tab, sources_tab = st.tabs(
            list(DETAIL_TABS), key=tab_key, on_change="rerun")
    else:
        labels = list(DETAIL_TABS)
        if "default" in signature(st.tabs).parameters:
            tabs = st.tabs(labels, default=active)
        else:
            labels.remove(active)
            labels.insert(0, active)
            tabs = st.tabs(labels)
        data_tab, history_tab, events_tab, sources_tab = (
            dict(zip(labels, tabs))[label] for label in DETAIL_TABS
        )
    with data_tab:
        with st.container(key="network_home_point_data" if mode == "overview" else "network_point_data"):
            paired = None
            if structural=="Bidirezionale":
                validated = validated_observations(network, (o for o in observations if o.infrastructure_id==item.id), utc_now())
                paired = {b.direction:applicable(validated,b.point_direction,last,"Physical Flow")
                          for b in verified_bindings(network,item.id)}
                if binding:
                    paired[binding.direction] = info.get("values",{}).get("Physical Flow")
            _operational_summary(network,item,info,compact=mode=="overview",paired=paired)
            _gie_detail(saved,item.id,network,first,last,mode=mode)
            from .italian_network import security_entries
            if any(b.infrastructure_id==item.id for b in security_entries(network)):
                st.button("Stress Test su questo ingresso",key="net_stress_"+mode,
                    on_click=_open_stress,args=(item.id,last),width="stretch")
    with history_tab:
        st.caption("TREND · D-30")
        if binding:
            _history(info["records"],binding.point_direction,last-timedelta(days=29),last,mode=mode)
            st.caption("Solo osservazioni già disponibili · giorni mancanti conservati, nessuna stima.")
        else:
            st.caption("Serie ENTSOG non associata. Eventuali dati GIE del singolo impianto sono nella scheda Dati.")
    with events_tab:
        _point_events(item,info,events,attention)
    with sources_tab:
        from .gas_data_page import open_explorer
        can_explore = any(o.value is not None or o.quality_status == "conflict" for o in info.get("records",()))
        for b in network.bindings_for(item.id):
            if b.provider not in ("AGSI+","ALSI") or b.mapping_confidence != "confirmed":
                continue
            result = saved.get("facilities",{}).get((b.provider,b.external_id),{})
            frame = result.get("frame",pd.DataFrame())
            field = "stock_twh" if b.provider == "AGSI+" else "sendout_gwh_d"
            can_explore |= field in frame and frame[field].notna().any()
        st.button("Esplora questi dati",key="net_data_explorer_"+mode,on_click=open_explorer,
                  args=(item.id,direction,first,last),kwargs={"navigate":mode=="overview"},
                  disabled=not can_explore,help="Disponibile per punti con osservazioni consultabili.")
        if binding:
            _source_status(info["status"],last)
        _point_provenance(network,item,observations,snapshots,binding,last-timedelta(days=29),last)
        if info.get("comparison_observations"):
            with st.expander("Confronti D-1 · evidenze"):
                st.dataframe([{"Misura":LABELS[o.indicator],"Valore":numero(o.value,2),"Unità":o.unit,
                    "Direzione":binding.direction,"Da":o.period_from.isoformat(),"A":o.period_to.isoformat(),
                    "Pubblicato":o.observed_at or "Non disponibile","Acquisito":local_time(o.retrieved_at),"ID fonte":o.source_id}
                    for o in info["observations"] if o.indicator in {r.indicator for r in info["comparison_observations"]}],
                    hide_index=True,width="stretch")


def panel(mode="full"):
    if mode == "overview":
        try:
            return overview_panel()
        except (OSError,ValueError,KeyError):
            st.info("Mappa temporaneamente non disponibile. Le analisi restano accessibili qui sotto.")
            return
    if mode != "full":
        raise ValueError("Modalità cartografica non riconosciuta")
    from .system_status import build_status
    from .system_status_page import policy as status_policy
    network, boundary, bundled = assets()
    _initialize_layers()
    focus = st.session_state.pop(FOCUS,None)
    if focus:
        st.session_state["net_period"] = focus["period"]
    if focus and focus["id"] in {i.id for i in network.infrastructure}:
        st.session_state["net_pending_selection"] = focus["id"]
        item = next(i for i in network.infrastructure if i.id == focus["id"])
        if focus.get("direction") in {b.direction for b in network.bindings_for(item.id,"ENTSOG")}:
            st.session_state["net_direction"] = focus["direction"]
        st.session_state["net_layers"] = sorted(set(st.session_state.get("net_layers",list(CATEGORIES)))|{item.category})
        for key in ("net_operators","net_regions","net_statuses","net_only_events"):
            st.session_state.pop(key,None)
    from .operational_sources_page import configured_key
    now,store = utc_now(),database()
    completed = _last_completed(now)
    info = acquisition.journal(store)
    connections = info.get("connections",{})
    api_key = configured_key()
    archive = st.session_state.get(ARCHIVE_KEY,False)
    default_last = min(max(s.last for s in bundled),completed) if archive else completed
    meta, period_col, actions = st.columns([3,2,2], vertical_alignment="bottom")
    with meta:
        st.caption("Italia · snapshot storico incluso" if archive else "Italia · dati pubblici e cache operativa")
        data_status = st.empty()
        _source_controls(connections,gie=bool(api_key))
    period = period_col.date_input("Periodo · giorni gas", value=(default_last-timedelta(days=6),default_last),
        min_value=date(2000,1,1), max_value=completed, key="net_period", format="DD/MM/YYYY")
    with actions:
        refresh_col, reset_col = st.columns(2)
        refresh_clicked = refresh_col.button("Aggiorna", icon=":material/refresh:", key="net_refresh", width="stretch",
            disabled=archive,help="Aggiorna tutti i punti e le direzioni verificati per il periodo selezionato.")
        reset_col.button("Reset filtri", on_click=reset_filters, key="net_reset", width="stretch")
    reading = _mode_selector("full")
    layer_col, event_col, filter_col = st.columns([5,1,1], vertical_alignment="bottom")
    layer_col.multiselect("Livelli", list(CATEGORIES), default=list(CATEGORIES),
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
    job = None
    if not archive and not refresh_clicked:
        requested = dict(first=first,last=last) if last<completed else {}
        job = acquisition.schedule(store,network,now,api_key=api_key,**requested)
    policy = status_policy()
    context = _window_context(network,bundled,st.session_state,now,store,min(first,last-timedelta(days=policy.baseline_days)),last,archive)
    snapshots = context["snapshots"]
    observations = validated_observations(network,merge_observations(snapshots),now)
    data = {} if archive else dict(st.session_state,operational_acquisition=info)
    state = _status_state(context,data,now,last)
    saved = state.get(STATE,{})
    iip_result = state.get("gie_iip", {}).get("result")
    iip, unresolved = iip_events(network, iip_result, first, last)
    interruption_sets = context["interruptions"]
    events, withheld = verified_events(network,(*iip, *(e for s in interruption_sets for e in s["records"])),first,last,now)
    unresolved += withheld
    event_ids = {e["infrastructure_id"] for e in events}
    visible = filter_infrastructure(network, st.session_state.net_layers,
        operators=[None if v == "Non indicato" else v for v in st.session_state.get("net_operators",[])],
        regions=st.session_state.get("net_regions",[]), statuses=st.session_state.get("net_statuses",[]),
        event_ids=event_ids if show_events and st.session_state.get("net_only_events") else None)
    lookup = {i.id:i for i in visible}
    visible_events = [e for e in events if e["infrastructure_id"] in lookup]
    pending = st.session_state.pop("net_pending_selection", st.session_state.get(SELECTED,st.session_state.get("net_infrastructure")))
    operational = build_status(network,snapshots,state,now,gas_day=last,
                               interruptions=interruption_sets,policy=policy)
    active_event_ids = {e["infrastructure_id"] for e in operational.active_events}
    finding_ids = {f.infrastructure_id for f in operational.attention if f.category not in ("quality","event") and f.infrastructure_id}
    displayed,identifier,directions,direction,intelligence = _reconcile_map(network,visible,observations,
        snapshots,last,now,saved,pending,st.session_state.get("net_direction"),policy,reading,active_event_ids,finding_ids,"full")
    options = [i.id for i in sorted(_selectable_items(displayed,reading),key=lambda i:(i.category!="entry",i.name))]
    st.session_state["net_infrastructure"] = identifier
    st.session_state["net_direction"] = direction
    summary = st.container(key="network_summary")
    with st.container(key="network_explorer"):
        map_col, detail = st.columns([1,1], gap="small")
    detail_content = detail.container(key="network_detail", border=True)
    with detail_content:
        identifier = st.selectbox("Infrastruttura", options, format_func=lambda k:_infrastructure_label(lookup[k]), key="net_infrastructure",
                                 placeholder="Nessuna infrastruttura nei filtri", disabled=not options,
                                 on_change=_widget_selection,args=("net_infrastructure",))
        if len(directions)>1:
            direction = st.selectbox("Direzione da consultare", directions, key="net_direction",
                format_func=arrow_text)
    if refresh_clicked and not archive:
        detail = (identifier,direction,first,last) if identifier else None
        job = acquisition.schedule(store,network,now,api_key=api_key,first=first,last=last,force=True,detail=detail)
    watch(store,job,connections,on_done=_publish_details)
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
        render_map(network,boundary,displayed,identifier,mode="full",observations=observations,day=last,
                   direction=direction,events=active_event_ids if reading == "ATTENTION" else event_ids if show_events else (),
                   show_labels=show_labels,reading_mode=reading,intelligence=intelligence,findings=finding_ids)
        render_legend((c for c in CATEGORIES if any(i.category == c for i in displayed)),reading,event_overlay=show_events)
        st.caption(f"{len(displayed)} elementi in questa lettura · {len(visible)} nel perimetro dei filtri. I gasdotti restano contesto geografico.")
        st.caption("Collegamenti schematici SciGRID 2021: non tracciati certificati né flussi sui gasdotti. Posizioni storiche indicative, salvo fonte del gestore.")
        st.caption("© SciGRID_gas / DLR-VE · CC BY 4.0 · INET_Raw 1.4 · confini Natural Earth, pubblico dominio")
        if not options:
            st.info("Nessuna infrastruttura nei filtri. Modifica i livelli o usa Reset filtri.")
        if "production" in st.session_state.net_layers:
            st.caption("Produzione: nessuna localizzazione verificata inclusa. I dati MASE restano nella vista Produzione.")
    with detail_content:
        if identifier:
            _detail(network,lookup[identifier],observations,snapshots,direction,operational.active_events,first,last,saved,
                    info=intelligence.get(identifier),attention=operational.attention,
                    displayed=displayed,reading=reading)
        else:
            _empty_selection(reading)
    _node_catalog_audit(network,saved,store,archive)
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
    national = state.get("AGSI+_IT", {}).get("result")
    if national and not national["frame"].empty:
        latest = national["frame"].iloc[-1]
        st.caption(f"Contesto nazionale GIE AGSI+ · {data_it(latest.gas_day)} · {numero(latest.stock_twh,2)} TWh · {numero(latest.fill_pct,1)}% · indipendente dai filtri geografici")
        failed = national["failed"] or state.get("AGSI+_IT",{}).get("error")
        st.caption("Acquisito "+local_time(national["acquired"])+(" · ultima cache, aggiornamento non riuscito" if failed else ""))
