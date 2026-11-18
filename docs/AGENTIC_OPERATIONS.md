# Process Automation & Agentic Operations

KPI operativi > Centro operativo. Four deterministic agents orchestrated by an explicit scan:
- Operations: overdue declared tasks (all dates), upcoming <=24h.
- Balancing: missing numeric SAS estimates on closed gas days in selected month. No invented thresholds.
- Settlement: exception or nonzero revision from latest version using existing daily controls, one selected participant/month. Prices and amounts are reported evidence, not payable instructions.
- Data Quality: monitor report timestamp, status and flags, a single proposal per provider; skipped sources are not success. No external retrieval.

No input = explicitly unavailable control, no fake healthy results. Priorities are review heuristics, not Snam SLAs or risk classification. Each proposal has deterministic logical key and evidence-version hash; repeated scans deduplicate identical evidence. Changed evidence creates a new review version. Old evidence is preserved and absence from latest results is not clearance. Scans are explicit: refresh after inputs change. Human transition requires note; verifying means a user annotation, not certified settlement or task completion. JSON handover includes evidence, timestamp, coverage, history and latest-scan membership; identifiers are hashed references, not anonymization. No actor authentication; do not use real sensitive identifiers or notes on public instance. No network, LLM, external messaging, task mutation, payments, shared persistence, or autonomous trading/dispatch. Session-only bounded store (600 cases / 20 events per case), export before resetting. Synthetic fixtures separate from imported data; demo uses November deadlines/SAS and September settlement. Monitor report not independently authenticated.

Tests exercise deterministic proposals, no input, valid transition, note requirement, idempotence, preserved decisions, demo isolation. Actual team procedures, permissions, notification channels, SLA and production access need separate agreement before live workflows.
