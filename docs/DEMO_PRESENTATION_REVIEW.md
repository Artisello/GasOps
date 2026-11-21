# Verifica della demo esplorabile · 21 novembre 2026

## Esperienza del pubblico

- Avvio predefinito in sola lettura, con sei sezioni selezionabili in qualsiasi ordine. Nessun percorso obbligatorio o pulsante Avanti/Indietro.
- Risultati già popolati; nessuna richiesta di file, testo, credenziali, date, scelta del modello o avvio del backtest.
- Navigazione verificata nel browser locale su tutte le sei sezioni. Verificati i layout a 375, 768, 1024 e 1440 CSS px; nessuno scorrimento orizzontale dell’intera pagina nei campioni ispezionati. Le tabelle di dettaglio possono scorrere localmente.
- Selezione delle aree verificata con freccia destra da tastiera; focus nativo con contorno blu di 2 px. Colori del pulsante primario verificati nel browser: testo `#10231f` su `#65dfbf`, coerenti con i test di contrasto.
- Viewport temporaneo ripristinato al termine. Verifiche locali, non certificazione di accessibilità né test di comprensione con utenti Snam. I cinque minuti sono l’obiettivo di presentazione, non una durata misurata con utenti.

## Evidenze

- Fixture BSO isolate dai registri importati; data di scenario fissata e natura sintetica visibili.
- Rettifica di esempio riconciliata con il motore esistente: quantità −4.200 €, prezzo 0 €, totale −4.200 €. Trenta giorni definitivi verificabili, una giornata modificata.
- Scadenze e briefing derivati dallo stesso registro demo. Il testo è deterministico, senza chiamate AI remote.
- Risultato JRC precalcolato dal backtest effettivo, con hash del file sorgente e dei moduli del motore. Test di riproduzione contro una nuova esecuzione su 28 date. Fonte, intervallo storico, baseline, copertura della fascia e limiti visibili.
- Test Streamlit su tutte le sezioni con richieste HTTP bloccate; verifica che non compaiano controlli operativi e che un registro preesistente rimanga identico.
- Workbench completo conservato dietro configurazione esplicita del server; le prove precedenti continuano a esercitarlo. Il flag non è un sistema di autenticazione.

## Controlli di rilascio

`python -m pytest -q`, `python -m pip check` e `python -m gasops_app.readiness`.

La verifica offline include il risultato storico della demo e ne rifiuta la provenienza obsoleta. API live, deployment pubblico, integrazioni aziendali, benefici e accettazione operativa non sono attestati da questi controlli.
