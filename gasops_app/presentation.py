"""An explorable, read-only BSO showcase with preloaded, traceable evidence."""
from datetime import date, datetime
from html import escape

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from .demo_cases import briefing, cases
from .demo_forecast import load as load_forecast
from .italiano import data_it, numero
from .visuals import AMBER, BLUE, MUTED, ROSE, TEAL, chip, kpi_grid

VIEWS = ("In sintesi", "Balancing", "Settlement", "Operations", "Previsioni", "Sviluppi")
NAV = "demo_view"


def _open(view):
    st.session_state[NAV] = view


def _heading(title, description, kind="Esempio simulato", period="18 novembre 2026 · ore 14:00 CET"):
    st.html('<div class="demo-section-meta">' + chip(kind, "historical" if "pubblic" in kind else "synthetic")
            + f'<span>{escape(period)}</span></div>')
    st.title(title)
    st.write(description)


def _insight(label, title, body, tone="teal"):
    st.html(f'<div class="demo-insight {escape(tone)}"><span>{escape(label)}</span>'
            f'<h3>{escape(title)}</h3><p>{escape(body)}</p></div>')


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


def _overview(pack):
    _heading("Il dato diventa una spiegazione.",
             "Una cabina di lettura per Balancing, Settlement e Operations. "
             "Esplora liberamente i casi: ogni risultato è già pronto.",
             "Scenari simulati", "Casi illustrativi · novembre e settembre 2026")
    b, r, o = pack["balancing"], pack["revision"], pack["operations"]
    with st.container(key="demo_cards"):
        columns = st.columns(3)
        cards = (
            ("Balancing", "Come sta cambiando il sistema?", numero(b["latest"], 0, signed=True), "GWh",
             "SAS di esempio alle 14:00", "Il cambio di segno emerge dalle pubblicazioni della giornata.", "teal"),
            ("Settlement", "Da dove arriva la rettifica?", numero(r["delta_cash_eur"], 0), "€",
             "Variazione dell’importo · 5 settembre", "Dal provvisorio al definitivo, con il motivo già spiegato.", "blue"),
            ("Operations", "Che cosa merita attenzione?", str(len(o["overdue"])), "scadute",
             "Attività aperte · al 18 novembre", "Una coda leggibile distingue ritardi e prossime scadenze.", "amber"),
        )
        for column, (view, question, value, unit, detail, potential, tone) in zip(columns, cards):
            with column, st.container(border=True, key="demo_card_" + view.lower()):
                st.html(f'<div class="demo-card {tone}"><span class="demo-eyebrow">{view}</span>'
                        f'<h2>{escape(question)}</h2><div class="demo-number">{escape(value)} '
                        f'<small>{escape(unit)}</small></div><span class="demo-card-detail">{escape(detail)}</span>'
                        f'<p>{escape(potential)}</p></div>')
                st.button("Esplora " + view, key="demo_open_" + view.lower(), on_click=_open,
                          args=(view,), width="stretch", icon=":material/arrow_forward:")
    left, right = st.columns([1.5, 1])
    with left, st.container(border=True):
        st.subheader("Un segnale. Una lettura immediata.")
        _sas_chart(b, "demo_home_sas", 230)
        st.caption("Esempio sintetico · SAS = sbilanciamento atteso del sistema. "
                   "La linea tratteggiata evidenzia il cambio di segno, non una soglia di allarme.")
    with right, st.container(border=True):
        st.subheader("Previsioni che si possono verificare")
        st.write("Il modello bayesiano è confrontato con un riferimento semplice su consumi italiani pubblici. "
                 "Risultati e fascia di incertezza sono già consultabili.")
        st.html(chip("JRC · dati pubblici storici 2015–2021", "historical"))
        st.button("Esplora le previsioni", key="demo_open_forecast", on_click=_open,
                  args=("Previsioni",), width="stretch", type="primary")
        st.caption("Archivio ENaGaD v1.1 · confronto sul dicembre 2021. Nessuna previsione attuale.")
        st.markdown("[Fonte: Joint Research Centre](https://doi.org/10.5281/zenodo.6364875)")
    st.caption("Potenzialità da sviluppare: collegare le fonti autorizzate, validare i controlli con il team "
               "e misurare il beneficio. La sezione Sviluppi distingue demo e pilot.")


def _balancing(pack):
    b = pack["balancing"]
    _heading("Il sistema cambia. Il segnale emerge.",
             "Leggi l’evoluzione delle pubblicazioni della stessa giornata e riconosci che cosa è cambiato.")
    kpi_grid([
        ("Ultima stima SAS", b["latest"], "GWh", "Pubblicazione di esempio · 14:00", 0, "teal"),
        ("Variazione dall’ultima pubblicazione", b["delta"], "GWh", "14:00 rispetto alle 13:00", 0, ""),
        ("Pubblicazioni confrontate", len(b["rows"]), "", "Stesso giorno gas · 07:00–14:00", 0, ""),
    ])
    left, right = st.columns([1.7, 1])
    with left, st.container(border=True):
        st.subheader("SAS nel corso della giornata")
        _sas_chart(b, "demo_balancing_sas", 310)
        st.caption("Giorno gas 18 novembre 2026 · orari Europe/Rome · dati interamente sintetici. "
                   "Il tratteggio indica il cambio di segno.")
    with right:
        change = b["sign_change_at"]
        _insight("COSA EMERGE", "Cambio di segno alle " + change.strftime("%H:%M") if change is not None else "Segno invariato",
                 "La stima attraversa lo zero nelle pubblicazioni mostrate. "
                 "L’ultimo aggiornamento aggiunge " + numero(b["delta"], 0) + " GWh rispetto al precedente.")
        _insight("PERCHÉ È UTILE", "Una lettura comune per il team",
                 "Riunire sequenza temporale, variazione e fonte aiuta a condividere il contesto del turno.", "blue")
    st.info("Il SAS riguarda l’intero sistema. Il saldo del singolo partecipante e il relativo importo "
            "si leggono nella sezione Settlement.", icon=":material/info:")
    with st.expander("Dati e riferimento del caso"):
        st.dataframe(b["rows"].assign(published_at=b["rows"].published_at.dt.strftime("18/11/2026 %H:%M CET"))
                     .rename(columns={"published_at": "Pubblicazione di esempio", "sas_gwh": "SAS · GWh"}),
                     hide_index=True, width="stretch")
        st.caption("Definizione: Codice di Rete XCII, cap. 9 §1.1, PDF p. 362. "
                   "Riferimento all’edizione fornita, non verifica di vigenza. Nessuna connessione Jarvis attiva nella demo.")
    st.caption("Nel pilot · collegamento a pubblicazioni autorizzate, cronologia delle revisioni "
               "e segnalazioni validate dal team. Nessuna azione automatica sulla rete.")


def _settlement(pack):
    r, s = pack["revision"], pack["settlement"]
    prior, final = pack["versions"]
    _heading("Una rettifica. Il motivo è già visibile.",
             "Lo stesso partecipante, lo stesso giorno gas, due versioni: dal numero alla spiegazione.",
             period="5 settembre 2026 · partecipante fittizio DEMO-001")
    kpi_grid([
        ("Importo provvisorio", prior.cash, "€", "Versione 1 · simulazione", 0, ""),
        ("Importo definitivo", final.cash, "€", "Versione 2 · simulazione", 0, ""),
        ("Impatto della rettifica", r["delta_cash_eur"], "€", "Definitivo meno provvisorio", 0, "rose"),
    ])
    left, right = st.columns([1.5, 1])
    with left, st.container(border=True):
        st.subheader("Da dove arrivano i " + numero(abs(r["delta_cash_eur"]), 0) + " €?")
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
    with right:
        _insight("SPIEGAZIONE DEL CASO", "Cambiano i prelievi, non i prezzi.",
                 f"I prelievi aumentano di {numero(final.withdrawn - prior.withdrawn, 0)} MWh. "
                 f"Il saldo passa da {numero(prior.imbalance, 0)} a {numero(final.imbalance, 0)} MWh. "
                 f"Il prezzo applicato resta {numero(final.buy, 0)} €/MWh.", "blue")
        _insight("CONTROLLO SUL MESE", f"{s['eligible']} giorni su {s['expected']} verificabili",
                 f"Il confronto provvisorio-definitivo rileva {s['revised']} giornata con variazioni nel mese di esempio. "
                 "Le altre giornate restano consultabili nel dettaglio.")
    st.caption("Importi sintetici con segno dal punto di vista del partecipante; non sono fatture. "
               "Il confronto spiega la differenza contabile, non certifica il settlement ufficiale.")
    with st.expander("Vedi componenti, versioni e riferimento"):
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
    st.caption("Nel pilot · riconciliazione con fonti e versioni autorizzate, gestione delle eccezioni "
               "e tracciabilità della revisione fino al controllo del team.")


def _due_text(value):
    return data_it(value) + (f" · {value:%H:%M} CET" if isinstance(value, datetime) else " · intera giornata")


def _operations(pack):
    o = pack["operations"]
    _heading("Le priorità si leggono a colpo d’occhio.",
             "Le attività già scadute vengono prima di quelle future. Un briefing riunisce le evidenze delle tre aree.")
    kpi_grid([
        ("Scadute e ancora aperte", len(o["overdue"]), "attività", "Tutte le scadenze del registro demo", 0, "rose"),
        ("Entro sette giorni", len(o["upcoming"]), "attività", "Aperte, non ancora scadute", 0, ""),
        ("Completate in tempo", o["on_time_pct"], "%", f"{o['on_time']}/{o['due']} scadenze trascorse · novembre", 0, "teal"),
    ])
    left, right = st.columns([1.5, 1])
    with left, st.container(border=True):
        st.subheader("La coda di attenzione")
        priorities = [("Scaduta", row) for row in o["overdue"]] + [("In scadenza", row) for row in o["upcoming"]]
        st.dataframe([{"Stato": status, "Attività": row["activity"], "Area": row["area"].title(),
                       "Scadenza di esempio": _due_text(row["due_at"])} for status, row in priorities],
                     hide_index=True, width="stretch")
        st.caption("Scadenze inventate per la demo: non sono obblighi o SLA Snam. "
                   "I ritardi includono attività di ottobre; il tasso di puntualità riguarda soltanto novembre.")
    with right, st.container(border=True):
        st.subheader("Briefing già leggibile")
        for sentence in briefing(pack):
            label, text = sentence.split(" · ", 1)
            st.markdown("**" + label + "**")
            st.write(text)
        st.caption("Sintesi generata da regole sui casi mostrati. Nessuna chiamata a un modello AI remoto.")
    st.caption("Nel pilot · assegnazioni e responsabilità concordate, collegamenti alle evidenze "
               "e assistente documentale con citazioni da sottoporre a revisione umana.")


def _forecast():
    _heading("Una previsione vale quanto la sua verifica.",
             "Il modello bayesiano viene confrontato con un riferimento settimanale sulle stesse date. "
             "La fascia mostra anche l’incertezza.", "Dati pubblici storici", "Italia · archivio JRC 2015–2021")
    try:
        snapshot = load_forecast()
    except (OSError, ValueError, KeyError):
        st.error("Il risultato storico non è disponibile per questa versione della demo.")
        return
    r = snapshot["result"]
    model, baseline = r["scores"]["bayesian_multi"], r["scores"]["weekly"]
    improvement = 100 * (baseline["mae"] - model["mae"]) / baseline["mae"]
    records = pd.DataFrame(r["records"])
    dates = pd.to_datetime(records.target)
    span = f"{data_it(dates.min())} – {data_it(dates.max())}"
    st.caption(f"Confronto D+1 · {r['test_n']} giorni gas · {span}. Risultato storico precalcolato con il motore del prototipo.")
    kpi_grid([
        ("Errore medio · Bayes multivariato", model["mae"], "GWh/giorno", "MAE · errore assoluto medio", 0, "blue"),
        ("Errore medio · riferimento settimanale", baseline["mae"], "GWh/giorno", "Stesse date e dati disponibili", 0, ""),
        ("Riduzione dell’errore nel campione", improvement, "%", "Rispetto al riferimento · non un risultato futuro", 1, "teal" if improvement > 0 else ""),
    ])
    with st.container(border=True):
        st.subheader("Consumi osservati e stime del modello")
        fig = go.Figure()
        fig.add_scatter(x=dates, y=records.bayesian_multi_high, line=dict(width=0), mode="lines",
                        showlegend=False, hoverinfo="skip", name="Limite superiore")
        fig.add_scatter(x=dates, y=records.bayesian_multi_low, line=dict(width=0), mode="lines", fill="tonexty",
                        fillcolor="rgba(131,180,255,.16)", name="Fascia nominale 80%", hoverinfo="skip")
        fig.add_scatter(x=dates, y=records.actual, name="Consumo osservato", mode="lines", line=dict(color=TEAL, width=3))
        fig.add_scatter(x=dates, y=records.bayesian_multi, name="Stima Bayes D+1", mode="lines", line=dict(color=BLUE, width=2, dash="dash"))
        fig.update_xaxes(tickformat="%d/%m")
        _chart(fig, "demo_forecast_history", "GWh/giorno gas", 325)
    left, right = st.columns(2)
    with left:
        _insight("POTENZIALITÀ", "Misurare il modello prima di fidarsi",
                 "Consumi recenti, calendario e settori industriale, elettrico e distribuzione entrano nel confronto. "
                 "Il vantaggio mostrato vale per questo campione storico.", "blue")
    with right:
        _insight("INCERTEZZA VISIBILE", numero(model["coverage_80"], 1) + "% dei valori nella fascia",
                 "La fascia nominale è all’80%: nel campione la copertura è inferiore. "
                 "La calibrazione va migliorata e verificata su altri periodi.", "amber")
    st.caption("Fonte: JRC ENaGaD v1.1, da osservazioni Snam; i dati possono includere stime e revisioni della fonte. "
               "Non è una previsione per oggi, né una misura di accuratezza operativa in produzione.")
    st.markdown(f"[Dataset pubblico JRC]({snapshot['url']}) · [Licenza CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)")
    with st.expander("Metodo, risultati completi e dati del grafico"):
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
    st.caption("Nel pilot · più periodi di validazione, dati e versioni disponibili al momento della previsione, "
               "calibrazione dell’incertezza e monitoraggio dell’errore.")


def _developments():
    _heading("Dalla dimostrazione a un pilot misurabile.",
             "La demo rende visibile il potenziale. Integrazioni e uso operativo richiedono uno sviluppo dedicato.",
             "Perimetro del prototipo", "Funzionalità dimostrate e sviluppi proposti")
    left, right = st.columns(2)
    with left, st.container(border=True):
        st.subheader("Già dimostrato qui")
        for title, body in (
            ("Leggere un cambiamento", "Sequenza e variazione del SAS su pubblicazioni simulate."),
            ("Spiegare una rettifica", "Calcolo delle due versioni, effetto quantità e prezzo, controlli su 30 giorni di esempio."),
            ("Riunire le priorità", "Scadenze ordinate e briefing deterministico sulle evidenze mostrate."),
            ("Verificare una previsione", "Backtest reale su archivio JRC con baseline e incertezza visibile."),
        ):
            st.markdown("**" + title + "**")
            st.write(body)
    with right, st.container(border=True):
        st.subheader("Da sviluppare con il team")
        for title, body in (
            ("Fonti autorizzate e versioni", "Connettori, permessi, controlli di qualità e allineamento del giorno gas."),
            ("Validazione BSO", "Regole concordate, riconciliazione sui casi reali e gestione delle eccezioni."),
            ("Assistente con evidenze", "Ricerca documentale e risposte con citazioni, accessi protetti e revisione umana."),
            ("Servizio scalabile", "Ruoli, audit, monitoraggio, continuità operativa e integrazione nei processi."),
        ):
            st.markdown("**" + title + "**")
            st.write(body)
    _insight("COME MISURARE IL VALORE", "Un perimetro piccolo. Un confronto concreto.",
             "Nel pilot confrontare tempo di verifica, eccezioni rilevate, copertura dei dati ed errore previsionale "
             "con una baseline concordata. Benefici, risparmi e SLA non sono ancora misurati.")
    with st.expander("Fonti e trasparenza della demo"):
        st.dataframe([
            {"Area": "Balancing", "Evidenza": "Pubblicazioni intraday inventate", "Perimetro": "18 novembre 2026 · nessun collegamento Jarvis"},
            {"Area": "Settlement", "Evidenza": "Registro sintetico, calcoli effettivi", "Perimetro": "DEMO-001 · settembre 2026"},
            {"Area": "Operations", "Evidenza": "Attività e scadenze inventate", "Perimetro": "Situazione al 18 novembre 2026, 14:00 CET"},
            {"Area": "Previsioni", "Evidenza": "Archivio pubblico JRC ENaGaD v1.1", "Perimetro": "Dati 2015–2021 · test dicembre 2021"},
            {"Area": "Riferimenti", "Evidenza": "Edizioni Snam fornite e riferimenti verificati", "Perimetro": "Supporto alla lettura, non certificazione di vigenza"},
        ], hide_index=True, width="stretch")
        st.markdown("[Archivio pubblico JRC](https://doi.org/10.5281/zenodo.6364875) · "
                    "[Riferimenti BSO](https://github.com/Artisello/GasOps/blob/main/docs/BSO_REFERENCE_GUIDE.md)")


def page():
    st.html('<div class="demo-masthead"><div class="gas-brand"><div class="gas-mark" aria-hidden="true">'
            '<span></span><span></span><span></span></div><div><strong>I.G.O.R.</strong>'
            '<small>Intelligent Gas Operations &amp; Risk</small></div></div>'
            '<div class="demo-masthead-note"><strong>Il potenziale BSO, in 5 minuti.</strong>'
            '<span>Demo esplorabile · sola lettura</span></div></div>')
    with st.container(key="demo_navigation"):
        view = st.radio("Esplora le potenzialità", VIEWS, key=NAV, horizontal=True, label_visibility="collapsed")
    pack = cases()
    with st.container(key="demo_content"):
        {"In sintesi": lambda: _overview(pack), "Balancing": lambda: _balancing(pack),
         "Settlement": lambda: _settlement(pack), "Operations": lambda: _operations(pack),
         "Previsioni": _forecast, "Sviluppi": _developments}[view]()
    st.html('<footer class="demo-footer"><strong>Prototipo per Snam · creato da Igor</strong>'
            '<span>Progetto indipendente, non ufficiale. Nessun dato operativo Snam o invio di ordini.</span></footer>')
