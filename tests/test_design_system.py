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
