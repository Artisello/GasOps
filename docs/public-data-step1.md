# I.G.O.R. — Public Data Warehouse / Step 1

Obiettivo: acquisire fonti ufficiali con provenienza e revisioni riproducibili, senza confondere file scaricati, dati validati e simulazioni.

## Fonti

- JRC ENaGaD Italia v1.1: archivio già presente nel repository, serie giornaliera nazionale e settoriale. [Dataset](https://doi.org/10.5281/zenodo.6364875), [metodologia](https://doi.org/10.2760/497677), CC BY 4.0. Autori: Nicola Zaccarelli, Sergio Giaccaria, Maksims Feofilovs, Ricardo Bolado-Lavín. Fonte originaria Snam.
- MASE UNMIG: [produzione nazionale di idrocarburi](https://unmig.mase.gov.it/ricerca-e-coltivazione-di-idrocarburi/produzione-nazionale-di-idrocarburi/). La pagina pubblica collega un CSV storico 2004–2026, licenza CC BY 4.0. Gas in Sm³, non GWh. Il link diretto è stato individuato, ma il file non è stato ispezionato in questa sessione. Il downloader non presume il formato nativo; il controllo è solo strutturale. Se non rettangolare o non scaricabile, fallisce senza pubblicare dati.
- Snam [Jarvis](https://jarvis.snam.it/public-data): bilanci, WKR, gas stock, dati operativi; priorità successiva. Formato nativo, autorizzazione al riutilizzo e modalità di acquisizione da verificare. Nessuna automazione Jarvis o GME introdotta.

## Avvio locale

Dalla radice, con le dipendenze già installate:

```sh
python -m gasops_app.warehouse seed-jrc
python -m gasops_app.warehouse fetch-mase
python -m gasops_app.warehouse manifest
python -m pytest -q tests/test_public_warehouse.py
```

Se il download MASE non funziona, scaricare il file dal portale ufficiale e verificarne la struttura in locale:

```sh
python -m gasops_app.warehouse inspect-mase file.csv
```

Il comando inspect non importa il file. Nessun invio ai modelli AI. Nessun job o costo aggiuntivo.

## Modello dati

- Archivio separato: `.gasops/public-warehouse.sqlite3` oppure GASOPS_STATE_DIR, nessuna modifica a state.sqlite3. Non aggiungere l'archivio al repository. Non collocarlo in cartelle pubbliche.
- Originali byte-for-byte, data di prima acquisizione, SHA-256, fonte e licenza. Snapshot immutabili per fonte/hash; copie identiche non creano nuove versioni.
- Osservazioni JRC con data gas, perimetro IT, metrica, valore decimale testuale, unità GWh/d e flag O/E; NA non è zero.
- MASE archiviato come raw_pending; nessuna conversione, aggregazione o esposizione nei KPI finché schema, granularità, copertura, totali e unità non siano verificati.
- SQLite come primo passo reversibile: niente nuova dipendenza. DuckDB/Parquet quando i volumi o le query lo giustificheranno. Nessuna garanzia di persistenza su Streamlit Community Cloud. Nessuna modifica alla UI o alle fonti live.

## Criteri di chiusura

Test deterministici, prova del seed con il JRC originale, prova live indipendente del CSV MASE e ispezione delle intestazioni. I test sintetici non certificano il contratto MASE. Step 2: adattatore nativo MASE, controllo aggregati e visualizzazione nella pagina Stoccaggi e forniture; in parallelo identificazione dei file pubblici Jarvis.
