# I.G.O.R.

**Intelligent Gas Operations & Risk**

Demo indipendente delle potenzialità per Balancing, Settlement e Operations. La sidebar dà accesso all’intero programma: mercato, Security of Supply, AI, rischi, documenti, KPI, controlli commerciali, fonti e casi dimostrativi.

**Panoramica → Mappa italiana**: mappa interattiva in apertura sia Demo sia Workbench, con KPI pubblici e accesso alla stessa infrastruttura in **Security of Supply → Mappa della rete**. La vista completa offre 456 elementi geografici italiani, estratto ENTSOG reale per 11 ingressi, filtri e dettagli consultabili anche offline. Aggiornamento mirato su richiesta; geografie storiche e copertura parziale esplicite. [Fonti, licenze e limiti](docs/ITALIAN_GAS_NETWORK_MAP.md).

La stessa mappa offre quattro letture: **Sistema, Flussi, Attenzione e Infrastrutture**. Le 69 centrali elettriche sono visibili dalla prima apertura. Punti e gasdotti hanno aree di click ampliate, separate dai simboli visibili. La Panoramica privilegia flusso e utilizzo; dettagli commerciali, bilancio e qualità restano apribili. La scheda condivisa mantiene storico, eventi e provenienza. Cambiare lettura conserva la selezione e non interroga le API.

**Security of Supply → Esplora dati**: confronto delle osservazioni ENTSOG e GIE già disponibili, con serie temporali, D-1, revisioni, tabella e CSV dalla stessa selezione. Accesso diretto dalla scheda Fonti della mappa e diagnostica condivisa con Source Health. Nessun caricamento o fetch al cambio filtro. [Funzioni e limiti del Data Explorer](docs/GAS_DATA_EXPLORER.md).

**Bilanciamento → Cockpit**: giorno gas, confronto nomination/rinomina/allocazione/flusso, pubblicazioni, driver, eventi e qualità. Vista pubblica di sistema distinta dai portafogli importati e autorizzati. Posizione non calcolabile quando gli input non bastano; nessun saldo ufficiale inventato. I controlli di settlement e riconciliazione esistenti restano accessibili. [Metodo e limiti](docs/BALANCING_COCKPIT.md).

**Bilanciamento → Scenario di mercato → Stress Test Italia**: demand shock, freddo ipotetico, perdita/taglio capacità di un ingresso verificato, riduzione LNG e limite storage, anche combinati. Estende il motore deterministico esistente; dati pubblici e Demo esplicita separati, copertura e mancanze visibili, JSON riproducibile. Accesso anche dalle schede della mappa. [Formule e limiti del modello di disponibilità](docs/ITALIAN_SECURITY_STRESS_TEST.md): non è un digital twin idraulico.

**Demo live:** https://snamigor.streamlit.app/

**Profili e caricamento.** La demo usa il profilo server `public_demo`; `GASOPS_APP_MODE=workbench` continua a scegliere il layout senza concedere accessi privati. `private_workbench` richiede identità OIDC verificata da Streamlit, issuer e subject autorizzati sul server e scadenza valida. In mancanza, l'accesso resta chiuso. `test` non concede privilegi. Configurazione e controlli pendenti: [production readiness](docs/PRODUCTION_READINESS.md).

La navigazione carica solo i moduli della vista richiesta. Modelli statistici, indice PDF e archivio remoto vengono caricati quando servono. L'assistente parte in modalità locale senza generare report; AI, acquisizioni e indicizzazione dei PDF pubblici richiedono un'azione esplicita. Cache, storico e dati mancanti mantengono il proprio significato e periodo.

**Navigazione semplice.** Selettori uniformi con nomi brevi, controlli da 44 px e disposizione su due colonne su telefono. Le schede della Panoramica aprono direttamente gli esempi. Nel mercato compaiono subito i consumi osservati: **Calcola previsione** avvia la stima, poi riutilizzata nella sessione. Un modello scelto esplicitamente evita gli altri calcoli finché non servono confronto o ripiego. Metodi, unità, fonti e formule restano gli stessi.

**Importazioni API.** In **Fonti e connessioni → Aggiorna fonti connesse** seleziona le fonti e importa anche tutti i punti verificati ENTSOG, con storico di 7/30 giorni e impianti GIE associati. L’esploratore riutilizza dodici indicatori pubblicati di stoccaggi/GNL, con unità separate. Confronto europeo opzionale, paginazione IIP limitata, autenticazione Terna riutilizzata nel lotto e cache conservata in caso di errore. [Copertura, fonti e limiti](docs/API_IMPORTS.md).

I.G.O.R. è un prototipo indipendente, non ufficiale Snam. Gli identificatori tecnici e le configurazioni di deployment restano invariati per compatibilità.

## Stato di rilascio

Prototipo dimostrativo indipendente, non sistema Snam certificato. [Checklist di rilascio e limiti](docs/PRODUCTION_READINESS.md) · [Demo esplorabile](DEMO.md).

`python -m gasops_app.readiness` verifica gli archivi inclusi e la persistenza in una cartella temporanea senza chiamare API, leggere Secrets o modificare dati di esercizio.

## Avvio locale

Da questa cartella usa Python 3.12 o successivo.

```sh
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

L’avvio apre una **panoramica essenziale con la sidebar visibile su desktop**. Le undici aree comprendono tutte le viste originali, Fonti e API ed Esempi BSO. La barra laterale resta disponibile in ogni pagina; su mobile si apre con il controllo nativo di Streamlit. Non ci sono pagine funzionali accessibili solo mediante una configurazione nascosta.

**Per esplorare gli esempi non servono file o chiavi personali.** Bilanciamento e KPI partono da casi dichiarati, i rischi mostrano già un calcolo, la ricerca PDF propone un risultato e l’assistente prepara un’analisi JRC. Se il modello AI è configurato e attivo, l’esempio usa il modello con le sole evidenze pubbliche JRC e i limiti di chiamata esistenti; altrimenti è un report locale esplicito. I registri importati restano distinti dai casi dimostrativi.

**Fonti e API** mostra disponibilità, ultimo controllo e collegamenti alle analisi. Un’unica azione aggiorna tutti i connettori pubblici disponibili e verifica modello AI e archivio remoto, se configurati. Eurostat, ARERA, ENTSOG, ACER e meteo non richiedono credenziali del visitatore; GIE e Terna usano soltanto le credenziali del server. Configurazione e verifica riuscita sono distinte. Le fonti non raggiungibili restano segnalate; non vengono sostituite con dati simulati. Jarvis e GME mantengono import e consultazione autorizzati, senza dichiarare endpoint automatici inesistenti. [Guida alla demo](DEMO.md).

Il confronto storico è precalcolato dal motore effettivo per una visualizzazione immediata. La demo controlla le impronte del file JRC e del codice del modello; il test di regressione ripete il backtest e confronta i risultati. Dopo modifiche ai motori o alla fonte, rigeneralo con `python -m gasops_app.demo_forecast`. Esegui i controlli con `python -m pytest -q` e `python -m gasops_app.readiness`.

### Workbench di sviluppo

Gli strumenti completi restano disponibili agli sviluppatori, con una configurazione del server esplicita:

```bash
GASOPS_APP_MODE=workbench streamlit run app.py
```

Questa variante conserva la scrivania tecnica iniziale e i controlli di configurazione nella sidebar. Le funzioni applicative sono raggiungibili anche nella modalità predefinita; il flag non le nasconde e non è autenticazione. Le istruzioni seguenti descrivono fonti, calcoli e strumenti di approfondimento disponibili nel programma.

Nel workbench, **Come usare questa vista** include un glossario contestuale con pagine e sezioni delle edizioni Snam fornite. La guida al modello CSV chiarisce unità, segni e significato delle componenti. [Riferimenti della guida BSO](docs/BSO_REFERENCE_GUIDE.md).

Il prototipo CLI originale è disponibile con `python gasops.py example.json` e `python -m unittest -v`.

## Fonti e unità

| Vista | Misure | Frequenza |
| --- | --- | --- |
| **Eurostat + ARERA** | Consumo interno osservato, disponibilità contabile, produzione, importazioni, esportazioni, scorte e media del PSV day-ahead (CMEM,m) | Mensile · GWh e €/MWh |
| **JRC** | Consumi italiani nazionali, industriali, per generazione elettrica e per il settore residenziale e commerciale. Archivio 2015–2021 disponibile offline | Giornaliera · GWh/giorno gas |
| **Dati di esempio** | 420 giorni simulati con stagionalità e anomalie note. Include offerta, stoccaggio e prezzo di esempio | Giornaliera · GWh e €/MWh |

Eurostat fornisce il consumo osservato (IC_OBS) e quello calcolato (IC_CAL_MG) secondo MOS GAS. La dashboard usa il secondo come disponibilità contabile, con un’unità comune di GWh (TJ a PCS ÷ 3,6). Le importazioni nette sottraggono le esportazioni. La variazione delle scorte è positiva in accumulo. Il prelievo netto nello scenario usa max(0, −variazione delle scorte). [Serie Eurostat](https://doi.org/10.2908/nrg_cb_gasm) · [Definizioni del bilancio mensile](https://eur-lex.europa.eu/eli/reg/2017/2010/oj/eng)

La componente CMEM,m di ARERA rappresenta il riferimento mensile del PSV day-ahead e viene associata ai volumi dello stesso mese civile. I prezzi di acquisto e vendita per la regolazione del singolo partecipante sono ipotesi modificabili. L’analisi dell’esposizione usa la precisione decimale. [Tabella ufficiale ARERA](https://www.arera.it/area-operatori/prezzi-e-tariffe/valore-cmemm-vulnerabili)

L’archivio locale `data/jrc/IT.v1.1.csv` è il file originale italiano del dataset ENaGaD v1.1. I dati sono attribuiti a Nicola Zaccarelli, Sergio Giaccaria, Maksims Feofilovs e Ricardo Bolado-Lavín, Joint Research Centre della Commissione europea, con osservazioni di fonte Snam. Il file conserva la sua intestazione, la licenza e i flag della fonte. [Dataset v1.1](https://doi.org/10.5281/zenodo.6364875) · [Metodologia JRC](https://doi.org/10.2760/497677) · [Licenza CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)

La dashboard indica l’ultimo periodo di ogni fonte, i flag pubblicati e lo stato della cache. Se un aggiornamento fallisce, può usare l’ultima copia verificata con la data originale. I prezzi mancanti rimangono vuoti. Quando mancano volumi allineati per uno scenario, l’app indica una base interamente di esempio. Le simulazioni restano separate dalle osservazioni.

La **prossima stima** e la fascia all’80% sono sopra il grafico. In **Mercato e previsioni**, il confronto mostra l’errore medio in GWh sul periodo successivo. Con **Automatico**, l’app sceglie il modello con l’errore medio più basso sulle stesse osservazioni storiche. Puoi scegliere un altro modello dal selettore.

Il modello bayesiano usa la stagionalità annuale. Per i dati giornalieri considera il giorno della settimana, le festività a data fissa e la persistenza dei consumi recenti. Per i mesi tiene conto del numero di giorni. La fascia all’80% stima l’incertezza sui coefficienti e sulle osservazioni future. Nei dettagli trovi quante osservazioni storiche sono rientrate nella fascia a un passo. Il confronto è cronologico sullo storico disponibile, che può includere revisioni successive. [Documentazione scikit-learn](https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.BayesianRidge.html)

Le bande empiriche dei modelli precedenti richiedono almeno 20 errori fuori campione per orizzonte. Il giorno gas inizia alle 06:00 Europe/Rome e le date di calcolo sono in UTC.

## Fonti normative e modello opzionale

Carica PDF con testo ricercabile su **Analisi normativa** o colloca le copie in `data/regulatory/`. Puoi anche indicare `GASOPS_PDF_DIR`. Il registro include riferimenti alle edizioni di Piombino 2023-I e Codice di Rete XCII. L’applicabilità attuale richiede verifica. I PDF originali restano locali.

Per abilitare un modello, copia `.env.example` in `.env`, imposta `GASOPS_LLM_MODEL` e l’URL compatibile, quindi seleziona il modello in **Modalità di analisi**. Ollama usa l’endpoint locale `/v1` e richiede un modello con chiamate a strumenti. Un endpoint HTTPS compatibile può usare `GASOPS_LLM_API_KEY`. La modalità esterna trasmette all’endpoint configurato domande, risultati ed estratti selezionati.

Gli agenti eseguono calcoli deterministici. I report dell'interfaccia e lo storico dell'assistente restano in sessione; scaricali per conservarli. SQLite sotto `.gasops/` conserva cache delle fonti e contatore delle richieste AI. `GASOPS_STATE_DIR` permette di cambiare la cartella. Il **Centro operativo AI** esporta JSON e Markdown.

## Modelli econometrici

ARIMA e SARIMAX (statsmodels, massima verosimiglianza) si aggiungono ai tre modelli esistenti. ARIMA prova (1,1,1) e (1,1,0); SARIMAX usa periodo 7 per giornaliero e 12 per mensile, con variabili di calendario note in anticipo per il giornaliero. I dati mensili sono modellati come tasso medio giornaliero e ricondotti a GWh/mese. Non si usano ancora meteo o altre variabili esogene osservate. La stima usa finestre limitate e salta fit non convergenti; la fascia predittiva all’80% è condizionata ai parametri stimati, non bayesiana. Il backtest stima i parametri prima del holdout (56 giorni / 30 mesi), aggiorna lo stato solo dopo ogni osservazione, mentre gli altri modelli effettuano refit progressivi. La selezione automatica si basa sul MAE degli stessi periodi, con RMSE, WAPE e bias (previsione meno osservato) come diagnostica. Mancanti non imputati. Non è una verifica su un test finale indipendente dalla selezione del modello. Per serie archiviate si tratta di proiezioni storiche.

## Rischio probabilistico

Apri **Rischio probabilistico** per simulare 1.000–100.000 scenari con seed riproducibile. La domanda può usare il primo periodo previsto e la deviazione standard di almeno 20 errori fuori campione a un passo; altrimenti usa volatilità manuali, esplicitamente illustrative. Offerta e prezzo sono ipotesi; per dati mensili l’offerta contabile non è capacità fisica. Shock gaussiani correlati tramite un fattore domanda comune, volumi troncati a zero; la correlazione offerta/prezzo è il prodotto delle altre due correlazioni. Mostra P5/P50/P95, probabilità di deficit, deficit atteso, VaR e CVaR/Expected Shortfall 95% e 99% del deficit e del costo lordo teorico (deficit GWh × 1000 × max(prezzo,0)). I prezzi mancanti non producono valori economici. Il CVaR usa esattamente la massa di coda empirica, inclusi i pareggi. L’intervallo Wilson misura soltanto l’errore Monte Carlo, non l’incertezza del modello. Non è una stima ufficiale di sicurezza degli approvvigionamenti, un costo netto o un settlement. Non si assume calibrazione congiunta, né traiettorie multiperiodali. L’agente di scenario include questi risultati nel JSON e nella sintesi con le ipotesi salvate, mantenendo invariati gli strumenti regolatori. L’esportazione della pagina conserva i parametri e la provenienza.

## Operazioni commerciali

Apri Registro operativo: una vista unica e cinque tab per fatture, prezzi, garanzie, scadenze, bilanci e GNL. I dati si riferiscono a un caso sintetico. Il controllo di prezzo copre il regime ordinario con estremi TSO disponibili e percentuale SA pubblicata fornita come input; sotto 2.000 MWh richiede 30 giorni precedenti esatti. Regime speciale, prezzi medi negativi e dati mancanti richiedono revisione. Il controllo EPSu confronta componenti già determinate e soglie 90/100%, non calcola autonomamente la disciplina delle garanzie. La riconciliazione confronta importi prima delle imposte per gruppi DS e segnala documenti multipli; non emette fatture. Le scadenze GNL utilizzano giorni lavorativi con calendario esplicito (non certificato); i termini di pagamento 15/30 giorni sono mostrati senza eventuali proroghe. Fonti: CdR XCII cap. 5 §§1.4.1/1.4.4, cap. 9 §4.4.1, cap. 18 §4.1.2; CdRig Piombino 2023-I allegato 14/A. Edizioni di studio, vigenza non verificata. Nessun dato aziendale richiesto o trasmesso.

## Fonti giornaliere recenti a costo zero

In Panoramica o Mercato e previsioni seleziona **ENTSOG · prelievi SRG giornalieri**. Il connettore interroga l’API pubblica senza chiave, con al massimo 13 finestre mensili, cache SQLite (12 ore per gli ultimi due mesi, 30 giorni per mesi precedenti), un tentativo per finestra e stop in caso di storico non disponibile. Aggiorna fonti rinnova solo i due mesi più recenti. Le fonti Eurostat/ARERA rimangono disponibili; l’archivio JRC 2015–2021 è separato.

Perimetro: tre aggregati di uscita SRG per distribuzione, industria e termoelettrico, mappati dal [tracker Bruegel](https://github.com/benmcwilliams/gas-demand/blob/main/src/data/inputs/entsog_points_mapping.xlsx), blob 9daf527c9f601432ada9f10d6a411214f1ac2132. [ENTSOG API manuale](https://transparency.entsog.eu/api/archiveDirectories/8/api-manual/ENTSOG_TP_API_UserManual_v3.0.pdf). Identificatori e unità controllati, dati incompleti/confittuali esclusi dalla somma. È un proxy del perimetro SRG, non un bilancio italiano nazionale ufficiale. I dati non sono uniti a JRC, non si inventano prezzi o offerta. Le eventuali simulazioni con dati di esempio sono esplicitamente etichettate. Dati a disposizione del provider, osservazioni soggette a revisione; nessuna garanzia di completezza o disponibilità live. Il connettore è nuovo e richiede verifica runtime del contratto API; i test deterministici usano payload sintetici. Nessuna nuova dipendenza o abbonamento. Per il prototipo usa la modalità deterministica; un LLM remoto configurato separatamente può generare costi.

Fonti future: Jarvis/GME (verificare accesso e formati), GIE AGSI/ALSI (API gratuita ma registrazione e chiave obbligatorie), Open-Meteo (free per uso non commerciale, nei limiti dei termini). Nessuna chiave richiesta per utilizzare questa release.

## Meteo: approfondimento facoltativo (MVP)

Solo con la serie giornaliera ENTSOG recente, apri **Mercato e previsioni → Meteo e domanda** e abilita la demo non commerciale. Non vengono eseguite chiamate meteo all’avvio. Due richieste senza chiavi a Open-Meteo (ERA5 e previsione), con cache SQLite e timeout esistenti. Tre località fisse (Milano, Roma, Napoli) a pesi uguali; HDD base 18 °C mediati tra località. Proxy di giorni civili, non temperatura nazionale ponderata né media esatta del giorno gas. Storico al massimo 365 giorni con ritardo ERA5 di sei giorni; date mancanti escluse. Confronto Ridge calendario vs calendario+HDD su 28 ultimi giorni completi, almeno 120 osservazioni. Dato meteo realizzato nel test: MAE condizionale, non backtest operativo di meteo previsto. Scenario dei prossimi sette giorni soltanto se l'errore condizionale si riduce. Non modifica selezione automatica, SARIMAX o simulazioni. Nessun costo obbligatorio o nuova dipendenza. La fonte gratuita è riservata all’uso non commerciale (https://open-meteo.com/en/terms), attribuzione CC BY 4.0. Le risposte live richiedono smoke test. Per il MVP non sono stati aggiunti altri provider, credenziali, job programmati o nuove pagine.

## Dati operativi aggiuntivi (facoltativi, MVP)

**Mercato e previsioni → Dati operativi e stoccaggi**: Jarvis, AGSI+, ALSI e IIP. **Registro operativo → Prezzi**: riferimento GME. Nessun nuovo menu, dipendenza, job periodico o costo obbligatorio.

- **Jarvis**: collegamento al portale pubblico e modello CSV normalizzato (non formato nativo Snam). Campi: gas_day (G), published_at (ISO 8601 con offset), expected_withdrawal_gwh, sas_gwh, expected_linepack_gwh; riportare solo dati pubblici autorizzati, in GWh, stimati per G e pubblicati durante G. I mancanti restano mancanti; conservazione delle versioni nell’analisi della sessione, conflitti bloccati. Nessuna acquisizione automatica perché schema e endpoint nativi non verificati. Non caricare dati riservati; nessun salvataggio o invio ai modelli.
- **GIE AGSI+**: registrazione gratuita su https://agsi.gie.eu/; imposta GASOPS_GIE_API_KEY nell’ambiente o nei segreti Streamlit (non nel repository). Su richiesta, un download per Italia o UE con 90 giorni, cache 24 ore, niente retry forzato. Dati separati: giacenza TWh, capacità TWh, riempimento %, iniezione ed erogazione GWh/d. Stati C/E/N e data di acquisizione visibili. La giacenza non è disponibilità di fornitura. Fonte GIE AGSI+ (manuale https://www.gie.eu/transparency-platform/GIE_API_documentation_v007.pdf). Nessun dato reale verificato senza chiave; test con payload sintetici.
- **GME**: link agli esiti ufficiali e spiegazione dei campi vicino al calcolatore ipotetico esistente. La licenza personale gratuita non autorizza automaticamente impieghi economici/commerciali o raccolta/analisi automatizzata. Le condizioni pubblicate (https://www.mercatoelettrico.org/Portals/0/Documents/it-IT/20261013CONDIZIONI_GENERALI_API.pdf, artt. 5, 6 e 6-bis) richiedono verifica e autorizzazione scritta per gli usi limitati; no scraping, connettore o import reale nella demo. MGASVolumes non identificato automaticamente con STSP title.

Le fonti non sono mischiate al forecasting, alle simulazioni o a dati aziendali. Nessuna nuova fonte o credenziale necessaria per aprire la demo.

### GIE: attribuzione obbligatoria e chiave condivisa

Usare GASOPS_GIE_API_KEY nei secrets Streamlit o in .env locale (alias precedente GASOPS_AGSI_API_KEY ancora valido). Una chiave con accesso All abilita tutte e tre le piattaforme; nessuna chiave viene salvata nel codice, URL, tabelle o export. Dati forniti gratuitamente da **Gas Infrastructure Europe (GIE)**: [AGSI+](https://agsi.gie.eu/), [ALSI](https://alsi.gie.eu/), [IIP](https://iip.gie.eu/). [Regole di attribuzione](https://iip.gie.eu/data-usage): fonte obbligatoria vicino ai dati, anche rielaborati. I grafici, tabelle e CSV AGSI+/ALSI indicano piattaforma e/o link; JSON IIP contiene fonte, link e acquisizione. Non inviare a LLM o includere nei report automatici in questo MVP.

ALSI: 90 giorni IT/UE, inventario in 10³ m³ LNG e send-out in GWh/d; rapporto send-out/riferimento dichiarato (non capacità disponibile). Formati inventory scalare (manuale v007) e nested lng/gwh supportati senza conversione presunta. Cache 24 ore. IIP: messaggi attivi richiesti da oggi ai prossimi sette giorni; segue solo metadati di paginazione verificati, fino a cinque pagine e 250 record, cache 2 ore. Limiti, errori e conteggi incoerenti mantengono la copertura parziale; acquisizione riferita alla copia più vecchia del lotto. Messaggi originali e revisioni distinte vengono conservati. Nessuna automazione o nuova dipendenza. Risposte GIE autenticate da verificare con le chiavi server; nessuna chiamata all’avvio. [Manuale AGSI/ALSI](https://www.gie.eu/transparency-platform/GIE_API_documentation_v007.pdf).

### Diagnostica fonti indipendenti

In Mercato e previsioni, la sezione Dati operativi e stoccaggi è prima dei grafici e rimane visibile anche se ENTSOG o Eurostat non sono disponibili. ENTSOG usa la forma documentata /operationaldatas, chiavi punto/operatore in maiuscolo e direzione in minuscolo, finestra mensile e timeout di lettura 20 s. La diagnostica distingue HTTP, timeout, connessione, JSON e dati/schema non validi senza mostrare credenziali o risposta grezza. Le chiavi sono ricostruite dagli identificativi Bruegel secondo il manuale ENTSOG v3.0; il live smoke test rimane da effettuare. Le verifiche di completezza e unità restano obbligatorie.

### ENTSOG: controllo risposta API

Il parser distingue array assente, risposta vuota, conteggi, campi, unità e date non validi. È stato osservato in un esempio pubblico del 15 novembre 2026 (https://voltstack.energy/insights/entsog-api-guide) che `meta.count=7` e `meta.total=8` con limite non vincolante. Si accetta solo la discrepanza di un record con count esatto, offset zero e meno di 500 record, marcando la fonte; non si ricostruiscono valori mancanti e si conservano esclusivamente somme giornaliere con tre aggregati presenti. Altre discordanze bloccano la finestra. Per la diagnosi locale, `python -m gasops_app.entsog_probe` esegue una sola richiesta di sette giorni e mostra HTTP, conteggi e risultato del parser, senza dump dei record; CI esegue il probe non bloccante soltanto sulla PR correttiva (nessuna schedulazione). Il test live è distinto dai test deterministici e non garantisce la disponibilità futura dell'API.

### Security of supply: accesso diretto

La pagina autonoma **Security of supply** (`/security-of-supply`) sostituisce il pannello nascosto in Mercato e previsioni; rimane un collegamento diretto nella pagina mercato. Nessuna dipendenza da ENTSOG, Eurostat o dai modelli statistici. AGSI+ Italia è la vista predefinita; si carica solo la fonte selezionata, una volta per selezione/sessione, con cache già esistente di 24 ore (AGSI/ALSI) o 2 ore (IIP); aggiornamento esplicito con pausa di 60 secondi per selezione/sessione. Il segreto GASOPS_GIE_API_KEY (o alias GASOPS_AGSI_API_KEY) è letto esplicitamente da st.secrets o dall’ambiente; non mostrato. Il parser accetta virgola o punto decimale e il singolo oggetto data come nel manuale GIE v007, non separatori delle migliaia ambigui. Diagnostica HTTP/autorizzazione/timeout/schema, valori mancanti conservati, crediti GIE in vista ed esportazioni. Nessuna chiave o dato reale verificato in CI; test offline con fixture.

### IIP: risposta API e diagnostica

La richiesta IIP mantiene i filtri from/to/status e la paginazione documentata dal wrapper pubblico gie_getumm (https://rdrr.io/cran/gie/src/R/gie_getumm.R); prima pagina da 20 messaggi, limite risposta 2 MB per IIP soltanto. Il parser distingue metadati mancanti/non validi, risposta vuota, oggetti singoli e collezioni associative; se last_page manca ma ci sono record validi, la completezza resta esplicitamente non verificata. Gli eventuali identificativi della collezione associativa sono conservati nell'export. Nessuna conversione di capacità né inferenza di assenza guasti. Credito GIE obbligatorio invariato. Non è stato verificato il payload autenticato; la documentazione IIP ufficiale completa è disponibile agli utenti registrati su https://iip.gie.eu/account. Gli errori riportano motivi controllati, non il corpo della risposta, l'URL autenticato o la chiave.

### ENTSOG: verifica della copertura giorno-settore (correzione)

Probe reale CI del 18 novembre 2026, job 134522078923: HTTP 200, periodo 8–14 novembre, 21 record, meta.count=21, meta.total=24, offset=0, limit=500. La precedente eccezione limitata a una singola riga è sostituita da una verifica dell'intera griglia richiesta: tre punti × giorni gas inclusivi. Con totale discordante, count deve coincidere con i record ricevuti, offset deve essere 0, la pagina non deve essere satura, il totale non può essere minore del count. Si accetta la finestra solo se tutti i valori richiesti sono presenti, validi e non conflittuali; si marca la discrepanza e non si certifica la completezza delle revisioni. In caso di lacune si riportano conteggi espliciti, senza imputare dati. Il probe live non bloccante viene eseguito sulla PR correttiva. Nessuna modifica alle altre fonti.

### Interfaccia analista

Menu raggruppato in Mercato, Operazioni e Analisi; Stoccaggi e forniture conserva il percorso /security-of-supply. Panoramica con accessi rapidi, periodo osservato e agenti espandibili. Fonti descritte in italiano con granularità, perimetro e limiti; modello previsionale nelle impostazioni avanzate (stessi algoritmi). Confronto modelli e backtest su richiesta nella pagina mercato; ordinamento numerico degli errori. La nota ENTSOG sul totale discordante si sposta in una sezione tecnica solo quando è esattamente la nota di copertura integrale: errori, cache obsoleta e storico parziale restano in evidenza. Vista GIE: denominazioni estese, ora locale, indicatori selezionabili e colonne leggibili con fonte sempre attribuita. Nessun nuovo provider o costo, né modifica del calcolo o della validazione. Test AppTest e unitari; verifica visiva del deployment separata.

### IIP: diagnostica della paginazione

Il wrapper pubblico usa last_page; il payload autenticato osservato dall'operatore sembra non includerlo. Non si presume che una pagina corta o un campo total certifichi la completezza. La sezione IIP mostra il numero di messaggi ricevuti e mantiene l'avvertenza di copertura non verificata. In Diagnostica paginazione IIP è disponibile un JSON con soli nomi strutturali filtrati e valori numerici dei campi di paginazione riconoscibili, inclusi eventuali contenitori meta/pagination: nessun corpo UMM, URL di continuazione o credenziale. Serve a verificare il contratto reale prima di estendere la paginazione. Non effettua nuove richieste né modifica il calcolo.

### IIP: metadati reali di paginazione

Diagnostica del deployment: data con 11 record, meta.current_page=1, meta.last_page=1, meta.per_page=50, meta.total=11, a fronte di size=20 richiesto. Si legge la paginazione annidata in meta mantenendo compatibilità con last_page al primo livello. La dimensione effettiva dichiarata dal server è accettata fino a 50 record; il limite del download resta 2 MB. Si controllano pagina, numero di record, totale, coerenza delle pagine e conflitti fra metadati. La dicitura di risposta completa riguarda solo la richiesta API e non certifica la copertura di tutte le indisponibilità. Se più pagine, resta visibile lo stato parziale: nessuna nuova chiamata automatica. Test con metadati reali e messaggi sintetici; attribuzione GIE invariata.

### IIP: vista operativa dei messaggi

La pagina mostra quattro riepiloghi, orario locale, periodo effettivamente richiesto, ricerca, filtri sui campi presenti, tabella e dettaglio record, CSV filtrato con attribuzione e JSON originale. La proiezione usa alias espliciti ispirati alle colonne del portale https://iip.gie.eu/; i nomi delle chiavi dei singoli UMM autenticati non sono ancora stati verificati. Campi assenti o conflittuali non vengono dedotti; timestamp senza offset non vengono convertiti; capacità multiple restano nel record originale, nessuna somma o severity score. Nessuna ulteriore chiamata API durante i filtri, stesso limite di paginazione e accredito. Test con fixture sintetiche; verifica sul deployment necessaria.

### Meteo v2: giorno gas e forecast settoriale

Dopo consenso esplicito per demo non commerciale, caricamento automatico per dataset/sessione ogni sei ore (cache SQLite, aggiornamento manuale limitato). Tre località a pesi uguali, temperature orarie UTC, finestre 06–06 Europe/Rome con 23/25 ore al cambio ora, nessuna imputazione. ERA5 fino a sette giorni prima; API forecast per sette giorni gas da domani. Due holdout cronologici di 28 giorni con embargo di sette giorni, almeno 120 giorni di addestramento per finestra e 21 giorni comuni per test. Confronto Ridge calendario aggregato / HDD aggregato / calendario settoriale / HDD settoriale. Previous Runs API temperature_2m_previous_day1 (lead fisso orario 24 ore, non emissione unica giornaliera o backtest completo a sette giorni) quando disponibile; altrimenti confronto realizzato esplicitamente condizionale. Nessuna assunzione di disponibilità storica delle revisioni ENTSOG. Totale settoriale coerente con somma delle stime, nessuna promozione automatica. Fonte Open-Meteo CC BY 4.0, termini free non commerciali. I modelli principali, SARIMAX, agenti e Monte Carlo restano invariati in questa fase; pesi territoriali non calibrati. Test con fixture; API orarie/previous devono ancora essere confermate live.

### AI Cloud: limite condiviso e report

Groq Cloud (`https://api.groq.com/openai/v1`, `openai/gpt-oss-120b`) usa Secrets o variabili GASOPS_LLM_*; in alternativa GROQ_API_KEY da sola. Groq e Grok/xAI sono distinti. Nessun endpoint remoto non Groq senza GASOPS_ALLOW_PAID_LLM=true; Ollama locale resta disponibile. Groq configurato selezionato di default; la CTA è AI solo se il modello è selezionato, altrimenti report deterministico. Test connessione manuale, conteggio condiviso SQLite atomico (30 tentativi/24h, 4/min, 3 chiamate/run, max 1024 token output e 32 KB richiesta). Questi limiti non sono un budget monetario, non certificano quota provider, possono azzerarsi con storage effimero; mantenere piano gratuito senza ricarica. Report completo cloud esegue tutti gli strumenti locali necessari e usa una sola chiamata per sintesi; domande mirate conservano tool calling limitato. Errori HTTP controllati e fallback. Solo dati pubblici o sintetici; non invia riepiloghi/estratti normativi o dati di settlement al provider, interpretazione normativa locale soltanto. Nessun segreto nei log UI. Verifica live con Test connessione AI dopo merge. Meteo/GIE non sono ancora strumenti del supervisore.

### Controllo AI e briefing operativo

Diagnostica sempre visibile nella sidebar e nella panoramica, anche in modalità deterministica. Test reale del percorso JSON con fonte sintetica (una richiesta AI, non un test dei dati live). `GROQ_API_KEY` è sufficiente; una chiave `gsk_` riconosciuta può usare l'endpoint Groq predefinito se non ne è specificato un altro. I provider remoti non Groq restano bloccati salvo autorizzazione esplicita. Selezionare il modello in Modalità di analisi. Opzioni Fonti del briefing AI: previa attivazione vengono consultati gli aggregati Italia AGSI+/ALSI e prima pagina IIP, oltre allo scenario meteo per ENTSOG giornaliero recente (uso non commerciale). Fonti indipendenti, cache esistente, richieste parallele, stato di freschezza, nessun raw UMM o segreto; risultati mancanti non sostituiti. Il briefing usa i riepiloghi con attribuzione GIE e Open-Meteo, senza sommare capacità o equiparare frequenze. Le opzioni richiedono autorizzazione all'uso/condivisione. Nessun ulteriore costo previsto entro quota provider, nessuna prova autenticata da CI. Test di regressione con HTTP fittizio e AppTest.

### Bollettino visibile nella panoramica

La CTA Genera bollettino AI (oppure Genera bollettino di mercato senza modello selezionato) apre il risultato nella stessa pagina, subito dopo i controlli fonte, prima dei grafici. Indicazione della modalità realmente eseguita, sintesi AI distinguibile dai calcoli locali, conteggi controlli/rilievi, fonte e periodo, dettagli espandibili, export Markdown/JSON e collegamento al Centro operativo. L'ultimo bollettino della sessione rimane visibile anche dopo una domanda separata o cambio dati/modello, con avvertenza se non corrisponde alla selezione. Non si recuperano automaticamente report di altri visitatori dalla cronologia condivisa. Corretto anche il formato della matrice di predizione meteo Ridge per output aggregato monodimensionale, emerso nella CI precedente.

### Interfaccia compatta

Firma nella navigazione: «Prototipo per SNAM creato da Igor» (progetto indipendente, non ufficiale). Controlli compatti, guida contestuale con popover nativi Info, spiegazioni metodologiche e dettagli tecnici secondari. La provenienza GIE, le etichette demo/simulazione, i limiti essenziali, gli errori e le avvertenze restano visibili. Funzionalità analitiche, fonti, quota AI e calcoli invariati. Test UI di regressione; verificare layout desktop/mobile sul deployment.

### Aggiornamenti a caldo e quota AI

Il wrapper SQLite non è memorizzato nella cache delle risorse Streamlit: una nuova istanza usa il medesimo database persistente e lo schema idempotente. Contatore non disponibile o vecchia classe: diagnostica controllata, test remoto disabilitato, prenotazione quota fail-closed. Nessun reset della quota o cancellazione dei dati. In presenza di moduli Python ancora caricati da un vecchio deployment, riavviare l'app.

### Panoramica accessibile

Indicatori principali in griglia adattiva, interpretazione in italiano semplice basata esclusivamente sui dati selezionati, bollettino con azione e risultato nello stesso pannello, grafico principale con legenda esplicita, fonti e approfondimenti secondari. Le serie di settore e prezzi restano in Mercato e previsioni; le sezioni operative mantengono i percorsi e i calcoli. Terminologia più accessibile, con etichette tecniche e avvisi sulle simulazioni conservati. Nessun nuovo servizio, nessuna dipendenza. Layout da verificare sul deployment desktop e mobile.

### Mercato e previsioni: area geografica e gerarchia

Perimetro esplicito sotto il titolo: Italia nazionale mensile (Eurostat/ARERA), rete Snam-SRG parziale giornaliera (ENTSOG), archivio italiano 2015–2021 (JRC), simulazione senza copertura reale. Tre indicatori principali con periodo osservato/stimato; schede Consumi e previsioni, Composizione e prezzi, Meteo, Modelli e dati. Le anomalie di qualità restano visibili anche nella vista principale. Il meteo resta condizionale e mantiene l'attivazione esplicita non commerciale, stessa cache e chiamate; Streamlit renderizza tutte le schede, quindi non è un caricamento lazy. Nessuna nuova copertura geografica UE, nessun nuovo modello, nessuna nuova dipendenza. I dati UE di stoccaggio e GNL restano nella pagina dedicata. Verifica visuale sul deployment ancora necessaria.

### Stoccaggi e forniture: vista operativa

Navigazione per funzione (Scorte, Gas liquefatto, Avvisi, Rete Snam); il perimetro Italia/aggregato UE GIE resta esplicito. Riempimento da fonte, barra solo per percentuali 0–100 e non indice di sicurezza. Indicatori della stessa data, variazioni rispetto all’esatta data sette giorni prima solo con valori validi, grafico a 30/90 giorni con lacune e unità esplicite. ALSI mantiene separati volume liquido ed energia; avvisi IIP con filtri espandibili, column order essenziale e dettaglio completo; Jarvis resta importazione manuale. Attribuzione GIE e avvisi visibili. Nessuna modifica a parser, limiti, cache o richieste. Test regressione; traffico autenticato e resa live da verificare.

### Bilanciamento: calcolo semplice e completo

Vista per partecipante ipotetico: immissioni/prelievi oppure formula del registro CdR XCII I+S+T netto−P, saldi con segno nella stessa unità, nessuna imputazione di componenti mancanti, flusso economico distinto dalla posizione energetica (anche con prezzi negativi). Confronto illustrativo ±10 €/MWh e download JSON. Il calcolo semplice mantiene le ipotesi del briefing; quello completo è locale alla pagina, non trasmesso al modello. Scenario aggregato separato, confronto base/scenario, fonte e frequenza, fallback sintetico dichiarato, gestione dello shock stoccaggio incompatibile con fonte senza contributo. Nessuna nuova fonte, API o formula normativa certificata; riferimenti del registro già presenti, edizioni di studio. Test con fixture; verifica live della UI necessaria.

### Scrivania fatture e garanzie

Riepilogo dinamico delle ipotesi della sessione: differenze assolute note, documenti non confrontabili, utilizzo MEPSu e date nei sette giorni successivi (inclusa la data di riferimento). Controllo separato delle due partite DS, presenza documento e data emissione modificabili, date di pagamento indicative sincronizzate con i documenti presenti. Scenario su Patt con limite MEPSu invariato e incremento teorico del denominatore per rapporto ≤90%, arrotondato per eccesso al centesimo; non è una richiesta di garanzia. Calendario ordinato con giorni residui, date trascorse non equivalenti a insoluti; giorno di riferimento della demo modificabile. Prezzi ordinari con dettaglio e storico ipotetico costante esplicito. Registro filtrabile per rettifiche, allocazione GNL modificabile con gli stessi controlli di conservazione. Esportazioni, zero richieste API, dati sintetici, nessuna fattura reale, nessun pagamento o promemoria automatico. Edizioni di studio e regole di calcolo già presenti; non certificata la vigenza. Test sintetici e UI; rendering live da verificare.

### Simulazione dei rischi: scenario e confronto

Cinque preset (base, domanda +10%, offerta −10%, prezzo +10 €/MWh, combinato) e stress personalizzato. Una simulazione per scenario base o due per confronto, con seed e shock comuni; i cambiamenti agiscono sui valori centrali e sulle deviazioni relative, mentre una deviazione assoluta da residui storici resta fissa. Output con probabilità, carenza media anche condizionata, costo lordo e variazioni rispetto alla base; VaR/CVaR a 95/99% selezionabili senza ricalcolo. Istogrammi aggregati a monte (48/40 bin al massimo), zeri del costo separati, lacune e troncamenti non nascosti. Perimetro e periodo espliciti, risultati della sessione identificati da fonte/previsione/preset, export completo JSON. Nessun aumento chiamate API, nessuna dipendenza aggiunta; rischio ipotetico a un solo periodo, non previsione ufficiale né settlement. Il modello probabilistico sottostante resta invariato. Verifica CI e visuale del deployment.

### Norme e documenti: ricerca e RAG isolati

La vista non mostra più il registro statico dei rilievi. Indicizza esclusivamente PDF caricati nella sessione o predisposti sul server; ricerca lessicale TF-IDF e frase esatta, pagina PDF originale, confronto di passaggi tra due documenti, raccolta riferimenti con hash ed export JSON. Nessun OCR, verifica vigenza o diff normativo automatico. Il registro storico resta nei calcoli/agente normativo preesistenti, separato dalla nuova vista. I PDF caricati nel nuovo archivio non alimentano l'agente di mercato né lo storico SQLite. Indice nella sessione, non cache globale; massimo 8 PDF, 24 MB/file, 64 MB/2.000 pagine complessive. Chiedi all’AI: usa il modello selezionato e la quota esistente; un solo tentativo, massimo sei estratti da 1.400 caratteri, nessun nome/hash/file intero inviato. Consenso esplicito per provider remoti e solo documenti pubblici/autorizzati. Le citazioni letterali devono essere contenute negli estratti; questo non certifica la correttezza semantica della risposta. Se nessun riscontro, nessuna chiamata; fallback alla ricerca. Su Streamlit Cloud l'elaborazione avviene sul server, non sul computer del visitatore; Ollama locale richiede un ambiente in cui il modello sia raggiungibile dal server. Non usare dati riservati su un deployment pubblico. Nessun nuovo servizio o dipendenza. Verifica live Groq necessaria.

### Assistente AI: workspace conversazionale

Chat con una domanda autonoma alla volta, scorciatoie Consumi/Previsioni/Stress +10% e bollettino completo. Scorciatoie e bollettino eseguono il piano deterministico e, con AI attiva, al massimo una chiamata di sintesi; le domande libere mantengono routing/review/sintesi e quota condivisa esistenti. Risposta e dati prima dei dettagli, modalità effettiva, periodo/fonte, rilievi, citazioni, traccia e download. Le ultime 12 analisi dell’assistente e le prese in carico rimangono nella sessione; non vengono scritte nello storico SQLite condiviso né si leggono report di altri visitatori. Lo storico precedente nel database non viene cancellato, e il bollettino della panoramica mantiene il comportamento precedente. Le singole richieste non hanno memoria conversazionale, non effettuano ricerca web e possono usare solo strumenti analitici disponibili. Per i PDF della sessione usa il RAG in Norme e documenti; eventuali riscontri normativi del supervisore restano edizioni di studio predisposte. Nessuna nuova dipendenza o costo obbligatorio. Test di isolamento dello storico e percorso a una sola chiamata, verifica visuale/autenticata sul deployment ancora necessaria.

### Archivio documentale durante la navigazione

I PDF caricati sono conservati in un manifest di sessione indipendente dal file_uploader. I nuovi caricamenti vengono aggiunti, non sostituiscono l’archivio, e sono deduplicati per SHA-256. I PDF validi restano anche in caso di caricamenti invalidi; i documenti originali sono visibili in una lista con download e rimozione esplicita. L’indice RAG è riusato fino a una modifica effettiva della raccolta; riferimenti salvati relativi alle edizioni ancora presenti vengono mantenuti, mentre risultati di ricerca/RAG obsoleti vengono invalidati. I file predisposti sul server sono distinti e non eliminabili dalla UI. Sessione privata, nessuna scrittura di PDF nello storico condiviso o su GitHub. Una nuova sessione, perdita della connessione o riavvio Streamlit può azzerare gli upload: non è ancora uno storage permanente autenticato. Test di regressione con uploader simulato e navigazione tra due viste; verificare anche caricamento e navigazione reali sul deployment.

### ENTSOG: copertura recente parziale

La finestra mensile più recente può conservare valori giorno-settore ricevuti e validati anche con totale API discordante e pagina non satura. Le finestre storiche mantengono la validazione precedente. I tre aggregati sono richiesti per il totale giornaliero: dati assenti, nulli e conflittuali non vengono trasformati in zero. Copertura esplicita e avvertenza sulle revisioni, nessuna fonte sintetica sostitutiva. La previsione espone la distanza dall’ultima osservazione valida; un dato vecchio non è etichettato come previsione aggiornata. Il confronto settimanale termina alla data osservata. Test 48/51 con 16 giorni completi e uno mancante, più conflitti e conteggi incoerenti. Il caso reale richiede verifica dopo refresh sul deployment.


### Archivio pubblico persistente (Supabase Storage)

Questa configurazione sostituisce il precedente archivio di sessione. I documenti
pubblicati restano in Storage anche dopo la chiusura del browser, una nuova
sessione o il redeploy Streamlit. Non si usa il disco effimero dell'app.
Il bucket è pubblico: ogni PDF è accessibile anche fuori da I.G.O.R. tramite URL.
Solo pubblicazione autorizzata, nessun documento aziendale riservato.

1. Scegli un progetto Supabase (preferibilmente dedicato a I.G.O.R.; verifica
   costi e quote). Storage > New bucket: gasops-documents, Public bucket,
   file size limit 24 MB, allowed MIME type application/pdf.
2. In Authentication > Users aggiungi un utente amministratore con email e
   password forte, conferma email, copia il suo UUID. Non abilitare signup
   pubblico solo per questo archivio. Non riutilizzare credenziali personali.
3. Nel SQL Editor esegui docs/gasops_document_storage_policies.sql dopo aver
   sostituito entrambi gli UUID di esempio con quello dell'amministratore.
   Verifica che non esistano policy generiche di scrittura applicabili al bucket.
   Non usare service_role; i visitatori leggono con la publishable key e le
   scritture richiedono il JWT dell'utente autorizzato dalla RLS.
4. In Streamlit Cloud > Manage app > Settings > Secrets aggiungi:

       GASOPS_DOCUMENTS_URL = "https://PROJECT_REF.supabase.co"
       GASOPS_DOCUMENTS_KEY = "sb_publishable_..."
       GASOPS_DOCUMENTS_ADMIN_ID = "UUID-amministratore"

   Conserva tutti i Secret già presenti. Non inserire chiavi private nel repo.
5. Norme e documenti > Gestisci archivio > Accedi, seleziona PDF, conferma
   pubblicazione. Apri la pagina in incognito e verifica anche dopo un reboot.
   Per rimuovere usa la gestione amministratore. Eventuali cache del provider
   possono conservare copie pubblicate per un periodo limitato.

8 documenti, 24 MiB per file, 64 MiB e 2.000 pagine complessive per l'indice.
I limiti aggregati sono controlli applicativi, non quote atomiche del bucket;
usa la gestione I.G.O.R. da un amministratore alla volta. I file nel bucket
devono essere PDF nella radice. Le aggiunte sono validate e deduplicate per
SHA-256, senza sovrascrivere versioni. Pubblicazione multipla non atomica:
in caso d'errore controllare i documenti già salvati. Cache pubblica di lettura
30 secondi e aggiornamento immediato dopo modifiche nello stesso processo.
Le sessioni admin scadono e richiedono nuovo accesso. Domande e segnalibri
rimangono privati alla sessione. Senza configurazione, solo PDF predisposti nel
repository/server; i visitatori possono caricare PDF nel loro spazio di sessione, senza pubblicarli. Gli upload
effimeri di versioni precedenti non sono recuperabili dopo la scadenza della
sessione: ricaricare i PDF originali. Nessun progetto/bucket configurato
automaticamente dall'app. Verificare RLS e persistenza sul deployment.

### Archivio pubblico senza Supabase (prototipo)

Per il demo pubblico, i documenti autorizzati possono essere pubblicati in `data/public-regulatory/` del repository. Questa cartella è deliberatamente separata da `data/regulatory/`, che rimane ignorata da Git. Da [GitHub](https://github.com/Artisello/GasOps/tree/main/data/public-regulatory) scegli Add file > Upload files; committa (o apri una PR se il ramo è protetto). Dopo il deployment, il programma legge i PDF direttamente dal repository distribuito. Non vengono inviati file all'esterno per la ricerca; l'uso del RAG remoto segue le regole di consenso già presenti. Non pubblicare dati riservati: i file rimangono anche nella cronologia Git. Limiti invariati: 8 documenti, 24 MiB per file, 64 MiB e 2.000 pagine complessive. La pubblicazione permanente direttamente dall'app richiede Supabase; il caricamento personale è sempre disponibile. L'override GASOPS_PDF_DIR per il workspace documentale rimane disponibile e prevale sulla cartella pubblica; eventuali PDF locali preesistenti non vengono pubblicati automaticamente.

### Caricamento PDF senza accesso GitHub

Ogni visitatore può aprire Norme e documenti > Carica PDF > Aggiungi ai miei PDF. L'indice personale (ricerca, confronto, lettura e RAG) è isolato per sessione, con i limiti già esistenti. Non usa cache globale, disco, repository o Storage. I documenti restano durante la navigazione ma NON dopo refresh, chiusura o riavvio. Archivio pubblico e I miei PDF sono due indici distinti. Non caricare documenti riservati su un deployment pubblico. La pubblicazione permanente richiede il backend Supabase già previsto (vedi sopra). Per consentire a un visitatore di pubblicare senza accesso GitHub, crea per lui un account Supabase Auth, copia UUID, aggiungilo a `GASOPS_DOCUMENTS_CONTRIBUTOR_IDS` (lista di UUID separati da virgole nei Secrets Streamlit) e applica `docs/gasops_document_contributors.sql` con quei medesimi UUID. L'utente accede con email/password in Pubblica nell’archivio condiviso; deve confermare che i PDF sono pubblicabili. I contributor non possono rimuovere o sovrascrivere PDF condivisi; solo l'admin può rimuovere. Le policy agiscono sul bucket anche fuori dall'app: i limiti aggregati restano applicativi, riservare gli account a persone fidate. Revocare l'UUID anche nella policy quando necessario. Non usare signup pubblico o service_role. Nessuna configurazione Supabase è necessaria per la modalità personale; non sono state apportate modifiche ad alcun progetto Supabase.

### Panoramica: quadro mercato e forniture

Tre indicatori principali (ultimo consumo/prelievo, variazione confrontabile, prima stima con data), grafico e composizione riferiti alla fonte selezionata, controlli qualità a lato e avvisi su dati non recenti visibili. Il grafico separa le stime dall'ultima osservazione valida anche con lacune finali, senza riempirle. Quadro indipendente Italia: prezzo ARERA CMEM,m, stoccaggi AGSI+ e send-out ALSI, con periodo proprio, attribuzione e avvisi; riusa il prezzo della serie mensile e gli snapshot GIE Italia già consultati nella sessione; nuove acquisizioni solo premendo Aggiorna indicatori, con cache esistenti e 60 secondi di cooldown di sessione. Se la fonte fallisce il valore resta assente, senza dati di esempio. Quadro supplementare non mostrato per JRC e simulazione. Il bollettino è separato sotto i dati, non parte in automatico. Nessuna nuova dipendenza o API a pagamento; verifica dei dati autenticati e visuale necessaria.

### Sentinella e Revisore

Sentinella: controlli locali alla visualizzazione della Panoramica, copertura recenti periodi, rilievi esistenti, stale/cache, variazione assoluta >=15% come segnale esplorativo (non soglia ufficiale), disponibilità della previsione e del suo intervallo. Nessuna sorveglianza in background. Revisore: Norme e documenti > Revisore, selezionare due documenti o il medesimo documento, tema e consenso se remoto. Ricerca TF-IDF fino a tre estratti per lato, una chiamata al modello con limite di quota esistente, fino a due ipotesi con doppia citazione distinta verificata letteralmente, suggerimento di verifica umana, export JSON con impronte SHA-256. Gli estratti non sono un audit completo né prova di correttezza giuridica. Nessuna modifica ai PDF o alle posizioni operative. Nessun dato riservato sul demo pubblico. I documenti personali e i risultati della revisione restano nella sessione; nessun invio implicito.

### Registro dei rilievi documentali

Dal Revisore aggiungi le ipotesi al Registro rilievi; consulta la pagina originale, assegna uno stato (Da verificare, In revisione, Da approfondire, Archiviato) e registra una motivazione. Dossier Markdown e JSON comprendono citazioni, hash delle edizioni PDF, modello e storico decisioni. Le ipotesi identiche non vengono duplicate o sovrascritte; i rilievi legati a PDF rimossi o cambiati sono eliminati dall'indice della sessione. Registro separato per archivio pubblico/personale e per visitatore, non persistente al refresh/riavvio, massimo 40 rilievi e 20 annotazioni per rilievo. Esportare prima di rimuovere documenti o chiudere la sessione. Le decisioni sono annotazioni umane e non certificazioni. Nessuna chiamata AI aggiuntiva o scrittura su storage.

### Balancing & Settlement – Daily Desk

Bilanciamento > Controllo giornaliero: demo sintetica oppure CSV normalizzato in sessione (modello scaricabile), schema esplicito MWh e €/MWh, fino a 10.000 righe/2 MiB, no identificativi reali o documenti riservati. Per utente e mese: ultimo stato per giorno gas, lacune, prezzi mancanti/negativi/invertiti, regressione fase e variazione stoccaggio; subtotal dei soli giorni definitivi senza eccezioni, separando addebiti e crediti. Rettifiche ultimo provvisorio → ultimo definitivo con bridge quantità a prezzi precedenti per il segno finale e prezzo residuo, mancante se controfattuale non valorizzabile. Nessuna fatturazione ufficiale, nessuna importazione automatica Jarvis/GME, nessuna equivalenza fra dati contabili e fisici. Nessun invio a LLM o persistenza. Link fonti pubbliche ufficiali; normalizzazione e diritto d'uso a carico dell'operatore.

Stato sistema: condivisione nella sessione del CSV Jarvis normalizzato tra Stoccaggi e forniture e Bilanciamento, ultimo snapshot per giorno gas, differenze tra le due ultime pubblicazioni, trend SAS separato da prelievi/linepack, avviso storico o ultimo snapshot importato oltre 3 ore (soglia informativa). Nessun download automatico né sostituzione con dati sintetici in questa vista.

### Interfaccia essenziale
Le pagine mostrano prioritariamente perimetro, dati, unità, periodo, azioni e anomalie. Le spiegazioni e le ipotesi sono consultabili dai pulsanti informativi (i), dai dettagli delle fonti e dalle sezioni di metodo. Le avvertenze relative a simulazioni, dati non aggiornati, riservatezza e autorizzazioni restano visibili. Il selettore del modello previsionale e le informazioni sulla fonte sono raccolti in Modello e fonte. Nessun cambiamento alle formule, ai provider, alla persistenza o ai controlli.

### KPI operativi BSO

Menu Operazioni > KPI operativi. Priorità all’agenda: puntualità = attività chiuse entro la scadenza / attività del mese con termine trascorso; include ritardi ancora aperti nel denominatore. Backlog include mesi precedenti, orizzonti 24h e 7 giorni sono sovrapposti. Demo a data fissa 18/11/2026, oppure importazione CSV con ID fittizio, area e timestamp ISO 8601 con offset; date senza ora scadono a fine giornata locale, un completamento senza ora non certifica l’orario. Target modificabile (di studio, non ufficiale). Esportazione e cancellazione, sessione soltanto. Calendario Snam separato: comunicazioni pubbliche del 06/10 e 23/10/2026, verificate il 18/11/2026, non prova di avvenuto adempimento né aggiornamento live. Fonte: https://www.snam.it/it/apis/news-commerciale.html . Balancing: media/picco del valore assoluto del SAS atteso, ultima pubblicazione importata per giorno gas concluso, copertura e fascia facoltativa. Settlement: copertura dei definitivi utilizzabili, eccezioni e rettifiche sul registro bilanci esistente. La copertura non misura la puntualità dei bilanci senza timestamp di rilascio. Dati di esempio distinti dai CSV importati, nessun accesso ai sistemi aziendali, nessun invio AI, nessun monitoraggio automatico o notifica. I KPI sono proposte da validare con il team.

## Centro operativo BSO

KPI operativi → Centro operativo: controlli deterministici, coda di revisione umana e passaggio di consegne in JSON. [Perimetro operativo e limiti](docs/AGENTIC_OPERATIONS.md).

## Compliance operativa

Norme e documenti → Compliance: collegamenti a evidenze letterali dei PDF pubblici, versione SHA-256, pagina, valutazione di pertinenza e tracciabilità dei rilievi BSO. [Perimetro e limiti](docs/REGULATORY_COMPLIANCE.md).

## Analista dati integrato

Assistente AI → Analista dati: confronta serie pubbliche caricate, statistiche, correlazioni, benchmark e backtest con risposta AI opzionale. [Metodo e limiti](docs/DATA_ANALYST.md).

### Pianificazione analitica AI

Assistente AI → Analista dati → Automatica (AI): il modello seleziona fonti, date e strumenti tra quelli consentiti; Python verifica il piano, calcola le evidenze e le rende consultabili. [Metodo e limiti](docs/AUTONOMOUS_ANALYST.md).

### Forecasting bayesiano multi-fonte

Laboratorio previsionale: regressione bayesiana con covariate storiche. Forecasting Snam: correzione bayesiana dei residui e gruppi di vintage Terna/ENTSOG su campioni comuni. [Metodo e limiti](docs/BAYESIAN_MULTISOURCE.md).

### Sessioni di aggiustamento

Bilanciamento → Controllo giornaliero: archivio economico separato per sessioni annuali e pluriennali, otto componenti, controlli delle differenze. [Metodo e limiti](docs/ADJUSTMENT_ENGINE.md).
