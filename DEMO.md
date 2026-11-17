# Demo GasOps AI in tre minuti

Avvia con `streamlit run app.py`. La dashboard si apre in **Panoramica**, sui dati mensili pubblici.

| Tempo | Mostra | Risultato |
| --- | --- | --- |
| 0:00–0:40 | Osserva **Eurostat + ARERA · mensili**. Apri **Mercato e previsioni** e prova il periodo del grafico. | Confronta consumi osservati, disponibilità contabile e prezzo CMEM,m. Il pannello delle fonti indica l’ultimo mese, il flag di pubblicazione e l’eventuale cache. |
| 0:40–1:10 | Seleziona **JRC · archivio giornaliero**. Guarda i consumi per settore. | La serie contiene 2.557 giorni italiani dal 2015 al 2021 e funziona offline. La previsione sulla coda dell’archivio è una proiezione storica. |
| 1:10–2:00 | Seleziona **Dati di esempio · giornalieri**. Premi **Avvia analisi di mercato AI** e apri il **Centro operativo AI**. | I sei agenti analizzano il caso. Nella simulazione con domanda a +10%, la copertura passa dal 96,6% all’87,8%. Apri un rilievo ed esporta il rapporto. |
| 2:00–2:35 | In **Bilanciamento**, imposta un prezzo d’acquisto di −42 e ricalcola. In **Scenari aggregati**, varia la domanda o lo stoccaggio. | Con il prezzo negativo, la posizione corta di esempio genera un credito. La tabella aggiorna la copertura e il valore indicativo del saldo. |
| 2:35–3:00 | Apri **Analisi normativa** ed esamina il preavviso di sette giorni. | Il registro collega il rilievo alle pagine PDF 103 e 104 di Piombino. Con il PDF caricato, puoi aprire le pagine originali. |

La demo sintetica include una lacuna temporale, un valore mancante, un duplicato, letture in conflitto, un’unità non valida, un orario errato e un picco anomalo dell’offerta. L’archivio JRC e i dati di esempio sono entrambi disponibili offline e ciascuno riporta la propria provenienza.
