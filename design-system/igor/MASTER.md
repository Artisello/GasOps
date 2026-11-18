# I.G.O.R. — Design system

Scope: operational analytics and credit/settlement support, desktop-first Streamlit and Plotly. Existing routes, models, public data sources and controls stay unchanged.

## Method and provenance
Manual selection from UI UX Pro Max catalogs at [reviewed revision](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill/tree/ed766d3bf62f32c8d27762ad49abdc3a4744c84f), not CLI-generated output. See [reasoning](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill/blob/ed766d3bf62f32c8d27762ad49abdc3a4744c84f/src/ui-ux-pro-max/data/ui-reasoning.csv) (Financial Dashboard 6, Analytics Dashboard 7, Invoice & Billing Tool 105), styles (Minimalism & Swiss Style), typography (Minimal Swiss 5), chart guidance (Trend Over Time 1), UX (9, 28, 36, 37, 41, 67, 69, 71, 79). Adapt recommendations to an operational console, not a landing page. No upstream scripts/dependencies shipped or executed.

## Visual system
- Dark slate foundation: background #0b111b, surface #101925, border #2e4054, foreground #f1f5f9, secondary text #a9b8ca.
- Teal #65dfbf = primary accent / selected action / observed series; blue #83b4ff = forecast or reference; amber #f2be72 = review; rose #f6929d = problem. Status text always accompanies color where it conveys meaning. Do not imply that high storage or a positive balance guarantees safety.
- One sans-serif family with local/system fallback (Inter if available), tabular figures. No external font download. Body readable at mobile widths, restrained hierarchy.
- Spacing 4/8/12/16 px; flat panels, thin borders, no gradients or decorative shadows. Focus ring remains visible; no automatic animation.
- Native Streamlit widgets, labels, focus and links. Never hide an alert, source, unit or stale indication to make the design cleaner.

## Page hierarchy
1. One page title, scope and reference date near the relevant data.
2. Existing controls ordered by task; one main action per panel.
3. Headline metrics and chart before detail. Explicit missing value, not zero or silently disappearing metric.
4. Secondary explanations in existing info/expanders; retain download, methodology, uncertainty and source links.
5. Observed line solid; forecast dashed; comparator dotted. Label series and axes; keep gaps visible and preserve data-table alternatives. No simulated or stale series presented as live.

## Review gates
Verify keyboard-only navigation, link/button focus, contrast >=4.5:1 for ordinary text, meaningful text status alongside colors, usable layout at 375/768/1024/1440 CSS px and browser zoom. Wide tables may scroll locally, not the page. Verify source freshness, dates, units, no implicit demo substitution. Run existing pytest and readiness checks. Browser verification required; static code review alone is not accessibility certification.
