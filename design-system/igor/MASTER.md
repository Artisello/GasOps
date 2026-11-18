# I.G.O.R. — Design system

Scope: operational analytics and credit/settlement support, desktop-first Streamlit and Plotly. Existing routes, models, public data sources and controls stay unchanged.

## Method and provenance
Manual selection from UI UX Pro Max catalogs at [reviewed revision](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill/tree/ed766d3bf62f32c8d27762ad49abdc3a4744c84f), not CLI-generated output. See [reasoning](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill/blob/ed766d3bf62f32c8d27762ad49abdc3a4744c84f/src/ui-ux-pro-max/data/ui-reasoning.csv) (Financial Dashboard 6, Analytics Dashboard 7, Invoice & Billing Tool 105), styles (Minimalism & Swiss Style), typography (Minimal Swiss 5), chart guidance (Trend Over Time 1), UX (9, 28, 36, 37, 41, 67, 69, 71, 79). Adapt recommendations to an operational console, not a landing page. No upstream scripts/dependencies shipped or executed.

## Visual system
- Dark slate foundation: background #0b111b, surface #14202e, divider #34475a, interactive border #61768c, foreground #f1f5f9, secondary text #b6c4d4.
- Teal #65dfbf = primary accent / selected action / observed series; blue #83b4ff = forecast or reference; amber #f2be72 = review; rose #f6929d = problem. Status text always accompanies color where it conveys meaning. Do not imply that high storage or a positive balance guarantees safety.
- One sans-serif family with local/system fallback (Inter if available), tabular figures. No external font download. Body readable at mobile widths, restrained hierarchy.
- Spacing 4/8/12/16/24/32 px; flat panels, thin borders, no gradients or decorative shadows. Focus ring remains visible; no automatic animation.
- Native Streamlit widgets, labels, focus and links. Never hide an alert, source, unit or stale indication to make the design cleaner.

## Page hierarchy
1. One page title, scope and reference date near the relevant data.
2. Existing controls ordered by task; one main action per panel.
3. Headline metrics and chart before detail. Explicit missing value, not zero or silently disappearing metric.
4. Secondary explanations in existing info/expanders; retain download, methodology, uncertainty and source links.
5. Observed line solid; forecast dashed; comparator dotted. Label series and axes; keep gaps visible and preserve data-table alternatives. No simulated or stale series presented as live.

## Review gates
Verify keyboard-only navigation, link/button focus, contrast >=4.5:1 for ordinary text, meaningful text status alongside colors, usable layout at 375/768/1024/1440 CSS px and browser zoom. Wide tables may scroll locally, not the page. Verify source freshness, dates, units, no implicit demo substitution. Run existing pytest and readiness checks. Browser verification required; static code review alone is not accessibility certification.

## Operational polish — implementation
- Keep the existing dark Minimal Swiss system and native Streamlit route/menu structure. Use a maximum content width of 1440 CSS px, clear heading scale, flat KPI surfaces and responsive gutters; preserve data density and all existing controls.
- Teal filled primary action with dark foreground, outlined secondary action, neutral disabled state; 44 CSS px target for main buttons and routes, and mobile information controls. Focus remains visible; transitions are short and respect reduced motion. Native form labels and status text remain available.
- Use the same chart text, panel and border tokens in CSS, Streamlit and the Plotly renderer. Preserve original analytical axes, labels, ranges, trace data, gaps, uncertainty and export options. Negative residual and deficit bars use a hatch in addition to color; do not interpret direction as regulatory approval.
- Source: [skill rules](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill/blob/ed766d3bf62f32c8d27762ad49abdc3a4744c84f/.claude/skills/ui-ux-pro-max/SKILL.md), [quick reference](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill/blob/ed766d3bf62f32c8d27762ad49abdc3a4744c84f/.claude/skills/ui-ux-pro-max/references/quick-reference.md), charts catalog rows 1 and 9, colors rows 6 and 7. Manual adaptation to Streamlit, not CLI generation.
- Additional automated gates: CSS/native/chart palette agreement, text/control contrast, and chart style preserving trace content and analytical choices. Visual acceptance still requires browser checks on all nine routes at desktop, tablet and mobile widths; confirm focus, popovers, tabs, controls, charts and overflow with zoom and reduced motion. Do not treat these tests as a WCAG certification.
