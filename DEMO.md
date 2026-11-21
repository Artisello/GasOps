# I.G.O.R. — Il potenziale BSO in cinque minuti

Avvia `streamlit run app.py`. Si apre direttamente una demo in sola lettura, con esempi già pronti. Il pubblico può navigare in qualsiasi ordine: nessun upload, configurazione, credenziale o esecuzione di modelli richiesta.

## Che cosa si scopre

| Sezione | Caso già visibile | Potenzialità |
| --- | --- | --- |
| In sintesi | Tre risultati BSO e una vista intraday | Capire il perimetro a colpo d’occhio e scegliere che cosa esplorare |
| Balancing | Otto pubblicazioni simulate del SAS, cambio di segno e ultima variazione | Condividere il contesto del sistema e ricostruire che cosa cambia |
| Settlement | Una rettifica di −4.200 € spiegata da due versioni dello stesso giorno gas | Risalire dall’importo alla variazione di quantità e prezzo |
| Operations | Due attività scadute, tre in arrivo e un briefing pronto | Riunire priorità ed evidenze delle tre aree |
| Previsioni | Backtest reale JRC, confronto con baseline e fascia bayesiana | Misurare errore e incertezza prima di valutare un uso operativo |
| Sviluppi | Ciò che è dimostrato e ciò che richiede un pilot | Concordare dati, validazione e metriche di valore |

Il menu resta disponibile in ogni vista ed è l’unico punto di navigazione. La schermata principale mostra solo indicatori, grafico e contesto essenziale. Briefing, spiegazioni, metodo e fonti sono nei dettagli facoltativi. Date, natura simulata o storica e limiti della fascia previsionale restano visibili.

## Trasparenza

- **Balancing:** valori intraday inventati per il giorno gas 18 novembre 2026; nessun collegamento Jarvis attivo. Il SAS di sistema resta distinto dal saldo del partecipante.
- **Settlement:** registro sintetico DEMO-001 di settembre 2026. I calcoli riutilizzano il motore del prototipo: il 5 settembre il saldo passa da −200 a −300 MWh, l’importo da −8.400 a −12.600 €, a prezzo invariato. Non sono fatture ufficiali.
- **Operations:** attività e scadenze inventate, situazione fissata al 18 novembre 2026 alle 14:00 CET. Non sono SLA Snam.
- **Previsioni:** archivio pubblico JRC ENaGaD v1.1, 2015–2021. Il confronto D+1 copre 28 giorni gas di dicembre 2021. Il risultato è precalcolato eseguendo il backtest effettivo e verificato nei test; non è una previsione odierna. Copertura della fascia e limiti sono visibili.
- **Briefing:** testo deterministico derivato dai casi mostrati, senza chiamate a un modello AI remoto. L’assistente con dati e documenti autorizzati è uno sviluppo proposto.

Il prototipo è indipendente e non ufficiale Snam. Non invia ordini, non modifica registri importati e non misura ancora risparmi o benefici operativi. La sezione Sviluppi rende esplicito il lavoro necessario per un pilot.

## Preparazione tecnica

Installare le dipendenze, eseguire `python -m pytest -q` e `python -m gasops_app.readiness`, quindi aprire la demo e verificare le sei sezioni. Per aggiornare il confronto dopo una modifica al modello o al CSV JRC: `python -m gasops_app.demo_forecast`. Le impronte della fonte e del codice impediscono di mostrare inconsapevolmente un risultato obsoleto.

I vecchi strumenti operativi sono conservati nel workbench di sviluppo: `GASOPS_APP_MODE=workbench streamlit run app.py`. Questa configurazione riguarda il server; non compare nell’esperienza del pubblico.
