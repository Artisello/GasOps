"""Page-level PDF evidence, lexical retrieval, and reviewed edition notes."""

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import re

import numpy as np
import pymupdf
from sklearn.feature_extraction.text import TfidfVectorizer

from .models import Citation, Finding

NETWORK = "92.Codice_di_Rete_RevXCII.pdf"
PIOMBINO = "CdRig_FSRU Piombino_Rev2023-I.pdf"
EDITIONS = {
    "6f2b88ed6de5f85a5603cbf5f3c1e32f18341bd26338177dc918921458d5d965": NETWORK,
    "5d9545eb7928be4b1dcc41dde38bb7adb1377db9443e88cc359b8c6b929edd7e": PIOMBINO,
}
MAX_PDF_BYTES = 24 * 1024 * 1024
MAX_PAGES = 800
MAX_DOCUMENTS = 8


def cite(document: str, page: int, section: str, evidence: str) -> Citation:
    return Citation(document=document, page=page, section=section, evidence=evidence)


SETTLEMENT_NOTE = cite(
    NETWORK, 394, "Cap. 9 §4.4.2",
    "Per uno sbilanciamento negativo si applica il prezzo di acquisto. Per uno positivo si usa il "
    "prezzo di vendita. Il paragrafo precedente definisce i due prezzi.",
)
BALANCING_NOTE = cite(
    NETWORK, 358, "Cap. 9 §1",
    "Il bilanciamento commerciale comprende le azioni degli utenti per allineare immissioni e "
    "prelievi, la contabilizzazione e l’allocazione del gas e i corrispettivi che incentivano l’equilibrio.",
)


@dataclass(frozen=True)
class Case:
    finding: Finding
    review: str
    search: str


REGISTER = (
    Case(Finding(
        id="notice-7", title="Preavviso di esattamente sette giorni", severity="high",
        detail="Le due tabelle passano da 8 giorni a meno di 7. Il coefficiente per sette giorni esatti "
               "resta da verificare prima di calcolare il corrispettivo.",
        category="Omissione testuale confermata",
        citations=[
            cite(PIOMBINO, 103, "Cap. 10 §1.1.1", "La tabella lato utente elenca 12, 11, 10, 9, 8 e <7 giorni."),
            cite(PIOMBINO, 104, "Cap. 10 §1.1.2", "La tabella lato operatore usa gli stessi intervalli di preavviso."),
        ],
    ), "Tabelle verificate · interpretazione aperta", "cancellazione mancata discarica preavviso sette giorni coefficiente"),
    Case(Finding(
        id="panigaglia", title="Panigaglia nel glossario di Piombino", severity="medium",
        detail="La voce Snam Rete Gas cita il collegamento con Panigaglia. Un’altra voce definisce "
               "il punto di entrata di Piombino. L’ambito del rinvio va chiarito prima di associarlo ai dati del terminale.",
        category="Ambiguità aperta",
        citations=[cite(PIOMBINO, 7, "Glossario (Glo-3)",
                        "La definizione di Snam Rete Gas cita Panigaglia nella stessa pagina della voce sul punto di entrata di Piombino.")],
    ), "Testo verificato · riferimento da chiarire", "panigaglia interconnessa terminale riferimento glossario"),
    Case(Finding(
        id="density", title="Stesso simbolo per due misure di densità", severity="medium",
        detail="Il simbolo dr indica sia la densità relativa adimensionale sia la massa volumica in kg/Sm³. "
               "Per calcolare l’indice di Wobbe occorre tenere distinte le due grandezze.",
        category="Conflitto di notazione confermato",
        citations=[
            cite(PIOMBINO, 125, "Cap. 12 §2.1", "La pagina usa dr per due quantità distinte e lo inserisce sotto radice nella formula di Wobbe."),
            cite(NETWORK, 644, "Glossario (Glo-4)", "La definizione di Wobbe rimanda alla radice quadrata della densità relativa."),
        ],
    ), "Notazione verificata · associazione da rivedere", "densità relativa massa volumica formula wobbe notation"),
    Case(Finding(
        id="references", title="Riferimenti circolari e incoerenti tra paragrafi", severity="medium",
        detail="Un rinvio circolare e un riferimento incoerente per i corrispettivi di trasporto possono portare "
               "alla tariffa sbagliata. Occorre individuare i riferimenti corretti prima di applicare le disposizioni.",
        category="Errore testuale confermato",
        citations=[
            cite(PIOMBINO, 112, "Cap. 10 §4.1", "Il §4.1 rimanda a un precedente §4.1."),
            cite(PIOMBINO, 148, "Cap. 18 §2(b)", "La fatturazione della capacità di trasporto rimanda al Cap. 10 §4.2."),
            cite(PIOMBINO, 109, "Cap. 10 §3.1", "Il §3.1 tratta i corrispettivi di trasporto. Il §4.2 riguarda scostamenti dei volumi di GNL a p. 112 del PDF."),
        ],
    ), "Rinvii verificati · riferimenti da chiarire", "riferimenti circolari precedente paragrafo fatturazione trasporto"),
    Case(Finding(
        id="tariff-units", title="Unità della tariffa di capacità da verificare", severity="medium",
        detail="La formula moltiplica una tariffa di assegnazione per una capacità giornaliera. "
               "L’unità e la base temporale della tariffa vanno verificate nella procedura applicabile.",
        category="Ambiguità aperta",
        citations=[
            cite(PIOMBINO, 103, "Cap. 10 §§1.1.1–1.1.2",
                 "Il mancato scarico usa T × α × C × Cd. La capacità Cd è giornaliera e per C si rimanda al Cap. 5."),
            cite(PIOMBINO, 108, "Cap. 10 §3", "Il corrispettivo base si applica alle quantità di GNL contrattualizzate per slot."),
        ],
    ), "Formula verificata · unità da chiarire", "tariffa unità corrispettivo capacità dimensionale assignment tariff units"),
    Case(Finding(
        id="dst-gas-day", title="Giorni gas di 23, 24 e 25 ore effettive", severity="medium",
        detail="Il glossario indica 24 ore e due estremi consecutivi alle 06:00. Con il cambio d’ora in "
               "Europe/Rome gli estremi distano 23 o 25 ore effettive. L’app calcola la durata sugli estremi UTC.",
        category="Rischio di implementazione",
        citations=[cite(NETWORK, 644, "Glossario (Glo-4)",
                        "Il giorno gas è definito come un periodo di 24 ore consecutive tra le 06:00 di due giorni di calendario.")],
    ), "Definizione e calendario verificati · modalità contabile da chiarire", "gas day giorno gas cambio ora ora legale daylight saving 23 25"),
    Case(Finding(
        id="accounting-zero", title="Dati mancanti valorizzati a zero nell’allocazione", severity="info",
        detail="Il valore contabile si applica al bilancio previsto dalla disposizione. "
               "Conviene conservare un flag per i dati assenti che identifichi l’origine dello zero.",
        category="Convenzione contabile",
        citations=[
            cite(NETWORK, 391, "Cap. 9 §4.3.4.1",
                 "Quando mancano le informazioni SII previste, al prelievo provvisorio per quel punto si attribuisce zero."),
            cite(NETWORK, 392, "Cap. 9 §4.3.4.2", "Il bilancio definitivo prevede a sua volta uno zero nel caso specificato."),
        ],
    ), "Convenzione documentata · zero contabile", "zero dati mancanti missing data allocazione bilancio provvisorio"),
    Case(Finding(
        id="zero-denominator", title="Allocazione proporzionale con totale pari a zero", severity="medium",
        detail="Il calcolo proporzionale è indefinito quando il denominatore vale zero. "
               "I passaggi citati coprono il caso con un totale positivo. Il caso limite richiede una verifica.",
        category="Rischio di implementazione",
        citations=[
            cite(NETWORK, 417, "Allegato 9/A §1.1", "L’esempio di ripartizione proporzionale ha una somma positiva dei programmi di trasporto."),
            cite(PIOMBINO, 111, "Cap. 10 §3.1", "Il corrispettivo di capacità usa Qtot come divisore per il periodo."),
        ],
    ), "Formula verificata · gestione del totale nullo da chiarire", "pro quota proportional zero denominator denominatore qt ot"),
)


@dataclass(frozen=True)
class Pdf:
    name: str
    digest: str
    data: bytes
    pages: int

    @property
    def title(self) -> str:
        return EDITIONS.get(self.digest, f"{self.name} [{self.digest[:8]}]")

    def render(self, page: int) -> bytes:
        with pymupdf.open(stream=self.data, filetype="pdf") as document:
            return document[page - 1].get_pixmap(matrix=pymupdf.Matrix(1.35, 1.35)).tobytes("png")


@dataclass(frozen=True)
class Passage:
    citation: Citation
    search: str
    is_pdf: bool = False


ALIASES = {
    r"commercial balancing|bilanciamento commerciale": "bilanciamento commerciale immissioni prelievi accounting allocation",
    r"seven days|sette giorni|\b7\s*(?:days|giorni)|cancellat|notice": "seven days preavviso mancata discarica coefficiente",
    r"imbalance|disequilibrio|settlement": "corrispettivi disequilibrio sbilanciamento buy sell",
    r"daylight|gas day|giorno.gas": "giorno gas cambio ora daylight saving 24 consecutive",
    r"density|densit": "densità relativa massa volumica Wobbe",
    r"zero denominator|denominatore": "pro quota denominatore qt proportional capacity",
    r"cross.reference|riferimenti|circular": "riferimenti circolari fatturazione precedente paragrafo",
    r"tariff|tariffa": "dimensionale corrispettivo unitario tariffa",
}


class Library:
    def __init__(self, inputs: tuple[tuple[str, bytes], ...] = ()):
        self.documents: dict[str, Pdf] = {}
        self.errors: list[str] = []
        passages = [Passage(BALANCING_NOTE, "commercial balancing bilanciamento commerciale definizione definition"),
                    Passage(SETTLEMENT_NOTE, "settlement imbalance formula buy sell disequilibrio")]
        passages.extend(Passage(c, f"{case.finding.title} {case.search}") for case in REGISTER
                        for c in case.finding.citations)

        for name, data in inputs[:MAX_DOCUMENTS]:
            name = Path(name).name
            try:
                pdf, extracted = self._extract(name, data)
            except (ValueError, RuntimeError) as error:
                self.errors.append(f"{name} · {error}")
                continue
            if pdf.title not in self.documents:
                self.documents[pdf.title] = pdf
                passages.extend(extracted)
        self.passages = passages
        self.index = TfidfVectorizer(
            ngram_range=(1, 2), strip_accents="unicode", sublinear_tf=True, max_features=45000,
            token_pattern=r"(?u)\b[\w-]{2,}\b",
        )
        self.matrix = self.index.fit_transform(
            [f"{p.search} {p.citation.evidence}" for p in passages]
        )

    @staticmethod
    def _extract(name: str, data: bytes) -> tuple[Pdf, list[Passage]]:
        if len(data) > MAX_PDF_BYTES or not data.startswith(b"%PDF-"):
            raise ValueError("Carica un PDF fino a 24 MB")
        passages: list[Passage] = []
        with pymupdf.open(stream=data, filetype="pdf") as document:
            if document.needs_pass or not 1 <= len(document) <= MAX_PAGES:
                raise ValueError("Carica un PDF senza password da 1 a 800 pagine")
            pdf = Pdf(name, sha256(data).hexdigest(), data, len(document))
            for page in document:
                text = " ".join(page.get_text(sort=True).split())
                if not text:
                    continue
                # Split by words to keep snippets readable and retain surrounding context.
                words = text.split()
                for start in range(0, len(words), 92):
                    snippet = " ".join(words[start:start + 120])
                    passages.append(Passage(
                        Citation(document=pdf.title, page=page.number + 1, evidence=snippet), "",
                        is_pdf=True,
                    ))
        if not passages:
            raise ValueError("Testo non estraibile. Usa un PDF con testo ricercabile.")
        return pdf, passages

    def search(self, query: str, limit: int = 5, document: str | None = None) -> list[Passage]:
        query = query.strip()[:600]
        if not query:
            return []
        expanded = " ".join(extra for pattern, extra in ALIASES.items() if re.search(pattern, query, re.I))
        vector = self.index.transform([f"{query} {expanded}"])
        scores = (self.matrix @ vector.T).toarray().ravel()
        matches: list[Passage] = []
        seen = set()
        for idx in np.argsort(-scores, kind="stable"):
            if scores[idx] < 0.065 or len(matches) == limit:
                break
            hit = self.passages[idx]
            source = hit.citation
            if document is not None and source.document != document:
                continue
            key = (source.document, source.page, hit.is_pdf)
            if key in seen:
                continue
            seen.add(key)
            matches.append(hit)
        return matches


def read_local_pdfs(directory: Path) -> tuple[tuple[str, bytes], ...]:
    if not directory.is_dir():
        return ()
    return tuple((path.name, path.read_bytes()) for path in sorted(directory.glob("*.pdf"))[:MAX_DOCUMENTS]
                 if path.is_file() and path.stat().st_size <= MAX_PDF_BYTES)
