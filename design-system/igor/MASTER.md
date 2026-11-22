# I.G.O.R. — Design system

Scope: a freely explorable BSO demonstration, desktop-first Streamlit and Plotly. Preserve calculations, models, public data sources and all existing feature routes. The default application exposes the complete program through its sidebar, with ready examples and no required upload or credential entry. Use native controls for free exploration.

## Method and provenance
Manual selection from UI UX Pro Max catalogs at [reviewed revision](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill/tree/ed766d3bf62f32c8d27762ad49abdc3a4744c84f), not CLI-generated output. See [reasoning](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill/blob/ed766d3bf62f32c8d27762ad49abdc3a4744c84f/src/ui-ux-pro-max/data/ui-reasoning.csv) (Financial Dashboard 6, Analytics Dashboard 7, Invoice & Billing Tool 105), styles (Minimalism & Swiss Style), typography (Minimal Swiss 5), chart guidance (Trend Over Time 1), UX (9, 28, 36, 37, 41, 67, 69, 71, 79). Adapt recommendations to an operational console, not a landing page. No upstream scripts/dependencies shipped or executed.

## Visual system
- Dark slate foundation: background #0d131d, surface #141e2b, hover #1e2b3c, decorative border #2e4054, interactive boundary #63768b, foreground #f1f5f9, secondary text #b0bed0. Primary action uses teal with dark #10231f foreground.
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

## Refinement: operational console

Reviewed [UI/UX Pro Max skill](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill/blob/main/.claude/skills/ui-ux-pro-max/SKILL.md) and its [web quick reference](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill/blob/main/.claude/skills/ui-ux-pro-max/references/quick-reference.md), manually (CLI not executed). Preserve the existing dark direction and native Material icons. Distinguish control outlines from decorative borders, reserve teal-filled buttons for primary actions, and preserve native disabled states. Aim for 44 CSS px height on navigation, text inputs, main buttons, tabs and topic help; do not override dense chart/table internals. Tabs scroll locally rather than shrinking their labels; long values can wrap. KPI units and source context stay visible. In multi-series breakdowns line patterns distinguish categories, not forecast status (the time/forecast chart retains its separate semantics). System fonts only; no additional frontend library or external assets.

Before merging, exercise all eleven routes, keyboard focus, tabs with long labels, 375/768/1024/1440 viewport widths and 200% zoom, narrow chart legends, dark-only contrast, warning/not-available cases and disabled controls. Static tests check selected token ratios and shared styling; they are not a browser audit.


## Interaction and workflow: internal prototype
- A direct, accurately labeled action is enough to import session-only public/synthetic data or refresh configured public sources. No repeated acknowledgement checkbox. Keep the brief data scope note, provider terms, temporal assumptions, parser/schema validation, quotas, and preservation of previous valid data.
- Keep public/shared archive access control and confirmation before irreversible shared publication/removal; retain explicit consent to transmit PDF extracts and restricted evidence to external AI. The source code is public and the deployment may still be publicly reachable, so an internal-prototype UX does not make it private.
- Start with a usable public JRC assistant report. Use the configured, active model within existing quotas; respect an explicitly selected local mode. The prepared example must never include visitor PDFs or imported records. Public-source refresh stays explicit; no implicit demo substitution. Show upload panels open only when needed; show document search before the expanded file inventory. Prefer concise labels and contextual help.
- Tests: one-click refresh (no calls on page render or selection), empty selection disabled, direct valid import, invalid import preserves previous state, local assistant default without configured AI.

## Primary CTA contrast
Keep the teal accent; enabled primary controls (including native form submit variants and Markdown/Material icon descendants) use dark #10231f foreground in default, hover, focus and pressed states. The pressed background is #50c6a7; disabled and secondary controls retain their own styling. Static contrast regression requires at least 7:1 for these three backgrounds. Browser computed-style verification remains required after deployment.

## Responsive rendering
Use horizontal, wrapping native radio navigation for expensive mutually exclusive workspaces; run only the selected branch instead of eager tabs. Preserve committed domain inputs and computed reports separately from transient widgets; unsubmitted edits can be lost on switching views. Public market selections may reuse a successful snapshot in the same session for under 60 seconds without altering its acquisition date, warnings or refresh semantics; explicit refresh always bypasses that reuse. Do not cache authorization decisions or AI reservations. Measure browser timings after deployment; fewer rendered branches are a structural improvement, not a measured latency claim.

## Task-oriented BSO entry

The default overview is a compact BSO snapshot with three metrics, a system-balance chart and the historical forecast comparison. The original operational desk remains in the optional workbench variant. Imported-version counts describe the presence of session data, never completeness, freshness or validation.

The default balancing route opens a declared synthetic settlement case and preserves imported registers. Existing system-data and market-scenario views remain accessible from the same page. A one-use navigation intent must select its exact page and view before widgets render, without replaying when another page is visited.

Use short contextual guides, full names at the first use of an acronym, human-readable months, side-by-side participant/month controls and a compact exception table. Source classification, signs, incomplete periods and accounting limits stay visible. The example points to an actual revision in the displayed records. Preserve full detail and export even when the first table shows fewer columns.

## Default: freely explorable presentation

The audience should see the potential in five minutes. Default to a populated overview and eleven sidebar destinations: Panoramica, Bilanciamento, Fatture e garanzie, KPI operativi, Mercato e previsioni, Security of Supply, Simulazione rischi, Norme e documenti, Assistente AI, Fonti e API, Esempi BSO. Keep the sidebar available on every page, open on desktop and accessible by the native mobile toggle. No feature page may be orphaned or restricted to an environment flag. The six presentation scenes remain in Esempi BSO.

Lead each view with its concrete result. No required sequence, upload or credential entry. Prepare settlement, KPI, risk, public PDF search and an assistant report while retaining complete optional controls. All BSO examples are explicitly synthetic; fixed scenario dates remain visible. Use the actual settlement/task engines for displayed numbers. The overview's public historical forecast comparison is precomputed and checked against source and engine hashes. Observed/estimated lines and uncertainty remain distinct. Show coverage limitations even when they weaken a sales claim.

Fonti e API exposes every existing integration and links to the relevant analysis. One explicit refresh coordinates all available providers; distinguish configured credentials, successful responses, dated archives and unavailable services. Preserve existing timeout, cache, quota and consent rules. Never print credentials or transmit personal evidence in prepared examples. Separate implemented capabilities from proposed pilot developments, and retain independent/non-official attribution. The optional workbench changes the initial desk and configuration controls, not feature access; it is not authentication.

## Minimal presentation

Use short functional titles, compact metric cards and one main chart or queue. Remove slogans, introductory paragraphs, repeated capability explanations and per-page pilot summaries. Show brief source/date context beside the result; keep the uncertainty calibration limit visible. Put methodology, references, briefing and full records in native, closed expanders. Operations uses a static table without a command toolbar. Keep native accessible navigation, clear units and independent attribution. No CSS hiding of warnings, widgets or source classifications.

## Non-color chart cues

Use diagonal hatching as well as color for negative forecast residuals (observed minus predicted) and deficit bins (supply minus demand below zero). Zero and positive values remain unhatched. Retain signs, labels, hover text, histogram frequencies, units and existing chart scales. A negative forecast residual denotes overprediction, not a regulatory finding. Keep the current palette, native controls and eleven-route navigation; the earlier PR #88 theme and layout proposals have been superseded by the current design.
