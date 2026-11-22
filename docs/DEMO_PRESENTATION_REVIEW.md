# Verifica della navigazione completa · 21 novembre 2026

## Copertura

- Sidebar nativa con undici collegamenti e indicazione della pagina corrente. Tutte le nove aree originali sono disponibili anche nella configurazione predefinita; si aggiungono Fonti e API ed Esempi BSO.
- La panoramica conserva il layout essenziale. Le funzioni complete restano raggiungibili: AI e analista dati, Security of Supply, mercato, previsioni, rischio, controlli commerciali, PDF, KPI e monitoraggio.
- I test navigano tutte le undici pagine utilizzando gli hash dei collegamenti nativi effettivamente renderizzati. Verificano inoltre un percorso di dipendenze dal programma a ogni modulo di pagina.
- Casi predisposti per bilanciamento, KPI, rischi e ricerca PDF; analisi pubblica JRC pronta nell’assistente. I registri già importati non vengono sostituiti.

## Fonti e API

Il coordinatore usa i connettori esistenti per tutti i servizi disponibili. GIE comprende AGSI+, ALSI e IIP; Terna comprende consuntivi, previsioni e contesto; modello AI e archivio documentale hanno verifiche dedicate. Le richieste mantengono timeout, limiti, quote e ultimo risultato valido. La lettura dell’archivio non pubblica o modifica documenti.

Verifica live locale dei connettori pubblici: Eurostat/ARERA acquisito; ACER acquisito; Open-Meteo acquisito. ENTSOG restituisce dati con avviso di copertura/metadati, conservato come “Da verificare”. GIE, Terna, modello AI e archivio remoto non hanno credenziali configurate nell’ambiente locale: il loro accesso effettivo va verificato sul deployment che le possiede. I test con fixture controllano che ogni adattatore configurato venga chiamato, che un errore non blocchi gli altri e che i risultati precedenti restino disponibili.

La configurazione è distinta dalla verifica riuscita. Nessuna sostituzione implicita di una fonte pubblica con dati sintetici. Le chiavi non compaiono nei risultati o nello stato UI. Gli invii del modello predisposto comprendono soltanto il quesito e le evidenze pubbliche JRC, mai PDF o registri personali.

## Verifiche

535 test pytest superati; otto controlli readiness offline superati e dipendenze coerenti (`pip check`). Verificate nel browser tutte le undici destinazioni, il caso di ricerca nei tre PDF pubblici, il calcolo dei rischi già pronto e il report locale dell’assistente. Layout a 375/768/1024/1440 px senza overflow della pagina nelle viste controllate; menu mobile apribile e navigabile, sidebar desktop e focus da tastiera visibile. Sono verifiche del prototipo; non attestano accettazione operativa Snam, accessibilità certificata o benefici economici.
