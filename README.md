# GasOps AI

Local decision support for Italian natural gas markets. GasOps AI is an independent, read-only proof of concept with five Streamlit views for market monitoring, forecasting, settlement, regulatory research and agent operations.

## Start locally

Use Python 3.12 or newer from the repository directory.

```sh
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Open the URL printed by Streamlit and select **Run AI Market Analysis**. The offline dataset, forecasting, simulations and reviewed edition notes work without network access or a model. The [three-minute demo](DEMO.md) walks through the workflow. Unit tests and the dashboard smoke test run with `python -m pytest -q`.

The original CLI remains available with `python gasops.py example.json` and `python -m unittest -v`.

## Sources and scope

- **Offline demo** covers 420 Italian gas days with annual and weekly seasonality and deliberate data defects. Storage and prices are simulated. The data quality gate quarantines invalid or conflicting records and marks missing periods without imputing zero.
- **Eurostat** supplies monthly Italian observed inland natural gas consumption, including publication flags. GasOps converts gross-calorific-value TJ to GWh and retains the schema, source timestamps and original retrieval time in an eight-hour SQLite cache. A failed refresh shows a previously verified cache with an explicit status, or a source error. [Eurostat series](https://doi.org/10.2908/nrg_cb_gasm) · [Statistics API guide](https://ec.europa.eu/eurostat/web/user-guides/data-browser/api-data-access/api-getting-started/api)
- **Source research** found daily operational reports in Snam Jarvis, market and balancing price publications at GME, a public ENTSOG network-flow API, and a registered AGSI storage API. Open-Meteo publishes weather reanalysis suitable for a future demand-covariate study. The verified integration in this release is Eurostat. [Snam commercial information](https://www.snam.it/it/i-nostri-business/trasporto/informazioni-commerciali.html) · [GME API guide](https://www.mercatoelettrico.org/Portals/0/Documents/en-US/20251015Manuale_tecnico_API_En.pdf) · [ENTSOG API manual](https://transparency.entsog.eu/api/archiveDirectories/8/api-manual/ENTSOG_TP_API_UserManual_v3.0.pdf) · [AGSI API guide](https://www.gie.eu/transparency-platform/GIE_API_documentation_v007.pdf) · [Open-Meteo archive](https://open-meteo.com/en/docs/historical-weather-api)

Eurostat covers consumption only. Supply, storage, market prices and same-period aggregate balance are unavailable in that view. Participant settlement always uses explicitly supplied hypothetical volumes and buy/sell prices. Aggregate gap is supply minus demand and coverage is supply divided by demand. Both are screening indicators. The app uses 06:00 Europe/Rome gas-day starts and UTC timestamps, preserving elapsed daylight saving hours.

The forecast compares a seasonal naive baseline and a seasonal ridge regression. Walk-forward estimates use only earlier observations. When a horizon has at least 20 out-of-sample errors, the band uses their 10th and 90th percentiles. The chart lookback changes the visible range.

## Regulatory evidence

Upload searchable PDFs in **Regulatory Intelligence** or place local copies in `data/regulatory/`. `GASOPS_PDF_DIR` can point to another local directory. This checkout recognizes the reviewed copies by SHA-256. The register and cited edition notes ship with the app so the demo remains reproducible. Full text retrieval and page viewing use the local originals.

The register covers the 2023-I Piombino regasification code and Network Code Rev. XCII. It identifies the exact-page evidence, classifications and interpretations that require review. Applicability and approved revisions require independent verification. The application keeps source PDFs out of Git.

## Optional model and local state

Copy `.env.example` to `.env`, set `GASOPS_LLM_MODEL` and the compatible base URL, then choose that model from **Execution mode**. Ollama uses its local `/v1` endpoint and requires an installed model with tool-calling support. An HTTPS OpenAI-compatible endpoint may use `GASOPS_LLM_API_KEY`. Selecting an external model sends the analyst question and selected tool evidence to that configured endpoint.

The supervisor quality-gates data tools, runs independent calls in parallel and validates results before reporting. A configured model can choose bounded tool calls, request one follow-up round and interpret cited tool results. Calculations stay in Python. Provider failure falls back to the deterministic workflow or its validated results.

The app binds to loopback. Cache, run history and review acknowledgements are stored in local SQLite under `.gasops/`, configurable via `GASOPS_STATE_DIR`. The Ops Centre exports JSON and Markdown with provenance, assumptions and findings.
