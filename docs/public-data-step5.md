# ACER Market Intelligence — Step 5

Mercato e previsioni > Mercato europeo ACER is independent of the demand source. No new dependency, API key, scheduler or AI call.

## TERMINAL
Public table: https://aegis.acer.europa.eu/terminal/price_assessments ; official download link https://aegis.acer.europa.eu/terminal/price_assessments/historical_data was followed and returned unsupported content type text/csv in authoring browser. Native CSV bytes/headers therefore unverified. Parser only accepts explicit columns matching observed public HTML headings (EUR/MWh), YYYY.MM.DD or ISO dates, comma/semicolon/tab, missing values and signed decimals. Reject conflicts and future dates. User-triggered download, existing SQLite cache 24h, max 2 MB and single attempt; manual CSV import session only. If native format varies, adapt after live diagnostic; no schema inference.

Bundled extract: 19 actual publication dates 1–25 September 2026, transcribed from the public TERMINAL HTML table consulted November 2026 (cached page, not latest). No synthetic placeholders; not the native original. SHA-256 covers decoded text only. UI clearly marks stale data. Source attribution in CSV; source legal notice https://www.acer.europa.eu/legal-notice ; only agency-published observations reproduced, no third-party licensed CHEST datasets. Check specific terms before further reuse. Methodology https://www.acer.europa.eu/gas/lng-price-assessment . Benchmark is published spread to TTF front-month, separate from outright DES spot prices. South minus NWE derived only from same-date paired data. No implied TTF calculation/forecast or settlement pricing.

## BAF
47 labels transcribed from 2025 report pp. 16 and 19, gas year 2023/2024: 23 zones imbalance quantities share and 24 zones net adjusted neutrality / market volume. Source https://www.acer.europa.eu/sites/default/files/documents/Publications/ACER-Gas-Balancing-Indicators-Highlights-2025.pdf (consulted Nov 2026); text extraction accessible, page screenshot attempted but cache miss. Retain rounded published values; no general efficiency ranking, cross-zone averaging or invented missing zones. Latest 2026 report (23 Oct 2026, GY 2024/2025) identified, PDF inaccessible; link only. CHEST links only, no ICIS/third party data ingestion.

No integration to forecasting/settlement or shared warehouse beyond cache; no live confirmation yet. Regression tests and opt-in CI smoke test. 
