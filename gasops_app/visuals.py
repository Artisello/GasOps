"""Dashboard styles and charts shared across analytical views."""

from datetime import date, datetime
from html import escape
from typing import Iterable

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from .data import ROME
from .forecast import Forecast, ForecastPoint
from .italiano import ESITI, TIPI, data_it, numero
from .models import AGENT_LABELS, Agent, Citation, Kind, Run

TEAL, BLUE, AMBER, ROSE, MUTED = "#65dfbf", "#83acff", "#f2be72", "#f6929d", "#a3b4c9"
CHIP = {
    Kind.SYNTHETIC: "synthetic", Kind.HISTORICAL: "historical", Kind.LIVE: "live",
    Kind.FORECAST: "forecast", Kind.SIMULATION: "simulation", Kind.ACCOUNTING: "review", Kind.PHYSICAL: "ok",
}
STATUS_STYLE = {"running": "running", "completed": "ok", "review": "review", "failed": "failed"}


def chip(label: str, style: str = "") -> str:
    return f'<span class="gas-chip {escape(style)}">{escape(label)}</span>'


def kind_tag(kind: Kind) -> str:
    return chip(TIPI[kind], CHIP[kind])


def local_time(value: datetime | None) -> str:
    if value is None:
        return "Non disponibile"
    local = value.astimezone(ROME)
    return f"{data_it(local)} · {local:%H:%M %Z}"


def header(title: str, meta: str, action: str | None = None, disabled: bool = False) -> bool:
    with st.container(key="page_header"):
        if action:
            left, right = st.columns([4, 1.85], vertical_alignment="center")
        else:
            left = st.container()
        with left:
            st.title(title)
            st.html(f'<div class="gas-header-meta">{meta}</div>')
        clicked = False
        if action:
            with right:
                clicked = st.button(action, icon=":material/play_arrow:", type="primary",
                                    width="stretch", disabled=disabled, key="analysis_launch")
        st.html('<div class="gas-topline"></div>')
    return clicked


def heading(label: str, right: str = "") -> None:
    st.html(f'<div class="gas-panel-head"><h2>{escape(label)}</h2>{right}</div>')


def kpi(label: str, value, unit: str, detail: str, decimals: int = 1, tone: str = "") -> None:
    rendered = numero(value, decimals)
    unit_label = unit if value is not None else ""
    st.html(f"""
    <div class="gas-kpi">
      <span class="key">{escape(label)}</span>
      <div class="readout"><span class="value {escape(tone)}">{rendered}</span>
        <span class="unit">{escape(unit_label)}</span></div>
      <span class="detail">{escape(detail)}</span>
    </div>
    """)


def forecast_readout(point: ForecastPoint, grain: str, *, historical: bool = False) -> None:
    period = data_it(date.fromisoformat(point.period), day=grain == "daily")
    label = "Proiezione storica" if historical else "Prossima stima"
    interval = (f"{numero(point.lower_80, 0)}–{numero(point.upper_80, 0)} GWh"
                if point.lower_80 is not None else "Campione insufficiente")
    st.html(f"""
        <div class="gas-forecast-readout">
          <div><small>{label} · {period}</small><strong>{numero(point.estimate, 0)} GWh</strong></div>
          <div><small>Fascia all’80%</small><strong>{interval}</strong></div>
        </div>
    """)


def rows(items: Iterable[tuple[str, str]]) -> None:
    contents = "".join(f'<li class="gas-row"><small>{escape(title)}</small><span class="num">{escape(value)}</span></li>'
                       for title, value in items)
    st.html(f'<ul class="gas-list">{contents}</ul>')


def steps(run: Run | None, grid: bool = False) -> str:
    entries = []
    for agent in Agent:
        status = "ready" if run is None else run.steps[agent].status
        text, style = ESITI[status], STATUS_STYLE.get(status, "")
        label = escape(AGENT_LABELS[agent])
        if grid:
            entries.append(f'<div class="gas-step"><strong>{label}</strong>{chip(text, style)}</div>')
        else:
            entries.append(f'<li class="gas-row"><span>{label}</span>{chip(text, style)}</li>')
    return f'<div class="gas-workflow">{"".join(entries)}</div>' if grid else f'<ul class="gas-list">{"".join(entries)}</ul>'


def evidence(citations: Iterable[Citation]) -> None:
    for citation in citations:
        suffix = f" · PDF p. {citation.page}" if citation.page else ""
        if citation.section:
            suffix += f" · {citation.section}"
        st.text(f"{citation.document}{suffix}")
        st.caption(citation.evidence)
        if citation.url:
            st.markdown(f"[Apri fonte]({citation.url})")


def _frame(fig: go.Figure, grain: str, unit: str, height: int) -> go.Figure:
    fig.update_layout(
        template="plotly_dark", height=height, separators=",.",
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=5, r=10, t=15, b=9), hovermode="x unified", dragmode="zoom",
        font=dict(family="Inter, Avenir Next, system-ui, sans-serif", color=MUTED, size=11),
        legend=dict(orientation="h", x=0, y=1.03, yanchor="bottom", xanchor="left",
                    font=dict(size=11), traceorder="normal", itemclick="toggle", itemdoubleclick="toggleothers"),
        hoverlabel=dict(bgcolor="#142235", bordercolor="#334963", font=dict(color="#edf4ff", size=12)),
        xaxis=dict(showgrid=True, gridcolor="rgba(153,180,214,0.09)", showline=True, linecolor="#253548",
                   tickformat="%d/%m" if grain == "daily" else "%m/%Y", zeroline=False, nticks=8),
        yaxis=dict(side="right", showgrid=True, gridcolor="rgba(153,180,214,0.12)", showline=True,
                   linecolor="#253548", tickformat=",.0f" if unit == "GWh" else ",.1f",
                   zeroline=False, nticks=6, automargin=True),
    )
    return fig


def _line(name: str, x, y, color: str, unit: str, grain: str, dash: str = "solid") -> go.Scatter:
    return go.Scatter(name=name, x=x, y=y, mode="lines", connectgaps=False,
                      line=dict(color=color, width=2, dash=dash),
                      hovertemplate=f"%{{y:,.2f}} {unit}<extra>{name}</extra>",
                      xhoverformat="%d/%m/%Y" if grain == "daily" else "%m/%Y")


def demand_chart(data: pd.DataFrame, projection: Forecast, grain: str, *, height: int = 330) -> go.Figure:
    fig = go.Figure()
    future = projection.points
    if future:
        dates = pd.to_datetime([p.period for p in future])
        lower = [p.lower_80 for p in future]
        upper = [p.upper_80 for p in future]
        if any(v is not None for v in upper):
            fig.add_trace(go.Scatter(x=dates, y=lower, mode="lines", showlegend=False, hoverinfo="skip",
                                     line=dict(width=0), legendgroup="interval"))
            fig.add_trace(go.Scatter(x=dates, y=upper, name="Fascia all’80%", fill="tonexty",
                                     fillcolor="rgba(131,172,255,0.17)", hoverinfo="skip",
                                     mode="lines", line=dict(width=0, color=BLUE), legendrank=4,
                                     legendgroup="interval"))
        fig.add_vrect(x0=data.index[-1], x1=dates[-1], fillcolor="rgba(131,172,255,0.04)", line_width=0)
        fig.add_vline(x=data.index[-1], line_color="#446492", line_dash="dot", line_width=1)
    demand = _line("Consumi", data.index, data["demand_gwh"], TEAL, "GWh", grain)
    demand.legendrank = 1
    fig.add_trace(demand)
    if data["supply_gwh"].notna().any():
        label = "Disponibilità contabile" if grain == "monthly" else "Offerta"
        supply = _line(label, data.index, data["supply_gwh"], "#afc3de", "GWh", grain)
        supply.update(line=dict(color="#afc3de", width=1.3, dash="dot" if grain == "monthly" else "solid"),
                      legendrank=2)
        fig.add_trace(supply)
    if future:
        dotted = _line("Previsione", dates, [p.estimate for p in future], BLUE, "GWh", grain, "dash")
        dotted.update(mode="lines+markers", marker=dict(size=4, color=BLUE), legendrank=3)
        fig.add_trace(dotted)
    return _frame(fig, grain, "GWh", height)


def mini_chart(values: pd.Series, label: str, grain: str, unit: str, color: str, *, zero: bool = False) -> go.Figure:
    fig = go.Figure(_line(label, values.index, values, color, unit, grain))
    if zero:
        fig.add_hline(y=0, line_dash="dot", line_color="#637891", line_width=1)
    fig.update_layout(showlegend=False)
    return _frame(fig, grain, unit, 185).update_xaxes(nticks=5)


def breakdown_chart(frame: pd.DataFrame, series: list[tuple[str, str, str]], grain: str) -> go.Figure:
    fig = go.Figure()
    for field, label, color in series:
        if frame[field].notna().any():
            fig.add_trace(_line(label, frame.index, frame[field], color, "GWh", grain))
    return _frame(fig, grain, "GWh", 223).update_xaxes(nticks=5)


def error_chart(forecast: Forecast, grain: str) -> go.Figure:
    values = pd.Series(
        [p.actual - p.estimate for p in forecast.backtest],
        index=pd.to_datetime([p.period for p in forecast.backtest]),
    )
    fig = go.Figure(go.Bar(x=values.index, y=values, marker_color=[TEAL if n >= 0 else ROSE for n in values],
                          hovertemplate="%{y:+,.1f} GWh<extra>Osservato − previsione</extra>"))
    fig.add_hline(y=0, line_color="#637891", line_width=1)
    return _frame(fig, grain, "GWh", 220)


def plot(figure: go.Figure, key: str) -> None:
    st.plotly_chart(figure, key=key, width="stretch", theme=None,
                    config={"displaylogo": False, "displayModeBar": "hover", "scrollZoom": False,
                            "modeBarButtonsToRemove": ["lasso2d", "select2d"]})
