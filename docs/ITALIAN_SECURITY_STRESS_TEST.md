# Italian Security of Supply Stress Test

**Bilanciamento → Scenario di mercato → Stress Test Italia** estende `finance.scenario`, lo stesso ingresso del calcolo deterministico precedente. `SecurityScenarioCase`, `StressDatum` e `SecurityStress` aggiungono componenti e provenienza. Il simulatore aggregato e il Monte Carlo di `risk.py` restano disponibili. Dalle schede degli ingressi della mappa si apre lo stesso Stress Test, punto e giorno gas.

## Confini e classificazioni

È un modello statico di disponibilità e domanda, **non un digital twin idraulico**. Non calcola pressione, instradamento, congestioni, risposta del linepack, probabilità dell’evento o sicurezza ufficiale. In assenza di relazioni topologiche operative documentate mostra **Impatto topologico non determinabile**, senza attribuire effetti ad altri impianti.

- **OBSERVED**: quantità pubblicate validate, con identità e timestamp.
- **FORECAST**: previsione compatibile già disponibile e selezionata, o stima pubblicata identificata come tale. Non viene generata una nuova previsione.
- **ASSUMPTION**: ipotesi e valori inseriti dall’utente; tutte le quantità della Demo sintetica appartengono a questa classe.
- **MODEL OUTPUT**: risultati calcolati, comprese somme di osservazioni. Le somme dei settori SRG o dei punti LNG/export mantengono derivazione e ID delle evidenze.

Il contesto iniziale legge esclusivamente copie pubbliche incluse, store/cache e dati pubblici in sessione. Nessun fetch al cambio filtro. Input assenti non sono sostituiti da fixture, giorni precedenti o registri individuali. La **Demo esplicita** richiede una selezione dedicata e non alimenta il contesto pubblico. Anche il vecchio simulatore aggregato ora richiede una scelta esplicita prima di usare fixture.

## Componenti e formule

`offerta = Σ ingressi di frontiera verificati + LNG + prelievo storage + produzione`

`fabbisogno = domanda domestica del perimetro dichiarato + esportazioni + iniezione storage`

`surplus/deficit teorico = offerta − fabbisogno`

ALSI Italia e somma dei terminali ENTSOG sono alternative già risolte da `system_status`, mai sommate. I consumi settoriali SRG non sono domanda nazionale certificata. Produzione giornaliera, esportazioni e altre componenti senza dati compatibili restano assenti. Giacenza storage, aggregati di immissioni e dati mensili non sono aggiunti ai flussi giornalieri. Linepack e risposta dinamica sono esclusi: il risultato non è un bilancio fisico o regolatorio riconciliato.

Demand shock: +5%, +10%, +20% o valore personalizzato. Il freddo usa una deviazione ipotetica sotto la base e una sensibilità dichiarata, senza introdurre una previsione meteo:

`domanda stress = domanda base × (1 + shock%/100) × (1 + scarto°C × sensibilità%/°C /100)`

Gli effetti sono moltiplicativi, fino a +300% complessivo. Esportazioni e iniezioni restano fisse. `LNG stress = LNG base × (1 − riduzione%/100)`. `Storage utilizzato = min(prelievo base, limite esplicito)`: il limite non crea una portata disponibile e non avvia redispatch.

La perdita del punto azzera la disponibilità del suo flusso noto e prevale sulla riduzione capacità, senza doppia sottrazione. Il taglio della Firm Technical Capacity applica `min(flusso base, capacità tecnica × (1 − riduzione%/100))`: nessun taglio del flusso quando esso è sotto il nuovo tetto. La riduzione richiede capacità compatibile; l’outage richiede il flusso. Il tetto è assunto nello stress, non è una misura di erogabilità fisica.

Il margine tecnico comparabile è `max(capacità tecnica − flusso, 0)`, per lo stesso punto, direzione e periodo. È distinto dalla Firm Available Capacity pubblicata, conservata come input con la sua classificazione. Non dimostra che il gas sia acquistabile o trasportabile altrove.

`storage richiesto = max(fabbisogno stress − offerta stress escluso storage, 0)`

L’ulteriore requisito è la parte che supera il prelievo storage usato nello scenario. Non è garantito da una giacenza o capacità non osservata. Ogni formula richiede tutte le sue componenti; mancanze e conflitti non diventano zero.

## Copertura e interfaccia

L’adattatore in `italian_network.py` riusa binding, merge/version handling e validazione della mappa. I driver riusano `system_status`; le letture locali riusano `gas_data.source_context` e la proiezione GIE esistente. Una risposta API parziale non invalida una misura puntuale completa: il flag di risposta e la copertura del singolo input restano distinti. Conflitti, periodi incompatibili e componenti incomplete sono trattenuti; la qualità stale è preservata.

La copertura conta le componenti del modello, **non una quota del gas nazionale**. Totali incompleti restano non calcolabili; i contributi noti sono esplicitamente parziali. Baseline e Stress Scenario mostrano unità, differenze e ipotesi. Fonti e input mantengono periodi, classificazioni, pubblicazione, acquisizione, qualità ed evidenze.

La mappa usa lo stesso rendering PyDeck offline. Il simbolo dedicato **ASSUMPTION** distingue lo stress ipotetico dagli eventi pubblicati; selezione da mappa ed elenco sono sincronizzate. Nessun altro gasdotto viene marcato congestionato. Restano visibili i limiti delle geografie storiche e le attribuzioni. Il calendario 06:00–06:00 Europe/Rome conserva giorni DST da 23/25 ore; le portate GWh/d non sono riscalate per 24 o per la durata del giorno.

## Riproducibilità e test

Il JSON contiene `schema_version`, `model_version`, `gas_day`, input validati e hash, `source_references`, `assumptions`, `units`, `calculation_parameters` e risultato. Il clock di riferimento fa parte degli input; non vengono aggiunti timestamp casuali di esecuzione. Decimal usa precisione 28. Stessi input, ipotesi e versione producono risultati e JSON ordinato identici.

L’export usa un elenco esplicito di campi, senza serializzare sessione, credenziali, file o registri privati. Le URL pubbliche ammesse sono prive di userinfo, query e fragment. Per riprodurre il calcolo verificare `schema_version == 1` e `model_version == finance.SECURITY_MODEL`, ricostruire `SecurityScenarioCase` da `inputs` e `SecurityStress` da `assumptions`, quindi chiamare `finance.scenario`. Nessun provider, geocoder o tile server è necessario.

I test coprono conservazione, combinazioni, soglie capacità, input mancanti/parziali, unità, non negatività, duplicati e conflitti, clock/DST, riproducibilità e assenza di credenziali nell’export. AppTest vieta HTTP e verifica Demo esplicita, isolamento dal portafoglio, controlli, ipotesi per giorno, export e navigazione Demo/Workbench. Restano attivi i test del simulatore aggregato, rischio, settlement e mappa esistenti.
