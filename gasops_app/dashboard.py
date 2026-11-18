"""Panoramica del mercato e analisi delle serie storiche."""

from datetime import date
from html import escape

import pandas as pd
import streamlit as st

from .agents import MarketContext
from .data import FIELDS, period_text
from .forecast import AUTOMATIC, MODELS
from .italiano import GRAVITA, MODALITA, MODELLI, data_it, numero
from .models import Kind, Provider
from .session import RUN_ANALYSIS, applicable_run, launch, preview_market, source_filters
from .visuals import AMBER, BLUE, ROSE, TEAL, breakdown_chart, chip, demand_chart, error_chart
from .visuals import forecast_readout, heading, header, kind_tag, kpi, local_time, mini_chart, plot, rows, steps


def _change(facts: dict, field: str) -> str:
    delta = facts.get(f"{field}_change_pct")
    return f"{numero(delta, signed=True)}% {facts['comparison']}" if delta is not None else "Confronto non disponibile"


def _metrics(context: MarketContext) -> None:
    facts = context.facts
    if not facts:
        st.warning("La serie non contiene consumi utilizzabili. Consulta i controlli qualità.")
        return
    origin = context.bundle.origin
    if origin.grain == "monthly":
        specs = [
            ("Consumo interno", "demand_gwh", "GWh/mese", _change(facts, "demand_gwh"), 1, "teal"),
            ("Disponibilità contabile", "supply_gwh", "GWh/mese", "Consumo interno calcolato", 1, ""),
            ("Importazioni nette", "net_imports_gwh", "GWh/mese", "Importazioni − esportazioni", 1, ""),
            ("Variazione delle scorte", "stock_change_gwh", "GWh/mese", "Positiva in accumulo", 1, "blue"),
            ("Prezzo PSV · ARERA", "price_eur_mwh", "€/MWh", "Media mensile CMEM,m", 2, ""),
        ]
    elif origin.archive:
        specs = [(title, field, "GWh/giorno", _change(facts, field), 1, tone) for title, field, tone in (
            ("Consumo nazionale", "demand_gwh", "teal"), ("Industria", "industry_gwh", ""),
            ("Generazione elettrica", "power_gwh", "blue"), ("Residenziale e terziario", "distribution_gwh", ""),
        )]
    else:
        specs = [
            ("Domanda di gas", "demand_gwh", "GWh/giorno", _change(facts, "demand_gwh"), 1, "teal"),
            ("Offerta di gas", "supply_gwh", "GWh/giorno", _change(facts, "supply_gwh"), 1, ""),
            ("Saldo semplificato", "gap_gwh", "GWh/giorno", "Offerta − domanda", 1,
             "rose" if (facts.get("gap_gwh") or 0) < 0 else "teal"),
            ("Copertura della domanda", "coverage_pct", "%", "Offerta ÷ domanda", 1, "blue"),
            ("Prezzo di esempio", "price_eur_mwh", "€/MWh", _change(facts, "price_eur_mwh"), 2, ""),
        ]
    for col, (title, field, units, description, decimals, tone) in zip(st.columns(len(specs)), specs, strict=True):
        with col:
            kpi(title, facts.get(field), units, description if facts.get(field) is not None else "Valore non disponibile",
                decimals, tone)


def _state(source: Provider) -> str:
    if source.refresh_failed:
        return "Cache · aggiornamento non riuscito"
    return "Cache verificata" if source.cached else "Acquisizione diretta"


def _source_panel(context: MarketContext) -> None:
    origin = context.bundle.origin
    facts = context.facts
    flags = context.bundle.rows.loc[context.bundle.rows["period"].eq(facts.get("period")), "source_flag"]
    raw_flag = next((flag for flag in flags if flag), "")
    status = "Archivio locale" if origin.archive else "Serie di esempio" if origin.kind == Kind.SYNTHETIC else _state(origin)
    details = [("Fonte", origin.name), ("Ultimo periodo", facts.get("label", "Non disponibile")),
               ("Stato", status)]
    if not origin.archive:
        details.append(("Data della fonte", local_time(origin.published_at)))
    if raw_flag:
        flag_labels = {"p": "provvisorio", "O": "dato originale", "E": "stima della fonte"}
        details.append(("Nota sulla misura", ", ".join(flag_labels.get(flag, flag) for flag in raw_flag.split())))
    for feed in origin.companions:
        period = data_it(date.fromisoformat(feed.latest_period), day=False) if feed.latest_period else "Non disponibile"
        details.extend([(feed.name, period), ("Stato ARERA", _state(feed))])
    rows(details)
    links = [f"[{feed.name}]({feed.url})" for feed in (origin, *origin.companions) if feed.url]
    if links:
        st.markdown(" · ".join(links))


def _quality_panel(context: MarketContext) -> None:
    issues = context.inspection.findings
    review = [finding for finding in issues if finding.severity != "info"]
    with st.container(border=True, key="panel_quality"):
        heading("Qualità dei dati", chip(f"{len(review)} DA RIVEDERE", "review") if review else chip("CONTROLLATI", "ok"))
        if review:
            selected = next((finding for finding in review if finding.id.startswith("outlier")), review[0])
            st.html(f'<div class="gas-alert"><strong>{escape(selected.title)}</strong>'
                    f'<small>{escape(selected.detail)}</small></div>')
        else:
            st.caption("Nessun rilievo richiede revisione.")
        if issues:
            with st.expander("Controlli e annotazioni"):
                for finding in issues:
                    st.markdown(f"**{finding.title}** · {GRAVITA[finding.severity]}")
                    st.caption(finding.detail)


def _charts(context: MarketContext, horizon: int, page: str, height: int = 330) -> pd.DataFrame:
    origin = context.bundle.origin
    data = context.inspection.usable.tail(horizon)
    title = ("Consumo interno e disponibilità" if origin.grain == "monthly" else
             "Consumi nazionali" if origin.archive else "Domanda e offerta")
    projection = context.projection
    heading(title, kind_tag(Kind.FORECAST) if projection.points else "")
    if not data["demand_gwh"].notna().any():
        st.info("Nessun consumo utilizzabile nel periodo selezionato.")
    else:
        if projection.points:
            forecast_readout(projection.points[0], origin.grain, historical=origin.archive)
        plot(demand_chart(data, projection, origin.grain, height=height), key=f"{page}_demand")
        horizon_text = "14 giorni gas" if origin.grain == "daily" else "6 mesi"
        if projection.points:
            model = MODELLI[projection.model]
            note = " · scelto dallo storico" if context.model == AUTOMATIC and projection.model in context.forecast_scores else ""
            st.caption(f"{model}{note} · orizzonte di {horizon_text}")
            if context.model not in (AUTOMATIC, projection.model):
                st.caption(f"Modello non disponibile per {MODELLI[context.model].lower()}.")
        else:
            st.caption("Serve una serie storica più lunga per generare una stima.")
    return data


def _supporting_charts(context: MarketContext, data: pd.DataFrame, page: str) -> None:
    origin = context.bundle.origin
    left, right = st.columns(2, gap="medium")
    with left, st.container(border=True, key=f"panel_{page}_detail"):
        if origin.grain == "monthly":
            heading("Produzione, importazioni e scorte", "<small>GWh/mese</small>")
            plot(breakdown_chart(data, [
                ("net_imports_gwh", "Importazioni nette", BLUE), ("production_gwh", "Produzione interna", TEAL),
                ("stock_change_gwh", "Variazione scorte", AMBER),
            ], origin.grain), f"{page}_balance")
        elif origin.archive:
            heading("Industria e generazione", "<small>GWh/giorno</small>")
            plot(breakdown_chart(data, [
                ("industry_gwh", "Industria", BLUE), ("power_gwh", "Generazione elettrica", AMBER),
            ], origin.grain), f"{page}_sector")
        else:
            heading("Saldo semplificato", "<small>GWh/giorno</small>")
            gap = data["supply_gwh"] - data["demand_gwh"]
            plot(mini_chart(gap, "Offerta − domanda", origin.grain, "GWh", ROSE, zero=True), f"{page}_gap")
    with right, st.container(border=True, key=f"panel_{page}_price"):
        if origin.archive:
            heading("Residenziale e terziario", "<small>GWh/giorno</small>")
            plot(mini_chart(data["distribution_gwh"], "Residenziale e terziario", origin.grain,
                            "GWh", TEAL), f"{page}_distribution")
        else:
            title = "Prezzo PSV · ARERA" if origin.grain == "monthly" else "Prezzo di esempio"
            heading(title, "<small>€/MWh</small>")
            price = data["price_eur_mwh"]
            if price.notna().any():
                plot(mini_chart(price, title, origin.grain, "€/MWh", AMBER), f"{page}_price")
                if origin.grain == "monthly":
                    st.caption("Media mensile del PSV day-ahead pubblicata come CMEM,m.")
            else:
                st.caption("Prezzo ufficiale assente per il periodo selezionato.")


def overview() -> None:
    top, controls = st.container(), st.container()
    with controls:
        selection = source_filters("overview")
    with top:
        clicked = header("Panoramica del mercato", selection.meta, RUN_ANALYSIS, disabled=selection.bundle is None)
    if not selection.bundle:
        return
    if clicked:
        launch(selection, full=True)

    context = preview_market(selection)
    _metrics(context)
    main, desk = st.columns([2.42, 1], gap="medium")
    with main:
        with st.container(border=True, key="panel_main"):
            data = _charts(context, selection.periods, "overview", height=314)
        _supporting_charts(context, data, "overview")
    with desk:
        with st.container(border=True, key="panel_source"):
            heading("Fonti e aggiornamento")
            _source_panel(context)
        _quality_panel(context)
        run = applicable_run(selection)
        with st.container(border=True, key="panel_agents"):
            heading("Stato degli agenti", chip("ULTIMA ANALISI", "ok") if run else chip("PRONTI"))
            st.html(steps(run))
    if run:
        with st.container(border=True, key="panel_overview_brief"):
            heading("Sintesi operativa", chip(MODALITA[run.mode]))
            for result in run.results.values():
                st.text(result.summary)
            if run.interpretation:
                st.caption("Interpretazione del modello da rivedere")
                st.text(run.interpretation)


def _model_comparison(context: MarketContext) -> None:
    projection = context.projection
    scores = context.forecast_scores
    with st.container(border=True, key="panel_market_errors"):
        heading("Confronto dei modelli")
        if scores:
            ordered = sorted(scores, key=lambda model: scores[model].mae)
            st.caption(f"Errore medio sul periodo successivo, sugli stessi {scores[ordered[0]].periods} periodi storici. "
                       "Valori più bassi indicano stime più vicine ai consumi osservati.")
            st.dataframe([{
                "Modello": MODELLI[name], "Errore medio (GWh)": numero(scores[name].mae, 1) if name in scores else "—",
                "RMSE (GWh)": numero(scores[name].rmse, 1) if name in scores else "—",
                "WAPE (%)": numero(scores[name].wape, 1) if name in scores else "—",
                "Bias (GWh)": numero(scores[name].bias, 1) if name in scores else "—",
                "In uso": "Sì" if name == projection.model else "",
            } for name in (*ordered, *(model for model in MODELS if model not in scores))],
                hide_index=True, width="stretch")
        else:
            st.caption("Servono almeno 12 osservazioni confrontabili per confrontare gli errori dei modelli.")
        with st.expander("Come leggere la fascia e verificare gli errori"):
            if projection.interval_kind == "posterior":
                st.write("La fascia all’80% descrive l’incertezza stimata dal modello bayesiano. "
                         "Le previsioni sono state ricostruite usando solo i dati disponibili prima di ogni periodo.")
                if projection.interval_coverage is not None:
                    included = round(projection.interval_coverage * projection.coverage_samples)
                    st.caption(f"Nel test storico, la fascia ha incluso {included} osservazioni su "
                               f"{projection.coverage_samples} per il periodo successivo.")
            elif projection.interval_kind == "model_based":
                st.write("Fascia predittiva state-space all’80%, condizionata ai parametri stimati. Non è una fascia bayesiana; il backtest aggiorna lo stato senza ristimare i parametri a ogni passo.")
                if projection.interval_coverage is not None:
                    st.caption(f"Copertura osservata: {projection.interval_coverage:.1%} su {projection.coverage_samples} periodi.")
            else:
                st.write("La fascia si basa sugli errori delle previsioni ricostruite sullo storico.")
            if projection.details:
                st.caption(projection.details)
            if projection.backtest:
                plot(error_chart(projection, context.bundle.origin.grain), "market_error")


def market() -> None:
    top, controls = st.container(), st.container()
    with controls:
        selection = source_filters("market")
    with top:
        header("Mercato e previsioni", selection.meta)
    if not selection.bundle:
        return

    context = preview_market(selection)
    origin = context.bundle.origin
    _metrics(context)
    with st.container(border=True, key="panel_market_chart"):
        visible = _charts(context, selection.periods, "market", height=348)
    _model_comparison(context)
    _supporting_charts(context, visible, "market")
    sources, quality = st.columns([1.3, 1], gap="medium")
    with sources:
        with st.container(border=True, key="panel_market_notes"):
            heading("Lettura del mercato")
            facts = context.facts
            if facts:
                st.write(f"Variazione dei consumi {_change(facts, 'demand_gwh').lower()}.")
                if "weekend_vs_weekday_pct" in facts:
                    st.write(f"Consumi medi nel fine settimana {numero(facts['weekend_vs_weekday_pct'], signed=True)}% "
                             "rispetto ai giorni feriali negli ultimi 84 giorni della serie.")
                if "peak_month" in facts:
                    st.write(f"Nei periodi disponibili, la media stagionale dei consumi è massima a "
                             f"{facts['peak_month']} e minima a {facts['low_month']}.")
                if origin.grain == "monthly":
                    st.caption("La disponibilità contabile descrive il bilancio mensile nazionale. "
                               "I saldi di trasporto richiedono osservazioni operative dedicate.")
            with st.expander("Dettaglio delle fonti"):
                _source_panel(context)
                for feed in (origin, *origin.companions):
                    st.caption(feed.description)
                    if not origin.archive and origin.kind != Kind.SYNTHETIC:
                        st.text(f"Acquisizione {feed.name} · {local_time(feed.retrieved_at)}")
                st.text(f"Impronta dati SHA-256 · {context.bundle.fingerprint}")
    with quality:
        _quality_panel(context)
    with st.expander("Osservazioni e previsioni"):
        raw = context.bundle.rows
        start = visible.index.min().date().isoformat() if len(visible) else ""
        st.caption("Record originali nel periodo del grafico, incluse le note della fonte.")
        headings = {**FIELDS, "period": "Periodo", "source_flag": "Flag della fonte", "timestamp_utc": "Inizio UTC"}
        if origin.grain == "monthly":
            headings["supply_gwh"] = "Disponibilità contabile"
            headings["price_eur_mwh"] = "Prezzo CMEM,m (€/MWh)"
        wanted = ["period", "timestamp_utc", *origin.fields, "source_flag"]
        st.dataframe(raw.loc[raw["period"] >= start, wanted].rename(columns=headings), hide_index=True, width="stretch")
        if context.projection.points:
            st.caption("PREVISIONE · GWh per periodo")
            projected = [{"Periodo": period_text(pd.Timestamp(p.period), origin.grain), "Stima (GWh)": numero(p.estimate),
                          "Estremo inferiore": numero(p.lower_80), "Estremo superiore": numero(p.upper_80)}
                         for p in context.projection.points]
            st.dataframe(projected, hide_index=True, width="stretch")
