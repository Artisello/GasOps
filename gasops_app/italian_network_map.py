"""Small, offline deck.gl scene. No tiles, geocoder, token or network requests."""
from html import escape
import pydeck as pdk

from .italian_network import CATEGORIES, COLORS, applicable
from .italiano import numero, data_it


def deck(network, boundary, visible, selected=None, event_ids=(), *, observations=(), day=None, direction="entry"):
    lookup = {g.infrastructure_id:g for g in network.geography}
    lines, points, highlight, labels, events = [], [], [], [], []
    for item in visible:
        geometry = lookup[item.id].geometry
        tooltip = {"infra_id":item.id, "safe_name":escape(item.name),
                   "safe_type":escape(CATEGORIES[item.category]), "safe_status":escape(item.status), "safe_value":""}
        if day and item.category in ("entry", "lng"):
            points_for_item = network.bindings_for(item.id,"ENTSOG")
            point = next((b for b in points_for_item if b.direction == (direction if item.id == selected else "entry")), None)
            value = applicable(observations,point.point_direction,day,"Physical Flow") if point else None
            if value is not None:
                tooltip["safe_value"] = f"{numero(value,1)} GWh/d · {'ingresso' if point.direction == 'entry' else 'uscita'} · {data_it(day)}"
        if geometry["type"] != "Point":
            feature = {"type":"Feature", "geometry":geometry, **tooltip,
                       "properties":{**tooltip, "color":COLORS[item.category]}}
            lines.append(feature)
            if item.id == selected:
                highlight.append(feature)
            continue
        row = {**tooltip, "position":geometry["coordinates"], "color":COLORS[item.category],
               "radius":9 if item.category in ("entry", "lng") else 5,
               "border":[245,250,255] if item.id == selected else [26,42,58]}
        points.append(row)
        if item.category in ("entry", "lng"):
            labels.append({**row, "label":item.name.split(" · ")[0].replace("FSRU ", "")})
        if item.id in event_ids:
            events.append(row)
    layers = [pdk.Layer("GeoJsonLayer", boundary, id="italy-outline", pickable=False,
        filled=True, stroked=True, get_fill_color=[22,40,55,240], get_line_color=[63,87,106,220],
        line_width_min_pixels=1)]
    if lines:
        layers.append(pdk.Layer("GeoJsonLayer", {"type":"FeatureCollection", "features":lines},
            id="historical-links", pickable=True, auto_highlight=True, filled=False,
            get_line_color="properties.color", line_width_min_pixels=1.4))
    if highlight:
        layers.append(pdk.Layer("GeoJsonLayer", {"type":"FeatureCollection", "features":highlight},
            id="selected-link", pickable=False, filled=False, get_line_color=[255,255,255], line_width_min_pixels=4))
    if points:
        layers.append(pdk.Layer("ScatterplotLayer", points, id="infrastructure-points", pickable=True,
            auto_highlight=True, get_position="position", get_fill_color="color", get_radius="radius",
            radius_units="pixels", stroked=True, get_line_color="border", line_width_min_pixels=1.5))
    if events:
        layers.append(pdk.Layer("ScatterplotLayer", events, id="event-rings", pickable=True,
            get_position="position", get_radius=14, radius_units="pixels", filled=False,
            stroked=True, get_line_color=[246,146,157], line_width_min_pixels=3))
    if labels:
        layers.append(pdk.Layer("TextLayer", labels, id="point-labels", pickable=False,
            get_position="position", get_text="label", get_color=[224,235,245],
            get_size=11, get_pixel_offset=[11,0], get_text_anchor="'start'", background=True,
            get_background_color=[13,24,36,195], background_padding=[3,2]))
    return pdk.Deck(layers=layers, initial_view_state=pdk.ViewState(latitude=41.9, longitude=12.5,
        zoom=4.75, min_zoom=4, max_zoom=12, pitch=0), map_provider=None, map_style=None,
        tooltip={"html":"<b>{safe_name}</b><br/>{safe_type}<br/>{safe_status}<br/>{safe_value}",
                 "style":{"backgroundColor":"#142231", "color":"#eef5fc", "fontSize":"12px"}})
