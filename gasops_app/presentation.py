"""An explorable, read-only BSO showcase with preloaded, traceable evidence."""
from datetime import date, datetime
from html import escape

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from .demo_cases import briefing, cases
from .demo_forecast import load as load_forecast
from .italiano import data_it, numero
from .visuals import AMBER, BLUE, MUTED, ROSE, TEAL, chip, kpi_grid, header

VIEWS = ("In sintesi", "Balancing", "Settlement", "Operations", "Previsioni", "Sviluppi")
NAV = "demo_view"


def _open_example(view):
    from .demo_application import examples
    st.session_state[NAV]=view
    st.switch_page(st.Page(examples,title="Esempi BSO",icon=":material/auto_awesome:",url_path="demo"))


def _heading(title, kind="Dati simulati", period="18 nov 2026 · 14:00 CET"):
    header(title,chip(kind, "historical" if "pubblic" in kind else "synthetic")
            + f'<span>{escape(period)}</span>')


def _chart(fig, key, unit, height=300):
    fig.update_layout(
        template="plotly_dark", height=height, separators=",.",
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=8, r=16, t=18, b=15), hovermode="x unified", dragmode=False,
        font=dict(family="Inter, Avenir Next, system-ui, sans-serif", color=MUTED, size=12),
        legend=dict(orientation="h", y=-.22, x=0, font=dict(size=12)),
        xaxis=dict(showgrid=False, automargin=True, fixedrange=True, nticks=5),
        yaxis=dict(title=unit, gridcolor="rgba(176,190,208,.12)", automargin=True,
                   zerolinecolor="#63768b", fixedrange=True),
    )
    st.plotly_chart(fig, key=key, width="stretch", theme=None,
                    config={"displayModeBar": False, "scrollZoom": False})


def _sas_chart(b, key, height=290):
    rows = b["rows"]
    hours = rows.published_at.dt.strftime("%H:%M")
    fig = go.Figure(go.Scatter(x=hours, y=rows.sas_gwh, name="SAS stimato · esempio",
                    mode="lines+markers", line=dict(color=TEAL, width=3), marker=dict(size=5),
                    hovertemplate="%{x} · %{y:+.0f} GWh<extra>SAS di esempio</extra>"))
    if b["sign_change_at"] is not None:
        change = b["sign_change_at"].strftime("%H:%M")
        fig.add_vline(x=change, line_dash="dot", line_color=AMBER)
    fig.update_layout(showlegend=False)
    _chart(fig, key, "GWh", height)


def _overview(pack, *, network=True):
    if network:
        from .italian_network_page import panel
        with st.container(key="network_home_title"):
            st.title("I.G.O.R. - Sistema Gas Italiano")
        panel(mode="overview")
        st.divider()
        st.subheader("Prova con un esempio")
        st.caption("Casi simulati separati dai dati pubblici della mappa")
    else:
        _heading("BSO, in sintesi", "Demo", "Casi simulati e dati pubblici storici")
    b, r, o = pack["balancing"], pack["revision"], pack["operations"]
    with st.container(key="demo_cards"):
        columns = st.columns(3)
        cards = (
            ("Balancing", "SAS di sistema", numero(b["latest"], 0, signed=True), "GWh",
             "Simulazione · 18 nov 2026, 14:00", "teal"),
            ("Settlement", "Rettifica", numero(r["delta_cash_eur"], 0), "€",
             "Simulazione · 5 set 2026", "blue"),
            ("Operations", "Attività scadute", str(len(o["overdue"])), "",
             "Simulazione · al 18 nov 2026", "amber"),
        )
        for column, (view, label, value, unit, detail, tone) in zip(columns, cards):
            with column, st.container(border=True, key="demo_card_" + view.lower()):
                st.html(f'<div class="demo-card {tone}"><h2>{escape(label)}</h2>'
                        f'<div class="demo-number">{escape(value)} <small>{escape(unit)}</small></div>'
                        f'<span class="demo-card-detail">{escape(detail)}</span></div>')
                action={"Balancing":"Esplora il bilanciamento","Settlement":"Esplora la rettifica","Operations":"Esplora le scadenze"}[view]
                st.button(action,key="demo_example_"+view.lower(),on_click=_open_example,args=(view,),
                          icon=":material/arrow_forward:",width="stretch")
    if network:
        return
    left, right = st.columns([1.5, 1])
    with left, st.container(border=True):
        st.subheader("SAS · giornata simulata")
        _sas_chart(b, "demo_home_sas", 230)
        st.caption("Tratteggio: cambio di segno · 12:00.")
    with right, st.container(border=True, key="demo_forecast_preview"):
        st.subheader("Previsioni")
        st.html(chip("JRC · dati pubblici storici", "historical"))
        try:
            snapshot = load_forecast()
        except (OSError, ValueError, KeyError):
            st.caption("Confronto storico non disponibile.")
        else:
            scores = snapshot["result"]["scores"]
            gain = 100 * (scores["weekly"]["mae"] - scores["bayesian_multi"]["mae"]) / scores["weekly"]["mae"]
            kpi_grid([("Errore in meno", gain, "%", "Bayes vs riferimento settimanale", 1, "blue")])
            st.caption("Campione: 28 giorni · dicembre 2021.")


def _balancing(pack):
    b = pack["balancing"]
    _heading("Balancing")
    kpi_grid([
        ("SAS stimato", b["latest"], "GWh", "Ultimo aggiornamento · 14:00", 0, "teal"),
        ("Variazione", b["delta"], "GWh", "Rispetto alle 13:00", 0, ""),
        ("Pubblicazioni", len(b["rows"]), "", "07:00–14:00", 0, ""),
    ])
    with st.container(border=True):
        _sas_chart(b, "demo_balancing_sas", 310)
        change = b["sign_change_at"]
        st.caption("Cambio di segno · " + change.strftime("%H:%M") if change is not None else "Segno invariato.")
    st.caption("SAS: sbilanciamento atteso del sistema. Il saldo del partecipante è nel Settlement.")
    with st.expander("Dettagli e fonti"):
        st.dataframe(b["rows"].assign(published_at=b["rows"].published_at.dt.strftime("18/11/2026 %H:%M CET"))
                     .rename(columns={"published_at": "Pubblicazione di esempio", "sas_gwh": "SAS · GWh"}),
                     hide_index=True, width="stretch")
        st.caption("Definizione: Codice di Rete XCII, cap. 9 §1.1, PDF p. 362. "
                   "Riferimento all’edizione fornita, non verifica di vigenza. Nessuna connessione Jarvis attiva nella demo.")


def _settlement(pack):
    r, s = pack["revision"], pack["settlement"]
    prior, final = pack["versions"]
    _heading("Settlement", period="5 set 2026 · DEMO-001")
    kpi_grid([
        ("Provvisorio", prior.cash, "€", "Versione 1", 0, ""),
        ("Definitivo", final.cash, "€", "Versione 2", 0, ""),
        ("Rettifica", r["delta_cash_eur"], "€", "Definitivo − provvisorio", 0, "rose"),
    ])
    with st.container(border=True):
        fig = go.Figure(go.Waterfall(
            x=["Provvisorio", "Effetto quantità", "Effetto prezzo", "Definitivo"],
            measure=["absolute", "relative", "relative", "total"],
            y=[float(prior.cash), float(r["quantity_effect_eur"]), float(r["price_effect_eur"]), 0],
            text=[numero(x, 0) + " €" for x in (prior.cash, r["quantity_effect_eur"], r["price_effect_eur"], final.cash)],
            textposition="outside", connector=dict(line=dict(color=MUTED, width=1)),
            decreasing=dict(marker_color=ROSE), increasing=dict(marker_color=TEAL), totals=dict(marker_color=BLUE),
            hovertemplate="%{x}<br>%{text}<extra></extra>"))
        fig.update_layout(showlegend=False)
        _chart(fig, "demo_revision_bridge", "€ · simulazione", 310)
        st.caption(f"Prelievi +{numero(final.withdrawn - prior.withdrawn, 0)} MWh · prezzo invariato: {numero(final.buy, 0)} €/MWh.")
    st.caption(f"{s['eligible']}/{s['expected']} giorni verificabili · {s['revised']} rettifica · importi simulati, non fatture.")
    with st.expander("Dettagli e fonti"):
        st.caption("Importi con segno dal punto di vista del partecipante. Nessuna certificazione del settlement ufficiale.")
        st.dataframe([
            {"Versione": "1 · provvisorio", "I · MWh": float(prior.injected), "S · MWh": float(prior.storage_net),
             "T netto · MWh": float(prior.psv_net), "P · MWh": float(prior.withdrawn), "DS · MWh": float(prior.imbalance)},
            {"Versione": "2 · definitivo", "I · MWh": float(final.injected), "S · MWh": float(final.storage_net),
             "T netto · MWh": float(final.psv_net), "P · MWh": float(final.withdrawn), "DS · MWh": float(final.imbalance)},
        ], hide_index=True, width="stretch")
        st.markdown("**DS = I + S + T netto − P.** La simulazione riutilizza il motore di controllo del prototipo.")
        st.caption("Codice di Rete XCII · cap. 9 §3.1.2, PDF pp. 370–372; §4.4.2, p. 394. "
                   "Edizione fornita; applicabilità e convenzioni di arrotondamento da validare.")
        st.dataframe(pd.DataFrame([
            {"Giorno gas": data_it(date.fromisoformat(x["day"])), "DS definitivo · MWh": float(x["ds_mwh"]),
             "Importo simulato · €": float(x["cash_eur"]), "Rettifica · €": float(x["delta_cash_eur"])}
            for x in s["records"]]), hide_index=True, width="stretch")


def _due_text(value):
    return data_it(value) + (f" · {value:%H:%M}" if isinstance(value, datetime) else "")


def _operations(pack):
    o = pack["operations"]
    _heading("Operations")
    kpi_grid([
        ("Scadute", len(o["overdue"]), "", "Ancora aperte · tutte le date", 0, "rose"),
        ("In arrivo", len(o["upcoming"]), "", "Entro 7 giorni", 0, ""),
        ("Puntualità", o["on_time_pct"], "%", f"{o['on_time']}/{o['due']} scadenze trascorse · novembre", 0, "teal"),
    ])
    with st.container(key="demo_queue"):
        priorities = [("Scaduta", row) for row in o["overdue"]] + [("In scadenza", row) for row in o["upcoming"]]
        st.table(pd.DataFrame([{"Stato": status, "Attività": row["activity"],
                              "Scadenza": _due_text(row["due_at"])} for status, row in priorities]).set_index("Attività"))
    st.caption("Scadenze di esempio · orari CET · nessuno SLA Snam.")
    with st.expander("Briefing BSO"):
        for sentence in briefing(pack):
            label, text = sentence.split(" · ", 1)
            st.markdown("**" + label + "**")
            st.write(text)
        st.caption("Sintesi deterministica dei casi mostrati, senza AI remota.")
    with st.expander("Dettagli"):
        st.caption("La coda include attività di ottobre e novembre. La puntualità riguarda solo le scadenze di novembre già trascorse.")
        st.dataframe([{"Attività": row["activity"], "Area": row["area"].title(), "Stato": row["status"],
                       "Scadenza": _due_text(row["due_at"])} for row in o["rows"]], hide_index=True, width="stretch")


def _forecast():
    _heading("Previsioni", "Dati pubblici storici", "JRC · Italia · dicembre 2021")
    try:
        snapshot = load_forecast()
    except (OSError, ValueError, KeyError):
        st.error("Confronto storico non disponibile.")
        return
    r = snapshot["result"]
    model, baseline = r["scores"]["bayesian_multi"], r["scores"]["weekly"]
    improvement = 100 * (baseline["mae"] - model["mae"]) / baseline["mae"]
    records = pd.DataFrame(r["records"])
    dates = pd.to_datetime(records.target)
    span = f"{data_it(dates.min())} – {data_it(dates.max())}"
    kpi_grid([
        ("Errore medio · Bayes", model["mae"], "GWh/giorno", "Modello multivariato", 0, "blue"),
        ("Errore medio · riferimento", baseline["mae"], "GWh/giorno", "Riferimento settimanale", 0, ""),
        ("Errore in meno", improvement, "%", "Sul campione storico", 1, "teal" if improvement > 0 else ""),
    ])
    st.caption(f"Test storico D+1 · {r['test_n']} giorni · {span}.")
    with st.container(border=True):
        fig = go.Figure()
        fig.add_scatter(x=dates, y=records.bayesian_multi_high, line=dict(width=0), mode="lines",
                        showlegend=False, hoverinfo="skip", name="Limite superiore")
        fig.add_scatter(x=dates, y=records.bayesian_multi_low, line=dict(width=0), mode="lines", fill="tonexty",
                        fillcolor="rgba(131,180,255,.16)", name="Fascia nominale 80%", hoverinfo="skip")
        fig.add_scatter(x=dates, y=records.actual, name="Consumo osservato", mode="lines", line=dict(color=TEAL, width=3))
        fig.add_scatter(x=dates, y=records.bayesian_multi, name="Stima Bayes D+1", mode="lines", line=dict(color=BLUE, width=2, dash="dash"))
        fig.update_xaxes(tickformat="%d/%m")
        _chart(fig, "demo_forecast_history", "GWh/giorno gas", 325)
    st.caption(f"Fascia nominale 80% · copertura osservata {numero(model['coverage_80'], 1)}%: da calibrare.")
    with st.expander("Metodo e fonti"):
        st.caption("JRC ENaGaD v1.1 · archivio 2015–2021, da osservazioni Snam con possibili stime e revisioni. "
                   "Risultato precalcolato, non previsione attuale. Vantaggio limitato al campione mostrato.")
        st.markdown(f"[Dataset pubblico JRC]({snapshot['url']}) · [Licenza CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)")
        st.write("Backtest cronologico a un giorno, sulle ultime 28 origini valutabili. "
                 "Si usano gli ultimi 730 giorni dell’archivio; i consumi sono ipotizzati disponibili dopo due giorni. "
                 "Ogni finestra riaddestra e normalizza il modello con dati passati. "
                 "I ritardi sono ipotesi di studio; lo storico finale non ricostruisce le pubblicazioni dell’epoca.")
        labels = {"weekly": "Riferimento settimanale", "autoregressive": "Ridge autoregressivo", "multivariate": "Ridge multivariato",
                  "bayesian_base": "Bayes autoregressivo", "bayesian_multi": "Bayes multivariato"}
        st.dataframe([{"Modello": labels[m], "MAE · GWh/giorno": score["mae"], "WAPE · %": score["wape"]}
                      for m, score in r["scores"].items()], hide_index=True, width="stretch")
        st.dataframe(records[["target", "actual", "bayesian_multi", "bayesian_multi_low", "bayesian_multi_high"]].rename(columns={
            "target": "Giorno gas", "actual": "Osservato · GWh", "bayesian_multi": "Stima · GWh",
            "bayesian_multi_low": "Limite inferiore · GWh", "bayesian_multi_high": "Limite superiore · GWh"}),
            hide_index=True, width="stretch")
        st.caption("Attribuzione: Zaccarelli, Giaccaria, Feofilovs e Bolado-Lavín · Joint Research Centre, Commissione europea.")
        st.text("SHA-256 file sorgente: " + snapshot["source_sha256"])


def _developments():
    _heading("Sviluppi", "Prototipo", "Dalla demo al pilot")
    left, right = st.columns(2)
    with left, st.container(border=True):
        st.subheader("Nella demo")
        st.markdown("- SAS e variazioni simulate\n- Rettifiche spiegate\n- Scadenze e briefing\n- Backtest su dati JRC")
    with right, st.container(border=True):
        st.subheader("Nel pilot · da sviluppare")
        st.markdown("- Fonti autorizzate e versioni\n- Validazione con il team BSO\n- Assistente con citazioni\n- Ruoli, audit e monitoraggio")
    st.caption("Valore da misurare: tempi di verifica, copertura, eccezioni ed errore previsionale.")
    with st.expander("Perimetro e fonti"):
        st.caption("Integrazioni, benefici, risparmi e SLA non sono ancora validati o misurati.")
        st.dataframe([
            {"Area": "Balancing", "Evidenza": "Pubblicazioni intraday inventate", "Perimetro": "18 novembre 2026 · nessun collegamento Jarvis"},
            {"Area": "Settlement", "Evidenza": "Registro sintetico, calcoli effettivi", "Perimetro": "DEMO-001 · settembre 2026"},
            {"Area": "Operations", "Evidenza": "Attività e scadenze inventate", "Perimetro": "Situazione al 18 novembre 2026, 14:00 CET"},
            {"Area": "Previsioni", "Evidenza": "Archivio pubblico JRC ENaGaD v1.1", "Perimetro": "Dati 2015–2021 · test dicembre 2021"},
            {"Area": "Riferimenti", "Evidenza": "Edizioni Snam fornite e riferimenti verificati", "Perimetro": "Supporto alla lettura, non certificazione di vigenza"},
        ], hide_index=True, width="stretch")
        st.markdown("[Archivio pubblico JRC](https://doi.org/10.5281/zenodo.6364875) · "
                    "[Riferimenti BSO](https://github.com/Artisello/GasOps/blob/main/docs/BSO_REFERENCE_GUIDE.md)")


def home():
    """Compact landing page inside the complete application's sidebar shell."""
    with st.container(key="demo_content"):
        _overview(cases())


def page():
    from .workspace import picker
    st.caption("Esempi guidati · sola lettura")
    with st.container(key="demo_navigation"):
        view = picker("Esplora le potenzialità", VIEWS, key=NAV,
                      labels={"Balancing":"Bilanciamento","Settlement":"Rettifiche","Operations":"Attività e scadenze"})
    pack = cases()
    with st.container(key="demo_content"):
        {"In sintesi": lambda: _overview(pack,network=False), "Balancing": lambda: _balancing(pack),
         "Settlement": lambda: _settlement(pack), "Operations": lambda: _operations(pack),
         "Previsioni": _forecast, "Sviluppi": _developments}[view]()
    st.html('<footer class="demo-footer">Creata da Igor · demo indipendente, non ufficiale Snam</footer>')
