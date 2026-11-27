"""Presentation only: directional symbols describe the Italian network perspective."""
from html import escape

from .italiano import numero
from .italian_network import direction_name

ARROWS = {"entry":"↘","exit":"↗","Solo ingresso":"↘","Solo uscita":"↗","Bidirezionale":"↔"}
TONES = {"entry":"entry","exit":"exit","Solo ingresso":"entry","Solo uscita":"exit","Bidirezionale":"both"}


def arrow_text(value):
    label = direction_name(value) if value in ("entry","exit") else str(value or "Non verificata")
    return (ARROWS[value]+" " if value in ARROWS else "")+label


def direction_chip(value):
    tone = TONES.get(value,"unknown")
    return f'<span class="igor-direction-chip {tone}">{escape(arrow_text(value))}</span>'


def direction_header(point_type, direction=None):
    if not point_type:
        return ""
    detail = ('<span class="igor-direction-context">Dati consultati</span>'+direction_chip(direction)
              if point_type=="Bidirezionale" and direction in ("entry","exit") else "")
    return '<div class="igor-direction-header">'+direction_chip(point_type)+detail+'</div>'


def paired_flow_html(values, *, active=None):
    """Values are already validated; None is unavailable, zero is a measurement."""
    cards = []
    for direction in ("entry","exit"):
        value = values.get(direction)
        label = arrow_text(direction)
        shown = numero(value,1) if value is not None else "N/D"
        state = " active" if direction==active else ""
        missing = " missing" if value is None else ""
        cards.append(f'<div class="igor-flow-card {direction}{state}{missing}">'
                     f'<span class="igor-flow-label">{escape(label)}</span>'
                     f'<div class="igor-flow-value">{escape(shown)} <small>GWh/d</small></div>'
                     + ('<span class="igor-flow-active">Direzione consultata</span>' if state else '')
                     +'</div>')
    return '<div class="igor-flow-pair" role="group" aria-label="Flussi fisici per direzione">'+''.join(cards)+'</div>'
