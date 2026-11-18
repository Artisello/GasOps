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

## Rischio probabilistico

Apri **Rischio probabilistico** per simulare 1.000–100.000 scenari con seed riproducibile. La domanda può usare il primo periodo previsto e la deviazione standard di almeno 20 errori fuori campione a un passo; altrimenti usa volatilità manuali, esplicitamente illustrative. Offerta e prezzo sono ipotesi; per dati mensili l’offerta contabile non è capacità fisica. Shock gaussiani correlati tramite un fattore domanda comune, volumi troncati a zero; la correlazione offerta/prezzo è il prodotto delle altre due correlazioni. Mostra P5/P50/P95, probabilità di deficit, deficit atteso, VaR e CVaR/Expected Shortfall 95% e 99% del deficit e del costo lordo teorico (deficit GWh × 1000 × max(prezzo,0)). I prezzi mancanti non producono valori economici. Il CVaR usa esattamente la massa di coda empirica, inclusi i pareggi. L’intervallo Wilson misura soltanto l’errore Monte Carlo, non l’incertezza del modello. Non è una stima ufficiale di sicurezza degli approvvigionamenti, un costo netto o un settlement. Non si assume calibrazione congiunta, né traiettorie multiperiodali. L’agente di scenario include questi risultati nel JSON e nella sintesi con le ipotesi salvate, mantenendo invariati gli strumenti regolatori. L’esportazione della pagina conserva i parametri e la provenienza.
