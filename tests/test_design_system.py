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
    tokens=dict(re.findall(r"--gas-([a-z-]+):\s*(#[0-9a-fA-F]{6})",css))
    for bg in ("bg","panel"):
        for fg in ("text","muted","teal","blue","amber","rose"):
            assert contrast(tokens[fg],tokens[bg])>=4.5


def test_theme_has_focus_reflow_and_motion_preferences():
    css=(ROOT/"gasops_app/theme.css").read_text()
    assert ":focus-visible" in css and "prefers-reduced-motion:reduce" in css
    assert ".gas-chip" in css and "overflow-wrap:anywhere" in css
    assert "display:none" not in css.replace(" ","")


def test_interactive_theme_contrast_and_consistency():
    import tomllib

    css=(ROOT/"gasops_app/theme.css").read_text()
    tokens=dict(re.findall(r"--gas-([a-z-]+):\s*(#[0-9a-fA-F]{6})",css))
    for bg in ("bg","panel","selected"):
        if bg!="selected":
            assert contrast(tokens["control"],tokens[bg])>=3
        assert contrast(tokens["blue"],tokens[bg])>=3
    assert contrast(tokens["teal"],tokens["selected"])>=4.5
    for bg in ("teal","primary-hover","primary-active"):
        assert contrast(tokens["on-primary"],tokens[bg])>=7
    theme=tomllib.loads((ROOT/".streamlit/config.toml").read_text())["theme"]
    for key, token in (("primaryColor","teal"),("backgroundColor","bg"),
                       ("secondaryBackgroundColor","panel"),("textColor","text"),
                       ("borderColor","border")):
        assert theme[key]==tokens[token]


def test_native_interaction_and_local_reflow_rules():
    css=(ROOT/"gasops_app/theme.css").read_text()
    assert "--gas-target:2.75rem" in css
    assert '[role="tablist"]' in css and "overflow-x:auto" in css
    assert '[kind="primary"]' in css
    assert '[kind="primaryFormSubmit"]' in css
    assert '[data-testid="stBaseButton-primaryFormSubmit"]' in css
    assert ':not(:disabled):not([aria-disabled="true"])' in css
    assert 'color:var(--gas-on-primary)!important' in css
    assert ':is(div,p,span,strong,em,svg)' in css
    assert ':is(:hover,:focus-visible)' in css
    assert 'background-color:var(--gas-primary-active)!important' in css
    assert "scroll-margin-block:4rem 1rem" in css
    assert "font-variant-numeric:tabular-nums" in css


def test_operational_controls_stay_in_flow_and_warnings_are_readable():
    css=(ROOT/"gasops_app/theme.css").read_text()
    for selector in ("net_view_focus_","net_view_reset_"):
        assert not re.search(r'\[class\*="st-key-'+selector+r'"\]\s*\{[^}]*position\s*:\s*absolute',css)
    note=re.search(r'\.gas-balance-note\s*\{([^}]+)\}',css).group(1)
    assert "line-clamp" not in note and "overflow:hidden" not in note
    assert "var(--gas-amber)" in note
    tokens=dict(re.findall(r"--gas-([a-z-]+):\s*(#[0-9a-fA-F]{6})",css))
    for bg in ("bg","panel","panel-hover","selected"):
        for fg in ("text","muted","blue","teal"):
            assert contrast(tokens[fg],tokens[bg])>=4.5
    assert "st-key-system_day_nav" in css
    assert "st-key-network_camera_" in css
    assert 'role="switch"' in css


def test_shared_page_header_avoids_decorative_dividers_and_duplicate_brand():
    visuals=(ROOT/"gasops_app/visuals.py").read_text()
    css=(ROOT/"gasops_app/theme.css").read_text()
    demo=(ROOT/"gasops_app/presentation.py").read_text()
    assert 'st.title(title)' in visuals
    assert 'gas-topline' not in visuals and 'gas-topline' not in css
    assert 'demo-masthead' not in demo and 'demo-masthead' not in css
    assert '.st-key-page_header h1' in css
