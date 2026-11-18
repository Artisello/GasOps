# P2 — consolidated KPI rendering and calculation consistency

Existing overview only: management report first after month and participant filters, populated after import handlers finish in the same render. Explicit refresh samples time after I/O. Detailed controls and exports kept; duplicate overdue warning removed and detail collapsed. Independent public KPI groups fail separately; combined error notice.

Reuse one inspection per bundle for market score and health/report in the same render, using local object identity rather than shared or persistent cache. No new provider calls, no extra dependencies, no weather default changes. No measured performance claims.

Future acquisitions must not count as valid coverage; comparison restricted to real/historical ENTSOG bundles. SAS training rejects vintages outside the historical gas day, including DST edge cases. 6PI uses shared gas-day cutoff; market action counts missing when no complete days. Tests use synthetic fixtures; CI/browser and real data validation remain necessary. This is a targeted consolidation, not production certification.
