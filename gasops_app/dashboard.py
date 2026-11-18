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
from .session import analysis_label, briefing_run, launch, preview_market, source_filters, market_scope, PUBLIC, DAILY
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
    kpi_grid([(title,facts[field],units,description,decimals,tone) for title,field,units,description,decimals,tone in specs if facts.get(field) is not None])


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
    comparison=("tra i sette giorni terminanti il "+facts["label"]+" e i sette precedenti (giorni confrontabili)"
                if origin.grain=="daily" else "rispetto al mese precedente")
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


def _charts(context: MarketContext, horizon: int, page: str, height: int = 330, *, readout=True) -> pd.DataFrame:
    origin = context.bundle.origin
    data = context.inspection.usable.tail(horizon)
    title = ("Consumo interno e disponibilità" if origin.grain == "monthly" else
             "Consumi nazionali" if origin.archive else "Prelievi sulla rete SRG" if "distribution_gwh" in origin.fields else "Domanda e offerta")
    projection = context.projection
    heading(title, kind_tag(Kind.FORECAST) if projection.points else "")
    if not data["demand_gwh"].notna().any():
        st.info("Nessun consumo utilizzabile nel periodo selezionato.")
    else:
        if projection.points and readout:
            forecast_readout(projection.points[0], origin.grain, historical=origin.archive or any(f.id=="stale" for f in context.inspection.findings))
        plot(demand_chart(data, projection, origin.grain, height=height), key=f"{page}_demand")
        horizon_text = "14 giorni gas" if origin.grain == "daily" else "6 mesi"
        if projection.points:
            model = MODELLI[projection.model]
            note = " · scelto dallo storico" if context.model == AUTOMATIC and projection.model in context.forecast_scores else ""
            st.caption(f"{model}{note} · orizzonte di {horizon_text}")
            if context.facts.get("period") and origin.grain=="daily":
                lead=(pd.Timestamp(projection.points[0].period)-pd.Timestamp(context.facts["period"])).days
                st.caption(f"Prima stima a {lead} giorni dall’ultima osservazione ({context.facts['label']}).")
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


def _briefing_period(run):
    # The usable observation may precede the publisher's last record.
    market=run.results.get(Agent.MARKET)
    observed=(market.values.get("period") if market else None) or run.assumptions.get("source_period")
    period=observed or run.source.latest_period
    if isinstance(period,str):
        try:
            return data_it(date.fromisoformat(period),day=run.source.grain=="daily")
        except ValueError:
            return period
    return "Periodo non disponibile"


def _briefing_highlights(run):
    market=run.results.get(Agent.MARKET)
    forecast=run.results.get(Agent.FORECAST)
    facts=market.values if market and market.status in ("completed","review") else {}
    series=forecast.values.get("forecast",{}) if forecast and forecast.status in ("completed","review") else {}
    points=series.get("points",[])
    point=points[0] if points else {}
    scope=_briefing_period(run)
    estimate_period=point.get("period")
    if estimate_period:
        try:
            estimate_period=data_it(date.fromisoformat(estimate_period),day=run.source.grain=="daily")
        except ValueError:
            pass
    historical=run.source.archive or any(f.id=="stale" for f in run.findings)
    estimate_label="Stima da dati storici" if historical else "Prossima previsione"
    if run.source.kind==Kind.SYNTHETIC:
        estimate_label="Previsione di esempio"
    comparison=facts.get("comparison") or ""
    def change(field):
        value=facts.get(field)
        return (numero(value,signed=True)+"% "+comparison).strip() if value is not None else scope
    interval=(numero(point["lower_80"],0)+"–"+numero(point["upper_80"],0)+" GWh · fascia 80%"
              if point.get("lower_80") is not None and point.get("upper_80") is not None else "")
    price_label="Prezzo di esempio" if run.source.kind==Kind.SYNTHETIC else "Prezzo PSV (ARERA)"
    kpi_grid([("Consumi",facts.get("demand_gwh"),"GWh",change("demand_gwh_change_pct"),1,""),
              (price_label,facts.get("price_eur_mwh"),"€/MWh",change("price_eur_mwh_change_pct"),2,""),
              (estimate_label,point.get("estimate"),"GWh"," · ".join(x for x in [estimate_period,interval] if x),1,"blue")])
    if not facts and market:
        st.caption(market.summary)
    if not point and forecast:
        st.caption(forecast.summary)


def _briefing_operational_context(public):
    """Keep source scope, availability and units beside each indicator."""
    if not public:
        return
    st.markdown("**Sicurezza delle forniture · contesto operativo**")
    cards=[]
    for name,label,field,unit in (("AGSI+","Stoccaggi Italia","fill_pct","%"),
                                  ("ALSI","Rigassificazione Italia","sendout_gwh_d","GWh/g"),
                                  ("IIP","Record UMM ricevuti","received_records","")):
        source=public.get(name)
        if not source:
            continue
        available=source.get("status")=="available"
        values=source.get("values",{}) if available else {}
        value=(source.get(field) if name=="IIP" else values.get(field)) if available else None
        raw_day=source.get("gas_day")
        detail=raw_day or ("Finestra IIP" if name=="IIP" else "")
        if not available:
            detail=source.get("reason") or "Dato non recente"
        elif name=="AGSI+":
            if values.get("stock_twh") is not None:
                detail+=" · "+numero(values["stock_twh"])+" TWh"
            if source.get("quality_review"):
                detail+=" · dato da verificare"
        elif name=="IIP":
            detail=f"{source.get('coverage','Copertura non indicata')} · record, non eventi"
        cards.append((label,value,unit,detail,0 if name=="IIP" else 1,""))
    if cards:
        kpi_grid(cards)
    weather=public.get("Open-Meteo")
    if weather:
        points=weather.get("points",[]) if weather.get("status")=="available" else []
        if points:
            peak=max(points,key=lambda p:p.get("hdd",float("-inf")))
            day=peak.get("period") or peak.get("day") or "data non indicata"
            st.caption("Meteo · picco HDD "+numero(peak.get("hdd"))+" il "+day+
                       " · "+numero(peak.get("temperature_c"))+" °C · previsione territoriale")
        else:
            st.caption("Meteo · previsione non disponibile o non recente.")
    missing=[name for name,item in public.items() if item.get("status")!="available"]
    if missing:
        st.caption("Copertura incompleta · "+", ".join(missing)+". Nessun valore sostitutivo.")


def _briefing_panel(selection) -> None:
    with st.container(border=True,key="panel_overview_brief"):
        lead,action=st.columns([2.2,1],vertical_alignment="center")
        with lead:
            st.subheader("Bollettino di mercato")
            info("Bollettino","Esegue sei strumenti di analisi e controlli locali. Il modello AI, se selezionato, interpreta i risultati condivisibili. Scenari e settlement possono essere dimostrativi; nessuna modifica operativa.")
        with action:
            clicked=st.button(analysis_label(),type="primary",icon=":material/auto_awesome:",width="stretch",key="analysis_launch",disabled=selection.bundle is None)
        extras=[]
        if st.session_state.get("briefing_gie",True):
            extras.append("GIE (AGSI+, ALSI e IIP)")
        if st.session_state.get("briefing_weather"):
            extras.append("Open-Meteo")
        if extras:
            info("Fonti del bollettino",", ".join(extras))
        if clicked:
            generated=launch(selection,full=True,compact=True)
            if generated is None:
                st.error("Il nuovo bollettino non è stato generato. L’eventuale risultato precedente resta qui sotto.")
        run=briefing_run()
        if run is None:
            st.caption("Nessun bollettino generato.")
        else:
            matches=bool(selection.bundle and run.input_sha256==selection.bundle.fingerprint
                         and run.assumptions.get("model")==selection.model)
            if not matches:
                st.warning("Bollettino precedente: fonte o modello cambiato. Genera un nuovo bollettino.")
            actual_ai=run.mode=="LLM-assisted" and bool(run.interpretation)
            st.markdown("**Ultimo bollettino generato**")
            mode="AI · "+(run.model or "modello selezionato") if actual_ai else "Calcoli locali"
            st.caption(" · ".join((local_time(run.finished_at),run.source.name,_briefing_period(run),mode)))
            if run.source.kind==Kind.SYNTHETIC:
                st.caption("Simulazione · dati fittizi.")
            if run.source.archive or run.source.refresh_failed or any(f.id=="stale" for f in run.findings):
                st.warning("Dati storici o aggiornamento da verificare. Non rappresentano il mercato attuale.")
            for warning in dict.fromkeys(run.warnings):
                st.warning(warning)
            _briefing_highlights(run)
            public=run.assumptions.get("public_operational_context") or {}
            _briefing_operational_context(public)
            if actual_ai:
                st.markdown("**Sintesi AI**")
                for paragraph in run.interpretation.splitlines():
                    if paragraph.strip():
                        st.text(paragraph.strip())
                info("Evidenze AI",", ".join(AGENT_LABELS[a] for a in run.interpretation_sources))
            issues=[f for f in run.findings if f.severity in ("high","medium")]
            completed=sum(r.status in ("completed","review") for r in run.results.values())
            st.caption(f"Analisi eseguite: {completed}/{len(run.steps)} · Da verificare: {len(issues)}")
            for finding in issues:
                if finding.severity=="high":
                    st.warning(finding.title+" — "+finding.detail)
            other_issues=[finding for finding in issues if finding.severity!="high"]
            if other_issues:
                with st.expander(f"Rilievi da verificare · {len(other_issues)}",expanded=True):
                    for finding in other_issues:
                        st.markdown("**"+finding.title+"**")
                        st.text(finding.detail)
            elif not issues:
                st.caption("Nessun rilievo nei controlli eseguiti.")
            with st.expander("Esposizione e stress test · simulazioni"):
                st.caption("Non sono posizioni, fatture o esposizioni reali dei partecipanti.")
                for agent in (Agent.SETTLEMENT,Agent.SCENARIO):
                    item=run.results.get(agent)
                    if item:
                        st.markdown("**"+AGENT_LABELS[agent]+"**")
                        st.text(item.summary)
                st.caption("Per EPSu, MEPSu e settlement effettivi servono i dati verificati del dossier operativo.")
            if public:
                with st.expander("Fonti operative consultate"):
                    for name,source in public.items():
                        status={"available":"Disponibile","stale":"Non recente","unavailable":"Non disponibile"}.get(source.get("status"),"Stato non indicato")
                        st.text(f"{source.get('source',name)} · {status} · {source.get('gas_day') or source.get('acquired') or 'data non indicata'}")
                        if source.get("reason"):
                            st.text(source["reason"])
                    st.json(public,expanded=False)
            with st.expander("Dettaglio degli agenti"):
                for agent,item in sorted(run.results.items(),key=lambda pair:list(Agent).index(pair[0])):
                    if agent in (Agent.SETTLEMENT,Agent.SCENARIO):
                        continue
                    st.markdown("**"+AGENT_LABELS[agent]+"**")
                    st.text(item.summary)
            d1,d2=st.columns(2)
            d1.download_button("Scarica bollettino",markdown(run,{}),f"igor-{run.id[:10]}.md",
                               mime="text/markdown",key="overview_brief_md",width="stretch")
            d2.download_button("Scarica dati JSON",json.dumps(run.model_dump(mode="json"),ensure_ascii=False,indent=2),
                               f"igor-{run.id[:10]}.json",mime="application/json",key="overview_brief_json",width="stretch")
            st.markdown("[Continua nell’Assistente AI](/operations)")
        # AI connection controls are in the sidebar.


def _overview_mix(context):
    facts=context.facts
    origin=context.bundle.origin
    total=facts.get("demand_gwh")
    if origin.grain=="daily" and "distribution_gwh" in origin.fields:
        fields=(("Distribuzione" if not origin.archive else "Residenziale e terziario","distribution_gwh"),
                ("Industria","industry_gwh"),("Centrali elettriche","power_gwh"))
        st.subheader("Composizione dei consumi")
        parts=[facts.get(field) for _,field in fields]
        st.caption(facts.get("label","Periodo non disponibile")+" · GWh/giorno gas")
        if total and all(v is not None and 0<=v<=total for v in parts) and abs(sum(parts)-total)<=max(.01,.001*total):
            for (label,_),value in zip(fields,parts,strict=True):
                st.markdown(f"**{label}** · {numero(value,1)} GWh ({numero(100*value/total,1)}%)")
                st.progress(float(value/total))
        else:
            rows([(label,numero(facts[field],1)) for label,field in fields if facts.get(field) is not None])
            st.caption("Quote non calcolate: componenti incomplete o non riconciliate.")
    elif origin.grain=="monthly":
        st.subheader("Bilancio nazionale")
        st.caption(facts.get("label","Periodo non disponibile")+" · GWh/mese")
        rows([(label,numero(facts.get(field),1)) for label,field in (
            ("Importazioni nette","net_imports_gwh"),("Produzione interna","production_gwh"),
            ("Variazione delle scorte","stock_change_gwh"),("Disponibilità contabile","supply_gwh")) if facts.get(field) is not None])
        info("Bilancio","Disponibilità statistica, non misura della capacità di rete.")
    else:
        st.subheader("Scenario di esempio")
        rows([(label,numero(facts.get(field),1)+unit if facts.get(field) is not None else "—") for label,field,unit in (
            ("Offerta","supply_gwh"," GWh/giorno"),("Saldo","gap_gwh"," GWh/giorno"),
            ("Copertura","coverage_pct","%"),("Prezzo ipotetico","price_eur_mwh"," €/MWh"))])
        st.caption("Valori sintetici, non mercato reale.")



def overview() -> None:
    top,controls=st.container(),st.container()
    with controls:
        selection=source_filters("overview")
    area,perimeter=market_scope(selection.name)
    with top:
        header("Panoramica del mercato","")
        st.markdown("**"+area+"** · "+perimeter)
    context=None
    if selection.bundle:
        context=preview_market(selection)
        st.caption("Fonte: "+context.bundle.origin.name)
        _market_headlines(context)
        findings=[f for f in context.inspection.findings if f.severity!="info"]
        stale=[f for f in findings if f.id=="stale" or f.id.startswith("public-cache")]
        if stale:
            st.caption("Ultimo dato valido · aggiornamento da verificare")
            with st.expander("Stato aggiornamento"):
                for f in stale:st.caption(f.title+" — "+f.detail)
        if not context.facts:
            st.warning("Nessuna osservazione utilizzabile. Consulta i controlli qualità.")
        with st.container(key="overview_split"):
            left,right=st.columns([2.15,1],gap="medium")
            with left,st.container(border=True,key="panel_main"):
                _charts(context,selection.periods,"overview",height=355,readout=False)
                point=next(iter(context.projection.points),None)
                if point and point.lower_80 is not None and point.upper_80 is not None:
                    st.caption("Intervallo stimato (80%) della prima stima: "+numero(point.lower_80,0)+"–"+numero(point.upper_80,0)+" GWh.")
                info("Come leggere il grafico","Linea continua: consumi osservati. Linea tratteggiata: stime del modello. La fascia indica l’incertezza. GWh misura energia.")
            with right:
                with st.container(border=True,key="panel_overview_mix"):
                    _overview_mix(context)
                with st.container(border=True,key="panel_overview_quality"):
                    from .sentinel import panel as sentinel_panel
                    sentinel_panel(context)
        with st.expander("Fonti e aggiornamento"):
            _source_panel(context)
    if selection.name in (PUBLIC,DAILY):
        from .overview_indicators import panel
        panel(context)
    _briefing_panel(selection)



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
            } for name in ordered],
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


def _market_headlines(context: MarketContext):
    """A single comparable reading: observed period, change, and next model period."""
    origin=context.bundle.origin
    facts=context.facts
    point=next(iter(context.projection.points),None)
    unit="GWh/mese" if origin.grain=="monthly" else "GWh/giorno gas"
    label=("Prelievi sulla rete SRG" if origin.grain=="daily" and not origin.archive
           and origin.kind!=Kind.SYNTHETIC else "Gas consumato")
    comparison=("Ultimi 7 giorni vs 7 precedenti" if origin.grain=="daily" else "Rispetto al mese precedente")
    stale=origin.refresh_failed or any(f.id=="stale" for f in context.inspection.findings)
    next_label="Stima da dati non recenti" if stale else "Stima successiva" if origin.archive or origin.kind==Kind.SYNTHETIC else "Consumo previsto"
    cards=[
        (label,facts.get("demand_gwh"),unit,facts.get("label","Dato non disponibile"),1,"teal"),
        ("Variazione dei consumi",facts.get("demand_gwh_change_pct"),"%",comparison,1,""),
        (next_label,point.estimate if point else None,unit,
         period_text(pd.Timestamp(point.period),origin.grain) if point else "Previsione non disponibile",1,"blue")
    ]
    kpi_grid(cards)
    info("Lettura dei dati",_plain_market(context))
    if point and facts.get("period"):
        lead=(pd.Timestamp(point.period)-pd.Timestamp(facts["period"])).days
        if origin.grain=="daily":
            st.caption(f"Orizzonte: {lead} giorni dall’ultima osservazione ({facts['label']}).")


def _market_quality_notice(context):
    findings=[f for f in context.inspection.findings if f.severity!="info"]
    if findings:
        urgent=[f for f in findings if f.id=="stale" or f.id.startswith("public-cache")]
        for item in urgent:
            st.warning(item.title+" — "+item.detail)
        remaining=[f for f in findings if f not in urgent]
        if remaining:
            critical=[f.title for f in remaining if f.severity=="high"]
            message=f"{len(remaining)} rilievi sui dati · Modelli e dati."
            if critical:
                message += " " + " · ".join(critical)
            st.warning(message)



def _market_data(context, visible):
    origin=context.bundle.origin
    with st.expander("Dati osservati e previsioni"):
        raw=context.bundle.rows
        start=visible.index.min().date().isoformat() if len(visible) else ""
        headings={**FIELDS,"period":"Periodo","source_flag":"Flag della fonte","timestamp_utc":"Inizio UTC"}
        if origin.grain=="monthly":
            headings["supply_gwh"]="Disponibilità contabile"
            headings["price_eur_mwh"]="Prezzo CMEM,m (€/MWh)"
        wanted=["period","timestamp_utc",*origin.fields,"source_flag"]
        st.caption("Record della fonte nel periodo selezionato.")
        st.dataframe(raw.loc[raw["period"]>=start,wanted].rename(columns=headings),hide_index=True,width="stretch")
        if context.projection.points:
            st.caption("Previsioni · GWh per periodo")
            st.dataframe([{"Periodo":period_text(pd.Timestamp(p.period),origin.grain),
                           "Stima (GWh)":p.estimate,"Estremo inferiore":p.lower_80,
                           "Estremo superiore":p.upper_80} for p in context.projection.points],
                         hide_index=True,width="stretch",column_config={
                             name:st.column_config.NumberColumn(format="%.1f")
                             for name in ("Stima (GWh)","Estremo inferiore","Estremo superiore")})
    with st.expander("Provenienza e metodologia"):
        _source_panel(context)
        note=st.session_state.get("market_source_note")
        if note:
            st.caption(note)
        for feed in (origin,*origin.companions):
            st.caption(feed.description)
        st.text("Impronta dati SHA-256 · "+context.bundle.fingerprint)


def market() -> None:
    header("Mercato e previsioni", "")
    view=st.radio("Vista mercato",["Domanda e previsioni","Mercato europeo ACER","Sistema elettrico Terna","Laboratorio previsionale","Forecasting Snam"],horizontal=True,label_visibility="collapsed",key="market_view")
    if view=="Forecasting Snam":
        from .snam_forecast_page import panel
        panel()
        return
    if view=="Laboratorio previsionale":
        from .predictive_page import panel
        panel()
        return
    if view=="Sistema elettrico Terna":
        from .terna_power_page import panel
        panel()
        return
    if view=="Mercato europeo ACER":
        from .acer_market_page import panel
        panel()
        return
    top,controls=st.container(),st.container()
    with controls:
        selection=source_filters("market")
    area,perimeter=market_scope(selection.name)
    with top:
        st.markdown("**"+area+"** · "+perimeter)
    if not selection.bundle:
        st.markdown("[Stoccaggi e forniture (Security of supply)](/security-of-supply)")
        return
    context=preview_market(selection)
    origin=context.bundle.origin
    st.caption("Fonte: "+origin.name+" · "+("mensile" if origin.grain=="monthly" else "giornaliera"))
    _market_headlines(context)
    _market_quality_notice(context)
    main,details,weather,methods=st.tabs(["Consumi e previsioni","Composizione e prezzi","Meteo","Modelli e dati"])
    visible=context.inspection.usable.tail(selection.periods)
    with main:
        with st.container(border=True,key="panel_market_chart"):
            _charts(context,selection.periods,"market",height=390,readout=False)
            if context.projection.points:
                p=context.projection.points[0]
                if p.lower_80 is not None and p.upper_80 is not None:
                    st.caption("Intervallo stimato (80%) per "+period_text(pd.Timestamp(p.period),origin.grain)+
                               ": "+numero(p.lower_80)+" – "+numero(p.upper_80)+" GWh.")
            info("Come leggere il grafico","Linea continua: consumi osservati. Tratteggio: stima del modello; la fascia rappresenta l’incertezza.",
                 "La previsione parte dall’ultimo periodo utilizzabile, non necessariamente da oggi. GWh misura energia.")
    with details:
        st.caption(area+" · "+perimeter)
        _metrics(context)
        _supporting_charts(context,visible,"market")
        facts=context.facts
        with st.expander("Abitudini di consumo"):
            if facts.get("weekend_vs_weekday_pct") is not None:
                st.write("Consumi medi nel fine settimana: "+numero(facts["weekend_vs_weekday_pct"],signed=True)+
                         "% rispetto ai feriali negli ultimi 84 giorni della serie.")
            if facts.get("peak_month") and facts.get("low_month"):
                st.write("Media stagionale massima: "+facts["peak_month"]+". Minima: "+facts["low_month"]+".")
            if facts.get("weekend_vs_weekday_pct") is None and not facts.get("peak_month"):
                st.caption("Dati insufficienti per descrivere le abitudini di consumo.")
    with weather:
        from .weather_page import weather_panel,outlook_panel
        if origin.kind in (Kind.HISTORICAL,Kind.LIVE) and not origin.archive:
            if origin.grain=="daily" and origin.name.startswith("ENTSOG"):weather_panel(context)
            else:outlook_panel()
        else:
            st.caption("Meteo disponibile per le fonti reali correnti.")
    with methods:
        if st.checkbox("Confronta i modelli previsionali",key="market_show_models"):
            _model_comparison(context)
        _quality_panel(context)
        _market_data(context,visible)
