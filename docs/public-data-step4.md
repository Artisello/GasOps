# Step 4 — ENTSOG Network Intelligence

New Stoccaggi e forniture > Interconnessioni view, independent of existing three-aggregate SRG demand source and GIE. Based on ENTSOG TP API manual v3.0:
https://transparency.entsog.eu/api/archiveDirectories/8/api-manual/ENTSOG_TP_API_UserManual_v3.0.pdf

One operator / point / direction, 1–31 completed Italian gas days, max 500 records, one on-demand keyless request, 12-hour existing SQLite cache, no automatic retries or scheduled calls. Candidate SRG entry IDs for Mazara and Melendugno from https://energy-desk-two.vercel.app/data?commodity=natgas ; verify returned point/operator identity. Other ITPs can be entered using exact identifier from official catalogue at https://transparency.entsog.eu/api/v1/operatorpointdirections.csv . No presumption of full Italian or EU border coverage.

Seven documented indicators: Physical Flow, Nomination, Renomination, Allocation, Firm Technical, Firm Booked, Firm Available. Same point/unit/day only. kWh/d to GWh/d / 1e6; no 23/25-hour multiplier; validate boundaries including DST using existing gas_timestamp. Missing, N/A, conflicting values remain missing; disagreeing metadata flagged; no auto selection of ambiguous revision. Raw statuses and source updates are carried when supplied, not a point-in-time vintage dataset.

KPI: last observed physical flow and technical utilization (same day), coverage of requested slots, physical flow minus daily nomination/renomination, allocation minus physical flow, booked/technical. These are descriptive differences of published aggregates, not shipper imbalance, guaranteed ex-ante forecast error, congestion, or settlement costs. No sums across points/directions or links to other models. No fake observations.

Attribution includes ENTSOG TP Transport Data, extraction date and URL on charts and exports. Terms https://transparency.entsog.eu/pdf/Terms_and_Conditions_of_Use.pdf ; respect provider restrictions, no bulk extraction or redistribution permission implied. Provider may revise data; cache is not durable revision history. No new software dependencies, API key, recurring job, or LLM calls.

CI: synthetic regression tests, not a verified live contract. The external tool could not open a live request in this session. Before production relying on the data, test multiple ITPs, inspect actual indicator/unit/labels/status and verify coverage; don't equate absence with zero.

Run python -m pytest -q tests/test_entsog_network.py
