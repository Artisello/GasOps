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
- Prepare the assistant controls in local mode; a report or remote model requires an explicit action. Respect the user's selected mode. Examples must never include visitor PDFs or imported records. Public-source refresh stays explicit; no implicit demo substitution. Show upload panels open only when needed; show document search before the expanded file inventory. Prefer concise labels and contextual help.
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

## Simple workspaces and immediate observations

Use the shared native `workspace.picker` for mutually exclusive page sections: one muted surface, short Italian labels, selected teal state and visible keyboard focus. Keep internal keys, values and URLs stable. At narrow widths use two columns; controls remain at least 44 px tall. Navigation hints explain the purpose in plain language; sidebar labels expand less familiar English/acronyms. No new fonts, frontend dependencies or decorative animation.

Market opening renders observed data without fitting a model. The single “Calcola previsione” action enables the estimate for the current data/model/source metadata/day; changing those inputs requires another action. Reading prices, weather or data does not fit models. Explicit comparison enables the already available estimates. A valid manually chosen model is fitted alone and reused by later comparisons; an unavailable choice keeps the existing all-model fallback. Automatic selection and all numerical methods are unchanged.

Overview example cards open the exact existing demo view in one click and preserve imported evidence. Fixtures remain labelled; source/missing/stale states and the single map are retained. Browser acceptance waits for Streamlit to finish the page before testing native WebGL gestures, so early streaming frames are not mistaken for the completed UI.


## UX Pro Max — accessibility and interaction hardening (2026-11-28)

Manual review of the upstream [skill](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill/blob/main/.claude/skills/ui-ux-pro-max/SKILL.md), [quick reference](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill/blob/main/.claude/skills/ui-ux-pro-max/references/quick-reference.md) and product/UX catalogues. Financial Dashboard and Analytics Dashboard both support the existing data-dense Swiss/minimal dark system. Streamlit is not a dedicated stack in the reviewed skill; adapt web guidance instead of introducing a JS stack. CLI not executed; no upstream code or dependencies installed. No replacement of prior design decisions.

- Accessibility first: preserve native controls, focus rings, keyboard-selectable map alternatives, text alongside color, warning text in full (never truncate critical data quality notes).
- Interaction: camera actions below the canvas, no overlap with data or native map controls. Calendar and camera actions use responsive wrapping groups and 44 CSS px height as a design target; this is more generous than the web WCAG 2.2 AA 24 CSS px minimum with exceptions.
- Responsive layout: local table overflow, readable direction/status labels, single-column narrow KPI/pair layout at 375px; no automatic motion. Secondary and primary actions retain distinct contrast and disabled semantics.
- Data integrity: no changes to calculations, date requests, bindings, or source disclosure. Existing status message has an atomic status role, not multiple competing regions.
- Verification: expanded static contrast checks and browser checks for mobile control geometry, target dimensions and non-overlap. These checks are not a full WCAG audit, and must be run against the actual deployment before making compliance claims.


## Page hierarchy — consolidated header

All default routes share the native title component in `visuals.header`. Keep one primary title per route, concise source/date/status context immediately beside its relevant result, and H2/H3 for individual analyses. The overview keeps its map-first layout and exact title "I.G.O.R. - Sistema Gas Italiano". Avoid decorative separators before workspace navigation and duplicate branding in guided examples; the sidebar already identifies the product. Preserve all navigation keys, controls, source warnings, non-official attribution and consent requirements. The operational sources title follows the selected existing workspace. Review desktop and mobile rendering and verify one native title per default route before release.


## Plotly — shared presentation layer

All rendered Plotly charts use `visuals.plot` and `chart_style`, including guided examples (read-only toolbar). Shared dark template, transparent surfaces, system font stack, muted tick labels, 13px base text/12px legend and ticks, Italian number separators and high-contrast tooltip surface. Axis automargins protect labels; existing chart-specific heights, margins, formats, units, ranges, grid visibility, legend placement, hover content and zoom constraints take precedence over generic layout defaults. The chart styling does not rewrite traces, values, missing observations, trace colors/dashes, patterns or uncertainty. Do not assign new colors from a generic palette when an analytical trace already encodes meaning. Normal operational charts retain the existing hover toolbar; guided examples retain a hidden toolbar. Disable scroll-to-zoom on both. No external fonts or new packages. Regression tests protect chart semantics and interaction policies; visual inspection at different viewport sizes remains required.


## P1 — map performance without stale operational caches

Build a PointIntelligenceIndex once per map render from the merged observations and current snapshot set. Validate all records against the confirmed bindings and the exact render timestamp, then group them by asset and direction; reuse for the default and selected-direction calculations. Keep the single-point public calculation API as a reference and regression-test equivalence, including unavailable and zero observations, freshness, failures and direction changes. Never cache operational results across users or timestamps: new publications, failures, permissions and changing freshness still take effect on the next render. Cache only immutable public geometry overlap results in a bounded 16-entry LRU keyed by visible point IDs and coordinates; return fresh mappings to callers. No new polling, fragments, provider requests, dependencies or changes to acquisitions. These changes reduce repeated work inside Streamlit reruns; they do not eliminate reruns or establish measured browser speedup. Profile actual deployments before making latency claims.


## Less is more — operational copy and layout

Prefer one short label per control, plain Italian over decorative uppercase English, and a single contextual qualification instead of repeating it in captions and expanded content. Workspace and map navigation use flat containers with a subtle separator; retain 44 px interaction targets and selected-state/focus contrast. Keep date, coverage, direction, missing-data and simulation disclosures visible; preserve all source references and downloadable evidence. No new tabs, navigation states or hidden operational alerts. Review browser text assertions when wording intentionally changes. No change to source acquisition, polling or calculations in this pass.


## Beginner-friendly progressive disclosure

Use native information popovers with the Material info icon and a short accessible label (e.g. Info, Riconciliazione) for optional definitions, examples and reading instructions. Prefer plain Italian, explain abbreviations and technical terms in context, and avoid repeated headings inside named tabs. Keep actual warnings, missing-data and simulation disclosures, source identifiers, dates and coverage visible or in their existing evidence sections; never hide a warning merely for aesthetics. Preserve detailed methodology and technical evidence behind existing expanders. Use 8px spacing for compact groups and 12px for common card padding, responsive content gutters, and avoid unnecessary minimum card heights. Maintain 44px main interaction targets and keyboard focus. Browser acceptance must verify that optional help can be opened and closed independently of the selected map reading.


## Plain-language navigation

Name screens by what a person can do, not by their implementation or an English industry acronym. Prefer Esplora dati, Bilanci e rettifiche, Calcola saldo utente, Simula scenario, Dati Snam and Agenda e scadenze. Keep canonical route URLs, widget keys and internal enum values unchanged; change visible labels with format_func or the existing picker mapping. Put map discovery first in the network selector while preserving the existing standalone scorte default and the application's explicit map intent. Use the existing native Info popovers for optional help, definitions and onboarding. Keep formal terminology in source citations, evidence, downloads, technical controls and calculations when necessary to avoid ambiguity. Never replace a technical concept with a simpler but incorrect one. Keep import restrictions, data availability, example-data warnings and provenance intact.


## Live-first presentation

The system overview is operational only: do not render or construct synthetic summary cards alongside public map data. Prefer public sources and imported records by default. When an acquired public market series is available in session, remove the redundant synthetic market source choice and keep the real historical archive explicitly labeled. Risk scenarios use the active or available acquired public base before a synthetic fixture; scenarios themselves remain hypothetical. When a relevant authorized settlement register or imported task/publication record is available, show the actual record directly and suppress the redundant example selector. Missing data must remain unavailable and must never be silently replaced by synthetic observations. Keep the separately labeled read-only guided cases and calculators for training or domains where no equivalent operational evidence is available. Preserve source dates, quality, coverage, import permissions and calculation logic. No live-availability guarantee is implied by a configured provider or a retained historical public copy.


## Remove rather than duplicate

Retire the standalone guided BSO showcase and executive walkthrough: their examples duplicate the actual balancing, settlement, operations and forecast tools. Keep examples only inside their relevant tools, explicitly labeled and never preferred to available real data. The operational overview renders the map directly. Preserve the existing public JRC archive, forecast/backtest engines, ACER evidence, import validation and operational tests. The retired /demo URL is intentionally no longer a registered destination. Existing Executive demo session selections migrate to operational indicators. Delete dedicated demo code, snapshot and CSS rather than keeping hidden copies.


## One task at a time

Commercial tools render only the selected view. Open actual document reconciliation by default; offer sample invoices explicitly only without an imported balance register. Do not mix simulated invoice, guarantee and calendar metrics into a global summary. Keep the existing settlement desk as the single balance/revision register; retain the distinct GNL allocation calculator. Do not repeat navigation catalogs or empty-state instructions when native controls already communicate the action. Keep required source, simulation and data-availability notices. Preserve core invoice and credit draft fields across commercial view changes in the session.


## Chat-first assistant

Default to Chiedi all’AI, regardless of model configuration; keep explicit activation, provider disclosure and quota protection. Esplora dati and Report remain separate task-oriented views. Show the selected evidence source and period near the chat; keep source/model settings and optional help in collapsed controls. Display a submitted question before computation and clearly separate failed requests from previous results. Free questions that can use independently available sources must not be blocked by a missing base market bundle. Keep history session-scoped, bounded and clearable. Distinguish model output from deterministic fallback and keep evidence and technical details available without repeated headings. Retire the separate GME assistant view and unsolicited GME price panels. For explicit GME questions only, display already acquired local observations with provenance; preserve the original readout in the bounded session history and direct missing data to the market workspace. Never fetch GME again when browsing assistant history or transmit licensed GME observations to an external model.


## Evidence-first analytical commands

The assistant supports a compact set of slash commands through the same validated, read-only question pipeline: /consumi, /scorte, /gnl, /prezzi, /produzione, /mase, /previsioni, /bollettino. Document them in an Info popover; unknown commands return a local guidance message without calling the model. Explicit market components and named sources take precedence over a mismatched base series. Distinguish observed percentage changes from hypothetical stress and parse explicit €/MWh price changes only in a scenario. The MASE UNMIG archive is an attributed historical transcription with exact year/month and available region selection, native units, no live claim and no substitution for an unavailable period. Terna actuals requested for a specific date use only complete observations from that date. Keep deterministic evidence for production, imports, exports, demand sectors and electricity, including zero values. Model synthesis starts with the useful answer, preserves periods, frequency, scope and unit, and states gaps instead of inventing data. The numeric validator checks supported unit-bearing claims but is not a proof of semantic correctness.


## Conversational follow-ups (P0)

Resolve explicit single-day follow-ups from the last chat analysis, not the selected historical entry or local reports. Preserve the previous user-defined indicator, named source and geography, and replace rather than concatenate the previous date. Show the resolved question and re-run the existing evidence pipeline. For explicit day comparisons, calculate chronological differences locally only from matched observed AGSI+, ALSI and SRG evidence with compatible scope, units, dates and availability, excluding flagged or estimated records. Distinguish percentage points from percentage changes. Do not silently interpret a weekly aggregate as a single day; request clarification for ambiguous scopes, multi-period comparisons, unsupported chart or causal references. Keep context session-only and reset it with history or failed analysis. No extra model call, persistent user memory or new dependency. Broader conversational planning, chart generation and document RAG are separate work.


## Autonomous assistant — no manual dataset or activation

Supersedes explicit assistant activation and manual source/model selection in earlier chat guidance. The configured model is immediately available in chat (no connection test or inference at render); global operator execution mode still applies to other tools. Only submitted questions or shortcuts trigger acquisition/inference; reports use the same automatic evidence routing without AI. Recognized public queries consult relevant validated adapters independently of a market base; unfamiliar public gas wording can use a bounded source-catalog selection, never arbitrary URLs, source identifiers, tool arguments or writes. Retain the three-call limit, remote quota enforcement, date and geographic validation, GME local-only policy and weather deployment restrictions. Computational questions automatically acquire an appropriate public daily or monthly series and use Automatic backtest selection, never an unsolicited synthetic substitute. Unknown/document questions retrieve actual indexed PDF passages from the public repository, public remote archive and permitted private/session collections; no shared cache of private uploads, no automatic remote transfer of excerpts or document questions. Local models use the existing citation-checked document RAG. Remote models without explicit document-sharing consent receive no PDF excerpts; show local passages instead. Missing, stale, unavailable and unsupported evidence are explicit. Source selectors remain in the dedicated data exploration tool, not in chat or reports. Preserve session-scoped conversation and independent history.


## Precise period evidence and gas-market semantics

Assistant historical requests must acquire the requested period, not merely search the default recent window. GIE exact closed gas days use the bounded range adapter; SRG uses a 14-day window ending at the requested closed gas day to preserve existing weekly context. Explicit month labels select national Eurostat and ARERA monthly observations, with MASE handled by its historical archive. Two explicitly compared days/months use only supported observed same-source, same-scope, same-unit pairs; exclude stale, estimated, partial or quality-review observations. Compute chronological absolute changes, percentage points for fill percentages, and relative changes only for positive baselines. Show both dates, units, coverage and source details; never represent two endpoints as a period average or total. Ambiguous aggregates or unsupported scopes return explicit gaps, not latest data. Never present ARERA CMEM,m as a daily PSV quote or ACER LNG–TTF benchmark as outright TTF. Keep absent direct quotes explicit. Strip stale nested values before model synthesis and validate explicit daily/monthly energy denominators against known source grain. No new UI settings, providers, dependencies or model calls for deterministic comparisons. Historical windows remain subject to provider access and publication coverage; no universal historical availability guarantee.
