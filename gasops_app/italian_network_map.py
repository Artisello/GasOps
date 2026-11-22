"""Small, offline deck.gl scene. No tiles, geocoder, token or network requests."""
from html import escape
import pydeck as pdk

from .italian_network import CATEGORIES, COLORS, applicable
from .italiano import numero, data_it

RADII = {"entry":6, "lng":6, "storage":4.5, "compressor":4, "production":4, "power":3.5, "node":2.5}


def display_name(name):
    return name.replace("_", " – ")


def deck(network, boundary, visible, selected=None, event_ids=(), *, observations=(), day=None, direction="entry", show_labels=True):
    lookup = {g.infrastructure_id:g for g in network.geography}
    lines, points, highlight, labels, events = [], [], [], [], []
    for item in visible:
        geometry = lookup[item.id].geometry
        tooltip = {"infra_id":item.id, "safe_name":escape(display_name(item.name)),
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
               "radius":RADII[item.category],
               "border":[245,250,255] if item.id == selected else [26,42,58]}
        points.append(row)
        if item.id == selected or show_labels and item.category in ("entry", "lng"):
            labels.append({**row, "label":display_name(item.name.split(" · ")[0].replace("FSRU ", "")),
                           "offset":[10,-10] if item.id == selected else [10,9]})
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
        selected_points = [r for r in points if r["infra_id"] == selected]
        if selected_points:
            layers.append(pdk.Layer("ScatterplotLayer", selected_points, id="selected-point", pickable=False,
                get_position="position", get_radius=10, radius_units=pdk.types.String("pixels"),
                radius_min_pixels=10, radius_max_pixels=10, filled=False, stroked=True,
                get_line_color=[245,250,255,210], get_line_width=1.5,
                line_width_units=pdk.types.String("pixels"), line_width_max_pixels=1.5))
        layers.append(pdk.Layer("ScatterplotLayer", points, id="infrastructure-points", pickable=True,
            auto_highlight=True, get_position="position", get_fill_color="color", get_radius="radius",
            radius_units=pdk.types.String("pixels"), radius_min_pixels=2.5, radius_max_pixels=7,
            stroked=True, get_line_color="border", get_line_width=1,
            line_width_units=pdk.types.String("pixels"), line_width_min_pixels=1, line_width_max_pixels=1.5))
    if events:
        layers.append(pdk.Layer("ScatterplotLayer", events, id="event-rings", pickable=True,
            get_position="position", get_radius=13, radius_units=pdk.types.String("pixels"),
            radius_min_pixels=13, radius_max_pixels=13, filled=False,
            stroked=True, get_line_color=[246,146,157], get_line_width=2,
            line_width_units=pdk.types.String("pixels"), line_width_max_pixels=2))
    if labels:
        layers.append(pdk.Layer("TextLayer", labels, id="point-labels", pickable=False,
            get_position="position", get_text="label", get_color=[224,235,245],
            get_size=11, size_units=pdk.types.String("pixels"), size_min_pixels=11, size_max_pixels=11,
            get_pixel_offset="offset", get_text_anchor="'start'", font_family=pdk.types.String("Arial, sans-serif"),
            background=True, get_background_color=[13,24,36,225], background_padding=[4,2]))
    return pdk.Deck(layers=layers, initial_view_state=pdk.ViewState(latitude=41.9, longitude=12.5,
        zoom=4.75, min_zoom=4, max_zoom=12, pitch=0), map_provider=None, map_style=None,
        tooltip={"html":"<b>{safe_name}</b><br/>{safe_type}<br/>{safe_status}<br/>{safe_value}",
                 "style":{"backgroundColor":"#142231", "color":"#eef5fc", "fontSize":"12px"}})
