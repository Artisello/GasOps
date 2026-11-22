# I.G.O.R. — Esplorare l’intero programma

Avvia `streamlit run app.py`. La sidebar è visibile su desktop e apribile dal controllo nativo su mobile. Ogni area è raggiungibile dal menu, senza cambiare configurazione del server.

| Area | Cosa si vede |
| --- | --- |
| Panoramica | Tre casi BSO e il confronto storico JRC |
| Bilanciamento | Rettifica già pronta; stime di sistema, simulazioni, riconciliazioni e regole nelle viste disponibili |
| Fatture e garanzie | Riconciliazione, esposizioni, scadenze, prezzi e bilanci GNL su casi dichiarati |
| KPI operativi | Registro demo già popolato; indicatori avanzati, monitoraggio e centro operativo |
| Mercato e previsioni | Consumi, previsioni, Terna, ACER, prezzi e analisi Snam |
| Security of Supply | AGSI+, ALSI, IIP, Jarvis, HS1, MASE e interconnessioni ENTSOG |
| Simulazione rischi | Calcolo già eseguito; ipotesi e stress test esplorabili |
| Norme e documenti | PDF pubblici predisposti e ricerca di esempio già eseguita; lettura, AI, confronti e dossier |
| Assistente AI | Analisi JRC già pronta; domande, analista dati e report locali |
| Fonti e API | Stato effettivo dei connettori e un’unica azione di aggiornamento |
| Esempi BSO | Casi essenziali in sola lettura e sviluppi del pilot |

Le viste complete restano disponibili per mostrare le funzionalità, ma non richiedono file del visitatore per esaminare i casi già predisposti. Non vengono inviate nomine, ordini o fatture.

## Fonti e connessioni

**Aggiorna fonti connesse** usa Eurostat/ARERA, ENTSOG, ACER e meteo, più GIE e Terna quando configurati. Con GIE include gli avvisi IIP; verifica inoltre modello AI e accesso in lettura all’archivio documentale quando presenti. Le credenziali sono esclusivamente del server e non vengono mostrate o richieste al pubblico. Il modello AI conserva i limiti di chiamata esistenti; la verifica invia solo un test sintetico.

La configurazione non viene indicata come connessione riuscita. Esiti, acquisizioni, cache e limiti restano distinguibili; una fonte non raggiungibile non viene sostituita da un esempio. I risultati sono condivisi con le viste operative della stessa sessione. Jarvis conserva l’import di pubblicazioni originali e GME consultazione/import nei limiti autorizzati.

L’assistente prepara un’analisi dei soli dati pubblici JRC. Usa il modello se attivo, oppure un report locale esplicitamente indicato. Non include PDF personali o registri importati e non riattiva l’AI dopo una scelta esplicita dei calcoli locali. Svuotare lo storico non provoca un’altra richiesta automatica.

## Perimetro

I casi BSO sintetici mantengono le date dichiarate: settembre e novembre 2026. Il backtest JRC riguarda il dicembre 2021, non il mercato attuale. Documenti Snam e formule si riferiscono alle edizioni fornite; vigenza e impiego operativo richiedono validazione. Benefici, risparmi e SLA non sono ancora misurati.

Per la sola variante tecnica iniziale è disponibile `GASOPS_APP_MODE=workbench streamlit run app.py`; non occorre per accedere alle funzionalità. Controlli: `python -m pytest -q` e `python -m gasops_app.readiness`.
