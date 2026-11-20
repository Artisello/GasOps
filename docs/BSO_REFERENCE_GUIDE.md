# Guida operativa dalle edizioni Snam allegate

La scrivania e le guide delle viste usano definizioni sintetiche ricavate dai quattro PDF forniti. Il catalogo `bso_reference.py` conserva documento, sezione, pagina PDF e impronta SHA-256 dell’edizione. Le pagine sono quelle del file, non il numero interno del capitolo.

| Informazione utile | Riferimento verificato | Uso nell’app |
| --- | --- | --- |
| Allocazione e programma giornaliero | Glossario XCII, PDF pp. 1 e 6 | Distinguere quantità attribuite e programmi |
| SAS e pubblicazioni di sistema | CdR XCII, cap. 9 §1.1, PDF p. 362 | Leggere giorno gas e istante di pubblicazione |
| Equazione del partecipante e termine T netto | CdR XCII, cap. 9 §3.1.2, PDF pp. 370–372 | Compilare il CSV con lo stesso perimetro e tutte le componenti |
| Prezzo applicabile al DS | CdR XCII, cap. 9 §4.4.2, PDF p. 394 | Distinguere acquisto/vendita e prezzi di sbilanciamento/PSV |
| Segni dello stoccaggio e nominato = allocato | CdR XCII, PDF pp. 369 e 371; CdStocc HS1 2026-I, PDF p. 181 | Evitare l’inversione del flusso tra trasporto e HS1 e rettifiche improprie del termine S |
| Giorno gas in ora solare per HS1 | CdStocc HS1 2026-I, glossario, PDF p. 5 | Mantenere il termine UTC+01 separato dal calendario Europe/Rome del trasporto |
| Scostamenti netti GNL e riparto proporzionale | CdRig Piombino 2023-I, cap. 9 §3.2.1, PDF p. 96 | Identificare gli input della simulazione già esistente |
| Utente GNL debitore/creditore | CdRig Piombino 2023-I, glossario, PDF p. 8 | Distinguere la disponibilità di GNL dal segno economico del settlement |

Sono indicazioni di lettura delle edizioni fornite, con applicabilità e aggiornamenti da verificare. Non costituiscono un nuovo motore di regole. I calcoli restano quelli delle viste esistenti; le nuove istruzioni spiegano unità, segni, perimetri e dati mancanti. Gli identificatori di edizione di HS1 e del glossario sono riconosciuti dall’archivio documentale anche se il file viene rinominato.
