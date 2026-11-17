# GasOps AI — educational multi-agent workflow prototype

Independent, unofficial example based on two provided Snam code editions. No Snam affiliation, production connectivity, credentials or operational actions. All example data are synthetic. Python 3.10+ with IANA timezone data (on Windows, install tzdata if needed).

```sh
python gasops.py example.json --output report.json
python -m unittest -v
```

Supervisor runs a quality gate, then parallel balance and settlement screening tools plus an independent regulatory screen. Blocking findings require human review. JSON contains source rule references, input SHA-256 and deterministic results. Simplified supply-minus-demand is NOT the official system imbalance equation. Settlement uses supplied imbalance and prices, excludes special conditions, taxes and adjustments. The 7-day rule is not guessed. This is not a certified billing engine or forecasting system.

Optional AI narrative only: with an already running local Ollama installation and local model, run `GASOPS_OLLAMA_MODEL=your-installed-model python gasops.py example.json`. The model receives the synthetic report and cannot invoke tools or perform operations. Its text is unverified. By default no model or network is used. Optional local model path has not been integration tested.

Future scope: public Jarvis/GME/ENTSOG ingestion, historical backtesting, versioned regulatory RAG, persistent orchestrator, human approvals, source provenance and full settlement rules. Never connect to production without authorization, validated rules and security review.
