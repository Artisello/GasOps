# Step 3 — Jarvis public intelligence

Official Snam sources:
- https://www.snam.it/it/i-nostri-business/trasporto/informazioni-commerciali.html confirms daily/annual operating data, provisional/final balances, WKR and Gas Stock publications.
- https://jarvis.snam.it/public-data?lang=it is the public catalogue; the dynamic file listings and actual native numeric files were not accessible in this environment.
- https://jarvis.snam.it/public-data?lang=it&periodo=2025&pubblicazione=Dati+Operativi+bilanciamento+%E2%80%93+giornalieri (daily balancing archive landing page).
- https://www.snam.it/en/our-businesses/news/2025/jarvis-marketplace-access-to-the-API-catalog.html announces a WKR API. Access, token, terms, endpoints and live payload not verified.
- https://www.snam.it/en/our-businesses/news/2025/publication-of-the-calibration-parameter-q-values-pursuant-to-resolution-482-2024-r-gas-and-operational-application-procedures.html explains q publications by gas day and cluster.

No actual numeric publication retrieved; no automated endpoint guessed, no public-source license assumed, no synthetic observations in the dashboard.

## Usage

Stoccaggi e forniture > Rete Snam > Archivio pubblicazioni (existing intraday estimates kept separate). Download the normalized header-only CSV. Copy only authorized public aggregate values from the original report. Use dot decimal, ISO gas-day date and actual publication timestamp with offset. If the publication time is not known, do not invent one. Preserve source signs and units. `report_ref` is a public title/ID only, no client details.

| family | stage | scope | metric | unit |
|---|---|---|---|---|
| balance | provisional / definitive | SRG | injections / withdrawals / balance_reported | MWh / GWh / Sm3 |
| wkr | forecast / observed | climate:public-code | wkr | ratio |
| q | published | cluster:public-code | q | fraction / percent |
| gas_stock | published | SRG | gas_stock | MWh / GWh / Sm3 |

These are I.G.O.R. mapping conventions, not a claim about all native report fields. Only map an actual matching value. Do not use for individual positions or inferred SAS. Missing data omitted, not zero. Use same units and scopes for comparisons. No implicit conversion or profiling calculation.

Revisions: group by gas day, exact metric, unit, scope; compare latest definitive with latest earlier provisional only when the newest record is definitive. Report distinct version counts and both timestamps; do not label missing pairs as zero. Later provisional invalidates comparison for that slice until review. WKR, q and gas stock latest by publication shown separately; all versions available in export.

Multi-file session accumulation, SHA-256 per input, UTC timestamps, exact decimal calculations, conflict rejection entire import, duplicate idempotence. No persistent storage in the public multi-user app; not sent to the LLM. This deliberately does not import unverified user extracts into the shared warehouse. CLI and public archive integration can follow after native files and permissions are verified.

Tests: `python -m pytest -q tests/test_jarvis_archive.py`. Synthetic fixtures test behavior, not source schema or live access. No new dependency, scheduled job, credential or production deployment.

Next: acquire actual public Jarvis exports with verified reuse permission; map native formats and reconcile against published totals; only then persist attributable validated observations or build operational KPIs.
