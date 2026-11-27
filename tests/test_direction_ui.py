from decimal import Decimal
import json

from gasops_app.direction_ui import arrow_text, direction_header, paired_flow_html
from gasops_app.italian_network_page import assets
from gasops_app.italian_network_map import deck


def test_direction_chips_and_cards_preserve_semantics():
    assert arrow_text("entry")=="↘ Ingresso"
    assert arrow_text("exit")=="↗ Uscita"
    assert arrow_text("Bidirezionale")=="↔ Bidirezionale"
    assert "Dati consultati" in direction_header("Bidirezionale","exit")
    assert "Dati consultati" not in direction_header("Solo uscita","exit")
    assert "&lt;script&gt;" in direction_header("<script>")
    html=paired_flow_html({"entry":Decimal("0"),"exit":None},active="exit")
    assert "0,0" in html and "N/D" in html
    assert "igor-flow-card exit active missing" in html
    assert "igor-flow-card entry missing" not in html


def test_directional_marker_variants_preserve_point_identity():
    network,boundary,_=assets()
    selected={"INET_BP_65":"entry-in","INET_BP_12":"entry-out","INET_BP_78":"entry-both"}
    items=tuple(i for i in network.infrastructure if i.id in selected)
    scene=json.loads(deck(network,boundary,items,reading_mode="SYSTEM",intelligence={},stable_picking=True).to_json())
    layers={l["id"]:l for l in scene["layers"]}
    points={r["infra_id"]:r for r in layers["infrastructure-points"]["data"] if r["active"]}
    assert set(points)==set(selected)
    for identifier,icon in selected.items():
        assert points[identifier]["icon"]==icon+"-outline"
        assert points[identifier]["hit_radius"]>0
        assert icon+"-outline" in layers["category-symbols"]["iconMapping"]
    assert not layers["category-symbols"]["pickable"]
