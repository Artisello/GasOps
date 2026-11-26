# API GME

Fonte: Gestore dei Mercati Energetici S.p.A. [Manuale tecnico, §§1–5](https://gme.mercatoelettrico.org/Portals/0/Documents/it-IT/20251015Manuale_tecnico_API.pdf), [Manuale utente, §§4–5](https://gme.mercatoelettrico.org/Portals/0/Documents/it-IT/20251015Manuale_Utente_API.pdf), [condizioni API, artt. 5–6 bis](https://www.mercatoelettrico.org/Portals/0/Documents/it-IT/20261013CONDIZIONI_GENERALI_API.pdf).

## Attivazione e verifica

- Configurare `[gme]` nei Secrets Streamlit con `username`, `password` e `base_url = "https://api.mercatoelettrico.org/request"`. Le viste GME usano questa configurazione in ogni layout.
- Configurare le credenziali sul deployment autorizzato. Per l’uso personale previsto dalla licenza standard GME, il controllo degli accessi è a monte di Streamlit, WebSocket incluse.
- In **Mercato e previsioni → Mercato gas**, scegliere dataset, segmento e fino a 31 giorni conclusi. L’acquisizione avviene in background, con controllo delle quote prima di ogni richiesta dati. In assenza di configurazione la vista rimanda agli esiti ufficiali.
- Per una verifica locale, nella directory dell’app con i Secrets disponibili, usare un breve periodo storico.

~~~sh
python -m gasops_app.gme_api igi 2026-11-17 2026-11-18 --authorized-private-use
~~~

Il comando controlla autenticazione, quote e schema. Stampa il numero di record validati e il segmento. Il test con credenziali richiede un’installazione autorizzata che le abbia disponibili in locale.

## Catalogo verificato

La piattaforma è `PublicMarketResults`. Le otto richieste usano `Attributes` vuoto. Gli intervalli seguono l’esempio operativo del manuale utente con date `yyyyMMdd` in stringa. Per MPL l’intervallo riguarda la data di sessione, mentre il giorno gas è un campo distinto.

| Dataset | Segmenti | Record e misure |
| --- | --- | --- |
| `GAS_ImbalancePrice` | `GAS` | Data flusso, estremi SRG e media di remunerazione in €/MWh, volume MGAS con unità non indicata |
| `GAS_IGIndex` | `IGI` | Data flusso, prodotto, indice in €/MWh |
| `GAS_ContinuousTrading` | `MGP-GAS`, `MI-GAS`, `MT-GAS` | Data flusso, mercato, prodotto, prezzi in €/MWh, volumi negoziati e OTC separati in MW e MWh, abbinamenti, posizioni aperte con unità non indicata |
| `GAS_DemandAndSupply` | `MGP-GAS`, `MI-GAS`, `MGS-Edison`, `MGS-Stogit`, `MGS-Adriatica`, `PB-GAS`, `PBZ-Edison stoccaggi`, `PBZ-G+1`, `PBZ-G+N`, `PBZ-Import`, `PBZ-Linepack`, `PBZ-LNG`, `PBZ-PSV`, `PBZ-Reintegro Stogit`, `PBZ-Risorse PSV`, `PBZ-Stogit` | Data flusso, mercato, lato, prezzo d’offerta e d’asta, volume della curva con unità non indicata |
| `GAS_MGASAuctionResults` | `MGP-GAS`, `MI-GAS` | Data flusso, mercato e prodotto, prezzo in €/MWh, volumi in MW e MWh, acquisti e vendite SRG con unità non indicata |
| `GAS_MGSAuctionResults` | `MGS` | Data flusso, impresa, tipo, prezzo in €/MWh, operatori, volumi e interventi SRG con unità non indicata |
| `GAS_MPLAuctionResults` | `MPL` | Data sessione, giorno gas, motivo, tipo e punto, prezzo in €/MWh, operatori, volumi e abbinamenti SRG con unità non indicata |
| `GAS_PGRResults` | `PGR` | Data sessione, prezzo e volumi GSE e operatori con unità non indicata, numero assegnatari. Il manuale API indica PGR come inattivo. |

Le unità riportate derivano dai campi del manuale, dal [glossario GME](https://gme.mercatoelettrico.org/en-us/Home/Glossary) e dai [report sui mercati del gas](https://www.mercatoelettrico.org/Portals/0/Documents/en-US/20261123ReportSettimanaleGas47-2026En.pdf). I valori senza unità documentata sono visualizzati nella scala della fonte. La validazione respinge chiavi duplicate e date fuori intervallo. Le misure assenti rimangono vuote, compreso il valore testuale "null" osservato sul servizio. La tipologia MGS vuota rimane non indicata. Il decoder accetta un solo documento JSON o XML piatto in un archivio Base64 ZIP limitato, senza estrazione su disco. Gli esiti gas sono documentati come JSON.

## Utilizzo in I.G.O.R.

- Panoramica mostra IGI, prezzo medio di remunerazione ed estremi SRG per il giorno gas, con acquisizione e differenza D−1 quando confrontabile. Consumi, previsioni e report dell’assistente mostrano il contesto di mercato dello stesso giorno nella vista locale. I prodotti ambigui restano consultabili separatamente nel mercato. IGI, PSV, CMEM,m e prezzi di sbilanciamento mantengono fonti e funzioni distinte.
- Bilanciamento mostra parametri e interventi SRG indicati dalla fonte. Stoccaggi presenta gli scambi MGS accanto alle viste AGSI+ e HS1.
- Il dettaglio Settlement del bilancio definitivo importato può stimare prezzi e importi usando i parametri API dello stesso giorno e il motore esistente. Verificare il regime, il volume STSP title e la percentuale del piccolo aggiustamento applicabile. Sotto 2.000 MWh servono le 30 medie giornaliere precedenti. La stima rimane separata dal registro e dai prezzi applicati da SRG. [ARERA, aggiornamento del TIB](https://www.arera.it/fileadmin/allegati/docs/24/Testo_aggiornato.pdf) · [Codice di rete Snam](https://www.snam.it/it/i-nostri-business/trasporto/codice-di-rete-tariffe-area-comitato-e-consultazioni/codice-di-rete.html).
- Simulazione rischi calibra i percentili delle variazioni IGI giornaliere sul periodo antecedente agli ultimi sette giorni e li verifica sul periodo tenuto fuori. I buchi interrompono le variazioni D−1. Si tratta di un test retrospettivo su una copia acquisita. Lo schema non fornisce timestamp di pubblicazione o versioni storiche per una verifica point-in-time.
- Assistente AI include una consultazione locale degli indicatori acquisiti. Gli estratti GME restano fuori dai prompt, dai provider AI e dalle previsioni operative.

I risultati sono conservati solo nella sessione Streamlit. Le viste attive aggiornano automaticamente i periodi recenti ogni ora e quelli storici ogni 12 ore. Dopo un errore attendono almeno 30 minuti. L’acquisizione avviene solo con una sessione aperta, una richiesta dati alla volta per processo. Il client centralizza JWT, timeout e quota per account. Rinnova il JWT prima della scadenza, ripete una lettura transitoria delle quote al massimo una volta e sospende le richieste su HTTP 429. I contatori GME possono conservare l’ultimo valore dopo la chiusura della finestra. Il client usa gli orari restituiti dal servizio per riconoscere le finestre già concluse. Un aggiornamento fallito o una risposta vuota lasciano consultabile l’ultima copia valida con la relativa data di acquisizione.

Lo smoke test del 26 novembre 2026 ha verificato autenticazione e quote e validato estratti con record per IGI, parametri di sbilanciamento, negoziazione continua, curve, aste MGAS e MGS. Gli intervalli campione di MPL e PGR hanno restituito risposte valide senza record.
