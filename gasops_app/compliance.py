"""Human-confirmed regulatory references, bound to exact operational evidence and PDF bytes.

No inference of legal applicability, validity, breach, or compliance.
"""
from hashlib import sha256
from datetime import datetime
import json

from .document_desk import page_text

STATE="compliance_links_v1"
MAX_LINKS=80
MAX_HISTORY=20
OUTCOMES=("Da valutare","Pertinente per la revisione","Non pertinente")
TOPICS={
    "Operations":("Scadenze e procedure applicabili","termini pubblicazione rettifica"),
    "Balancing":("Pubblicazioni e informazioni di bilanciamento","bilanciamento giorno gas informazioni"),
    "Settlement":("Allocazioni, bilanci e rettifiche","bilancio definitivo corrispettivi rettifica"),
    "Data Quality":("Provenienza, misure e disponibilità delle informazioni","dati misura pubblicazione"),
}
OFFICIAL={
    "Codice di Rete Snam":"https://www.snam.it/it/i-nostri-business/trasporto/codice-di-rete-tariffe-area-comitato-e-consultazioni/codice-di-rete.html",
    "ARERA – Testi integrati (TIB)":"https://www.arera.it/area-operatori/testi-integrati",
    "ARERA – Bilanciamento gas":"https://www.arera.it/area-operatori/bilanciamentogashtm",
    "ARERA – Deliberazione 482/2024/R/gas":"https://www.arera.it/atti-e-provvedimenti/dettaglio/24/482-24",
    "Snam – Avvisi commerciali":"https://www.snam.it/it/apis/news-commerciale.html",
}


def normalize(s):
    return " ".join(s.split())


def digest(obj):
    return sha256(json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()


def add_reference(links,case,docs,document,page,quote,section,now):
    """Verify exact contiguous normalized text from the actual selected page."""
    if now.tzinfo is None or case.get("agent") not in TOPICS or not case.get("id"):
        raise ValueError("Caso o timestamp non valido.")
    if not isinstance(quote,str) or not isinstance(section,str) or len(quote)>1000:
        raise ValueError("Estratto non valido.")
    quote=normalize(quote)
    section=normalize(section)
    if not 15<=len(quote)<=300 or len(section)>120:
        raise ValueError("Estratto di 15–300 caratteri e riferimento di massimo 120 caratteri.")
    pdf=docs.documents.get(document)
    if pdf is None or type(page) is not int or not 1<=page<=pdf.pages:
        raise ValueError("Documento o pagina non disponibile.")
    if sha256(pdf.data).hexdigest()!=pdf.digest:
        raise ValueError("Impronta PDF incoerente.")
    if quote not in normalize(page_text(pdf,page)):
        raise ValueError("L'estratto non è presente letteralmente nella pagina selezionata.")
    body={"case_id":case["id"],"document":document,"sha256":pdf.digest,
          "page":page,"quote":quote,"section_declared":section}
    key=digest(body)
    if any(r["id"]==key for r in links):
        return list(links),False
    if len(links)>=MAX_LINKS:
        raise ValueError("Limite collegamenti raggiunto. Esporta il registro.")
    return [*links,{**body,"id":key,"created":now.isoformat(),"outcome":OUTCOMES[0],"history":[]}],True


def edition_status(link,docs):
    if docs is None:
        return "Archivio non consultato"
    pdf=docs.documents.get(link["document"])
    if pdf is None or pdf.digest!=link["sha256"] or not 1<=link["page"]<=pdf.pages:
        return "Edizione assente o cambiata"
    return "Copia indicizzata corrispondente"


def assess(link,outcome,note,docs,now):
    if now.tzinfo is None or outcome not in OUTCOMES or outcome==link["outcome"]:
        raise ValueError("Decisione non valida o invariata.")
    if edition_status(link,docs)!="Copia indicizzata corrispondente":
        raise ValueError("Edizione non corrispondente: creare un nuovo collegamento.")
    note=note.strip()
    if not 1<=len(note)<=400 or len(link["history"])>=MAX_HISTORY:
        raise ValueError("Motivazione obbligatoria (max 400 caratteri) o storico esaurito.")
    event={"at":now.isoformat(),"from":link["outcome"],"to":outcome,"note":note}
    return {**link,"outcome":outcome,"history":[*link["history"],event]}


def case_links(links,case_id,docs):
    return [{**r,"edition_status":edition_status(r,docs)} for r in links if r["case_id"]==case_id]


def export_register(links,cases,docs):
    known={r["id"] for r in cases}
    return json.dumps({"schema":1,"notice":"Riferimenti documentali e valutazioni umane di pertinenza; vigenza e conformità non certificate.",
       "links":[{**r,"edition_status":edition_status(r,docs),"case_present":r["case_id"] in known} for r in links]},
       ensure_ascii=False,indent=2)
