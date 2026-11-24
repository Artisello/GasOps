# Balancing Cockpit & Reconciliation

**Bilanciamento → Sistema e portafoglio** è la vista iniziale in Demo e Workbench. Il collegamento dalla Panoramica usa il giorno gas selezionato. Il confronto per punto si apre subito. Pubblicazioni, eventi e componenti del bilancio si caricano quando apri la relativa vista.

## Due perimetri

**Sistema gas** usa osservazioni pubbliche, copie incluse, cache e import Jarvis già presenti. Se non hai scelto una data, la vista apre l’ultimo giorno con flusso fisico disponibile nella finestra dell’esploratore. Quando scegli una data, la tabella legge l’intervallo di quel giorno e segnala le misure assenti.

**Portafoglio importato** usa soltanto `settlement_desk_csv_v1` con provenienza `user_upload` e autorizzazione d’uso registrata. Gli importatori esistenti di bilanci ed esiti comunicati registrano la dichiarazione di autorizzazione, acquisizione e hash. Importazioni precedenti senza tale dichiarazione restano negli strumenti originali e non vengono promosse automaticamente a portafoglio. Gli esempi guidati e i dati pubblici non alimentano la posizione individuale. La dichiarazione d’uso non certifica autonomamente i diritti o l’autenticità del file.

**Apri il giorno nel settlement** mostra lo stesso partecipante, mese e giorno nel dettaglio. **Confronta con esiti** richiede un estratto indipendente autorizzato. Le versioni discordanti restano non confrontabili secondo `reconcile_days`.

La conferma nel modulo dei bilanci riguarda esplicitamente l’intero registro della sessione, comprese le versioni già importate. Non viene dedotta dall’importazione di un singolo CSV.

## Posizione di sistema

Il prototipo non dispone attualmente di un adattatore che attesti l’autenticità di un saldo ufficiale Snam. Un formato validato, un file XLSX nativo, un campo `balance_reported`, una data dichiarata o un’etichetta `official` non costituiscono tale attestazione. Nessun import viene quindi presentato come saldo ufficiale.

In assenza di un dato ufficiale attestato, l’etichetta è **Estimated System Position — I.G.O.R.**. Una stima è disponibile soltanto con immissioni e prelievi aggregati SRG dello stesso report, giorno, fase e timestamp di pubblicazione, con unità energetiche esplicite compatibili e valori univoci. È il residuo **immissioni − prelievi del perimetro dichiarato**, non il SAS ufficiale né il DS dello shipper. MWh → GWh usa il fattore esatto 1.000. Sm³ senza conversione verificata, report diversi, date/fasi discordanti, conflitti o componenti assenti rendono la posizione **Non calcolabile**. Gli input e la formula rimangono nella scheda Fonti.

Non si sommano frontiere ENTSOG, domanda SRG, aggregati GIE, gas in stoccaggio o linepack per fabbricare un saldo nazionale. I driver riusano `system_status.build_status`, con perimetri, unità e coperture visibili. Le stime di linepack riusano `linepack.revisions`; non sostituiscono misure fisiche di inizio e fine giorno, né `physical_delta`.

## Riconciliazione per punto

La tabella confronta **Nomination, Renomination, Allocation e Physical Flow** per le 16 direzioni associate alle infrastrutture ENTSOG verificate. Il denominatore è il catalogo mappato, non il mercato italiano completo. Sono conservati anche punti/direzioni senza dati.

I valori devono essere utilizzabili nel dataset validato condiviso con l’Explorer, avere ID fonte, stesso punto/direzione, unità GWh/d e intervallo esattamente coincidente con il giorno gas 06:00–06:00 Europe/Rome. Il calendario comune conserva i giorni DST da 23 e 25 ore. Una quantità pubblicata in GWh/d non viene moltiplicata o divisa arbitrariamente per 24. Unità/intervalli incompatibili, duplicati discordanti e misure assenti impediscono il confronto; zero pubblicato rimane zero.

Le differenze sono **R−N**, **A−R** e **F−A**, soltanto per coppie presenti e omogenee. Sono confronti descrittivi tra definizioni distinte, non differenze di settlement, formule di DS o prove di quadratura regolatoria. Stati provvisori/non confermati sono espliciti; non è necessario che un programma confermato e un flusso provvisorio condividano lo stesso stato editoriale per visualizzarne lo scarto descrittivo. Non si sommano valori commerciali e fisici o direzioni diverse.

Il CSV conserva i valori esatti, differenze, periodo, note e un oggetto `evidence` con ID fonte, pubblicazione, acquisizione, unità originale, qualità, stato e versioni di ogni indicatore. La tabella arrotonda solo la presentazione. La scheda punto apre la stessa infrastruttura e direzione nella mappa esistente.

## Pubblicazioni, audit e stati

`entsog_vintages.audit_rows` estende le strutture esistenti di vintage: legge revisioni reali del dataset normalizzato e archivi portabili validati/deduplicati da `merge`/`digest`. Conserva `source_id`, giorno, punto/direzione, intervallo, unità, pubblicazione, acquisizione, vecchio/nuovo valore, motivo e qualità. Una sola versione non genera un vecchio valore o una revisione. Pubblicazioni contemporanee discordanti sono conflitti, senza ordinamento inventato. Una nuova acquisizione invariata non diventa una revisione.

I vintage portabili precedenti contengono solo acquisizione: questa non diventa data di pubblicazione o ID originale del provider. Il digest identifica l’archivio. Le variazioni tra acquisizioni sono distinte dalle revisioni pubblicate e non sovrascrivono la riconciliazione corrente. Le pubblicazioni aggregate Jarvis riusano `revision_rows` per le coppie provvisorio/definitivo disponibili; i file nativi conservano foglio, riga, versione e hash, con unità/orari non confermati esclusi dai calcoli.

Per i bilanci individuali, `merge_csv` conserva metadati di prima acquisizione per ciascuna versione, senza aggiornare il timestamp di una versione identica reimportata. Nessuna data di pubblicazione è aggiunta se il registro non la contiene. I calcoli e i risultati economici restano delegati a `daily_controls`, `revision_effects` e `reconcile_days`.

La progressione **Nomination → Renomination → Allocation → Reconciliation → Settlement** indica disponibilità, non esecuzione. Nel sistema il settlement individuale è sempre non disponibile. Il registro del portafoglio non contiene programmi e flussi per punto: i primi tre passaggi restano non disponibili. Un calcolo economico disponibile non certifica una fattura o un settlement completato.

La scheda Eventi mostra soltanto eventi documentati e associati da `system_status` ai binding verificati. Nessun evento nella copia non significa assenza di interruzioni. Non esiste un registro di azioni eseguite nei dati attuali: il cockpit lo dichiara senza inventare interventi. Fonte e qualità riusano il monitor esistente; pubblicazione, acquisizione, copertura e stato della cache sono distinti.

## Prestazioni e verifica

Nessun nuovo fetch, motore, database, job o dipendenza runtime. `gas_data.source_context` carica una volta le fonti locali condivise, quindi `collect` e i driver riusano lo stesso contesto. Limiti dell’Explorer invariati: ultimi 92 giorni, 24 payload recenti, 8 MB totali, 10.000 righe; export fino a 5.000 righe/5 MB. Import nativi e archivi mantengono i propri limiti e la persistenza in sessione.

`tests/test_balancing_cockpit.py` e `tests/test_balancing_cockpit_page.py` coprono duplicati/conflitti, unità e conversioni, direzioni, DST, dati mancanti/zero, fasi provvisorie, stima/non calcolabilità e rifiuto di etichette ufficiali non attestate, isolamento system/shipper, autorizzazione, filtri, audit/vintage e drill-down Demo/Workbench. Restano in esecuzione i test originali dei motori di settlement, riconciliazione, rettifiche, linepack, Jarvis e navigazione. Le fixture generate sono sintetiche; la prima vista usa l’estratto ENTSOG pubblico incluso.

Validazione locale del 23 novembre 2026: suite completa con **743 test superati**, 118 regressioni mirate, 9 controlli di readiness e `pip check`. Dopo gli ultimi ritocchi di layout sono stati rieseguiti i 7 test della pagina. AppTest vieta le richieste HTTP nei nuovi percorsi. Verifica nel browser a 1440×1000 e 390×844: controlli da tastiera, quattro schede, separazione del portafoglio vuoto, accesso ai controlli precedenti, grafico e tabelle senza overflow della pagina. Il CSV scaricato dal browser contiene 16 punti/direzioni per il 19 novembre 2026, con null distinti dagli zeri e provenienza/versioni conservate. La CI ripete suite e readiness sulla revisione della PR; API autenticate e deployment restano fuori dalla verifica live.
