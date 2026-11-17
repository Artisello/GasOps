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
    NETWORK, 394, "Ch. 9 §4.4.2",
    "A negative user imbalance is valued using the buy price and a positive imbalance using the sell price. "
    "The code defines separate prices in the preceding section.",
)
BALANCING_NOTE = cite(
    NETWORK, 358, "Ch. 9 §1",
    "Commercial balancing covers how users match their network injections and withdrawals, plus the "
    "accounting, allocation and economic incentives that support balancing.",
)


@dataclass(frozen=True)
class Case:
    finding: Finding
    review: str
    search: str


REGISTER = (
    Case(Finding(
        id="notice-7", title="Exactly seven days’ notice", severity="high",
        detail="Both tables skip the equality case. The charge or compensation cannot be derived for "
               "exactly seven days from these tables. Escalate the coefficient selection for review.",
        category="Confirmed textual omission",
        citations=[
            cite(PIOMBINO, 103, "Ch. 10 §1.1.1", "User-side table lists 12, 11, 10, 9, 8 and <7 days."),
            cite(PIOMBINO, 104, "Ch. 10 §1.1.2", "Operator-side table uses the same notice boundaries."),
        ],
    ), "Tables verified · interpretation open", "cancellazione mancata discarica preavviso sette giorni coefficiente"),
    Case(Finding(
        id="panigaglia", title="Panigaglia in the Piombino glossary", severity="medium",
        detail="The entry for SRG mentions the network’s Panigaglia connection. A separate entry defines "
               "the Piombino entry point. Check intended scope before mapping the glossary to terminal data.",
        category="Unresolved ambiguity",
        citations=[cite(PIOMBINO, 7, "Glossary (Glo-3)",
                        "Panigaglia appears under Snam Rete Gas on the same page as the Piombino entry-point definition.")],
    ), "Text verified · intended reference open", "panigaglia interconnessa terminale riferimento glossario"),
    Case(Finding(
        id="density", title="Density symbol reused for two quantities", severity="medium",
        detail="The same symbol labels dimensionless relative density and mass density in kg/Sm³. "
               "A parser must keep those fields separate for the Wobbe calculation.",
        category="Confirmed notation conflict",
        citations=[
            cite(PIOMBINO, 125, "Ch. 12 §2.1", "The page defines two different quantities as dr and uses dr under the square root in the Wobbe formula."),
            cite(NETWORK, 644, "Glossary (Glo-4)", "The Wobbe definition refers to the square root of relative density."),
        ],
    ), "Notation checked · mapping needs review", "densità relativa massa volumica formula wobbe notation"),
    Case(Finding(
        id="references", title="Circular and mismatched paragraph references", severity="medium",
        detail="A self-reference and a mismatched transport billing pointer can send a reader to the "
               "wrong tariff. Confirm the intended targets before applying any provision.",
        category="Confirmed textual error",
        citations=[
            cite(PIOMBINO, 112, "Ch. 10 §4.1", "The clause refers back to the preceding §4.1 while itself numbered §4.1."),
            cite(PIOMBINO, 148, "Ch. 18 §2(b)", "The transport capacity billing bullet points to Ch. 10 §4.2."),
            cite(PIOMBINO, 109, "Ch. 10 §3.1", "The transport charges subsection is §3.1. §4.2 concerns LNG volume deviation on PDF p. 112."),
        ],
    ), "References checked · intended targets open", "riferimenti circolari precedente paragrafo fatturazione trasporto"),
    Case(Finding(
        id="tariff-units", title="Capacity tariff unit needs reconciliation", severity="medium",
        detail="The fee multiplies an assignment tariff by a daily capacity. Confirm the unit and time "
               "basis of the tariff from the applicable assignment procedure before deriving an amount in euros.",
        category="Unresolved ambiguity",
        citations=[
            cite(PIOMBINO, 103, "Ch. 10 §§1.1.1–1.1.2",
                 "The missed-unloading calculation uses T × α × C × Cd. This passage gives a daily basis for Cd and refers to Ch. 5 for C."),
            cite(PIOMBINO, 108, "Ch. 10 §3", "The base charge text describes a separate application to contracted LNG quantities per slot."),
        ],
    ), "Formula checked · unit basis open", "tariffa unità corrispettivo capacità dimensionale assignment tariff units"),
    Case(Finding(
        id="dst-gas-day", title="23, 24 and 25 elapsed hours", severity="medium",
        detail="The glossary names both a 24-hour duration and consecutive 06:00 boundaries. In "
               "Europe/Rome the boundaries are 23 and 25 elapsed hours across seasonal clock changes. "
               "The dashboard derives elapsed time from the UTC boundaries.",
        category="Potential implementation risk",
        citations=[cite(NETWORK, 644, "Glossary (Glo-4)",
                        "The definition specifies 24 consecutive hours and starts and ends at 06:00 local calendar time.")],
    ), "Definition and calendar checked · accounting treatment open", "gas day giorno gas cambio ora ora legale daylight saving 23 25"),
    Case(Finding(
        id="accounting-zero", title="Missing allocation data recorded as zero", severity="info",
        detail="The accounting default applies to the specified transport balance. Preserve the absence "
               "of source data as an independent flag so the allocated zero cannot be read as a measured zero.",
        category="Regulatory accounting convention",
        citations=[
            cite(NETWORK, 391, "Ch. 9 §4.3.4.1",
                 "Where the required SII user data are missing, provisional withdrawals at that point are allocated as zero."),
            cite(NETWORK, 392, "Ch. 9 §4.3.4.2", "The definitive process sets zero in its specified missing-data case as well."),
        ],
    ), "Documented choice · namespace accounting zero", "zero dati mancanti missing data allocazione bilancio provvisorio"),
    Case(Finding(
        id="zero-denominator", title="Proportional allocation with zero total", severity="medium",
        detail="A proportional calculation is undefined when its total denominator is zero. Neither "
               "cited example supplies a zero-total result. Route the edge case for review before calculating.",
        category="Potential implementation risk",
        citations=[
            cite(NETWORK, 417, "Annex 9/A §1.1", "The proportional allocation example assumes a positive sum of transport programmes."),
            cite(PIOMBINO, 111, "Ch. 10 §3.1", "The transport capacity fee share divides by Qtot for the period."),
        ],
    ), "Formula checked · zero-total handling open", "pro quota proportional zero denominator denominatore qt ot"),
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
            raise ValueError("Expected a PDF up to 24 MB")
        passages: list[Passage] = []
        with pymupdf.open(stream=data, filetype="pdf") as document:
            if document.needs_pass or not 1 <= len(document) <= MAX_PAGES:
                raise ValueError("Expected an unlocked PDF with 1–800 pages")
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
            raise ValueError("No extractable text. Use a searchable PDF.")
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
