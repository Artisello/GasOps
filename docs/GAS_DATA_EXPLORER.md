# Unified Gas Data Explorer

In **Security of Supply → Esplora dati**, scegliere provider, punto, indicatore e periodo. La prima apertura usa l’estratto pubblico ENTSOG incluso, senza credenziali o upload. **Confronta punti** aggiunge fino a tre serie compatibili. **Fonti → Esplora questi dati** della mappa apre lo stesso punto, direzione e periodo, anche dalla Panoramica. Il collegamento è disabilitato per infrastrutture con sola geografia; una richiesta non disponibile è spiegata prima di proporre altre serie.

## Perimetro

| Fonte già presente | Misure esposte | Associazione |
| --- | --- | --- |
| ENTSOG, mappa e scrivania rete | Physical Flow, Nomination, Renomination, Allocation, Firm Technical, Firm Booked, Firm Available | Punto/direzione; associazione geografica solo con binding verificato |
| ENTSOG, estrazioni delle interruzioni | Capacità interrotta pubblicata | Punto/direzione verificato; zero conservato senza dichiarare un evento attivo |
| GIE AGSI+ | Storage inventory, TWh | Singolo impianto verificato oppure aggregato IT/EU/DE distinto |
| GIE ALSI | LNG send-out, GWh/d | Singolo impianto verificato oppure aggregato IT/EU/DE distinto |

I menu offrono soltanto serie con valori numerici o conflitti documentati. GIE appare dopo che dati effettivi sono presenti in sessione o cache. I valori nazionali non sono assegnati ai singoli impianti. I messaggi qualitativi IIP restano nella vista **Avvisi di mercato**: non diventano capacità o giorni privi di eventi. Le altre misure GIE e l’archivio delle estrazioni storiche della scrivania restano nelle viste originali.

## Dataset e regole

`gas_data.collect` produce una proiezione tabellare degli oggetti `Snapshot`/`Observation` e dei frame GIE esistenti. Nessun nuovo modello di osservazione, database, cache o connettore. Parser, binding, calendario e fusione delle estrazioni sono riutilizzati. L’adattatore della scrivania conserva gli ID e le acquisizioni di ogni risposta, quando presenti; per estrazioni legacy senza ID usa il localizzatore ufficiale del punto con una nota esplicita.

La stessa selezione validata alimenta tabella ed export. Il grafico è una sua proiezione su calendario con celle vuote esplicite: nessuna interpolazione, riempimento o somma automatica. Si confrontano soltanto stesso provider, indicatore, unità e base temporale. GWh/d e TWh rimangono distinti.

Campi: provider, infrastructure_id, point_direction, indicator, value, unit, gas_day, period_from/to, observed_at, retrieved_at, source_id/url, quality_status, publication_status, cached/failed/partial. Sono conservati anche unità/intervalli originali, ambito, revisioni JSON, conteggi e provenienza di D-1.

- `observed_at` è la pubblicazione comunicata dalla fonte; `retrieved_at` è l’acquisizione. Non si sostituisce la prima con la seconda. GIE con sola data conserva orari e pubblicazione assenti (`publisher_day`).
- Il calendario ENTSOG usa 06:00–06:00 Europe/Rome, compresi giorni da 23 e 25 ore. Intervalli non allineati restano in tabella/CSV senza forzarli in una serie giornaliera.
- Unità invalide, binding non verificati, timestamp futuri, duplicati discordanti e capacità sovrapposte non confrontabili non alimentano grafico o D-1. Le righe ammesse alla consultazione conservano il motivo di esclusione dai calcoli.
- Copie identiche non moltiplicano le osservazioni. Una risposta più recente sostituisce il proprio intervallo, incluse le lacune; risposte contraddittorie con acquisizione identica trattengono il valore e mostrano le versioni. Non si recuperano valori vecchi per coprire buchi nuovi.
- D-1 richiede il giorno precedente esatto della stessa serie. Può precedere l’inizio del filtro se già caricato; CSV e tabella ne conservano valore, ID, pubblicazione e acquisizione. Un giorno precedente diverso non lo sostituisce.

Il writer CSV condiviso con GIE, scrivania ENTSOG e Source Health conserva i metadati per riga, i valori negativi numerici e protegge il testo interpretabile come formula.

## Source Health

L’Explorer riusa `source_health.gas_health` e il renderer del monitor. Il monitor esistente comprende anche le serie della mappa, senza duplicare gli aggregati GIE nazionali già controllati. Mostra ultima acquisizione riuscita, ultimo periodo valido, copertura, età della copia più vecchia utilizzata, pubblicazione se nota, revisioni ed eventuale fallimento di aggiornamento. L’età considera anche le evidenze utilizzate per D-1.

| Stato | Definizione diagnostica |
| --- | --- |
| Live | Acquisizione diretta recente, periodo corrente atteso, controlli superati |
| Cached | Stessa condizione, dati interamente provenienti da copia |
| Historical | Periodo selezionato precedente all’ultimo atteso |
| Partial | Lacune, risposta parziale, conflitti, metadati o pubblicazione da verificare |
| Stale | Acquisizione oltre TTL o aggiornamento fallito |

Priorità: **Stale → Partial → Historical → Cached → Live**; i flag restano separati. Soglie diagnostiche: 12 ore ENTSOG, 24 ore GIE, non SLA del provider. Il periodo atteso ENTSOG termina all’ultimo giorno gas concluso; GIE al giorno civile precedente. Gli intervalli originali contano record consultabili, senza inventare copertura giornaliera. Il monitor usa le finestre diagnostiche esistenti di 14 giorni; l’Explorer il periodo scelto. Gli stati non certificano disponibilità fisica o telemetria in tempo reale.

## Prestazioni e limiti

Nessun fetch al cambio filtro o all’apertura. Le viste originali mantengono gli aggiornamenti espliciti. Lettura soltanto di chiavi note nello Store SQLite: prima i metadati, poi al massimo 24 payload recenti, 2 MB ciascuno e 8 MB totali. Finestra fino agli ultimi 92 giorni, massimo 10.000 righe validate. Un limite o una cache non valida genera un avviso; lo storico completo resta nelle viste originali. Nessun caricamento integrale dello storico.

CSV massimo 5.000 righe e 5 MB: oltre il limite occorre restringere periodo/punti. Senza rete rimangono consultabili estratto incluso, sessione e cache disponibili. Non si fabbricano misure, date di pubblicazione, utilizzi di capacità o dati live. Autenticazione GIE, disponibilità futura dei provider e deployment non sono verificati dalle fixture offline.

## Verifica

`tests/test_gas_data.py`: filtri, unità, DST, D-1, buchi, revisioni, duplicati, conflitti, timestamp, binding, cache limitata, CSV e stati qualità. `tests/test_gas_data_page.py`: menu effettivi, confronto, tabella/CSV, interruzioni, GIE condizionale, Source Health e drill-down Demo/Workbench con HTTP vietato. Comandi: `python -m pytest -q`, `python -m gasops_app.readiness`, `python -m pip check`.

Verifica del 23 novembre 2026: **722 test** nella suite completa, 9 controlli readiness e dipendenze coerenti; dopo la correzione delle tacche dell’asse X, **36 test mirati** superati. Browser reale a 1440×1000 e 390×844: drill-down, confronto tra punti, periodo da tastiera, tabella, capacità su intervalli originali, diagnostica ed export. CSV scaricato e riletto: 6 osservazioni di due punti su tre giorni, metadati e zeri conservati. Date uniche e leggibili; nessun overflow orizzontale della pagina mobile. Queste verifiche riguardano il prototipo locale, non il deployment o i provider autenticati.

Riferimenti di formato: [manuale ENTSOG API v3](https://transparency.entsog.eu/api/archiveDirectories/8/api-manual/ENTSOG_TP_API_UserManual_v3.0.pdf), [manuale GIE v007](https://www.gie.eu/transparency-platform/GIE_API_documentation_v007.pdf). Provenienza e licenze geografiche rimangono nella [documentazione della mappa](ITALIAN_GAS_NETWORK_MAP.md).
