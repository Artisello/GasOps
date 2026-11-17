"""Market overview and forecasting pages."""

from html import escape

import pandas as pd
import streamlit as st

from .agents import MarketContext
from .data import FIELDS, period_text
from .forecast import MODELS, forecast
from .models import Kind
from .session import applicable_run, launch, preview_market, sidebar, source_filters
from .visuals import AMBER, ROSE, chip, demand_chart, error_chart, heading, header, kind_tag, kpi, local_time
from .visuals import mini_chart, plot, rows, steps
from .workbench import balancing, operations, regulatory


def _change(facts: dict, field: str) -> str:
    delta = facts.get(f"{field}_change_pct")
    return f"{delta:+.1f}% {facts['comparison']}" if delta is not None else "Comparison unavailable"


def _overview_metrics(context: MarketContext) -> None:
    facts = context.facts
    if not facts:
        st.warning("This dataset has no usable demand periods. Open the quality findings for details.")
    measure = "GWh/day" if context.bundle.origin.grain == "daily" else "GWh/month"
    price_title = "Demo reference price" if context.bundle.origin.kind == Kind.SYNTHETIC else "Market price"
    specs = (
        ("Gas demand", "demand_gwh", measure, _change(facts, "demand_gwh") if facts else "Unavailable", 1, "teal"),
        ("Gas supply", "supply_gwh", measure,
         _change(facts, "supply_gwh") if facts.get("supply_gwh") is not None else "Supply unavailable", 1, ""),
        ("Simplified imbalance", "gap_gwh", measure, "Supply − demand", 1,
         "rose" if (facts.get("gap_gwh") or 0) < 0 else "teal"),
        ("Demand coverage", "coverage_pct", "%", "Supply ÷ demand", 1, "blue"),
        (price_title, "price_eur_mwh", "EUR/MWh",
         _change(facts, "price_eur_mwh") if facts.get("price_eur_mwh") is not None else "Price unavailable", 2, ""),
    )
    for col, (title, field, units, description, decimals, tone) in zip(st.columns(5), specs, strict=True):
        with col:
            kpi(title, facts.get(field), units, description, decimals, tone)


def _source_panel(context: MarketContext) -> None:
    origin = context.bundle.origin
    facts = context.facts
    latest = facts.get("period")
    flags = context.bundle.rows.loc[
        context.bundle.rows["period"].eq(latest), "source_flag"
    ].astype(str)
    raw_flag = next((flag for flag in flags if flag), None)
    status = "Cached · refresh failed" if origin.refresh_failed else "Cached" if origin.cached else (
        "Offline fixture" if origin.kind == Kind.SYNTHETIC else "Fetched from Eurostat"
    )
    details = [("Source", origin.name), ("Latest usable period", facts.get("label", "Unavailable")),
               ("Source timestamp", local_time(origin.published_at)), ("Connection", status)]
    if raw_flag:
        details.append(("Observation flag", "p · provisional" if raw_flag == "p" else raw_flag))
    rows(details)
    if origin.url:
        st.link_button("Eurostat dataset", origin.url, icon=":material/open_in_new:")


def _quality_panel(context: MarketContext) -> None:
    issues = context.inspection.findings
    review = [finding for finding in issues if finding.severity != "info"]
    with st.container(border=True, key="panel_quality"):
        heading("Data quality", chip(f"{len(review)} TO REVIEW", "review") if review else chip("CHECKED", "ok"))
        if review:
            selected = next((finding for finding in review if finding.id.startswith("outlier")), review[0])
            st.html(f'<div class="gas-alert"><strong>{escape(selected.title)}</strong>'
                    f'<small>{escape(selected.detail)}</small></div>')
        else:
            st.caption("No review findings in this series.")
        if issues:
            with st.expander("Inspect data checks"):
                for finding in issues:
                    st.markdown(f"**{finding.title}** · {finding.severity}")
                    st.caption(finding.detail)


def _charts(context: MarketContext, horizon: int, page: str, height: int = 330) -> pd.DataFrame:
    origin = context.bundle.origin
    data = context.inspection.usable.tail(horizon)
    heading("Demand and supply" if data["supply_gwh"].notna().any() else "Observed inland consumption",
            kind_tag(Kind.FORECAST) if context.projection.points else "")
    if not data["demand_gwh"].notna().any():
        st.info("No usable demand values in the selected lookback.")
    else:
        plot(demand_chart(data, context.projection, origin.grain, height=height), key=f"{page}_demand")
        horizon_text = "14 gas days" if origin.grain == "daily" else "6 months"
        if context.projection.points:
            st.caption(f"{context.model} · {horizon_text} ahead · GWh per period")
        else:
            st.caption(f"{context.model} requires more usable history.")
    return data


def overview() -> None:
    top, controls = st.container(), st.container()
    with controls:
        selection = source_filters("overview")
    with top:
        clicked = header("Market overview", selection.meta, "Run AI Market Analysis", disabled=selection.bundle is None)
    if not selection.bundle:
        return
    if clicked:
        launch(selection, full=True)

    context = preview_market(selection)
    _overview_metrics(context)
    main, desk = st.columns([2.42, 1], gap="medium")
    with main:
        with st.container(border=True, key="panel_main"):
            data = _charts(context, selection.periods, "overview", height=314)
        left, right = st.columns(2, gap="medium")
        grain = context.bundle.origin.grain
        with left, st.container(border=True, key="panel_imbalance"):
            heading("Simplified imbalance", '<small>GWh per period</small>')
            gap = data["supply_gwh"] - data["demand_gwh"]
            if gap.notna().any():
                plot(mini_chart(gap, "Supply − demand", grain, "GWh", ROSE, zero=True), "overview_gap")
            else:
                st.caption("This screening indicator requires same-period supply and demand.")
        with right, st.container(border=True, key="panel_price"):
            heading("Demo reference price" if context.bundle.origin.kind == Kind.SYNTHETIC else "Market price",
                    '<small>EUR/MWh</small>')
            price = data["price_eur_mwh"]
            if price.notna().any():
                plot(mini_chart(price, "Reference price", grain, "EUR/MWh", AMBER), "overview_price")
            else:
                st.caption("This dataset contains consumption volumes only.")
    with desk:
        with st.container(border=True, key="panel_source"):
            heading("Source and freshness")
            _source_panel(context)
        _quality_panel(context)
        run = applicable_run(selection)
        with st.container(border=True, key="panel_agents"):
            heading("Agent status", chip("LAST RUN", "ok") if run else chip("READY"))
            st.html(steps(run))
    if run:
        with st.container(border=True, key="panel_overview_brief"):
            heading("Executive summary", chip(run.mode))
            for result in run.results.values():
                st.text(result.summary)
            if run.interpretation:
                st.caption("Model interpretation · human review")
                st.text(run.interpretation)


def market() -> None:
    top, controls = st.container(), st.container()
    with controls:
        selection = source_filters("market")
    with top:
        header("Market & forecasting", selection.meta)
    if not selection.bundle:
        return

    context = preview_market(selection)
    origin = context.bundle.origin
    _overview_metrics(context)
    with st.container(border=True, key="panel_market_chart"):
        visible = _charts(context, selection.periods, "market", height=348)
    evidence, errors = st.columns([1, 1.55], gap="medium")
    with evidence:
        with st.container(border=True, key="panel_market_notes"):
            heading("Market analysis")
            facts = context.facts
            if facts:
                st.write(f"Demand change {_change(facts, 'demand_gwh').lower()}.")
                if "weekend_vs_weekday_pct" in facts:
                    st.write(f"Weekend demand averaged {facts['weekend_vs_weekday_pct']:+.1f}% "
                             "versus weekdays over the latest 84 calendar days.")
                if "peak_month" in facts:
                    st.write(f"Month-of-year averages peak in {facts['peak_month']} and are lowest in "
                             f"{facts['low_month']} across usable observations.")
                if origin.kind == Kind.SYNTHETIC:
                    st.caption("The fixture includes annual and weekly demand seasonality.")
                else:
                    st.caption("Monthly consumption supports trend analysis. Weather, sector activity and prices are outside this series.")
            with st.expander("Source details"):
                _source_panel(context)
                st.caption(origin.description)
                st.text(f"Data SHA-256 · {context.bundle.fingerprint}")
        _quality_panel(context)
    with errors:
        with st.container(border=True, key="panel_market_errors"):
            heading("Forecast error", '<small>One-step walk-forward · Actual − forecast</small>')
            projections = {name: context.projection if name == context.model else
                           forecast(context.inspection.usable["demand_gwh"], origin.grain, name) for name in MODELS}
            score = pd.DataFrame([{
                "Model": name, "MAE (GWh)": round(fit.mae, 2) if fit.mae is not None else None,
                "RMSE (GWh)": round(fit.rmse, 2) if fit.rmse is not None else None, "Scored periods": len(fit.backtest),
            } for name, fit in projections.items()])
            st.dataframe(score, hide_index=True, width="stretch")
            if context.projection.backtest:
                plot(error_chart(context.projection, origin.grain), "market_error")
                st.caption("Prediction bands use the 10th–90th percentiles of preceding out-of-sample errors at each horizon.")
            else:
                st.caption("No comparable out-of-sample predictions for this model.")
    with st.expander("Inspect observations and forecasts"):
        raw = context.bundle.rows
        start = visible.index.min().date().isoformat() if len(visible) else ""
        st.caption(f"Source records since {start}. Raw flags and anomalies are preserved here.")
        st.dataframe(raw.loc[raw["period"] >= start].rename(columns=FIELDS), hide_index=True, width="stretch")
        if context.projection.points:
            st.caption("FORECAST · GWh per period")
            st.dataframe([item.model_dump() for item in context.projection.points], hide_index=True, width="stretch")
