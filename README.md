# GasOps AI

Strumento indipendente in sola lettura per analizzare il mercato italiano del gas. La dashboard Streamlit include panoramica, previsioni, simulazioni di bilanciamento e regolazione, ricerca normativa e un centro operativo per sei agenti.

## Avvio locale

Da questa cartella usa Python 3.12 o successivo.

```sh
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

La panoramica parte dal bilancio mensile italiano. **Avvia analisi di mercato AI** esegue i controlli qualità, le previsioni, la ricerca documentale e le simulazioni con verifica dei risultati. L’analisi funziona anche senza un modello linguistico. La [guida di tre minuti](DEMO.md) mostra anche le opzioni offline. Esegui i test con `python -m pytest -q`.

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

Gli agenti eseguono calcoli deterministici e salvano fonti, storico e revisioni in SQLite sotto `.gasops/`. `GASOPS_STATE_DIR` permette di cambiare la cartella. Il **Centro operativo AI** esporta JSON e Markdown.

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

ALSI: 90 giorni IT/UE, inventario in 10³ m³ LNG e send-out in GWh/d; rapporto send-out/riferimento dichiarato (non capacità disponibile). Formati inventory scalare (manuale v007) e nested lng/gwh supportati senza conversione presunta. Cache 24 ore. IIP: messaggi attivi richiesti da oggi ai prossimi sette giorni, max 100 messaggi e prima pagina, cache 2 ore. In caso di paginazione l’elenco è esplicitamente parziale. Mostra i messaggi originali senza inferire unità, revisioni o calcolare capacità persa. Nessuna automazione o nuova dipendenza. Schema IIP autenticato e risposte live ancora da verificare; filtri IIP basati sul wrapper pubblico gie_getumm (https://rdrr.io/cran/gie/src/R/gie_getumm.R). Nessuna chiamata all’avvio. [Manuale AGSI/ALSI](https://www.gie.eu/transparency-platform/GIE_API_documentation_v007.pdf).
