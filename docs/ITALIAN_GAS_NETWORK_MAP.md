# Rete gas italiana

La scheda **Fonti → Esplora questi dati** apre il [Data Explorer unificato](GAS_DATA_EXPLORER.md) sul punto/direzione e periodo selezionati, mantenendo la selezione della mappa. Il monitor qualità riusa le stesse diagnostiche delle osservazioni.

Vista **Security of Supply → Mappa della rete**. Nella demo è la vista iniziale di questa sezione; tutte le altre viste restano accessibili. Titolo: **Rete gas italiana**. La mappa è informativa, con dati pubblici e provenienza verificabile; non controlla infrastrutture.

La **Panoramica Demo e Workbench** apre con **I.G.O.R. — Sistema Gas Italiano**, i quattro KPI pubblici del [System Status](SYSTEM_STATUS.md) e una mappa alta **500 px**. Su desktop il dettaglio, la ricerca e le schede sono a destra. Sotto 1100 px la mappa precede il pannello, senza scorrimento orizzontale. La vista completa ripartisce lo spazio tra mappa e dettaglio, mantenendo i 650 px di altezza. `italian_network_page.panel(mode="overview")` riusa asset, modello e rendering della vista `mode="full"`. I casi BSO simulati e la scrivania Workbench restano sotto il bilancio e l’attenzione operativa, con etichette separate.

## Operational Intelligence Map · P1

Un selettore compatto attiva una sola lettura della stessa scena PyDeck. Nessuna seconda mappa, cache o copia delle geometrie.

| Modalità | Elementi e significato |
|---|---|
| **Sistema** (`SYSTEM`) | Gasdotti, frontiere, GNL, stoccaggi, compressori e **69 centrali elettriche già visibili senza selezionarle**. Colori di categoria; simbolo pieno con misure ENTSOG confrontabili sul giorno, contorno quando manca il dato operativo. Nessun colore di rischio presunto. Anche i 177 nodi geografici storici sono visibili per impostazione predefinita. Il livello Nodi può essere disattivato nella mappa estesa. |
| **Flussi** (`FLOW`) | Punti con binding univoco confermato e flusso fisico valido per il giorno gas. Direzione, capacità firm tecnica/disponibile, utilizzo, variazione D-1 e stato fonte nei tooltip e nella scheda. Gasdotti statici come contesto geografico. |
| **Attenzione** (`ATTENTION`) | Cerchio rosa: evento pubblicato con associazione verificata. Rombo ambra: indicatore I.G.O.R. calcolato, con regola/soglia/evidenze nella scheda. Cerchio grigio tratteggiato: dato atteso assente o cache da aggiornare. Una riduzione della capacità tecnica rispetto a D-1 è un confronto derivato esplicito. |

La selezione resta soltanto se pertinente alla lettura; in caso contrario viene scelto un punto valido oppure non viene mostrato alcun dettaglio. I gasdotti in Flussi e Attenzione restano contesto non selezionabile. Filtri e periodo sono conservati. La ricerca alternativa rispetta il perimetro della lettura e distingue le categorie. Le sessioni con la precedente lettura INFRASTRUCTURE passano a Sistema.

La selezione nativa memorizza indici di array: filtrare fisicamente i bersagli del mouse poteva spostare il clic su un altro impianto al cambio lettura. Ora gli indici conservano la stessa identità; i bersagli esclusi hanno raggio zero e le etichette escluse testo/dimensione nulli, senza geometria visibile o cliccabile. Simboli e anelli sono decorativi e compaiono soltanto per gli elementi effettivamente mostrati. Il backend rifiuta comunque gli identificativi fuori dal perimetro visibile. Geometrie, coordinate e camera rimangono quelle del componente esistente.

La vista completa parte con tutti i livelli selezionati, inclusi i nodi. Il livello Nodi può essere disattivato nei filtri della vista estesa; nessun asset viene eliminato dal catalogo. La migrazione una tantum ripristina i nodi nel precedente insieme predefinito completo senza nodi, conservando gli altri sottoinsiemi. Le 69 centrali rimangono visibili per impostazione predefinita.

La scheda è condivisa tra le due viste e contiene sette sezioni: **IDENTITÀ, STATO, DATI FISICI, DATI COMMERCIALI, TREND, EVENTI, DATI E PROVENIENZA**, distribuite tra Dati, Storico, Eventi e Fonti. Sono esposte soltanto le misure pubblicate disponibili, compresi Allocation e Firm Booked quando presenti. Unità normalizzata, direzione e intervallo originale restano consultabili. Le capacità con intervallo fonte valido ma non confrontabile sul giorno sono etichettate ed escluse dai rapporti. Fonti conserva ID, pubblicazione, acquisizione, qualità, revisioni, licenza, versione e accuratezza geografica, oltre alle evidenze D-1.

Lo storico legge una finestra di **30 giorni incluso D** dalla memoria/cache esistente; non scarica dati cambiando scheda. L’estratto incluso contiene sette giorni: sono indicati come **7/30**, mantenendo i buchi e senza interpolazione; lo zoom iniziale del grafico evita lo spazio vuoto prima della prima osservazione. Il confronto D-1 richiede il giorno di calendario precedente e non è sostituito da “ultima osservazione disponibile”. Nessuna misura assente diventa zero e nessun flusso anima i gasdotti.

L’utilizzo è `Physical Flow / Firm Technical × 100`, solo con stessa identità, direzione, unità GWh/d e copertura dell’intero giorno gas. Intervalli sovrapposti in conflitto o con capacità diverse bloccano il rapporto. Lo spazio disponibile usa esclusivamente **Firm Available pubblicata e confrontabile**: non si presenta `tecnica − flusso` come capacità commerciale disponibile. Le regole di esclusione di dati futuri e mapping non confermati sono condivise con il System Status; lo schema degli snapshot esistente non cambia.

Interruzioni e IIP passano dalla stessa verifica e deduplicazione del System Status. Eventi senza associazione certa, release contraddittorie e messaggi futuri non vengono localizzati. Un’interruzione pubblicata a zero non è un evento attivo. I conteggi e i limiti di copertura restano visibili; l’assenza di eventi sulla mappa non certifica assenza di indisponibilità. Soglie e finding riusano il modello P0, senza nuove chiamate o motori paralleli.

**Esplora la rete** apre l’infrastruttura selezionata nella vista completa, mantenendo identificativo e periodo e azzerando i filtri aggiuntivi di operatore, regione, stato e soli avvisi. I dati e gli import della sessione restano conservati. La selezione è salvata in uno stato indipendente dai widget; le chiavi dei grafici sono distinte per modalità. Il callback nativo legge gli oggetti selezionati prima del rerun, senza un secondo rerun a cascata. I gasdotti hanno un’area di clic di **18 px** quasi trasparente, separata dal tratto visibile di **1,1 px**. I punti hanno bersagli invisibili di **14–28 px di diametro**, secondo la categoria, e simboli visibili limitati a **6–18 px**. Ingressi e GNL hanno priorità sulle infrastrutture minori nelle sovrapposizioni; l’ordine di selezione resta stabile tra letture e filtri, gli elementi nascosti hanno bersaglio nullo. Una nuova chiave del componente evita di riusare indici di picking delle versioni precedenti, conservando l’ID selezionato. Nessuna geometria duplicata o spostata.

La barra delle tre letture ha un fondo uniforme e pulsanti nativi da almeno 44 px, disposti in tre colonne compatte anche su mobile; le etichette pubbliche sono italiane, le chiavi interne restano compatibili. Nella Panoramica la scheda mette in evidenza flusso e utilizzo, con capacità/dati commerciali in una tabella apribile. Il bilancio completo e le segnalazioni di qualità sono raccolti in sezioni chiuse, senza rimuovere dati, esportazioni, avvisi operativi, storico o provenienza. Il messaggio di bilancio non riconciliabile resta visibile anche a sezione chiusa. Le soglie, il giorno gas, le fonti e i calcoli non cambiano.

Il fondo mare e il contorno italiano hanno contrasto distinto. I simboli locali differenziano frontiere (rombi), GNL (quadrati), stoccaggi (serbatoi), compressione (triangoli), centrali (fulmini) e nodi. Le etichette danno priorità alla selezione e cercano spazio verso l’interno, con un margine conservativo per gli schermi piccoli. Anche il gasdotto selezionato ha il proprio nome, ancorato alla parte centrale del collegamento. Le etichette usano testo da 12 px e fondo scuro; la selezione sale a 14 px, con evidenziazione verde e priorità di disposizione. Anche il nome è cliccabile e rimanda allo stesso identificativo dell’impianto o del gasdotto. Nella vista generale si privilegiano frontiere e GNL; scegliendo un solo livello sono disponibili anche i nomi di quel livello. I tooltip conservano il nome completo e restano nell’angolo del riquadro, senza tagli ai bordi. Il titolo ha un margine dedicato che protegge le discendenti dal bordo della mappa. **I riferimenti alle città sono stati rimossi su richiesta**: la mappa mostra solo elementi utili alla rete. Il grafico storico riserva 52 px sotto l’asse, usa date `gg/mm`, massimo quattro tacche e tema scuro con margini automatici. In Panoramica non compaiono filtri avanzati permanenti né comandi di aggiornamento delle API; gli asset condivisi vengono acquisiti una sola volta dalla cache esistente. L’inquadratura deriva dai confini reali in proiezione Mercatore e dalla dimensione del contenitore, con 10 px di margine. Il piccolo componente locale `map_viewport/index.html` misura soltanto la propria larghezza: comunica una volta al caricamento e al ridimensionamento (debounce 150 ms), senza richieste esterne né dipendenze JavaScript. Filtri e selezioni non ridimensionano o reinizializzano la camera. Nessuna seconda mappa o geometria duplicata.

## Selezione, zoom e dati nella Panoramica

Il cursore della mappa è una freccia. La selezione evidenzia soltanto l’infrastruttura scelta: paese, gasdotti, simboli, avvisi e testi mantengono i propri colori e la propria opacità. Il renderer nativo Streamlit applicava una trasparenza globale alle primitive con selezione attiva. Si usano ora le proprietà di colore di icone/testi di [GeoJsonLayer](https://deck.gl/docs/api-reference/layers/geojson-layer) e i colori espliciti dei sottolivelli per paese e linee. Nessuna modifica a Streamlit o JavaScript esterno nell’app.

La legenda riutilizza gli stessi SVG e colori dell’atlante della mappa, inclusi i serbatoi degli stoccaggi. Le immagini sono URL `data:` locali, visualizzabili anche con tutto il traffico esterno bloccato.

Lo zoom minimo è l’inquadratura italiana adattata al contenitore meno 0,25 livelli; il massimo è 9, per esplorare i dettagli regionali. Rotazione con trascinamento e touch disabilitata, inclinazione bloccata. **Vista Italia** ripristina l’inquadratura senza cancellare selezione, filtri o copie dei dati; il reset della vista è indipendente tra Panoramica e approfondimento.

La scheda selezionata nella Panoramica include **Dati, Storico, Eventi e Fonti**, con gli stessi calcoli e indicatori della vista completa. Per i punti con più direzioni è disponibile Ingresso/Uscita; **Esplora la rete** mantiene anche questa scelta oltre a infrastruttura, lettura e periodo. I dati GIE del singolo impianto già in cache restano distinti dal contesto nazionale. Nessuno storico o flusso è inventato per un gasdotto senza misure associate.

Le chiavi dei selettori e dei grafici sono distinte tra le due viste. Selezioni, schede, indicatori, zoom e reset della vista non interrogano le API.

## Copertura effettiva

| Livello | Elementi | Significato |
|---|---:|---|
| Gasdotti | 163 | Collegamenti **schematici storici**, non rilievi dei tracciati |
| Ingressi e uscite | 7 | Mazara, Gela, Melendugno/San Foca, Tarvisio, Passo Gries, Gorizia, Bizzarone |
| Terminali GNL | 5 | Panigaglia, Adriatic LNG, OLT, Piombino, Ravenna |
| Stoccaggi | 20 | Archivio storico, inclusi progetti; stato attuale non presunto |
| Compressione | 15 | Localizzazioni storiche indicative, inclusi elementi non riconfermati |
| Centrali elettriche a gas | 69 | Livello distinto, selezione del combustibile gas in SciGRID |
| Nodi | 177 | Nodi storici visibili per default |
| Produzione | 0 | Nessuna localizzazione pubblica verificata incorporata |
| **Totale** | **456** | Italia, Sicilia, Sardegna e terminali offshore pertinenti |

Sono confermati **16 mapping punto/direzione ENTSOG per 12 infrastrutture**: sette frontiere e cinque terminali. L’estratto iniziale contiene **365 osservazioni normalizzate** relative agli **11 ingressi** pubblicanti, giorni gas **14–20 novembre 2026**, acquisite il **22 novembre 2026**. Bizzarone è mappato in uscita, senza serie inclusa nell’estratto iniziale.

Gli indicatori ricevuti sono Physical Flow, Nomination, Renomination, Allocation, Firm Technical, Firm Booked e Firm Available. Le risposte operative iniziali hanno conteggi dichiarati non riconciliati: sono esplicitamente **parziali**, anche dove i sette giorni di flusso sono presenti. L’estratto interruzioni riguarda soltanto Mazara: pubblicazioni a valore zero, conservate come tali e non trasformate in eventi.

Sono disponibili **sei associazioni GIE a singoli impianti**: ALSI per i cinque terminali e AGSI+ per **Cornegliano**. Le giacenze richiedono la chiave del server già utilizzata dall’app. I gruppi virtuali **VGS HUB1/HUB2** non sono assegnati ai singoli siti. Nessun dato nazionale viene ripartito geograficamente.

## Architettura

- `gasops_app/italian_network.py`: infrastrutture fisiche, geografie, identificativi esterni e osservazioni separati; filtri, selezione e KPI.
- `italian_network_sources.py`: catalogo ENTSOG, pagine operative e dati GIE del singolo impianto. Riusa `public_data.retrieve`, `Store`, `_amount`, `gas_timestamp`, `query_params` e i parser AGSI+/ALSI esistenti.
- `italian_network_events.py`: interruzioni ENTSOG e associazioni IIP esclusivamente tramite codici esatti.
- `italian_network_refresh.py`: aggiornamento esplicito e indipendente per fonte, conservazione delle copie precedenti e limite di un tentativo al minuto per sessione.
- `italian_network_map.py`: scena PyDeck con confini, stile e atlante SVG incorporati. Su Streamlit 1.67+ si usa l’omissione nativa del basemap tramite `map_provider=None`, senza sovrascrivere lo stile predefinito PyDeck. Le versioni precedenti usano uno stile locale `data:application/json` senza sorgenti: `map_style=None` può attivare CARTO automatico. Nessun tile, geocoder, token cartografico o nuovo framework frontend.
- `italian_network_page.py`: filtri, selezione nativa con clic, selettore accessibile, scheda, storico, qualità ed export JSON attribuito. Descrizione accessibile nativa quando supportata, equivalente testuale sulle versioni precedenti.
- `data/italian-network/`: geometrie, mapping revisionati, estratti operativi reali, licenza SciGRID e manifest SHA-256.

L’identità geografica rimane stabile anche se cambia un codice operativo. Il binding conserva fonte, data di acquisizione e grado di conferma. Le osservazioni conservano intervalli con offset, giorno gas dove riconoscibile, unità, acquisizione, pubblicazione, stato e versioni ricevute. Licenza, versione del dataset e qualità geografica rimangono disponibili nel modello e nell’export.

Il catalogo ENTSOG viene interrogato nuovamente durante l’aggiornamento. Una chiave assente, invalida, senza dati o con nome cambiato non viene utilizzata come identità riconfermata. Se il catalogo non è raggiungibile, resta utilizzabile il mapping della copia già verificata, con avviso esplicito.

## Fonti e diritti

| Fonte | Uso effettivo | Condizioni |
|---|---|---|
| [SciGRID_gas INET_Raw 1.4](https://zenodo.org/records/4750979), pubblicato il 12/05/2021 | Geometrie e metadati storici italiani | **CC BY 4.0**, attribuzione DLR-VE / Diettrich, Pluta, Medjroubi; licenza originale inclusa |
| [Natural Earth admin-0 5.1.1](https://www.naturalearthdata.com/downloads/10m-cultural-vectors/10m-admin-0-countries/) | Solo confine italiano semplificato, isole comprese | [Pubblico dominio](https://www.naturalearthdata.com/about/terms-of-use/) |
| [ENTSOG TP](https://transparency.entsog.eu/) | Identità, flussi, nomine, allocazioni, capacità e interruzioni | [Condizioni, art. 4](https://transparency.entsog.eu/pdf/Terms_and_Conditions_of_Use.pdf): uso e memorizzazione con fonte, sezione e data di estrazione |
| [GIE AGSI+/ALSI/IIP](https://www.gie.eu/transparency/) | Cataloghi pubblici; inventari e UMM tramite accesso server opzionale | [Manuale v007](https://www.gie.eu/transparency-platform/GIE_API_documentation_v007.pdf), riutilizzo con attribuzione GIE; [condizioni IIP](https://iip.gie.eu/data-usage) |
| Gestori dei terminali | Quattro coordinate numeriche pubblicate, con riferimento puntuale | Fatti geografici elementari; nessuna redistribuzione di PDF o cartografie del gestore |

Coordinate pubblicate utilizzate:

- Piombino: **42°56′21.95″ N, 10°33′33.18″ E**, [Terminal Booklet rev. 9 del 09/10/2025, §3.1](https://www.snam.it/content/dam/snam/pages-attachments/it/i-nostri-business/rigassificazione/documents/codice-tariffe-area-comitato/codice-di-rigassificazione-fsru-italia/manuali-terminale/Terminal%20Booklet%20rev.9%20-%20%28Piombino%20Terminal%29.pdf).
- Ravenna: **44°27′50.52″ N, 12°23′53.48″ E**, [Terminal Information Booklet rev. 1.1 del 04/06/2025, §3.1](https://www.snam.it/content/dam/snam/pages-attachments/it/i-nostri-business/rigassificazione/documents/codice-tariffe-area-comitato/codice-di-rigassificazione-fsru-ravenna/manuali-del-terminale/Terminal%20Information%20Booklet%20-%20Rev.1.1.pdf).
- Adriatic LNG: **45°05′26.30″ N, 12°35′04.99″ E**, [Access Code, capitolo VII, Annex I](https://www.adriaticlng.it/wps/wcm/connect/5ab814a1-34f6-46b8-82e7-1b919d7e5d0f/CAP%2BVII%2Ben.pdf?MOD=AJPERES). Data dell’edizione non verificata. La coordinata sostituisce il nodo onshore Cavarzere dell’archivio SciGRID.
- OLT: **43°38′40″ N, 09°59′20″ E**, [Terminal Information Booklet rev. 26 del 09/04/2026, §2.1](https://www.oltoffshore.it/wp-content/uploads/2026/04/GU-OM-Marine-02-FSRU-Toscana-Terminal-Information-and-regulation-booklet-docx-Rev26.pdf). Sostituisce la posizione costiera indicativa dell’archivio.

Panigaglia mantiene la posizione storica indicativa. “Operativo nel catalogo GIE” descrive la finestra dell’anagrafica, non l’assenza di manutenzioni o indisponibilità istantanee.

Nessuna carta Snam/ENTSOG è stata vettorializzata. Le coordinate `tpMapX/tpMapY` del catalogo ENTSOG sono schematiche e **non vengono usate come longitudine/latitudine**.

## API collegate

Riferimento: [ENTSOG API manual v3.0](https://transparency.entsog.eu/api/archiveDirectories/8/api-manual/ENTSOG_TP_API_UserManual_v3.0.pdf).

| Endpoint | Uso e limite |
|---|---|
| ENTSOG `/operatorpointdirections` | Operatore `IT-TSO-0001`, massimo 500 righe; pagina incompleta esclusa dal rinnovo del catalogo |
| ENTSOG `/operationaldatas` | Un punto/direzione selezionato, 1–31 giorni conclusi, sette indicatori, massimo **3 pagine da 200** |
| ENTSOG `/interruptions` | Stesso punto/direzione, una pagina da **200**, copertura parziale dichiarata se satura o non verificabile |
| ENTSOG `/connectionpoints`, `/interconnections`, `/operators` | Verificati nell’acquisizione iniziale dei cataloghi; metadati pertinenti conservati, nessuna scansione runtime |
| AGSI+/ALSI `/api/about?show=listing` | Cataloghi pubblici verificati senza chiave il 22/11/2026; binding degli impianti revisionati esplicitamente |
| AGSI+/ALSI `/api` | Coppia esatta `company`/`facility`, paese IT, periodo selezionato, pagina da 100; parser esistenti, chiave `x-key` server-side |
| AGSI+ nazionale e IIP `/api` | Loader esistenti `load_agsi` e `load_iip`; stati di sessione condivisi `AGSI+_IT` e `gie_iip` |

Il parametro corretto è **`timeZone`**, ora corretto anche nel client di rete preesistente. Il manuale avverte che la conversione richiesta CET/CEST può non essere applicata; vengono perciò conservati gli offset e gli intervalli effettivi della risposta. La vista non corregge arbitrariamente gli orari della fonte.

`aggregatedData`, qualità gas e indicatori operativi di capacità interruptible non sono aggiunti a questa vista. Il tipo Firm/Interruptible è conservato nelle interruzioni. Le viste esistenti MASE, Terna e Jarvis restano disponibili senza duplicare connettori o attribuire aggregati nazionali a punti geografici.

## Calcoli e qualità

- Giorno gas italiano **06:00–06:00 Europe/Rome**, comprese durate di 23 e 25 ore. La portata mantiene l’unità della fonte; non viene integrata come energia senza ipotesi esplicite.
- `kWh/d → GWh/d`: divisione per **1.000.000**. Nessuna conversione tra volume liquido GNL, volume di gas, energia e potenza.
- N/A, campo assente e conflitto non diventano zero. Gli zeri pubblicati rimangono osservazioni valide.
- Le versioni duplicate vengono riconciliate anche fra pagine diverse. Prevale la pubblicazione esplicitamente più recente; versioni discordanti senza ordine certo sono escluse dai calcoli e restano tracciate.
- Le capacità iniziali includono intervalli **07:00–07:00** e intervalli plurimensili. Una capacità entra nel rapporto di utilizzo soltanto se copre l’intero **stesso** giorno gas del flusso. Non si sposta 07:00 a 06:00.
- Il KPI flussi somma soltanto gli **ingressi di frontiera selezionati con valore disponibile**, con denominatore di copertura. Esclude uscite, GNL e aggregati. Non è denominato “importazioni totali italiane”.
- Utilizzo: somma dei flussi / somma delle capacità tecniche dei soli ingressi confrontabili, con capacità positiva e flusso non negativo. Non è la media semplice delle percentuali né un indice dell’intera rete.
- I punti ENTSOG sono contati come infrastrutture distinte, evitando duplicazioni entry/exit. Nessun flusso puntuale è assegnato ai segmenti dei gasdotti.
- IIP: solo EIC impianto o EIC di punto confermato; nessun fuzzy matching per nome o testo. Messaggi ambigui, gruppi virtuali, codici societari e stati non dimostrati restano fuori dalla mappa. Cancellazioni e revisioni sono considerate prima della localizzazione.
- Uno zero ENTSOG di capacità interrotta non genera un evento. Assenza di eventi localizzati non significa assenza di indisponibilità nazionali.
- Storico, min/max/media e copertura usano solo dati disponibili. Il confronto tra medie di periodi consecutivi appare soltanto se entrambi i periodi sono completi.

## Date e stato delle misure

Il riepilogo usa **solo le osservazioni che contribuiscono ai KPI del giorno gas mostrato**: flussi di frontiera, capacità confrontabili e flussi utilizzati nel conteggio della copertura. Una nomina più recente o un altro giorno gas non ridatano questi KPI. Sono esposte prima e ultima acquisizione, età della copia contribuente più vecchia, pubblicazione della fonte se disponibile e completezza del perimetro. Un aggiornamento recente di un solo punto lascia visibile l’età degli altri.

- **Non disponibile**: nessuna osservazione utilizzabile per le misure mostrate.
- **Storico**: giorno precedente all’ultimo giorno gas concluso o copia contribuente più vecchia del TTL operativo di 12 ore.
- **Aggiornato**: giorno corrente concluso, acquisizioni non future entro TTL, copertura completa, snapshot riconciliati, pubblicazioni confermate e nessun fallimento pertinente.
- **Parziale**: altre combinazioni con almeno un dato utilizzabile. Lo stato della completezza resta distinto dalla data.

I KPI senza valori utilizzabili vengono nascosti; il conteggio di copertura resta visibile. Gli zeri pubblicati restano valori validi. Le scorte nazionali GIE mantengono il proprio giorno, acquisizione e stato di fallback, senza ereditare le date ENTSOG.

La scheda operativa cerca l’ultimo flusso valido nel periodo scelto. Capacità tecnica/disponibile, nomina e rinomina si riferiscono a quel giorno; utilizzo e variazione sul giorno precedente appaiono solo quando confrontabili. Le osservazioni del confronto storico contribuiscono anche alla provenienza della scheda. Intervalli originali, revisioni e identificativi restano negli expander.

## Aggiornamento, cache e prestazioni

Aprire la vista, cambiare filtri, selezionare un impianto e navigare **non esegue richieste API**. Misurazione locale prima dell’intervento: asset 15 ms, KPI 1 ms, scena JSON 19 ms / circa 634 KB. Con simboli distinti, riusando le sole proprietà necessarie per il disegno, la scena completa con gli stili protetti dalla selezione resta intorno a 840 KB e 40 ms: nessuna ricostruzione GIS o clustering introdotto. Queste misure Python non sono tempi del browser o garanzie di latenza del deployment. La geometria pesa circa 340 KB e l’estratto operativo circa 404 KB, compresi gli intervalli originali e le revisioni; gli asset vengono letti tramite cache Streamlit. I 456 elementi non richiedono clustering o un caricamento GIS pesante.

**Aggiorna** interroga il catalogo, il solo punto/direzione selezionato e le sue interruzioni. Se la chiave GIE è configurata sul server, aggiorna anche l’eventuale impianto associato, le scorte nazionali e IIP, riutilizzando gli stati delle viste esistenti. Un limite di un minuto evita richieste ripetute della stessa sessione. I limiti del periodo sono applicati prima delle richieste.

Si riusano timeout, limiti di dimensione, gestione redirect autenticati e SQLite di `public_data.retrieve`. TTL: catalogo sette giorni, operazioni/interruzioni dodici ore, inventari ventiquattro ore, IIP due ore. Il refresh esplicito tenta il provider; se fallisce, conserva la data originaria della copia valida. Il fallimento di una fonte non cancella le altre. Il reset modifica soltanto filtri e selezione, senza eliminare dati o import preesistenti.

Le chiavi non vengono scritte negli asset, nei parametri URL, nell’export o nella sessione della mappa. La dipendenza diretta aggiunta, `pydeck>=0.9,<1`, era già transitiva di Streamlit. Shapely/pyshp servono soltanto all’ETL offline.

I simboli hanno dimensioni di 6–16 pixel, limitate a 18; gli obiettivi di selezione sottostanti restano limitati a un raggio di 7 pixel a ogni zoom. I simboli sono decorativi: obiettivo del marker ed etichetta rimandano allo stesso identificativo, mantenendo una sola selezione attiva. Le unità sono costanti `pydeck.types.String("pixels")`: una semplice stringa veniva serializzata come espressione `@@=pixels`, causando cerchi sproporzionati nel renderer. Selezione e avvisi hanno anelli separati, limitati rispettivamente a dimensioni di 22 e 28 pixel. I test verificano il JSON trasmesso per ogni categoria. Il filtro Nomi mantiene sempre riconoscibile l’elemento selezionato; la sintesi mostra solo KPI pertinenti ai livelli attivi.

## Rigenerare gli asset

Usare un ambiente ETL separato con le dipendenze dell’app e `shapely`, `pyshp`. Acquisire le fonti soltanto dopo aver verificato la versione e i diritti:

- [Archivio INET_Raw](https://zenodo.org/api/records/4750979/files/INET_Raw.zip/content), MD5 **`08a85a3aceb2d0736476244f2b4d3962`**, controllato dallo script.
- [Archivio Natural Earth](https://naciscdn.org/naturalearth/10m/cultural/ne_10m_admin_0_countries.zip), admin-0 5.1.1.

```bash
python -m scripts.build_italian_network \
  --scigrid-zip /percorso/INET_Raw.zip \
  --natural-earth-zip /percorso/ne_10m_admin_0_countries.zip \
  --curated data/italian-network/curated.json \
  --retrieved-at DATA_ORA_ISO_CON_OFFSET \
  --output /cartella/estratto
```

In alternativa usare `--italy-geojson data/italian-network/italy.geojson` al posto di `--natural-earth-zip` per riutilizzare esattamente il confine incluso. La semplificazione è di 0,008 gradi con topologia preservata. Il ritaglio dei collegamenti storici usa un margine di 0,025 gradi per l’incertezza costiera: **non è una delimitazione legale di acque territoriali**. Gli impianti offshore con coordinate del gestore sono conservati indipendentemente da quel ritaglio.

Il filtro SciGRID accetta solo paese IT o estremi IT/IT e conserva i soli consumatori con combustibile gas. Nessun segmento viene aggiunto per raccordare marker. Le correzioni manuali sono esplicite in `curated.json`, con fonte e data proprie. Il catalogo dei binding richiede revisione umana: non viene rigenerato automaticamente per somiglianza di nome.

Preparare o rinnovare il piccolo estratto operativo dal repository:

```bash
python -m scripts.refresh_italian_network --all-entry --days 7 --interruptions
python -m scripts.refresh_italian_network --manifest-only
```

Senza `--all-entry` si aggiorna soltanto Mazara, oppure il `--point` esplicito già presente nei binding. Il comando non viene invocato dall’app. Conserva gli estratti precedenti se il provider fallisce, senza ridatarli. Verificare differenze, diritti e copertura prima di distribuire asset aggiornati. Il manifest SHA-256 controlla i file della release; non certifica la completezza del sistema gas.

## Validazione eseguita

- **P1: 686 test passati nella suite completa**, inclusi snapshot storici round-trip, sette indicatori, zero/mancante, direzioni, DST 23/25 ore, capacità sovrapposte non confrontabili, headroom pubblicata, mapping non confermati, dati futuri/stale, eventi duplicati/in conflitto e selezione persistente. **9 controlli readiness offline**, `pip check` e `git diff --check` superati. Chrome/WebGL2 in **Demo e Workbench**, a 1440, 820, 390 e 375 px con traffico esterno bloccato: quattro letture, 69 centrali senza selezione, clic reale su una centrale, selezione stabile dopo cambio lettura, punto/gasdotto, zoom/reset, ricerca da tastiera disambiguata, storico e drill-down P0 verificati. Nessun accesso a tile/geocoder o provider durante il percorso; nessuna dipendenza runtime aggiunta. IIP autenticato e deployment restano esclusi dalla verifica live di questo incremento.
- Test deterministici con fixture sintetiche dichiarate: identità, paese, WGS84, coordinate offshore, duplicati, gruppi virtuali, unità, segni, N/A, revisioni e conflitti, paginazione e limiti, giorni gas con DST, capacità disallineate, TTL e fallback con timestamp originale.
- Streamlit AppTest: apertura offline, cambio livelli/regione/periodo, selezione e dettaglio, pick nativo validato dal backend, selezioni obsolete ignorate, zero risultati, reset senza perdita dei dati, GIE nazionale separato, tutte le undici pagine principali raggiungibili.
- Browser reale Playwright / Chrome, WebGL2 su Streamlit 1.67 (renderer nativo; SwiftShader opzionale con `--software-rendering`): clic fisici su punto e gasdotto, tooltip, pan/zoom, mantenimento della selezione, trasferimento di infrastruttura e periodo a Security of Supply, selezione da tastiera e ritorno alla Panoramica. Viewport 1440×1000, 820×1180, 390×844 e 375×812: pannello a destra su desktop, mappa prima del dettaglio sugli schermi piccoli, assenza di overflow orizzontale. Controllati anche spazio sotto il titolo e date del grafico entro i bordi. Le verifiche successive leggono i colori dei sottolivelli effettivamente renderizzati, confrontandoli prima e dopo la selezione; esercitano i limiti reali di zoom con ripetuti eventi della rotella, Vista Italia, cursore, immagini della legenda e cambio indicatore nello storico della Panoramica. Tutto il traffico esterno del browser è bloccato: nessuna richiesta a basemap o dati operativi; resta soltanto il tentativo del framework per un’icona Material, senza dipendenze della mappa.
- Smoke live limitati del 22/11/2026: cataloghi ENTSOG, sette indicatori per undici ingressi, `/interruptions` su Mazara; cataloghi AGSI+/ALSI pubblici. I dati ricevuti e le loro acquisizioni sono inclusi negli asset. **Inventari GIE e IIP autenticati non verificati live localmente**: adapter e separazione delle fonti sono coperti da fixture, non dichiarati come accesso riuscito.
- Test Panoramica: apertura di entrambe le Panoramiche con HTTP vietato, navigazione alla stessa infrastruttura e ritorno, selezione dei gasdotti, chiavi indipendenti, unica lettura degli asset, limiti dei KPI, date e stato GIE, dati mancanti, etichette e spazio dell’asse temporale. **631 test passati** nella suite completa P4 dopo i test mirati; **9 controlli readiness offline passati**. Nuove regressioni: acquisizioni miste, indicatori/giorni estranei al KPI, cache scaduta, dati futuri, completezza e fallimenti pertinenti, zero/mancante, confronto giornaliero e inquadratura Mercatore su quattro formati, direzione coerente tra tooltip/dettaglio/navigazione, zoom/reset e geometria condivisa dei simboli della legenda. AppTest della versione precedente eseguiti anche con l’API Streamlit 1.49; flusso corrente verificato sull’ambiente installato.

Il controllo browser è ripetibile dal repository, con Streamlit già avviato e Playwright installato soltanto nell’ambiente di sviluppo:

```bash
streamlit run app.py --server.port 8766 --server.headless true
python -m scripts.check_network_browser --url http://127.0.0.1:8766 \
  --chrome "/percorso/al/browser/Chrome" --output /tmp/igor-map-browser
```

Omettendo `--chrome` si usa Chromium di Playwright. Le immagini e `checks.json` sono salvati fuori dal repository; il comando non preme Aggiorna né interroga le API. Ripetere l’avvio con `GASOPS_APP_MODE=workbench` per la seconda modalità. La verifica sul deployment e sui browser del team resta distinta dai controlli locali.

## Esclusioni e priorità

Overpass ha risposto HTTP 406 anche a richieste mirate; Wikidata HTTP 403; una ricerca pubblica puntuale Nominatim non ha prodotto risultati. Nessuna di queste fonti è incorporata o dichiarata funzionante. La cartografia Snam resta un riferimento esterno: nessuna licenza utilizzabile per estrarne tracciati è stata verificata.

Non sono inclusi tracciati aggiornati certificati, rete regionale distinta, punti di riconsegna completi, impianti di miscelazione o localizzazioni produttive MASE. Non sono attribuiti stato corrente o capacità correnti ai 20 stoccaggi e alle 69 centrali storiche. Le sole capacità storiche dei gasdotti sono mostrate come metadati datati, senza aggregazioni operative.

Valutazione P1: le pagine ufficiali [MASE/UNMIG Cartografia](https://unmig.mase.gov.it/cartografia/) e [Stoccaggio del gas naturale](https://unmig.mase.gov.it/stoccaggio-del-gas-naturale/) pubblicano informazioni mensili e collegamenti a CSV/KML, con CC BY 4.0 dichiarata per i dati di stoccaggio. La presenza di un titolo minerario non identifica automaticamente la posizione di un impianto né il suo stato operativo: in questo incremento non sono stati aggiunti nuovi elementi senza il controllo incrociato di geometria e identità. Gli asset e i mapping verificati restano quelli inclusi. Non sono state aggiunte chiamate GME o Jarvis autenticate.

Priorità successive: 1) dataset geografico ufficiale aggiornato con licenza esplicita; 2) verifica degli inventari e UMM con accesso GIE del deployment; 3) collaudo sul dispositivo e sul browser del team; 4) estensione dei mapping di singoli impianti documentabili; 5) maggiore copertura e riconciliazione della paginazione ENTSOG, mantenendo limiti e provenienza.


## Verifica copertura API dei nodi

La mappa estesa include **Copertura API dei nodi**, un controllo del catalogo ENTSOG Operator Point Directions per Snam Rete Gas (IT-TSO-0001), riutilizzando l'adattatore HTTP e cache esistenti. L'acquisizione è esplicita, non parte selezionando un nodo e non è disponibile in modalità archivio. Il report indica data, operatore, righe e conflitti, ed è esportabile in JSON per tutti i nodi.

La copia inclusa del 22 novembre 2026 contiene 32 righe. Il confronto nominale esatto (anche su alias separati da slash o trattino) produce 9 nodi con punti già associati ad altre infrastrutture, 168 senza corrispondenza esatta e nessuna nuova associazione verificata. I dati dei punti già associati non vengono duplicati. Eventuali nuovi candidati restano da revisionare: omonimia e disponibilità del catalogo non provano identità fisica. Aggregati, punti virtuali e hub non sono usati come identificativi di nodi interni. L'audit copre il catalogo esaminato, non tutti i gestori italiani né i portali riservati.

Per i nodi privi di associazioni operative la scheda presenta geografia, provenienza e risultati dell'audit senza schede di telemetria vuote. Nessuna osservazione, binding o metrica nazionale viene modificata.


## Linguaggio visivo delle direzioni

Le viste operative riutilizzano `direction_ui`: ↘ ingresso nella rete italiana, ↗ uscita e ↔ punto bidirezionale secondo i binding ENTSOG confermati. Le frecce sono simboli semantici, non orientamenti geografici, velocità o direzioni dedotte dei gasdotti. I rombi delle frontiere in Sistema e Flussi conservano il pieno/contorno relativo alla disponibilità dei dati e incorporano un glifo direzionale; in Attenzione la simbologia degli avvisi resta prioritaria. Tooltip, etichette, selettori e legenda condividono la stessa semantica. I riquadri bidirezionali mostrano separatamente i due flussi fisici del giorno gas, con N/D distinto da zero e direzione consultata evidenziata. Non vengono sommate le direzioni né alterati i dati esportati.
