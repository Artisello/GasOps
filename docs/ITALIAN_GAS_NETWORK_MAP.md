# Rete gas italiana

Vista **Security of Supply → Mappa della rete**. Nella demo è la vista iniziale di questa sezione; tutte le altre viste restano accessibili. Titolo: **Rete gas italiana**. La mappa è informativa, con dati pubblici e provenienza verificabile; non controlla infrastrutture.

## Copertura effettiva

| Livello | Elementi | Significato |
|---|---:|---|
| Gasdotti | 163 | Collegamenti **schematici storici**, non rilievi dei tracciati |
| Ingressi e uscite | 7 | Mazara, Gela, Melendugno/San Foca, Tarvisio, Passo Gries, Gorizia, Bizzarone |
| Terminali GNL | 5 | Panigaglia, Adriatic LNG, OLT, Piombino, Ravenna |
| Stoccaggi | 20 | Archivio storico, inclusi progetti; stato attuale non presunto |
| Compressione | 15 | Localizzazioni storiche indicative, inclusi elementi non riconfermati |
| Centrali elettriche a gas | 69 | Livello distinto, selezione del combustibile gas in SciGRID |
| Nodi | 177 | Nodi storici opzionali |
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
- `italian_network_map.py`: scena PyDeck con confini italiani incorporati; nessun tile provider, geocoder, token cartografico o nuovo framework frontend.
- `italian_network_page.py`: filtri, selezione nativa con clic, selettore accessibile, scheda, storico, qualità ed export JSON attribuito.
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

## Aggiornamento, cache e prestazioni

Aprire la vista, cambiare filtri, selezionare un impianto e navigare **non esegue richieste API**. La geometria pesa circa 340 KB e l’estratto operativo circa 404 KB, compresi gli intervalli originali e le revisioni; gli asset vengono letti tramite cache Streamlit. I 456 elementi non richiedono clustering o un caricamento GIS pesante.

**Aggiorna** interroga il catalogo, il solo punto/direzione selezionato e le sue interruzioni. Se la chiave GIE è configurata sul server, aggiorna anche l’eventuale impianto associato, le scorte nazionali e IIP, riutilizzando gli stati delle viste esistenti. Un limite di un minuto evita richieste ripetute della stessa sessione. I limiti del periodo sono applicati prima delle richieste.

Si riusano timeout, limiti di dimensione, gestione redirect autenticati e SQLite di `public_data.retrieve`. TTL: catalogo sette giorni, operazioni/interruzioni dodici ore, inventari ventiquattro ore, IIP due ore. Il refresh esplicito tenta il provider; se fallisce, conserva la data originaria della copia valida. Il fallimento di una fonte non cancella le altre. Il reset modifica soltanto filtri e selezione, senza eliminare dati o import preesistenti.

Le chiavi non vengono scritte negli asset, nei parametri URL, nell’export o nella sessione della mappa. La dipendenza diretta aggiunta, `pydeck>=0.9,<1`, era già transitiva di Streamlit. Shapely/pyshp servono soltanto all’ETL offline.

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

- Test deterministici con fixture sintetiche dichiarate: identità, paese, WGS84, coordinate offshore, duplicati, gruppi virtuali, unità, segni, N/A, revisioni e conflitti, paginazione e limiti, giorni gas con DST, capacità disallineate, TTL e fallback con timestamp originale.
- Streamlit AppTest: apertura offline, cambio livelli/regione/periodo, selezione e dettaglio, pick nativo validato dal backend, selezioni obsolete ignorate, zero risultati, reset senza perdita dei dati, GIE nazionale separato, tutte le undici pagine principali raggiungibili.
- Scene PyDeck: dati incorporati, Italia soltanto, nessun URL di tile o token, layer selezionabili con ID stabili. La selezione viene verificata lato Python; **la resa WebGL e il clic fisico in un browser non sono stati verificati in questa sessione**.
- Smoke live limitati del 22/11/2026: cataloghi ENTSOG, sette indicatori per undici ingressi, `/interruptions` su Mazara; cataloghi AGSI+/ALSI pubblici. I dati ricevuti e le loro acquisizioni sono inclusi negli asset. **Inventari GIE e IIP autenticati non verificati live localmente**: adapter e separazione delle fonti sono coperti da fixture, non dichiarati come accesso riuscito.
- Suite completa: **592 test passati**; gate offline esteso al manifest e agli asset della mappa. AppTest della nuova vista eseguiti anche con l’API Streamlit 1.49. I warning osservati sono deprecazioni PyMuPDF/SWIG già presenti.

## Esclusioni e priorità

Overpass ha risposto HTTP 406 anche a richieste mirate; Wikidata HTTP 403; una ricerca pubblica puntuale Nominatim non ha prodotto risultati. Nessuna di queste fonti è incorporata o dichiarata funzionante. La cartografia Snam resta un riferimento esterno: nessuna licenza utilizzabile per estrarne tracciati è stata verificata.

Non sono inclusi tracciati aggiornati certificati, rete regionale distinta, punti di riconsegna completi, impianti di miscelazione o localizzazioni produttive MASE. Non sono attribuiti stato corrente o capacità correnti ai 20 stoccaggi e alle 69 centrali storiche. Le sole capacità storiche dei gasdotti sono mostrate come metadati datati, senza aggregazioni operative.

Priorità successive: 1) dataset geografico ufficiale aggiornato con licenza esplicita; 2) verifica degli inventari e UMM con accesso GIE del deployment; 3) collaudo visuale WebGL e usabilità nel browser del team; 4) estensione dei mapping di singoli impianti documentabili; 5) maggiore copertura e riconciliazione della paginazione ENTSOG, mantenendo limiti e provenienza.
