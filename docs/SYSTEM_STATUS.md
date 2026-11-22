# Panoramica · stato del sistema gas italiano

La Panoramica Demo e Workbench usa `system_status.build_status`: una funzione senza I/O che riceve il catalogo verificato, le copie ENTSOG già caricate e la sessione. Riusa calendario Europe/Rome, normalizzazione e revisioni ENTSOG, controlli qualità della sessione e associazione degli eventi. Nessuna nuova cache, dipendenza o API. Il benchmark fornito orienta la gerarchia stato → copertura → mappa → bilancio → eccezioni → dettaglio; gli altri sviluppi del benchmark restano fuori da questo P0.

## Contratto e tempo

`OverviewStatus` distingue giorno gas selezionato, attivo, ultimo concluso e ultimo osservato. Lo stato temporale è `active`, `last_completed` o `historical`. Gli estremi UTC e la durata 23/24/25 ore derivano da `gas_calendar.gas_day_bounds`: nessun fattore orario aggiunto ai dati già pubblicati in GWh/d.

Il default è l’ultimo giorno concluso con osservazioni valide disponibili, comprese scorte o prelievi già caricati. Senza osservazioni si seleziona l’ultimo concluso con valori N/A. Nessuna data futura oltre il giorno attivo. Il selettore mantiene una copia del giorno indipendente dal ciclo di vita dei widget.

Un Physical Flow giornaliero non è un consuntivo se il suo intervallo non è ancora concluso. Nel giorno attivo i flussi GIE possono comparire soltanto con stato esplicito E, come stime; una giacenza TWh resta distinta dal flusso giornaliero. Il forecast già calcolato conserva sempre la classificazione di stima.

Ogni `Measure` conserva valore nullo o Decimal, unità, proprio giorno gas, fonte/ID, pubblicazione se conosciuta, acquisizione originale, tipo, freschezza, copertura, perimetro, note e riferimenti alle evidenze. `observed_at` non viene sostituito con `retrieved_at`. Nel riepilogo, acquisizione significa la più vecchia tra le misure contribuenti; una pubblicazione aggregata non viene dichiarata se manca per una delle misure. Data di acquisizione, data osservata e classificazione storica sono indipendenti.

La freschezza segue soglie diagnostiche I.G.O.R.: 12 ore ENTSOG/dati del forecast, 24 ore inventari GIE, 2 ore IIP. Un errore di refresh mantiene i valori precedenti e le loro date. Queste soglie non rappresentano SLA dei provider. I controlli aggiuntivi della sessione continuano a usare `source_health.session_health` e le sue finestre, riutilizzando l’ispezione del bundle SRG.

## Componenti del bilancio

| Componente | Evidenza accettata | Copertura e limiti |
|---|---|---|
| Importazioni | Physical Flow sui punti ENTSOG ITP italiani mappati, direzione entry | Soli punti di frontiera; esclude GNL e aggregati settoriali |
| Send-out GNL | ALSI Italia del giorno; in alternativa Physical Flow degli ingressi GNL mappati | Le due fonti non vengono sommate; nemmeno quando il valore pubblicato è zero |
| Erogazione stoccaggi | AGSI+ Italia, `withdrawal_gwh_d`, giorno esatto | Le giacenze TWh non sostituiscono un flusso |
| Produzione nazionale | N/A | Il modulo MASE usa dati mensili; nessuna disaggregazione giornaliera presunta |
| Domanda convenzionale | Distribuzione + industria dal bundle giornaliero ENTSOG SRG già validato | Due aggregati distinti, entrambi necessari; perimetro SRG, non totale nazionale certificato |
| Domanda termoelettrica | Aggregato gas SRG `power_gwh` | Non energia elettrica Terna convertita in gas |
| Esportazioni | Physical Flow sui punti ITP mappati, direzione exit | N/A in assenza di copie della direzione corretta |
| Iniezione stoccaggi | AGSI+ Italia, `injection_gwh_d`, giorno esatto | Distinta dall’erogazione |
| Δ linepack fisico | N/A | Mancano misure fisiche ai due estremi; niente residui né revisioni del linepack atteso |

La giacenza negli stoccaggi può usare l’ultima data precedente disponibile, indicandola nel KPI; i flussi della strip richiedono il giorno esatto. Il KPI prelievi SRG somma i tre aggregati e non è una decima componente del bilancio. Il forecast è ammesso solo da un bollettino pubblico giornaliero già calcolato, con data target esatta e ultimo periodo di training precedente al target: è una stima, non un consuntivo. Run sintetici, archivi JRC, frequenze mensili e perimetri non compatibili non alimentano il modello di sistema.

La copia ENTSOG inclusa nel repository supporta inizialmente **2/9 componenti**, frontiere e GNL. Gli altri flussi diventano leggibili solo se presenti nei dati già acquisiti. Il numeratore conta componenti con un valore, anche se il loro perimetro è parziale: il dettaglio conserva punti coperti/attesi. Non è una percentuale di bilancio fisico. Non si calcola un totale supply/demand, un residuo o una chiusura artificiale. La pagina dichiara **«Bilancio non riconciliabile con i dati disponibili»**.

Copertura dei punti, completezza della risposta e stato della pubblicazione sono separati: 6/6 punti possono avere una risposta parziale o una pubblicazione non confermata. Le note descrivono il motivo senza cambiare il denominatore dei punti.

## Attenzione operativa

L’etichetta è sempre **«Indicatori di attenzione calcolati da I.G.O.R.»**. Le regole sono deterministiche e hanno severità informativa:

- copia critica scaduta o aggiornamento fallito, con età e soglia;
- componente mancante o flusso atteso assente in una finestra effettivamente acquisita;
- utilizzo oltre 90%, configurabile, solo con flusso e capacità tecnica applicabili allo stesso intero giorno/direzione/unità;
- scarto assoluto oltre 30% dalla mediana dei precedenti 28 giorni, con almeno 14 valori validi; percentuale e numerosità minima configurabili; niente confronto percentuale con mediana zero;
- evento ENTSOG/IIP pubblicato e associato con codice verificato al punto, sovrapposto al giorno selezionato.

Ogni finding conserva ID stabile per regola/fonte/punto/direzione/giorno, categoria, descrizione, regola, soglia, valore, unità, date ed evidenze. La deviazione conserva anche mediana e numerosità. I duplicati esatti IIP ed ENTSOG contano una volta. Revisioni ordinabili usano la pubblicazione più recente; conflitti alla stessa pubblicazione restano irrisolti. Uno zero di capacità interrotta non è un evento. Nomi, aziende e gruppi virtuali non localizzano un avviso.

La copertura degli avvisi è separata: nessun evento associato non dimostra assenza di indisponibilità nazionali. I messaggi irrisolti sono segnalati nel modello. Il pulsante **Apri punto** usa il meccanismo `FOCUS` già presente. Mantiene punto/direzione/giorno; la mappa completa consente solo giorni conclusi e il periodo coperto dalle copie, quindi gli estremi vengono limitati quando necessario. Le altre evidenze della sessione non vengono modificate.

## UI e verifiche

Titolo compatto, giorno/stato/copertura, massimo quattro KPI, mappa esistente con dettaglio a destra, strip con nove componenti, elenco di attenzione e accesso a Security of Supply. Soglie e provenienza sono secondarie. Casi sintetici BSO restano in una sezione separata della Demo; nessun valore simulato completa il modello pubblico, neppure in Workbench.

Test in `test_system_status.py` e `test_system_status_page.py`: missing/zero, DST e giorni, copertura, TTL ed errori di refresh, assenza di sovrapposizione tra fonti/componenti, unità/identità/intervalli/futuro, soglie e baseline, eventi e revisioni, forecast ammessi/esclusi, separazione delle modalità, HTTP vietato, selezione e ritorno dalla mappa. I test cartografici e di apertura aggiornano le aspettative del nuovo header e mantengono le verifiche delle altre pagine.

`scripts/check_network_browser.py` verifica con Chrome/WebGL2 e traffico esterno bloccato quattro KPI, nove componenti, drill-down degli indicatori, clic/pan/zoom, colori della selezione, legenda, storico, date e assenza di overflow su quattro larghezze. Non aggiorna fonti e non modifica il deployment.

Validazione locale P0: **657 test passati** nella suite completa; **9 controlli readiness offline passati**, `pip check` e `git diff --check` superati. Browser reale su entrambe le modalità a 1440, 820, 390 e 375 px. Inventari GIE autenticati e deployment restano fuori dalla verifica live di questo incremento.
