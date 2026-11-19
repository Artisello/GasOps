# I.G.O.R. — Design system

Scope: operational analytics and credit/settlement support, desktop-first Streamlit and Plotly. Existing routes, models, public data sources and controls stay unchanged.

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

Before merging, exercise all nine routes, keyboard focus, tabs with long labels, 375/768/1024/1440 viewport widths and 200% zoom, narrow chart legends, dark-only contrast, warning/not-available cases and disabled controls. Static tests check selected token ratios and shared styling; they are not a browser audit.


## Interaction and workflow: internal prototype
- A direct, accurately labeled action is enough to import session-only public/synthetic data or refresh configured public sources. No repeated acknowledgement checkbox. Keep the brief data scope note, provider terms, temporal assumptions, parser/schema validation, quotas, and preservation of previous valid data.
- Keep public/shared archive access control and confirmation before irreversible shared publication/removal; retain explicit consent to transmit PDF extracts and restricted evidence to external AI. The source code is public and the deployment may still be publicly reachable, so an internal-prototype UX does not make it private.
- Start with usable local assistant reports when AI is not configured; retain explicit provider activation. No automatic provider requests or demo substitution. Show upload panels open only when needed; show document search before the expanded file inventory. Prefer concise labels and contextual help.
- Tests: one-click refresh (no calls on page render or selection), empty selection disabled, direct valid import, invalid import preserves previous state, local assistant default without configured AI.

## Primary CTA contrast
Keep the teal accent; enabled primary controls (including native form submit variants and Markdown/Material icon descendants) use dark #10231f foreground in default, hover, focus and pressed states. The pressed background is #50c6a7; disabled and secondary controls retain their own styling. Static contrast regression requires at least 7:1 for these three backgrounds. Browser computed-style verification remains required after deployment.
