# Snam forecasting reliability

Optional extended experiment in Market > Forecasting Snam. Re-import annual archives for exact F (direct clients), H (other networks), J (exports) labels. G thermoelectric and K storage are not complete across horizons. Terna is separate; no aligned archival electricity vintage history verified.

Fixed ridge residual contender, shared dated training and evaluation samples vs the published Snam, weekly naive and baseline ridge. Anchor evaluation to latest mature baseline outcome. Refuse insufficient shared dates. Warm-up produces out-of-training predictions; empirical 90% nominal interval uses up to 90 previously available absolute errors, minimum 30, with finite-sample order statistic. Report observed coverage; no guarantee, no automatic model promotion. Provisional G-1 reference, unconfirmed native units, possible historical revisions. Session only, no external calls or credentials.

Local independent profile of supplied archive, cutoff 18 November 2026 15:00, 90 shared target dates through November 17: MAE thousands native units (weekly / Snam / baseline / extended): G 199.31 / 30.84 / 32.45 / 31.04; G+1 199.31 / 52.35 / 52.13 / 52.82; G+2 199.31 / 102.65 / 96.50 / 94.06. Exploratory, reproduce final code on authorized inputs. Tests use synthetic fixtures. No raw data committed.
