"""Plain-language reading aids grounded in the supplied Snam study editions.

The catalogue contains paraphrases and page references, never executable rules.
PDF identities are content hashes; no local attachment path is shipped.
"""
from dataclasses import dataclass

import streamlit as st

from .regulatory import NETWORK, PIOMBINO

STORAGE = "CdStocc_HS1_Rev2026-I.pdf"
GLOSSARY = "Glossario_RevXCII.pdf"
SOURCES = {
    NETWORK: ("Codice di Rete · XCII", "6f2b88ed6de5f85a5603cbf5f3c1e32f18341bd26338177dc918921458d5d965", 649),
    PIOMBINO: ("CdRig Piombino · 2023-I", "5d9545eb7928be4b1dcc41dde38bb7adb1377db9443e88cc359b8c6b929edd7e", 175),
    STORAGE: ("CdStocc HS1 · 2026-I", "66a1bbd9b206ce1c6f6d54e67fb55a54bc98a45afab2da4f4f676905ee3964c1", 284),
    GLOSSARY: ("Glossario del Codice di Rete · XCII", "c75f99d120fdcbf610196426ca9cfb792fc7053ed2bb4a627e14983fbcaa4471", 9),
}


@dataclass(frozen=True)
class Term:
    title: str
    meaning: str
    application: str
    references: tuple[tuple[str, str, int], ...]


TERMS = {
    "allocation": Term("Allocazione: a chi viene attribuito il gas",
        "È l’attribuzione contabile agli utenti del gas misurato in entrata o in uscita dalla rete.",
        "Usa quantità attribuite allo stesso partecipante, giorno gas e versione. Il totale della rete non sostituisce il bilancio dell’utente.",
        ((GLOSSARY, "Glossario · Allocazione", 1),)),
    "nomination": Term("Nomina: il programma giornaliero",
        "È il programma comunicato dall’utente per le quantità da immettere e prelevare nel giorno gas.",
        "Distingui il programma dalle misure e dalle allocazioni; confronta dati con lo stesso perimetro.",
        ((GLOSSARY, "Glossario · Programma giornaliero o prenotazione", 6),)),
    "sas": Term("SAS: una stima del sistema",
        "È la stima dello sbilanciamento atteso dell’intero sistema al termine del giorno gas. Le pubblicazioni includono anche linepack e prelievi attesi.",
        "Controlla giorno gas e ora di pubblicazione. Non usare il SAS come saldo o importo del singolo partecipante.",
        ((NETWORK, "Cap. 9 §1.1", 362),)),
    "balance": Term("DS: il saldo del partecipante",
        "Il bilancio dell’utente confronta immissioni, stoccaggio e transazioni nette con i prelievi: DS = I + S + T netto − P.",
        "Compila tutte le componenti in MWh per lo stesso giorno gas. Un dato mancante non equivale a zero.",
        ((NETWORK, "Cap. 9 §3.1.2", 370),)),
    "prices": Term("Prezzi di sbilanciamento: acquisto e vendita",
        "Per DS negativo il codice applica il prezzo di acquisto; per DS positivo riconosce il prezzo di vendita.",
        "Importa i prezzi di sbilanciamento del giorno gas in €/MWh. Il prezzo PSV non li sostituisce. Il segno del flusso economico va letto anche alla luce di eventuali prezzi negativi.",
        ((NETWORK, "Cap. 9 §4.4.2", 394),)),
    "storage": Term("Stoccaggio: attenzione al verso del segno",
        "Nel trasporto il gas erogato dallo stoccaggio è positivo e quello iniettato è negativo. Nel flusso F del bilancio HS1 l’iniezione è positiva e l’erogazione negativa.",
        "Verifica il perimetro del file prima dell’import. Nel bilancio dell’utente di trasporto, S è il termine programmato comunicato dallo stoccaggio e non va rettificato come un normale prelievo.",
        ((NETWORK, "Cap. 9 §3.1.1 · segno del termine S", 369),
         (NETWORK, "Cap. 9 §3.1.2 · termine Sk", 371),
         (STORAGE, "Cap. 7 §3.1 · flusso F", 181))),
    "transactions": Term("T netto: tutte le componenti del bilancio",
        "Il termine T netto raccoglie il saldo delle transazioni previsto dal Codice di Rete; il segno positivo indica acquisto di gas.",
        "Nel CSV I.G.O.R. il campo psv_net_mwh rappresenta questo saldo completo. Non limitarlo alle sole transazioni bilaterali al PSV se la fonte include altre componenti.",
        ((NETWORK, "Cap. 9 §3.1.2 · transazioni nette", 372),)),
    "gas_day": Term("Giorno gas: controlla la convenzione oraria",
        "Il glossario di rete descrive l’intervallo dalle 06:00 alle 06:00 successive. Per HS1 il documento specifica sempre l’ora solare.",
        "I controlli di trasporto I.G.O.R. usano Europe/Rome; HS1 usa UTC+01 tutto l’anno. Non allineare i file dalla sola data: verifica gli estremi UTC, soprattutto in estate e nei cambi d’ora.",
        ((GLOSSARY, "Glossario · Giorno-gas", 4),
         (STORAGE, "Glossario · Giorno Gas", 5))),
    "lng": Term("GNL: ripartire uno scostamento",
        "Nell’edizione Piombino, lo scostamento in eccesso o difetto, al netto dei margini concordati, si ripartisce proporzionalmente ai quantitativi dell’ultimo programma mensile di riconsegna pertinente.",
        "Per la simulazione usa il programma aggiornato e lo scostamento già netto dei margini. Un totale programmato nullo impedisce il riparto.",
        ((PIOMBINO, "Cap. 9 §3.2.1", 96),)),
    "lng_position": Term("GNL: utente debitore e creditore",
        "Nel glossario Piombino la qualifica dipende dalla disponibilità di GNL rispetto alle riconsegne programmate del mese; il debitore include anche chi richiede liquefazione virtuale.",
        "Questa qualifica riguarda il programma GNL: non equivale al segno in euro delle carte Crediti e Addebiti del settlement.",
        ((PIOMBINO, "Glossario · Utente debitore / creditore", 8),)),
}
AREAS = {
    "home": ("allocation", "nomination", "sas", "balance", "storage", "gas_day", "lng", "lng_position"),
    "system": ("sas", "nomination", "allocation", "gas_day"),
    "settlement": ("balance", "prices", "storage", "transactions", "allocation"),
    "operations": ("nomination", "gas_day", "allocation", "lng_position"),
    "storage": ("storage", "gas_day"),
}


def render_terms(area, key):
    st.markdown("**Termini e riferimenti Snam**")
    selected = st.selectbox("Termine da chiarire", AREAS[area],
                            format_func=lambda value: TERMS[value].title, key=key)
    term = TERMS[selected]
    st.write(term.meaning)
    st.caption("In I.G.O.R. · " + term.application)
    for document, section, page in term.references:
        st.caption(f"{SOURCES[document][0]} · {section} · PDF p. {page}")
    st.caption("Edizioni allegate e verificate per questi riferimenti; applicabilità al caso e aggiornamenti da verificare.")


def template_guide():
    with st.popover("Come compilare il modello", icon=":material/help:"):
        st.markdown("**Quantità in MWh, prezzi in €/MWh.** Non inserire volumi in Smc nel campo energia.")
        st.markdown("- **injected_mwh / withdrawn_mwh**: immissioni e prelievi del partecipante.\n"
                    "- **storage_net_mwh**: erogazione in rete positiva, iniezione a stoccaggio negativa.\n"
                    "- **psv_net_mwh**: termine T netto completo; acquisti positivi e vendite negative.\n"
                    "- **buy_eur_mwh / sell_eur_mwh**: prezzi di sbilanciamento del giorno.\n"
                    "- **version / stage**: versione crescente e fase provisional o definitive.")
        st.caption("Tutte le quantità sono obbligatorie: un dato assente non va sostituito con zero. Date, partecipante e perimetro devono corrispondere.")
        st.caption("CdR XCII · cap. 9 §3.1.2, PDF pp. 370–372; §4.4.2, p. 394. Glossario XCII · PCS, p. 6.")
