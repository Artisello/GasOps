# Importazioni dai servizi esterni

Il punto di accesso è **Fonti e connessioni**. Il pulsante acquisisce i dati delle fonti selezionate; filtri, cambio pagina e selezione della mappa non avviano acquisizioni. Le analisi e l’esploratore riutilizzano gli stessi adattatori, cache e stati di sessione.

| Fonte | Informazioni utilizzabili | Accesso e periodo |
|---|---|---|
| Eurostat / ARERA | Bilancio mensile e riferimento prezzo, con fonti distinte | Pubblico; finestre esistenti |
| ENTSOG SRG | Prelievi e componenti settoriali realmente pubblicate | Pubblico; controlli di copertura esistenti |
| ENTSOG rete italiana | Physical Flow, Nomination, Renomination, Allocation, Firm Technical, Firm Booked, Firm Available e interruzioni documentate | Tutte le direzioni con associazione verificata; ultimi 7 o 30 giorni gas conclusi |
| GIE AGSI+ | Giacenza, working gas capacity, riempimento, iniezione, erogazione e capacità tecniche di iniezione/erogazione | Chiave server; 90 giorni per gli aggregati IT e opzionalmente UE; impianti della mappa nel periodo selezionato |
| GIE ALSI | Send-out, inventario energetico e liquido, massimo inventario e send-out di riferimento dichiarati | Chiave server; aggregati e soli impianti associati; nessuna conversione volume/energia presunta |
| GIE IIP | Record UMM originali attivi nella finestra richiesta | Chiave server; oggi–D+7; massimo 5 pagine, ciascuna di massimo 50 record |
| Terna | Generazione/carico osservati, previsioni MSD1, capacità e indice industriale | Credenziali server; periodi originali dei diversi adattatori |
| ACER | Valutazioni e benchmark GNL pubblicati | CSV ufficiale; date e metodi della fonte |
| Open-Meteo | Temperature, HDD e contesto meteo previsto | Solo quando l’integrazione è abilitata per l’uso previsto |
| AI / archivio documentale | Verifica di accesso tramite le integrazioni già presenti | Selezione esplicita; il pulsante non genera analisi né importa il contenuto dei PDF |
| Snam Jarvis, GME, MASE | Importazioni e archivi già supportati nelle rispettive viste | Nessun endpoint automatico aggiunto senza adattatore verificato e accesso previsto |

Gli indicatori sono proposti solo se esistono valori utilizzabili. La giacenza massima GNL e il riferimento di send-out restano grandezze dichiarate, senza diventare capacità commerciale disponibile. Le variazioni di riempimento rispetto a D-1 sono punti percentuali. Una misura mancante resta assente; uno zero pubblicato resta zero.

## Acquisizione e prestazioni

- La verifica del catalogo ENTSOG precede le interrogazioni dei punti: operatore, identificativo, direzione ed etichetta devono corrispondere. Nessuna nuova associazione geografica viene inventata.
- Il lotto riutilizza il motore della mappa e include gli impianti GIE confermati senza ripetere acquisizioni nazionali o IIP. Le sessioni mantengono fino a 24 snapshot; la lettura della cache considera fino a 96 estrazioni entro l’esistente limite di 8 MB.
- Il budget di 90 secondi viene controllato tra punti e impianti, oltre ai timeout delle singole richieste. I punti rinviati restano espliciti e hanno priorità nel lotto successivo. Non è un timeout rigido dell’intera operazione.
- Restano il limite di un aggiornamento al minuto, la conservazione dell’ultima copia valida e l’indipendenza degli errori tra fonti e perimetri. Il pannello mostra fonte corrente e durata di ogni acquisizione.
- Il token Terna è riutilizzato soltanto nel contesto del lotto, fino alla scadenza dichiarata meno 15 secondi, con massimo 300 secondi. Non viene scritto in sessione, SQLite o esportazioni; credenziali diverse hanno voci separate. Un HTTP 401 invalida il riuso.
- HTTP 400/401/403/404/405/410/422/429 non causano una ripetizione immediata della stessa richiesta. Gli errori transitori conservano la politica di tentativi esistente.
- I task paralleli di Eurostat/ARERA, indicatori e briefing ereditano il contesto del chiamante: la modalità di sola cache rimane efficace anche nei thread di acquisizione.

## Completezza e provenienza

IIP segue il numero di pagina soltanto se totale, dimensione e pagina corrente sono verificati. Se mancano metadati, cambia il totale, si ripetono record, manca una pagina o si raggiunge il limite, la risposta rimane parziale. Record identici vengono deduplicati; revisioni diverse dello stesso identificativo sono conservate. `pages_loaded`, `pagination_complete` e `limit_reached` sono inclusi nell’esportazione. La data di acquisizione è la più vecchia tra le pagine utilizzate; non viene presentata come data di pubblicazione.

Serie, tabella e CSV dell’esploratore usano il dataset normalizzato esistente. Aggregati e impianti restano distinti, come unità e periodi. Le etichette Live/Cached/Historical/Partial/Stale e i controlli di qualità rimangono quelli del monitor delle fonti. Un errore su un’interruzione non cancella i flussi acquisiti e non dimostra assenza di eventi.

## Riferimenti e verifica

Le richieste seguono il [manuale ENTSOG](https://transparency.entsog.eu/api/archiveDirectories/8/api-manual/ENTSOG_TP_API_UserManual_v3.0.pdf), il [manuale GIE AGSI/ALSI](https://www.gie.eu/transparency-platform/GIE_API_documentation_v007.pdf) e la [documentazione Terna OAuth](https://developer.terna.it/docs/read/Access_Token). Resta visibile l’attribuzione della fonte.

I test coprono pagine mancanti e incoerenti, duplicati/revisioni, limiti, cache, unità GIE, budget e associazioni della rete, scadenza e isolamento del token, richieste rifiutate, selezione esplicita e propagazione della modalità offline. Le risposte autenticate GIE/Terna richiedono una verifica nel deployment dotato delle relative credenziali. I test sintetici non attestano disponibilità live, abilitazioni contrattuali o completezza futura del servizio.
