# Lean BSO operational core

Study editions supplied by user: CdR XCII (PDF pp. 351, 362, 368–370, 378–380) and CdRig Piombino 2023-I (p. 88). Applicability and current versions not certified. No new dependencies, menu items, provider accounts or write actions.

Balancing > Stato sistema / Stoccaggi e forniture > Rete Snam: existing authorized, non-confidential normalized CSV is cumulative, exact duplicate versions deduplicate, conflicts reject atomically; cap 2,000 records; download canonical CSV to restore; no server persistence or scheduled collection. Prior hashes retained in session; restored CSV has its own hash. Missing metrics hidden from headline cards. New optional study of revisions: match close-relative UTC cutoff (one-hour backward tolerance) and last publication within 90 min of end-of-day; train only on prior closed days, minimum 30, empirical median and 10/90 quantiles; growing-window retrospective diagnostic after 20 more pairs, raw baseline and coverage. No actual imbalance label; no signed short/long probability or market action. Current stale >3h excluded. Not an operational calibrated forecast, no guarantee of improvement. Does not ingest native unverified intraday schemas.

KPI > Calendario Snam: calculated six study deadlines, user-supplied holidays, weekdays, no fabricated time for date-only terms; does not assert completion. Rinomination final cutoff 3h before gas-day end, provisional G+1 11:30, definitive M+1 day 28 adjusted to workday, manifest error window +2 workdays, LNG proposal 9th workday 13:00 and debtor/creditor notification 8th workday 12:00. Verify exceptions and actual calendar; no automatic reminders.

Balancing > Controllo giornaliero: optional public SRG network aggregate CSV, exact phase/day and all terms in GWh supplied, GNC calculated (signed) as residual; compare supplied GNC only, tolerance explicitly study parameter. No imputing missing terms, no coupling to participant DS, SAS, settlements or invoices. Existing settlement desk unchanged. No actual source acquisition or private data; tests use fixtures. Separate later work: full EPSu/MEPSu calculation, adjustments, LNG stock and vessel scenarios, and broader rules, after inputs and applicable editions confirmed.

## Registro di settlement e giornate concluse

Il CSV dei bilanci aggiunge le nuove versioni al registro della sessione. Una riga
già acquisita è ignorata se identica. Una versione in conflitto blocca l’intero
nuovo estratto. Il registro completo è esportabile e ricaricabile con le medesime
quantità e gli stessi prezzi. L’export dei controlli conserva l’impronta del
registro e quelle dei file acquisiti. Le date sono limitate agli anni 2000–2100,
come negli estratti di riconciliazione; immissioni e prelievi non possono essere
negativi.

Il controllo usa come termine l’ultimo giorno gas concluso alle 06:00
Europe/Rome. Le durate effettive di 23, 24 e 25 ore sono visibili nel dettaglio
giornaliero insieme agli estremi UTC. Le giornate aperte restano consultabili e
sono escluse dagli importi utilizzabili, dalle rettifiche e dalla chiusura del
mese. KPI e riconciliazione applicano il proprio termine di riferimento alla
stessa funzione di controllo.

Il confronto predefinito mostra la variazione tra le ultime due versioni,
comprese rettifiche tra definitivi. È disponibile anche il confronto fra ultimo
provvisorio e definitivo. La scomposizione quantità/prezzo conserva il delta
economico e richiede il prezzo controfattuale pertinente. Il dettaglio del
giorno espone tutte le componenti I, S, T e P, i prezzi e la storia delle versioni.
Duplicati ambigui, regressioni di fase, stoccaggio modificato o prezzi da rivedere
escludono la giornata dai subtotali utilizzabili.

I prezzi di sbilanciamento restano quelli dichiarati nei dati di ingresso.
Riferimenti di metodo per quantità e prezzi sono gli articoli 21–23 del
[Regolamento UE 312/2014](https://eur-lex.europa.eu/eli/reg/2014/312/oj) e i
[risultati pubblicati dal GME](https://gme.mercatoelettrico.org/it-it/Home/Esiti/Gas/PrezzoSbilanciamento/Esiti/PrezzoSbilanciamento).
Le convenzioni di arrotondamento e la verifica delle edizioni applicabili
richiedono convalida specialistica.
