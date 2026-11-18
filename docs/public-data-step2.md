# Step 2 — MASE historical production

## Delivered

Three attributed **transcriptions**, not native downloads:
- UNMIG Databook 2025, table “Produzione di idrocarburi. Serie storica 2004–2024”: annual IT / land / sea, billions of standard cubic meters, original rounding.
- Report 2025, data through 31/12/2025, update 27/04/2026: annual/monthly national, land, sea; annual regional/marine breakdown. Sm³ as published. Source: https://unmig.mase.gov.it/wp-content/uploads/dati/produzione/produzione-2025.pdf
- Report 2026, version 22/05/2026 (screenshot of report), data through 28/02/2026: January and February only. The portal currently reports newer data but this edition was independently readable. No zero filling. The report URL can be updated by the provider.

Source: MASE–UNMIG, CC BY 4.0. Historical source: https://unmig.mase.gov.it/wp-content/uploads/2025/09/databook-2025.pdf . Original tables are not bundled. No claim of copying original bytes. Source IDs distinguish editions; hash covers the transcription, not original PDF. Published totals are retained, not recomputed from components; source inconsistencies may remain. No ungrounded Sm³-to-GWh conversion.

UI: Stoccaggi e forniture > Produzione. The dashboard uses packaged extracts, independent of GIE and without network calls. To also populate local warehouse:

```sh
python -m gasops_app.warehouse seed-mase-reports
python -m gasops_app.warehouse manifest
python -m pytest -q tests/test_mase_archive.py tests/test_public_warehouse.py
```

## Open work

- Native UNMIG CSV link verified on the official page, but the bytes were not accessible in the authoring environment. Step 1 downloader remains raw_pending. No guesses at its schema.
- SISEN publishes annual regional and provincial gas distribution workbooks and monthly gas-balance workbooks; actual workbook contents are not accessible through the current browser (JS) or local network. Links included; no fabricated workbook schemas or consumption values. SISEN declares source attribution / IODL 2.0 on its open-data page: https://sisen.mase.gov.it/dgsaie/open-data . Verify individual file reuse terms before publication.
- No changes to forecasts, operational KPIs, settlement, scheduler or existing data sources. The 2025 report and 2026 edition are historical, not live. Future native ingestion should use a distinct source ID, explicit units and revision metadata; no automatic joins across geography, frequency or vintage.
