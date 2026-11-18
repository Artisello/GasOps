from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]


def contrast(a,b):
    def lum(v):
        n=[int(v[i:i+2],16)/255 for i in (1,3,5)]
        linear=[x/12.92 if x<=0.04045 else ((x+0.055)/1.055)**2.4 for x in n]
        return sum(x*y for x,y in zip(linear,(0.2126,0.7152,0.0722)))
    x,y=sorted((lum(a),lum(b)))
    return (y+.05)/(x+.05)


def test_design_tokens_text_contrast():
    css=(ROOT/"gasops_app/theme.css").read_text()
    tokens=dict(re.findall(r"--gas-([a-z]+):\s*(#[0-9a-fA-F]{6})",css))
    for bg in ("bg","panel"):
        for fg in ("text","muted","teal","blue","amber","rose"):
            assert contrast(tokens[fg],tokens[bg])>=4.5


def test_theme_has_focus_reflow_and_motion_preferences():
    css=(ROOT/"gasops_app/theme.css").read_text()
    assert ":focus-visible" in css and "prefers-reduced-motion:reduce" in css
    assert ".gas-chip" in css and "overflow-wrap:anywhere" in css
    assert "display:none" not in css.replace(" ","")


def test_native_theme_and_operational_palette_agree():
    import tomllib
    from gasops_app import visuals

    css=(ROOT/"gasops_app/theme.css").read_text()
    tokens=dict(re.findall(r"--gas-([a-z-]+):\s*(#[0-9a-fA-F]{6})",css))
    theme=tomllib.loads((ROOT/".streamlit/config.toml").read_text())["theme"]
    assert theme["base"]=="dark"
    for field,key in (("backgroundColor","bg"),("secondaryBackgroundColor","panel"),
                      ("textColor","text"),("primaryColor","teal"),("borderColor","control")):
        assert theme[field]==tokens[key]
    for name in ("TEAL","BLUE","AMBER","ROSE","MUTED","TEXT","PANEL","BORDER"):
        assert getattr(visuals,name)==tokens[name.lower()]
    for bg in ("teal","accent-hover"):
        assert contrast(tokens["on-accent"],tokens[bg])>=4.5
    assert contrast(tokens["control"],tokens["panel"])>=3
    for fg,bg in (("muted","neutral-bg"),("review-text","review-bg"),
                  ("history-text","history-bg"),("teal","selected"),
                  ("sim-text","sim-bg"),("rose","error-bg")):
        assert contrast(tokens[fg],tokens[bg])>=4.5


def test_shared_chart_style_preserves_data_and_analytical_choices():
    import plotly.graph_objects as go
    from gasops_app.visuals import MUTED, style_figure

    fig=go.Figure(go.Scatter(x=[1,2,3],y=[2,None,4],name="Previsione",
                             line=dict(dash="dash"),connectgaps=False))
    fig.update_layout(xaxis=dict(title="Periodo",range=[1,3]),
                      yaxis=dict(title="GWh",type="log"),showlegend=False)
    traces=fig.to_dict()["data"]
    assert style_figure(fig) is fig
    assert fig.to_dict()["data"]==traces
    assert fig.layout.xaxis.title.text=="Periodo"
    assert tuple(fig.layout.xaxis.range)==(1,3)
    assert fig.layout.yaxis.type=="log"
    assert fig.layout.showlegend is False
    assert fig.layout.xaxis.automargin and fig.layout.yaxis.automargin
    assert fig.layout.font.color==MUTED
