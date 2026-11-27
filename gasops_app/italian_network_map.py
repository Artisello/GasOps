"""Small, offline deck.gl scene. No tiles, geocoder, token or network requests."""
from html import escape
from importlib.metadata import version
import json
import math
from urllib.parse import quote
import pydeck as pdk

from .italian_network import CATEGORIES, COLORS, applicable, verified_bindings, direction_label
from .italiano import numero, data_it
from .direction_ui import arrow_text, ARROWS

RADII = {"entry":6, "lng":6, "storage":4.5, "compressor":4, "production":4, "power":3.5, "node":2.5}
HIT_RADII = {"entry":14,"lng":14,"storage":11,"compressor":10,"production":10,"power":10,"node":7}
PICK_PRIORITY = {"node":0,"power":1,"production":1,"compressor":2,"storage":3,"entry":4,"lng":4}
LOCAL_STYLE = {"version":8,"sources":{},"layers":[{"id":"sea","type":"background",
               "paint":{"background-color":"#0b1726"}}]}
# A local style URL also works with Streamlit versions that replace map_style=None
# with remote CARTO tiles. A dict style is not supported by its JSON renderer.
LOCAL_STYLE_URL = "data:application/json,"+quote(json.dumps(LOCAL_STYLE,separators=(",",":")))
NATIVE_BASEMAP_OMISSION = tuple(int(v) for v in version("streamlit").split(".")[:2]) >= (1,67)
SYMBOLS = {
    "entry":'<path d="M12 2 22 12 12 22 2 12Z"/>',
    "lng":'<rect x="3" y="3" width="18" height="18" rx="3"/>',
    "storage":'<path d="M3 7V18C3 24 21 24 21 18V7Z"/><ellipse cx="12" cy="6" rx="9" ry="4"/>',
    "compressor":'<path d="M12 2 23 22H1Z"/>',
    "production":'<path d="M12 1 23 9 19 22H5L1 9Z"/>',
    "power":'<path d="M14 1 3 14H10L8 23 22 9H14Z"/>',
    "node":'<circle cx="12" cy="12" r="7"/>'}
ICON_SIZES = {"entry":18,"lng":18,"storage":15,"compressor":13,"production":13,"power":13,"node":6}
_ATLAS_SYMBOLS = {**SYMBOLS,**{c+"-outline":f'<g fill="none" stroke="white" stroke-width="1.8">{s}</g>' for c,s in SYMBOLS.items()},
    "ring":'<circle cx="12" cy="12" r="10" fill="none" stroke="white" stroke-width="2"/>',
    "finding":'<path d="M12 2 22 12 12 22 2 12Z" fill="none" stroke="white" stroke-width="1.7"/>',
    "quality":'<circle cx="12" cy="12" r="10" fill="none" stroke="white" stroke-width="1.7" stroke-dasharray="3 2"/>',
    "assumption":'<circle cx="12" cy="12" r="10" fill="none" stroke="white" stroke-width="2" stroke-dasharray="3 2"/><path d="m8 8 8 8m0-8-8 8" fill="none" stroke="white" stroke-width="2"/>'}
# Abstract glyphs, not geographic headings or observed flow animations.
_DIRECTION_PATHS = {"entry":"M8 8L16 16M10 16H16V10",
                    "exit":"M8 16L16 8M10 8H16V14",
                    "both":"M6 12H18M9 9L6 12L9 15M15 9L18 12L15 15"}
_DIRECTION_ICONS = {"Solo ingresso":"entry-in","Solo uscita":"entry-out","Bidirezionale":"entry-both"}
for kind,variant in zip(("entry","exit","both"),_DIRECTION_ICONS.values()):
    path = _DIRECTION_PATHS[kind]
    mask = "arrow-"+kind
    _ATLAS_SYMBOLS[variant] = (
        f'<mask id="{mask}" maskUnits="userSpaceOnUse" x="0" y="0" width="24" height="24">'
        f'<rect width="24" height="24" fill="white"/><path d="{path}" fill="none" stroke="black" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></mask>'
        f'<g mask="url(#{mask})">{SYMBOLS["entry"]}</g>')
    _ATLAS_SYMBOLS[variant+"-outline"] = (
        f'<g fill="none" stroke="white" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'
        f'{SYMBOLS["entry"]}<path d="{path}"/></g>')
ICON_MAPPING = {category:{"x":n*24,"y":0,"width":24,"height":24,"mask":True} for n,category in enumerate(_ATLAS_SYMBOLS)}
ICON_ATLAS = "data:image/svg+xml,"+quote(f'<svg xmlns="http://www.w3.org/2000/svg" width="{24*len(_ATLAS_SYMBOLS)}" height="24" fill="white">'+
    ''.join(f'<g transform="translate({n*24} 0)">{symbol}</g>' for n,symbol in enumerate(_ATLAS_SYMBOLS.values()))+'</svg>')
MAX_ZOOM = 9
# Fixed bins, comparable across dates.
FLOW_SIZES = ((0, 9), (100, 12), (500, 15), (float("inf"), 18))


def flow_icon_size(value):
    if value is None:
        return 9
    return next(size for upper,size in FLOW_SIZES if abs(value) <= upper)


def focus_camera(camera, geometry):
    lon, lat = label_anchor(geometry)
    return {**camera, "longitude":lon, "latitude":lat,
            "zoom":min(MAX_ZOOM, max(camera["zoom"]+1.6, 6.4))}

MARK_COLORS = {"ring":[246,146,157],"finding":[242,190,114],"quality":[180,194,211],"assumption":[255,202,110]}


def legend_symbol(category, *, outlined=False):
    """The legend and atlas use exactly the same authored SVG geometry."""
    color = ",".join(map(str,COLORS.get(category,MARK_COLORS.get(category,[161,175,192]))))
    shape = _ATLAS_SYMBOLS.get(category,'<path d="M1 11h22v2H1Z"/>').replace('stroke="white"',f'stroke="rgb({color})"')
    if outlined:
        shape = f'<g fill="none" stroke="rgb({color})" stroke-width="1.8">{shape}</g>'
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="24" height="24" fill="rgb({color})">{shape}</svg>'
    return "data:image/svg+xml,"+quote(svg)


def point_features(rows):
    return {"type":"FeatureCollection","features":[{"type":"Feature",
        "geometry":{"type":"Point","coordinates":row["position"]},"properties":row} for row in rows]}


def label_anchor(geometry):
    if geometry["type"] == "Point":
        return geometry["coordinates"]
    line = geometry["coordinates"] if geometry["type"] == "LineString" else max(geometry["coordinates"],key=len)
    middle = len(line)//2
    return line[middle] if len(line)%2 else [(a+b)/2 for a,b in zip(line[middle-1],line[middle])]


def display_name(name):
    return name.replace("_", " – ")


# Historical coordinates are indicative. This is a UI grouping tolerance,
# not a statement that the facilities share equipment or a certified location.
NEARBY_METRES = 250


def nearby_points(network, visible):
    """Return distinct visible point IDs within a small geographic tolerance."""
    ids = {i.id for i in visible}
    points = [(g.infrastructure_id, g.geometry["coordinates"]) for g in network.geography
              if g.infrastructure_id in ids and g.geometry["type"] == "Point"]
    groups = {identifier: [] for identifier, _ in points}
    for index, (identifier, (lon,lat)) in enumerate(points):
        for other, (other_lon,other_lat) in points[index+1:]:
            if abs(lat-other_lat) > .003 or abs(lon-other_lon) > .005:
                continue
            dy = (other_lat-lat)*111195
            dx = (other_lon-lon)*111195*math.cos(math.radians((lat+other_lat)/2))
            if math.hypot(dx,dy) <= NEARBY_METRES:
                groups[identifier].append(other)
                groups[other].append(identifier)
    return {identifier:tuple(sorted(others)) for identifier,others in groups.items() if others}


def fit_italy(boundary, width, height, padding=10):
    """Fit the real country's Mercator bounds; retain islands without cropping."""
    positions = []
    def collect(coords):
        if isinstance(coords[0],(int,float)):
            positions.append(coords)
        else:
            for part in coords:collect(part)
    for feature in boundary["features"]:
        collect(feature["geometry"]["coordinates"])
    west,east = min(p[0] for p in positions),max(p[0] for p in positions)
    mercator = lambda latitude:math.log(math.tan(math.pi/4+math.radians(latitude)/2))
    south,north = min(mercator(p[1]) for p in positions),max(mercator(p[1]) for p in positions)
    scale = min((width-2*padding)*360/(east-west),(height-2*padding)*2*math.pi/(north-south))
    return {"longitude":(west+east)/2,"latitude":math.degrees(2*math.atan(math.exp((south+north)/2))-math.pi/2),
            "zoom":math.log2(scale/512)}


def label_layout(labels, *, zoom=4, width=None, height=None, longitude=12.5, latitude=41.5):
    """Screen-space placement in the measured viewport; selection first."""
    placed, boxes = [], []
    scale = 512*2**zoom
    center_x = scale*longitude/360
    center_y = -scale*math.log(math.tan(math.pi/4+math.radians(latitude)/2))/(2*math.pi)
    for row in labels:
        row={**row,"label":row["label"][:34]+"…" if len(row["label"])>35 else row["label"]}
        size = row.get("label_size",12)
        lon,lat = row["position"]
        x = scale*lon/360
        y = -scale*math.log(math.tan(math.pi/4+math.radians(lat)/2))/(2*math.pi)
        label_width = sum(.3 if c in "ilIjt .,:;|" else .85 if c in "MW@" else .56 for c in row["label"])*size+10
        half_height = size/2+4
        # Eastern names grow toward the interior, keeping coastal labels on screen.
        sides = ("end","start") if lon > 15 else ("start","end")
        candidates = [(14 if a == "start" else -14,y,a) for a in sides for y in (-14,14)]
        if label_width > 180:
            candidates += [(0,-16,"middle"),(0,16,"middle")]
        for dx,dy,anchor in candidates:
            left = x+dx-(label_width if anchor == "end" else label_width/2 if anchor == "middle" else 0)
            box = (left,y+dy-half_height,left+label_width,y+dy+half_height)
            # Keep the label within the actual horizontal frame.
            if width and (box[0] < center_x-width/2+5 or box[2] > center_x+width/2-5):
                continue
            if height and (box[1] < center_y-height/2+5 or box[3] > center_y+height/2-5):
                continue
            if not any(box[0]<b[2]+3 and box[2]>b[0]-3 and box[1]<b[3]+3 and box[3]>b[1]-3 for b in boxes):
                placed.append({**row,"offset":[dx,dy],"anchor":anchor})
                boxes.append(box)
                break
    return placed


def bidirectional_preview(bindings, observations, day, info):
    """Describe verified directions and separate published physical flows for D."""
    by_direction = {b.direction:b for b in bindings}
    if set(by_direction) != {"entry","exit"}:
        return None
    if day is None:
        return "Ingresso e uscita dalla rete italiana"
    active = info.get("binding")
    lines = [data_it(day)+" · flussi fisici"]
    for direction,label in (("entry","Ingresso"),("exit","Uscita")):
        binding = by_direction[direction]
        if active and active.point_direction == binding.point_direction and info.get("day",day) == day:
            value = info.get("values",{}).get("Physical Flow")
        else:
            value = applicable(observations,binding.point_direction,day,"Physical Flow")
        lines.append(arrow_text(direction)+": "+(numero(value,1)+" GWh/d" if value is not None else "N/D"))
    return "\n".join(lines)


def deck(network, boundary, visible, selected=None, event_ids=(), *, observations=(), day=None, direction="entry", show_labels=True, mode="full", viewport_width=600,
         reading_mode="INFRASTRUCTURE", intelligence=None, finding_ids=(), stable_picking=False, scenario_ids=(), focus_id=None):
    camera = fit_italy(boundary,viewport_width,498 if mode in ("overview","scenario") else 648)
    national_zoom = camera["zoom"]
    lookup = {g.infrastructure_id:g for g in network.geography}
    if focus_id in lookup and focus_id in {i.id for i in visible}:
        camera = focus_camera(camera, lookup[focus_id].geometry)
    visible = tuple(visible)
    nearby = nearby_points(network, visible)
    point_categories = {i.category for i in visible if i.category != "pipeline"}
    bindings_by_id = {}
    for binding in verified_bindings(network):
        bindings_by_id.setdefault(binding.infrastructure_id,[]).append(binding)
    lines, points, highlight, labels, events, findings, quality, assumptions = [], [], [], [], [], [], [], []
    for item in visible:
        geometry = lookup[item.id].geometry
        tooltip = {"infra_id":item.id, "safe_name":escape(display_name(item.name)),
                   "safe_type":escape(CATEGORIES[item.category]), "safe_status":escape(item.status), "safe_value":"",
                   "safe_summary":"Geografia storica · seleziona per i dettagli"}
        info = intelligence.get(item.id,{}) if intelligence is not None else {}
        if intelligence is not None:
            tooltip["safe_status"] = escape(info.get("status",{}).get("status","Sola geografia")+
                (" · cache da aggiornare" if info.get("stale") else ""))
            binding = info.get("binding")
            if binding:
                tooltip["direction"] = binding.direction
                values = info["values"]
                names = {"Physical Flow":"Flusso", "Firm Technical":"Capacità tecnica firm", "Firm Available":"Disponibile pubblicata"}
                text = [f"{'ingresso' if binding.direction == 'entry' else 'uscita'} · {data_it(day)}"]
                text.extend(f"{label}: {numero(values[name],1)} GWh/d" for name,label in names.items() if name in values)
                if info.get("utilization_pct") is not None:
                    text.append(f"Utilizzo: {numero(info['utilization_pct'],1)}%")
                if info.get("change_gwh_d") is not None:
                    text.append(f"Δ D-1: {numero(info['change_gwh_d'],1)} GWh/d")
                tooltip["safe_value"] = "\n".join(escape(t) for t in text)
                flow = values.get("Physical Flow")
                summary = "Flusso: " + numero(flow,1) + " GWh/d" if flow is not None else "Flusso non disponibile"
                tooltip["safe_summary"] = escape(text[0]+" · "+summary)
        if reading_mode == "ATTENTION":
            signals = []
            if item.id in event_ids: signals.append("Avviso pubblicato")
            if item.id in finding_ids or info.get("capacity_change_gwh_d") is not None:
                signals.append("Indicatore I.G.O.R.")
            if info.get("binding") and (info.get("stale") or not info.get("flow_available")):
                signals.append("Qualità dati")
            if signals:
                tooltip["safe_summary"] = escape(" · ".join(signals)+" · Apri Eventi")
        label_style = {"label_size":14 if item.id == selected else 12,
                       "label_color":[192,255,234] if item.id == selected else [226,237,247],
                       "label_background":[20,54,51,245] if item.id == selected else [13,24,36,235],
                       "label_priority":1000 if item.id == selected else {"entry":600,"lng":500,"storage":100,"compressor":80}.get(item.category,0)}
        if intelligence is None and day and item.category in ("entry", "lng"):
            points_for_item = network.bindings_for(item.id,"ENTSOG")
            point = next((b for b in points_for_item if b.direction == (direction if item.id == selected else "entry")), None)
            value = applicable(observations,point.point_direction,day,"Physical Flow") if point else None
            if value is not None:
                tooltip["safe_value"] = f"{numero(value,1)} GWh/d · {'ingresso' if point.direction == 'entry' else 'uscita'} · {data_it(day)}"
                tooltip["safe_summary"] = tooltip["safe_value"]
        bindings = bindings_by_id.get(item.id,())
        structural = direction_label(bindings)
        if structural:
            tooltip["safe_status"] = arrow_text(structural)+" · ENTSOG"
            if reading_mode != "ATTENTION":
                preview = bidirectional_preview(bindings,observations,day,info)
                if preview is not None:
                    tooltip["safe_summary"] = escape(preview)
                elif day is not None:
                    binding = bindings[0]
                    active = info.get("binding")
                    flow = (info.get("values",{}).get("Physical Flow")
                            if active and active.point_direction == binding.point_direction and info.get("day",day)==day
                            else applicable(observations,binding.point_direction,day,"Physical Flow"))
                    tooltip["safe_summary"] = escape(data_it(day)+" · flusso fisico\n"+arrow_text(binding.direction)+": "+
                        (numero(flow,1)+" GWh/d" if flow is not None else "N/D"))
                if info.get("stale"):
                    tooltip["safe_summary"] += "\nCopia da aggiornare (direzione attiva)"
        if geometry["type"] != "Point":
            feature = {"type":"Feature", "geometry":geometry, **tooltip,
                       "properties":{**tooltip, "color":COLORS[item.category]}}
            lines.append(feature)
            if item.id == selected:
                highlight.append(feature)
                position = label_anchor(geometry)
                labels.append({**tooltip,**label_style,"position":position,"label":display_name(item.name)})
            continue
        if item.id in nearby:
            tooltip["safe_summary"] += f"\n{1+len(nearby[item.id])} punti vicini · clicca per scegliere"
        row = {**tooltip, "position":geometry["coordinates"], "color":COLORS[item.category],
               "category":item.category,"icon":item.category+("-outline" if intelligence is not None
                   and reading_mode != "INFRASTRUCTURE" and not info.get("available") else ""),"icon_size":ICON_SIZES[item.category],
               "radius":RADII[item.category],"hit_radius":HIT_RADII[item.category],
               "active":True,"border":[26,42,58]}
        if item.category=="entry" and structural in _DIRECTION_ICONS and reading_mode!="ATTENTION":
            row["icon"] = _DIRECTION_ICONS[structural]+("-outline" if row["icon"].endswith("-outline") else "")
        # Context stays selectable, while primary points dominate visually.
        if reading_mode in ("SYSTEM","FLOW","ATTENTION"):
            if item.id != selected and item.category in ("power","node","compressor"):
                row["color"] = [*row["color"],150]
                row["icon_size"] = max(6,row["icon_size"]-3)
            if reading_mode == "FLOW" and info.get("flow_available"):
                row["icon_size"] = flow_icon_size(info["values"].get("Physical Flow"))
        points.append(row)
        if item.id == selected or show_labels and (item.category in ("entry", "lng") or len(point_categories) == 1):
            name = display_name(item.name.split(" · ")[0].replace("FSRU ", ""))
            if structural and item.category=="entry":
                name = ARROWS[structural]+" "+name
            flow = info.get("values",{}).get("Physical Flow")
            if reading_mode == "FLOW" and info.get("flow_available") and flow is not None:
                name += " · "+(ARROWS.get(info.get("binding").direction,"")+" " if info.get("binding") and structural=="Bidirezionale" else "")+numero(flow,0)
            labels.append({**row, **label_style,"label":name,
                           "offset":[10,-10] if item.id == selected else [10,9]})
        if item.id in event_ids:
            events.append(row)
        if item.id in scenario_ids:
            assumptions.append(row)
            row["safe_status"]="ASSUMPTION · stress ipotetico sul punto; non evento pubblicato"
        if reading_mode == "ATTENTION":
            if item.id in finding_ids or info.get("capacity_change_gwh_d") is not None:
                findings.append(row)
            if info.get("binding") and (info.get("stale") or not info.get("flow_available")):
                quality.append(row)
    layers = [pdk.Layer("GeoJsonLayer", boundary, id="italy-outline", pickable=False,
        filled=True, stroked=True, get_fill_color=[23,40,54,255], get_line_color=[100,132,150,230],
        line_width_min_pixels=1.2,
        # Explicit sublayer colors keep Streamlit's native selection tint from
        # dimming the background or the rest of the network.
        _sub_layer_props={"polygons-fill":{"getFillColor":[23,40,54,255]},
                          "polygons-stroke":{"getColor":[100,132,150,230]}})]
    if lines:
        # Visible strokes stay thin; only the invisible picking corridor widens.
        # Alpha 1 remains pickable without a visible corridor across the map.
        layers.append(pdk.Layer("GeoJsonLayer", {"type":"FeatureCollection", "features":lines},
            id="pipeline-hit-targets", pickable=reading_mode not in ("FLOW","ATTENTION"), auto_highlight=True, highlight_color=[101,223,191,75],
            filled=False, get_line_color=[91,139,181,1], get_line_width=18,
            line_width_units=pdk.types.String("pixels"), line_width_min_pixels=18, line_width_max_pixels=18,
            _sub_layer_props={"linestrings":{"getColor":[91,139,181,1]}}))
        layers.append(pdk.Layer("GeoJsonLayer", {"type":"FeatureCollection", "features":lines},
            id="historical-links", pickable=False, filled=False,
            get_line_color="properties.color", line_width_min_pixels=.8 if reading_mode != "INFRASTRUCTURE" else 1.1,
            _sub_layer_props={"linestrings":{"getColor":[*(COLORS["pipeline"] if reading_mode == "INFRASTRUCTURE" else [60,103,140]),255]}}))
    if highlight:
        layers.append(pdk.Layer("GeoJsonLayer", {"type":"FeatureCollection", "features":highlight},
            id="selected-link-halo", pickable=False, filled=False, get_line_color=[101,223,191,100],
            line_width_min_pixels=8, line_width_max_pixels=8,
            _sub_layer_props={"linestrings":{"getColor":[101,223,191,100]}}))
        layers.append(pdk.Layer("GeoJsonLayer", {"type":"FeatureCollection", "features":highlight},
            id="selected-link", pickable=False, filled=False, get_line_color=[170,255,231],
            line_width_min_pixels=3, line_width_max_pixels=3,
            _sub_layer_props={"linestrings":{"getColor":[170,255,231,255]}}))
    if points or stable_picking:
        selected_points = [r for r in points if r["infra_id"] == selected]
        if selected_points:
            layers.append(pdk.Layer("GeoJsonLayer", point_features(selected_points), id="selected-point", pickable=False,
                point_type=pdk.types.String("icon"),icon_atlas=pdk.types.String(ICON_ATLAS),icon_mapping=ICON_MAPPING,
                get_icon=pdk.types.String("ring"),get_icon_color=[245,250,255,255],get_icon_size=22,
                icon_size_units=pdk.types.String("pixels"),icon_size_min_pixels=22,icon_size_max_pixels=22))
        # Stable category priority puts key entry/LNG targets above minor nodes.
        # The order does not change with selection, mode or filters.
        pick_order=sorted((i for i in network.infrastructure if lookup[i.id].geometry["type"]=="Point"),
                          key=lambda i:(PICK_PRIORITY[i.category],i.id))
        targets = sorted(points,key=lambda r:(PICK_PRIORITY[r["category"]],r["infra_id"]))
        if stable_picking:
            # Native selection stores array indices. Keep their identity stable
            # when a reading/filter hides rows; radius 0 draws/picks nothing.
            by_id = {r["infra_id"]:r for r in points}
            targets = [by_id.get(i.id,{"infra_id":i.id,"position":lookup[i.id].geometry["coordinates"],
                "category":i.category,"radius":0,"hit_radius":0,"active":False,
                "safe_name":"","safe_status":"","safe_summary":""}) for i in pick_order]
        layers.append(pdk.Layer("ScatterplotLayer", targets, id="infrastructure-points", pickable=True,
            auto_highlight=True, highlight_color=[230,245,255,60],get_position="position", get_fill_color=[20,34,49,1], get_radius="hit_radius",
            radius_units=pdk.types.String("pixels"), radius_min_pixels=0, radius_max_pixels=14,
            stroked=False, get_line_color="border", get_line_width=1,
            line_width_units=pdk.types.String("pixels"), line_width_min_pixels=1, line_width_max_pixels=1.5))
        # Keep one picking identity per point; the symbols are presentation only.
        symbols = [{k:r[k] for k in ("position","color","category","icon","icon_size")} for r in points]
        layers.append(pdk.Layer("GeoJsonLayer", point_features(symbols), id="category-symbols", pickable=False,
            point_type=pdk.types.String("icon"),
            icon_atlas=pdk.types.String(ICON_ATLAS), icon_mapping=ICON_MAPPING,
            get_icon="properties.icon",get_icon_color="properties.color",get_icon_size="properties.icon_size",
            icon_size_units=pdk.types.String("pixels"),icon_size_min_pixels=6,icon_size_max_pixels=18))
    for rows,identifier,icon,color,size in ((events,"event-rings","ring",[246,146,157,255],28),
            (findings,"finding-marks","finding",[242,190,114,255],34),
            (quality,"quality-marks","quality",[180,194,211,255],29),
            (assumptions,"scenario-assumptions","assumption",[255,202,110,255],32)):
        if not rows:
            continue
        layers.append(pdk.Layer("GeoJsonLayer", point_features(rows), id=identifier, pickable=False,
            point_type=pdk.types.String("icon"),icon_atlas=pdk.types.String(ICON_ATLAS),icon_mapping=ICON_MAPPING,
            get_icon=pdk.types.String(icon),get_icon_color=color,get_icon_size=size,
            icon_size_units=pdk.types.String("pixels"),icon_size_min_pixels=size,icon_size_max_pixels=size))
    if labels or stable_picking:
        labels.sort(key=lambda r:-r["label_priority"])
        arranged = label_layout(labels,zoom=camera["zoom"],width=viewport_width,
            height=498 if mode in ("overview","scenario") else 648,longitude=camera["longitude"],latitude=camera["latitude"])
        if stable_picking:
            by_id = {r["infra_id"]:r for r in arranged}
            arranged = [by_id.get(i.id,{"infra_id":i.id,"position":label_anchor(lookup[i.id].geometry),"label":"",
                "label_size":0,"label_color":[0,0,0,0],"label_background":[0,0,0,0],
                "offset":[0,0],"anchor":"start","active":False,
                "safe_name":"","safe_status":"","safe_summary":""}) for i in network.infrastructure]
        layers.append(pdk.Layer("GeoJsonLayer", point_features(arranged), id="point-labels", pickable=False,
            point_type=pdk.types.String("text"),get_text="properties.label",get_text_color="properties.label_color",
            get_text_size="properties.label_size",text_size_units=pdk.types.String("pixels"),text_size_min_pixels=0 if stable_picking else 12,text_size_max_pixels=14,
            get_text_pixel_offset="properties.offset",get_text_anchor="properties.anchor",text_font_family=pdk.types.String("Arial, sans-serif"),
            text_font_weight=pdk.types.String("500"),text_character_set=pdk.types.String("auto"),text_background=True,
            get_text_background_color="properties.label_background",text_background_padding=[3,2]))
    return pdk.Deck(layers=layers, initial_view_state=pdk.ViewState(**camera,min_zoom=national_zoom-.25,max_zoom=MAX_ZOOM,
        pitch=0,min_pitch=0,max_pitch=0),
        views=[pdk.View(type="MapView",controller={"dragPan":True,"scrollZoom":True,"doubleClickZoom":True,
            "touchZoom":True,"dragRotate":False,"touchRotate":False,"keyboard":True})],
        map_provider=None, **({} if NATIVE_BASEMAP_OMISSION else {"map_style":LOCAL_STYLE_URL}),
        tooltip={"html":"<b>{safe_name}</b><br/>{safe_status}<br/>{safe_summary}",
                 "style":{"backgroundColor":"#122331", "color":"#eef5fc", "fontSize":"12px",
                          "pointerEvents":"none","maxWidth":"240px","whiteSpace":"pre-line",
                          "border":"1px solid #39576b","borderRadius":"8px","padding":"8px 10px",
                          "boxShadow":"0 4px 14px rgba(0,0,0,.24)"}})
