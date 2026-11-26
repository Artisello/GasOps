# I.G.O.R. — Production readiness

## Release decision

Target: independent public demonstration, not production Snam operations. No official calculations, SLA, trading, billing, dispatch or validated regulatory opinions. Keep external datasets, demo inputs, manual declarations and forecasts distinct. This change does not activate paid services, deploy, rename the repo or modify existing remote data.

## Offline release gates
1. Python 3.12, install requirements in clean environment; pip check; full pytest; python -m gasops_app.readiness. CI records resolved packages, not a fully locked reproducible build. Readiness validates bundled archives and temporary SQLite backup/restore, not actual operational records.
2. Run the manual dependency audit workflow; inspect findings and address or explicitly document any accepted risk. Not a penetration test; advisory provider network may fail. Resolve exact transitive versions before a long-lived deployment.
3. Confirm no secrets or private files in current tree AND git history; no history rewrite here. Rotate any found credentials; use Streamlit Secrets or private environment. Only `data/public-regulatory` and the explicitly public Supabase bucket are public archives. `GASOPS_PDF_DIR` is ignored without private authorization. Inspect actual Supabase grants/RLS and bucket policies before enabling management; test unauthorized write/delete and authorized roles on a controlled environment. Listing connected projects does not identify or certify the deployed GasOps bucket.
4. Review source licenses and permissions; explicit opt-in for scheduled checks. API tests and credential validation under operator control. Check coverage, revision dates and units on official pages. Never market a source as live just because parser tests pass.
5. Smoke test all 9 routes on deployed instance with two independent browser sessions: no cross-visitor report/document leakage; graceful no-key/no-provider behavior; empty KPI and historical views; model opt-in; PDF review authorization; responsive desktop/mobile. Record screenshots and date. Follow DEMO.md.
6. No real Snam participant records in public deployment. AI starts deterministic even when configured. Explicit activation authorizes remote public analytical requests, with separate PDF consent. Reports, chat and visitor PDF indexes stay in session. Server PDF overrides and private previews bypass process-wide caches. The web Store wrapper rejects unauthenticated private-history reads/writes. Existing SQLite records are not deleted; inventory and securely handle older persisted reports.
7. Private monitor: verify scheduler, access permissions, disk quota, actual backups and restore (separate protected directory). Collection timestamps represent completed attempts, not source publication. Diagnostic job is disabled until authorized variables configured; no secret/data artifact publication.
8. Rollback: revert release commit through GitHub, redeploy last verified revision, preserve local state and Secrets, never blindly roll back databases or public document archive. Back up first. If unauthorized disclosure suspected, restrict access, revoke credentials, investigate and follow applicable incident process.

## Acceptance matrix

| Area | Evidence to obtain | Status before external review |
|---|---|---|
| Offline tests and structural gate | CI success on exact release SHA | Pending CI |
| Dependencies | Manual audit and resolved inventory | Pending |
| Public demo | Nine routes, desktop/mobile, dual sessions | Pending deployed smoke |
| Public providers | Current authorized source response and attribution | Partial; previously tested contracts vary |
| Jarvis/GME | Authorized native sources | Jarvis uploads, GME background API in active sessions |
| Terna/GIE | Real authenticated tests and terms | Pending operator |
| Regulations and settlement | Current editions, independently reconciled examples | Study only |
| Monitoring | Enabled job and protected archive with recovery test | Opt-in, not activated here |
| Formal production use | Snam owner review, access model, security/compliance and operational acceptance | Not certified |

Release only a clearly labelled demo after gates relevant to the demo pass. A real operational deployment needs an authorized environment, access control, independent validation, data retention and support ownership. Do not erase or modify existing data as part of this checklist.

## Operational sources in Overview and Security of Supply

Overview and the existing operational views read the validated SQLite cache and submit background work on demand or when evidence is due. A cold start requests 90 completed Italian gas days. Requests for the most recent seven days take precedence. The ENTSOG network worker processes every verified direction with bounded date windows, timeouts and pacing. National AGSI+/ALSI reuse the configured GIE key. Incremental runs refresh the recent window after 12 hours for ENTSOG/SRG and 24 hours for GIE. Selecting an uncached date requests that date. After a timeout or quota error the last validated copy remains available with its acquisition time. Failed recent requests are eligible again after 15 minutes. Use a persistent volume for `GASOPS_STATE_DIR` to retain SQLite state across deployment restarts. [ENTSOG API guide](https://transparency.entsog.eu/api/archiveDirectories/8/api-manual/ENTSOG_TP_API_UserManual_v3.0.pdf).

The default date is the latest completed gas day with at least 80% of the best observed coverage in the visible history. This compares valid point directions, SRG sector totals and available GIE aggregates. Balance components use the selected gas day with Europe/Rome boundaries, including 23/25-hour days. The storage stock KPI can show an earlier date explicitly. Use **Fonti operative → Consulta lo snapshot storico** for the bundled archive. The map refresh includes all verified points for the selected period and the selected infrastructure's optional details.

## 23 November 2026 hardening: scope and contracts

Base: `c992f11` (merged PR #134). This increment adds no pages, analytical models, infrastructure telemetry or production deployment. It preserves public demo fixtures, the workbench layout, all existing routes and the single network map.

### Access boundary

- `GASOPS_PROFILE=public_demo` is the default; unknown values fail closed to the public profile. The legacy `GASOPS_APP_MODE` controls layout only. `test` has no private permissions.
- `private_workbench` requires `st.user.is_logged_in`, the exact server-configured `GASOPS_AUTH_ISSUER`, a subject in `GASOPS_PRIVATE_SUBJECTS`, and a non-expired `exp`. Missing claims deny access. No URL, form or session-state value chooses a server profile. The application checks access before importing page modules; private operations check it again.
- The standard requirements include `streamlit[auth]` for the Workbench. Configure Streamlit OIDC in `[auth]` with a real identity provider for that profile. Identity-token expiry is checked on each private operation. Identity-provider logout/revocation and operational authorization are deployment acceptance items. See [Streamlit authentication](https://docs.streamlit.io/develop/concepts/connections/authentication).
- GME uses the server-side `[gme]` Streamlit Secrets. Its availability is independent of the application profile. Configure the integration on the deployment authorized to consume the GME account’s data. The standard GME licence calls for private use, so enforce access at the deployment boundary for that use. See [GME deployment configuration](gme-market.md).
- Public visitors cannot read configured private server PDF directories or persisted report history. Public Supabase management is disabled, including direct calls to the archive HTTP boundary. An authorized private user still needs the existing Supabase administrator/contributor identity and Storage policies.
- Public PDF uploads remain supported in the visitor's session and keep the existing separate remote-AI consent. Only public repository PDFs/public bucket objects use the shared resource cache. No private upload enters a global cache or export of another session.
- Supabase SQL templates were reviewed against [Storage access control](https://supabase.com/docs/guides/storage/security/access-control): public SELECT is intentional for declared public documents; INSERT/DELETE are bound to explicitly allowed Auth UUIDs. Actual grants, RLS, bucket contents, anonymous direct writes and deployed Auth were **not tested**: no GasOps project reference/administrative deployment configuration was identified. Connected project availability is not evidence of correct GasOps policies.

### Temporal evidence

`freshness.temporal_evidence` adds a common presentation contract to existing source-health rows and map evidence. It retains `gas_day`, the UTC observation interval, `observed_at`, `published_at` when known, `retrieved_at`, cache age, coverage, publication status and data status. Original observation models, adapter units, direction and provenance remain intact. Map legacy status keys are retained for compatibility; displayed source badges use the common data status. The cockpit and Explorer reuse Source Health; system balance evidence and overview source details retain publication/acquisition separately.

Primary status precedence: unavailable measure → failed refresh with retained measure → stale cache → partial/invalid temporal metadata → historical observation period → cached current-period observation → current validated period. Historical/cached/partial/stale/failed flags are retained independently. “Current” means validated for the reference period, **not** a live provider check. A recent download never promotes a 2021 observation to current. A stale acquisition does not by itself change the observation period to historical. Missing values stay absent; zero is a valid measurement only when published. Timestamp uncertainty stays absent; no publication time is synthesized from an acquisition. DST uses existing Europe/Rome 06:00 boundaries (23/24/25 hours).

Cache thresholds stay separate from tolerated observation age: 12 hours for ENTSOG/ARERA/Terna diagnostic rows, 24 hours for GIE inventories, six hours for weather outlook and 24 hours for archived weather. A three-day observation allowance never extends a provider's 24-hour cache threshold. The final freshness/source-health regressions cover this independently (**51 passed** locally).

Provider capabilities extend the existing Fonti e API catalog, without a second connector registry. Configuration, successful last explicit reachability/schema check, usable observations, period, acquisition and limitations are separate columns. No live check means **Verifica live pendente**, not connected/validated. Public archives (including MASE) remain historical; Jarvis uses authorized imports. GME uses the configured API with a session-local cache. AGSI+ and ALSI were verified against the Italian aggregates. Live Terna validation remains pending operator access.

### Loading and usability

- Route modules and statistical/document-search libraries load on demand; formulas and parameters are unchanged. Empty PDF workspaces do not import the text-indexing library.
- Public repository PDF metadata is cheap to show; “Apri PDF pubblici” authorizes indexing. The index is then reused across reruns and public sessions. Private/session PDFs never enter that cache.
- Remote archive refresh and IIP/other GIE perimeters require explicit controls. National AGSI+/ALSI use the shared background reader described above. Market source rendering reads only validated existing cache; “Aggiorna dati” authorizes acquisition. An expired local copy retains its original timestamp and is not reported as a failed request when no request occurred.
- Opening the assistant prepares controls only; it no longer runs a forecast/report or chooses a remote model. Existing starters, reports, exports and explicit AI activation remain available.
- Domande mirate come «CMEM,m del 21/10/2026», «differenziale GNL–TTF in Europa» o «flusso in ingresso a Tarvisio» selezionano la fonte pertinente. Il flusso di un punto usa le osservazioni ENTSOG verificate già in cache, con giorno gas e direzione. Le date esplicite richiedono lo stesso giorno o il mese di competenza della fonte.
- L’assistente verifica le quantità con unità riconosciute rispetto alle evidenze della sezione citata. Dopo un tentativo di correzione, conserva i dati validati e i link alle fonti. Le richieste IGI e prezzi di sbilanciamento GME sono consultabili localmente, fuori dal prompt e dall’esportazione dei valori.

### Reproducible acceptance

Automatic: `python -m pip check`, `python -m pytest -q`, `python -m gasops_app.readiness`. Negative access/session/temporal tests are in `tests/test_release_safety.py`. Existing tests for the public document index, per-visitor documents/chat, source health, gas-day/DST, models and map remain regression gates.

Real browser (development dependency only; installed Chrome, no production dependency):

```sh
npm install --no-save playwright-core
node scripts/check_release_browser.cjs --url http://127.0.0.1:8770 \
  --chrome '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' \
  --output /tmp/igor-release-browser
```

Alternatively set `GASOPS_PLAYWRIGHT_MODULE` to an isolated playwright-core installation. The script uses two independent browser contexts, native controls, one generated non-sensitive canary PDF, explicit local report actions, route navigation and a mobile viewport. External browser requests are blocked and recorded. It writes `acceptance.json` and screenshots. Failures remain failures; no screenshot or AppTest alone is a completed native browser acceptance. `scripts/check_network_browser.py` remains the dedicated marker/pipeline/WebGL regression script.

| Control | Result / evidence |
|---|---|
| Negative private access, arbitrary URL/session flags, server PDF override | PASS — automated negative regressions and private-browser direct URL attempts; exact run recorded with the PR |
| Cache-only navigation, missing data and source timing | PASS — automatic regressions; no acquisition during view/filter changes |
| Nine principal routes + Fonti/API and demo | PASS — native Chromium on localhost; Workbench overview also tested |
| Two independent sessions, PDF/report and map selection | PASS — native Chromium contexts, canary PDF, explicit report and distinct map modes; marker at 12 px offset and pipeline at 8 px offset selected |
| Actual OIDC login/role revocation | NOT TESTED — no production identity provider/claims available |
| Actual Supabase policies and direct resource authorization | NOT TESTED — project/bucket mapping unavailable; no production changes |
| Authenticated GIE/Terna live APIs | NOT TESTED — operator credentials/terms required |
| Current deployed Streamlit revision | NOT TESTED — read-only attempt at https://snamigor.streamlit.app/ timed out in an independent browser context; this commit was not deployed |
| Production data retention, backup and recovery | NOT TESTED — existing persistent state preserved |

This matrix does not certify Snam operational readiness. Residual public-demo risk includes any sensitive documents already placed in a public bucket or repository, unverified remote policies and legacy data retained on the server. Restrict/remove exposure through an authorized incident process if discovered; this change does not erase records or change production permissions.

Local comparative loading sample (Python 3.12, same machine/environment, network forbidden, Streamlit AppTest with the same profiling wrapper): first Overview run **5.816 s → 2.819 s**; median of three subsequent reruns **0.201 s → 0.211 s**. Scikit-learn and statsmodels are absent from the initial Overview imports after the change. This measures local initialization, not Streamlit Cloud/network latency and is not a timing assertion in CI.

Local validation: `pip check` and the nine offline readiness checks passed. Full suite before the last added consistency regression: **789 passed, one SARIMAX convergence failure** already reproduced on unchanged `main` in the same Mac environment (documented in PR #134). Final map, access, archive and weather regressions: **82 passed**. The current PR's complete Linux CI is the authoritative exact-commit result; statistical formulas/parameters were not changed to hide the local numerical difference.
