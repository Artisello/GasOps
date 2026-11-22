"""Italian network explorer, usable offline before any optional API refresh."""
from dataclasses import asdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from html import escape
import json

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from .data import ROME
from .entsog import _last_completed, _start
from .entsog_network import INDICATORS
from .italiano import numero, data_it
from .italian_network import (ASSETS, CATEGORIES, COLORS, applicable, filter_infrastructure,
                              load_network_assets, map_kpis, merge_observations, selected_id)
from .italian_network_events import iip_events, relevant_events, parse_interruptions
from .italian_network_map import deck, display_name
from .italian_network_refresh import STATE, refresh_network
from .italian_network_sources import decode_snapshot
from .models import utc_now
from .session import database
from .visuals import local_time, plot, kpi_grid

LABELS = dict(zip(INDICATORS, ("Flusso fisico", "Nomina", "Rinomina", "Allocazione",
                              "Capacità tecnica", "Capacità prenotata", "Capacità disponibile")))
FILTER_KEYS = ("net_layers", "net_operators", "net_regions", "net_statuses", "net_period",
               "net_events", "net_only_events", "net_labels", "net_infrastructure", "net_direction", "net_indicator")


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
    st.session_state["net_map_epoch"] = st.session_state.get("net_map_epoch", 0)+1


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


def _history(observations, point, first, last):
    available = [name for name in INDICATORS if any(o.point_direction == point and o.indicator == name for o in observations)]
    if not available:
        return
    if st.session_state.get("net_indicator") not in available:
        st.session_state["net_indicator"] = available[0]
    indicator = st.selectbox("Storico", available, format_func=LABELS.__getitem__, key="net_indicator")
    days, values = _daily(observations, point, first, last, indicator)
    usable = [v for v in values if v is not None]
    if not usable:
        st.caption("Nessun valore confrontabile sull’intero giorno gas nel periodo.")
        return
    figure = go.Figure(go.Scatter(x=days, y=[float(v) if v is not None else None for v in values],
        mode="lines+markers", connectgaps=False, line={"color":"#65dfbf", "width":2.5},
        marker={"size":5}, hovertemplate="%{x|%d/%m/%Y}<br>%{y:.2f} GWh/d<extra></extra>"))
    figure.update_layout(height=220, margin={"l":0,"r":0,"t":8,"b":10},
                         yaxis_title="GWh/d", showlegend=False)
    plot(figure, key="net_entsog_history")
    st.caption(f"{len(usable)}/{len(days)} giorni gas · 06:00–06:00 Europe/Rome")
    if len(usable) >= 2:
        st.caption(f"Min {numero(min(usable),1)} · Max {numero(max(usable),1)} · Media {numero(sum(usable)/len(usable),1)} GWh/d")
        length = len(days)
        _, prior = _daily(observations, point, first-timedelta(days=length), first-timedelta(days=1), indicator)
        if len(usable) == length and all(v is not None for v in prior):
            delta = sum(usable)/length-sum(prior)/length
            st.caption(f"Media vs {length} giorni precedenti: {numero(delta,1)} GWh/d · periodi completi")


def _gie_detail(saved, identifier, network, first, last):
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
            series = st.selectbox("Storico GIE", numeric, format_func=lambda c:labels[c][0], key="net_gie_series_"+binding.provider)
            fig=go.Figure(go.Scatter(x=frame.gas_day, y=frame[series], mode="lines+markers", connectgaps=False))
            fig.update_layout(height=190,margin={"l":0,"r":0,"t":5,"b":5},yaxis_title=labels[series][1])
            plot(fig, key="net_gie_history_"+binding.provider)
        st.caption(f"Fonte: {result['source']} · stato {latest.status}")
        st.link_button("Apri fonte GIE", result["source_url"])


def _detail(network, item, observations, snapshots, direction, events, first, last, saved):
    geo = next(g for g in network.geography if g.infrastructure_id == item.id)
    st.subheader(display_name(item.name))
    st.caption(" · ".join([CATEGORIES[item.category], *item.regions]))
    if item.operator:
        st.write(item.operator)
    st.caption(item.status)
    bindings = network.bindings_for(item.id, "ENTSOG")
    binding = next((b for b in bindings if b.direction == direction), None)
    if binding:
        st.caption(f"ENTSOG {binding.external_id} · {'Ingresso' if direction == 'entry' else 'Uscita'}")
        rows = [o for o in observations if o.point_direction == binding.point_direction
                and o.period_from < _start(last+timedelta(days=1)) and o.period_to > _start(first)]
        days, values = _daily(rows, binding.point_direction, first, last, "Physical Flow")
        published = [(d,v) for d,v in zip(days,values) if v is not None]
        if published:
            day, flow = published[-1]
            st.metric("Ultimo flusso pubblicato", numero(flow,1)+" GWh/d")
            st.caption("Giorno gas "+data_it(day))
            capacity = applicable(rows, binding.point_direction, day, "Firm Technical")
            if capacity is not None and capacity > 0 and flow >= 0:
                st.caption(f"Utilizzo capacità tecnica: {numero(100*flow/capacity,1)}% · intervalli confrontabili")
        if rows:
            _history(observations, binding.point_direction, first, last)
            with st.expander("Valori e qualità"):
                latest = [max((o for o in rows if o.indicator == indicator), key=lambda o:(o.period_to,o.period_from))
                          for indicator in INDICATORS if any(o.indicator == indicator for o in rows)]
                st.dataframe([{"Misura":LABELS[o.indicator],"GWh/d":numero(o.value,2),
                    "Da":o.source_period_from or o.period_from.isoformat(),"A":o.source_period_to or o.period_to.isoformat(),
                    "Qualità":o.quality_status,"Stato fonte":o.publication_status,"Versioni":len(o.revisions)} for o in latest],
                    hide_index=True, width="stretch")
                st.caption("Intervalli originali. N/A e conflitti esclusi dai calcoli; le capacità devono coprire lo stesso giorno gas.")
                st.caption("Acquisizione più recente: "+local_time(max(o.retrieved_at for o in rows)))
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


def panel():
    network, boundary, bundled = assets()
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
        min_value=min(s.first for s in bundled), max_value=_last_completed(now), key="net_period", format="DD/MM/YYYY")
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
    pending = st.session_state.pop("net_pending_selection", None)
    if pending in options:
        st.session_state["net_infrastructure"] = pending
    if st.session_state.get("net_infrastructure") not in options:
        st.session_state["net_infrastructure"] = "INET_BP_65" if "INET_BP_65" in options else options[0] if options else None
    summary = st.container(key="network_summary")
    map_col, detail = st.columns([3.5,1.2], gap="medium")
    detail_content = detail.container(key="network_detail", border=True)
    with detail_content:
        identifier = st.selectbox("Infrastruttura", options, format_func=lambda k:display_name(lookup[k].name), key="net_infrastructure",
                                 placeholder="Nessuna infrastruttura nei filtri", disabled=not options)
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
    in_period = [o for o in observations if o.infrastructure_id in lookup and o.gas_day
                 and first <= o.gas_day <= last and o.value is not None]
    if in_period:
        data_status.caption(f"ENTSOG · acquisito {local_time(max(o.retrieved_at for o in in_period))} · copertura parziale")
    else:
        data_status.caption("Nessun dato operativo per questi filtri e questo periodo.")
    with summary:
        items = [("Infrastrutture",metrics["mapped"],"", "Nei livelli selezionati",0)]
        if metrics["mapped_points"]:
            items.append(("Punti con dati",metrics["valid_points"],"",f"Su {metrics['mapped_points']} punti ENTSOG",0))
        if metrics["mapped_entry_points"]:
            items.extend([("Ingressi di frontiera",metrics["entry_flow_gwh_d"],"GWh/d",f"{metrics['valid_entry_points']}/{metrics['mapped_entry_points']} ingressi coperti",1),
                ("Utilizzo capacità",metrics["utilization_pct"],"%",f"{metrics['comparable_points']} ingressi confrontabili",1)])
        kpi_grid(items)
        if metrics["mapped_points"]:
            st.caption(f"Giorno gas: {data_it(last)} · flussi aggregati dei soli ingressi di frontiera; GNL separato.")
    with map_col:
        chart_key = "italian_network_deck_"+str(st.session_state.get("net_map_epoch",0))
        event = st.pydeck_chart(deck(network,boundary,visible,identifier,event_ids if show_events else (),
            observations=observations,day=last,direction=direction,show_labels=show_labels),
            key=chart_key, height=650, on_select="rerun", selection_mode="single-object")
        pick = selected_id(event, set(options))
        signature = repr(event.get("selection", {}))
        signature_key = chart_key+"_seen"
        if pick and st.session_state.get(signature_key) != signature:
            st.session_state[signature_key] = signature
            if pick != identifier:
                st.session_state["net_pending_selection"] = pick
                st.rerun()
        legend = " · ".join(f'<span style="color:rgb({",".join(map(str,COLORS[c]))})">●</span> {escape(CATEGORIES[c])}'
                             for c in st.session_state.net_layers if metrics["categories"][c])
        st.html('<div style="font-size:12px;color:#b0bed0">'+legend+'</div>')
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
        st.dataframe([{"Livello":CATEGORIES[c],"Mappate":metrics["categories"][c]} for c in CATEGORIES],hide_index=True)
        relevant = [s for s in snapshots if s.first <= last and s.last >= first
                    and any(o.infrastructure_id in lookup for o in s.records)]
        if relevant:
            st.caption("Dati operativi: ENTSOG TP Transport Data · acquisizione più recente "+local_time(max(s.acquired for s in relevant)))
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
