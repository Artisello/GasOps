# Assistant data query engine (P1)

The main chat routes explicit historical interval questions to a bounded, deterministic query engine. It does not execute generated SQL/Python, invoke an LLM, transmit retrieved data to a provider, or add a new UI workspace.

Examples:
- Totale delle importazioni negli ultimi 12 mesi
- Media dei prelievi SRG negli ultimi 30 giorni
- Variazione del riempimento degli stoccaggi negli ultimi 7 giorni
- Media del CMEM,m da agosto 2026 a ottobre 2026
- Correlazione tra prelievi SRG e riempimento degli stoccaggi negli ultimi 30 giorni

The supported catalog subset includes Eurostat national monthly balance, ENTSOG daily Italian SRG withdrawals, ARERA CMEM,m and Italian AGSI+ indicators. The source and metric semantics are reused from the assistant's catalog. The query accepts one explicit interval and operation, at most three metrics, 36 completed months or 90 completed gas days. ENTSOG uses at most three bounded requests; other selected families use existing source adapters. GIE needs configured credentials. Existing source licensing and local-only restrictions remain intact.

Means are unweighted arithmetic means. Totals are permitted only for monthly national energy quantities and daily SRG withdrawal quantities. Changes compare the first and last observations, and differences between percentages use percentage points. Standard deviations are sample standard deviations; daily Pearson correlation requires two nonconstant series and at least 14 matched observations, and does not imply causation. All operations require complete period coverage; missing observations are explicitly reported. Recent months may be incomplete due to publication lag; do not silently move the requested interval.

No substitutions across gas/electricity markets, national/SRG scopes or unsupported countries; no historical forecast, free-form statistical code, PSV/TTF quotes or interval comparisons yet. Other existing chat paths and the separate Esplora dati planner remain unchanged. The report retains calculated evidence, source links, dates, coverage and available provenance; the report SHA-256 identifies the calculated payload, not the raw source response.

Regression cases use artificial data and do not verify live provider authorization or coverage.
