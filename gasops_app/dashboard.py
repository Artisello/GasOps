"""Panoramica del mercato e analisi delle serie storiche."""

from datetime import date
import json
from html import escape

import pandas as pd
import streamlit as st

from .agents import MarketContext
from .data import FIELDS, period_text
from .forecast import AUTOMATIC, MODELS
from .italiano import GRAVITA, MODALITA, MODELLI, data_it, numero
from .models import AGENT_LABELS, Agent, Kind, Provider
from .session import analysis_label, briefing_run, launch, preview_market, source_filters
from .reports import markdown
from .visuals import AMBER, BLUE, ROSE, TEAL, breakdown_chart, chip, demand_chart, error_chart
from .visuals import forecast_readout, heading, header, info, kind_tag, kpi_grid, local_time, mini_chart, plot, rows, steps


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
            ("Gas consumato", "demand_gwh", "GWh/mese", _change(facts, "demand_gwh"), 1, "teal"),
            ("Disponibilità contabile", "supply_gwh", "GWh/mese", "Bilancio statistico, non capacità", 1, ""),
            ("Importazioni nette", "net_imports_gwh", "GWh/mese", "Importazioni − esportazioni", 1, ""),
            ("Variazione delle scorte", "stock_change_gwh", "GWh/mese", "Positiva in accumulo", 1, "blue"),
            ("Prezzo del gas · PSV", "price_eur_mwh", "€/MWh", "Media mensile CMEM,m", 2, ""),
        ]
    elif origin.grain == "daily" and "distribution_gwh" in origin.fields:
        specs = [(title, field, "GWh/giorno", _change(facts, field), 1, tone) for title, field, tone in (
            ("Consumo nazionale" if origin.archive else "Prelievi sulla rete SRG", "demand_gwh", "teal"), ("Industria", "industry_gwh", ""),
            ("Centrali elettriche", "power_gwh", "blue"), ("Residenziale e terziario" if origin.archive else "Distribuzione", "distribution_gwh", ""),
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
    kpi_grid([(title,facts.get(field),units,description if facts.get(field) is not None else "Dato non disponibile",
               decimals,tone) for title,field,units,description,decimals,tone in specs])


def _plain_market(context: MarketContext) -> str:
    facts=context.facts
    origin=context.bundle.origin
    if not facts or facts.get("demand_gwh") is None:
        return "Consumi non disponibili per la fonte selezionata."
    delta=facts.get("demand_gwh_change_pct")
    if delta is None:
        return "Dati insufficienti per confrontare i consumi."
    direction="in aumento" if delta>0 else "in diminuzione" if delta<0 else "invariati"
    magnitude=f" ({numero(delta,signed=True)}%)" if delta else ""
    comparison="tra gli ultimi sette giorni e i sette precedenti" if origin.grain=="daily" else "rispetto al mese precedente"
    subject=("Nella simulazione, i consumi" if origin.kind==Kind.SYNTHETIC else
             "Nell’archivio storico, i consumi" if origin.archive else
             "I prelievi osservati sulla rete SRG" if origin.grain=="daily" else "I consumi nazionali")
    return subject+" sono "+direction+magnitude+" "+comparison+"."




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
    if not origin.archive and origin.kind != Kind.SYNTHETIC:
        if origin.published_at is not None:
            details.append(("Data della fonte", local_time(origin.published_at)))
        details.append(("Ultima acquisizione", local_time(origin.retrieved_at)))
    if raw_flag:
        flag_labels = {"p": "provvisorio", "O": "dato originale", "E": "stima della fonte"}
        details.append(("Nota sulla misura", ", ".join(flag_labels.get(flag, flag) for flag in raw_flag.split())))
    for feed in origin.companions:
        period = data_it(date.fromisoformat(feed.latest_period), day=False) if feed.latest_period else "Non disponibile"
        details.extend([(feed.name, period), ("Stato ARERA", _state(feed))])
    rows(details)
    if origin.grain == "daily" and "distribution_gwh" in origin.fields and not origin.archive:
        st.caption("Prelievi SRG · perimetro parziale")
        info("Info perimetro","Tre aggregati ENTSOG/SRG: proxy parziale, non domanda nazionale ufficiale. Nessun prezzo o offerta osservati.",origin.description)
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
             "Consumi nazionali" if origin.archive else "Prelievi sulla rete SRG" if "distribution_gwh" in origin.fields else "Domanda e offerta")
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
        elif origin.grain == "daily" and "distribution_gwh" in origin.fields:
            heading("Industria e generazione", "<small>GWh/giorno</small>")
            plot(breakdown_chart(data, [
                ("industry_gwh", "Industria", BLUE), ("power_gwh", "Generazione elettrica", AMBER),
            ], origin.grain), f"{page}_sector")
        else:
            heading("Saldo semplificato", "<small>GWh/giorno</small>")
            gap = data["supply_gwh"] - data["demand_gwh"]
            plot(mini_chart(gap, "Offerta − domanda", origin.grain, "GWh", ROSE, zero=True), f"{page}_gap")
    with right, st.container(border=True, key=f"panel_{page}_price"):
        if origin.grain == "daily" and "distribution_gwh" in origin.fields:
            label = "Residenziale e terziario" if origin.archive else "Distribuzione"
            heading(label, "<small>GWh/giorno</small>")
            plot(mini_chart(data["distribution_gwh"], label, origin.grain,
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


def _briefing_panel(selection) -> None:
    with st.container(border=True,key="panel_overview_brief"):
        lead,action=st.columns([2.2,1],vertical_alignment="center")
        with lead:
            st.subheader("Bollettino di mercato")
            st.caption("Cosa sta succedendo e cosa controllare.")
        with action:
            clicked=st.button(analysis_label(),type="primary",icon=":material/auto_awesome:",width="stretch",key="analysis_launch",disabled=selection.bundle is None)
        with st.container():
            info("Info bollettino","Il pulsante esegue i sei agenti e i controlli locali. Il modello AI, se selezionato, interpreta i risultati condivisibili.","Non modifica le fonti, i calcoli o le posizioni operative. Scenari e settlement possono essere dimostrativi.")
        extras=[]
        if st.session_state.get("briefing_gie"):
            extras.append("GIE (AGSI+, ALSI e IIP)")
        if st.session_state.get("briefing_weather"):
            extras.append("Open-Meteo")
        if extras:
            st.caption("Fonti aggiuntive: "+", ".join(extras))
        if clicked:
            generated=launch(selection,full=True)
            if generated is None:
                st.error("Il nuovo bollettino non è stato generato. L’eventuale risultato precedente resta qui sotto.")
        run=briefing_run()
        if run is None:
            st.caption("Nessun bollettino generato. Premi il pulsante in alto: il risultato apparirà qui.")
        else:
            matches=bool(selection.bundle and run.input_sha256==selection.bundle.fingerprint
                         and run.assumptions.get("model")==selection.model)
            if not matches:
                st.warning("Bollettino precedente: fonte o modello previsionale attuale diverso. Genera un nuovo report per aggiornare i risultati.")
            actual_ai=run.mode=="LLM-assisted" and bool(run.interpretation)
            st.markdown("**Ultimo bollettino generato**")
            st.caption(local_time(run.finished_at)+" · "+run.source.name+" · "+
                       (run.source.latest_period or "periodo non indicato"))
            if actual_ai:
                st.caption("Interpretazione AI · "+(run.model or "modello non indicato"))
                st.text(run.interpretation)
                st.caption("Interpretazione da verificare · "+", ".join(AGENT_LABELS[a] for a in run.interpretation_sources))
            else:
                st.caption("Report deterministico · nessuna interpretazione AI generata.")
            for warning in run.warnings:
                st.warning(warning)
            completed=sum(r.status=="completed" for r in run.results.values())
            issues=sum(f.severity in ("high","medium") for f in run.findings)
            c1,c2,c3=st.columns(3)
            c1.metric("Controlli completati",f"{completed}/{len(run.steps)}")
            c2.metric("Rilievi da verificare",issues)
            c3.metric("Modalità effettiva","AI" if actual_ai else "Deterministica")
            if run.summary:
                st.text(run.summary)
            public=run.assumptions.get("public_operational_context") or {}
            if public:
                with st.expander("Fonti operative consultate"):
                    for name,source in public.items():
                        status={"available":"Disponibile","stale":"Non recente","unavailable":"Non disponibile"}.get(source.get("status"),"Stato non indicato")
                        st.text(f"{source.get('source',name)} · {status} · {source.get('gas_day') or source.get('acquired') or 'data non indicata'}")
                        if source.get("reason"):
                            st.text(source["reason"])
                    st.json(public,expanded=False)
            with st.expander("Dettaglio completo · scenari, normativa e settlement"):
                st.caption("Scenari e regolazione economica possono utilizzare ipotesi dimostrative, non posizioni reali.")
                for agent,item in run.results.items():
                    st.markdown("**"+AGENT_LABELS[agent]+"**")
                    st.text(item.summary)
                st.html(steps(run))
            d1,d2=st.columns(2)
            d1.download_button("Scarica bollettino",markdown(run,{}),f"gasops-{run.id[:10]}.md",
                               mime="text/markdown",key="overview_brief_md",width="stretch")
            d2.download_button("Scarica dati JSON",json.dumps(run.model_dump(mode="json"),ensure_ascii=False,indent=2),
                               f"gasops-{run.id[:10]}.json",mime="application/json",key="overview_brief_json",width="stretch")
            st.markdown("[Centro operativo AI: domande, storico e riscontri](/operations)")
        # AI connection controls are in the sidebar.


def overview() -> None:
    top,controls=st.container(),st.container()
    with controls:
        selection=source_filters("overview")
    with top:
        header("Panoramica del mercato",selection.meta)
    if not selection.bundle:
        _briefing_panel(selection)
        return
    context=preview_market(selection)
    st.subheader("Il mercato in breve")
    st.caption("Ultimo dato · "+context.facts.get("label","Non disponibile"))
    _metrics(context)
    st.write(_plain_market(context))
    _briefing_panel(selection)
    with st.container(border=True,key="panel_main"):
        _charts(context,selection.periods,"overview",height=345)
        info("Come leggere il grafico","Linea continua: consumi osservati. Linea tratteggiata: consumi previsti. L’intervallo indica l’incertezza della stima, non una garanzia.","GWh è una misura di energia; 1 GWh equivale a 1.000 MWh.")
    _quality_panel(context)
    with st.expander("Fonti e aggiornamento"):
        _source_panel(context)
    st.markdown("[Mercato e previsioni](/market) · [Stoccaggi e forniture](/security-of-supply) · [Registro operativo](/ledger)")


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
                "Modello": MODELLI[name], "Errore medio (GWh)": round(scores[name].mae, 1) if name in scores else None,
                "RMSE (GWh)": round(scores[name].rmse, 1) if name in scores else None,
                "WAPE (%)": round(scores[name].wape, 1) if name in scores and scores[name].wape is not None else None,
                "Bias (GWh)": round(scores[name].bias, 1) if name in scores else None,
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
    st.markdown("[Stoccaggi e forniture (Security of supply) — AGSI+, ALSI, IIP e Jarvis](/security-of-supply)")
    if not selection.bundle:
        return

    context = preview_market(selection)
    origin = context.bundle.origin
    st.caption("Ultimo periodo osservato · " + context.facts.get("label", "Non disponibile"))
    _metrics(context)
    st.write(_plain_market(context))
    with st.container(border=True, key="panel_market_chart"):
        visible = _charts(context, selection.periods, "market", height=348)
    from .weather_page import weather_panel
    weather_panel(context)
    _supporting_charts(context, visible, "market")
    if st.checkbox("Mostra confronto dei modelli e backtest", key="market_show_models"):
        _model_comparison(context)
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
                note = st.session_state.get("market_source_note")
                if note:
                    st.caption(note)
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
