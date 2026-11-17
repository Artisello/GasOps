# Three-minute GasOps AI demo

Launch with `streamlit run app.py`. Start in **Market overview** with **Italy · offline demo** and **Deterministic**.

| Time | Show | What to point out |
| --- | --- | --- |
| 0:00–0:40 | In Overview, click **Run AI Market Analysis**. | Trace the six tool executions. The latest simulated demand is 2,348.4 GWh, supply is 2,268.7 GWh and coverage is 96.6%. The outlier panel flags a supply spike on 3 November 2026. |
| 0:40–1:25 | Open **AI Operations Centre**. Select the latest run, expand an agent and export JSON or Markdown. | Review the forecast, signed simulated settlement of −€50,400 and +10% demand scenario at 87.8% coverage. Inspect the input fingerprint and the human review queue. Try the example question about last week. |
| 1:25–2:05 | Open **Balancing & Settlement**. Change the buy price to −42 and calculate. Open **Aggregate scenarios** and vary storage or supply. | The short position becomes a simulated credit at a negative buy price. The aggregate table recomputes coverage and gap value separately. |
| 2:05–2:40 | Open **Regulatory Intelligence** and inspect the exactly seven days finding. | The two Piombino tables on PDF pp. 103–104 omit equality, so the case remains open for review. With the original PDF installed, open the cited page in the Evidence explorer. |
| 2:40–3:00 | Open **Market & Forecasting**. Compare error scores, then select **Eurostat · Italy** with network access. | The public source switches the charts to monthly Italian consumption and displays flags and freshness. Stay on the offline source when presenting without internet. |

The default fixture includes a missing period, a missing demand value, a duplicated row, a conflicting reading, an invalid unit, an inconsistent timestamp and a supply outlier. Publication time in the fixture is simulated. The reviewed edition notes are available from a clean checkout. Add the original PDFs locally for full-page inspection and broader retrieval.
