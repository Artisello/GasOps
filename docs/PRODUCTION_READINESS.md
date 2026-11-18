# I.G.O.R. — Production readiness

## Release decision

Target: independent public demonstration, not production Snam operations. No official calculations, SLA, trading, billing, dispatch or validated regulatory opinions. Keep external datasets, demo inputs, manual declarations and forecasts distinct. This change does not activate paid services, deploy, rename the repo or modify existing remote data.

## Offline release gates
1. Python 3.12, install requirements in clean environment; pip check; full pytest; python -m gasops_app.readiness. CI records resolved packages, not a fully locked reproducible build. Readiness validates bundled archives and temporary SQLite backup/restore, not actual operational records.
2. Run the manual dependency audit workflow; inspect findings and address or explicitly document any accepted risk. Not a penetration test; advisory provider network may fail. Resolve exact transitive versions before a long-lived deployment.
3. Confirm no secrets or private files in current tree AND git history (this change only adds ignore rules; no history rewrite). Rotate any found credentials; use Streamlit Secrets or private environment. Do not place sensitive PDFs in public-regulatory or a GASOPS_PDF_DIR configured on a public deployment. The document archive treats the configured directory as public. Inspect actual Supabase grants/RLS and bucket policies before enabling upload; test unauthorized write/delete and authorized roles on a controlled environment. No actual Supabase access verified here.
4. Review source licenses and permissions; explicit opt-in for scheduled checks. API tests and credential validation under operator control. Check coverage, revision dates and units on official pages. Never market a source as live just because parser tests pass.
5. Smoke test all 9 routes on deployed instance with two independent browser sessions: no cross-visitor report/document leakage; graceful no-key/no-provider behavior; empty KPI and historical views; model opt-in; PDF review authorization; responsive desktop/mobile. Record screenshots and date. Follow DEMO.md.
6. No real Snam participant records in public deployment. Keep AI deterministic by default. Explicit model selection authorizes remote public analytical requests, with separate PDF consent. Public UI reports only in session; export before closing. Legacy PDF uploads bypass global cache. Existing SQLite records are not deleted; inventory and securely handle any older persisted reports.
7. Private monitor: verify scheduler, access permissions, disk quota, actual backups and restore (separate protected directory). Collection timestamps represent completed attempts, not source publication. Diagnostic job is disabled until authorized variables configured; no secret/data artifact publication.
8. Rollback: revert release commit through GitHub, redeploy last verified revision, preserve local state and Secrets, never blindly roll back databases or public document archive. Back up first. If unauthorized disclosure suspected, restrict access, revoke credentials, investigate and follow applicable incident process.

## Acceptance matrix

| Area | Evidence to obtain | Status before external review |
|---|---|---|
| Offline tests and structural gate | CI success on exact release SHA | Pending CI |
| Dependencies | Manual audit and resolved inventory | Pending |
| Public demo | Nine routes, desktop/mobile, dual sessions | Pending deployed smoke |
| Public providers | Current authorized source response and attribution | Partial; previously tested contracts vary |
| Jarvis/GME | Native public formats and permission | Manual/link-only |
| Terna/GIE | Real authenticated tests and terms | Pending operator |
| Regulations and settlement | Current editions, independently reconciled examples | Study only |
| Monitoring | Enabled job and protected archive with recovery test | Opt-in, not activated here |
| Formal production use | Snam owner review, access model, security/compliance and operational acceptance | Not certified |

Release only a clearly labelled demo after gates relevant to the demo pass. A real operational deployment needs an authorized environment, access control, independent validation, data retention and support ownership. Do not erase or modify existing data as part of this checklist.
