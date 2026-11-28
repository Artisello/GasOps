"""Local lexical/concept retrieval, with exact PDF provenance.

No embeddings, generated queries, external services or inferred citations.
Controlled synonyms are retrieval hints only, never factual evidence.
"""
import re
from unicodedata import normalize, combining

CONCEPTS=(
    ("deposito cauzionale","cauzione","cash collateral","security deposit"),
    ("preavviso","notice period","termine di preavviso"),
    ("sbilanciamento","disequilibrio","imbalance"),
    ("bilanciamento commerciale","commercial balancing"),
    ("giorno gas","gas day"),
    ("rigassificazione","regasification"),
    ("forza maggiore","force majeure"),
    ("capacità interrompibile","interruptible capacity"),
    ("capacità continua","firm capacity"),
    ("allocazione","allocation"),
    ("nomina","nomination"),
    ("fatturazione","invoicing"),
    ("potere calorifico superiore","pcs","gross calorific value"),
    ("mancata discarica","failure to unload"),
)
CANDIDATES=24
REF=re.compile(r"\b(articolo|art\.?|capitolo|cap\.?|paragrafo|paragraph|section)\s*(\d+(?:\.\d+)*)(?!\d|\.\d)|§\s*(\d+(?:\.\d+)*)(?!\d|\.\d)",re.I)
PAGE=re.compile(r"\b(?:pagina|pag\.?|pdf\s+p\.?|page)\s*(\d+)\b",re.I)


def clean(text):
    return "".join(ch for ch in normalize("NFKD",text.casefold()) if not combining(ch))


def phrase(text,term):
    return bool(re.search(r"(?<!\w)"+re.escape(clean(term))+r"(?!\w)",text))


def tokens(text,stop):
    return {t for t in re.findall(r"[\w-]+",clean(text)) if len(t)>=2 and t not in stop}


def hints(query):
    normalized=clean(query)
    return tuple(group for group in CONCEPTS if any(phrase(normalized,v) for v in group))


def references(text):
    result=set()
    for m in REF.finditer(clean(text)):
        label=m.group(1) or "§"
        kind="article" if label.startswith("art") else "chapter" if label.startswith("cap") else "section"
        result.add((kind,m.group(2) or m.group(3)))
    return result


def score(query,hit,stop):
    """Comparable across indexes; raw TF-IDF scores never cross archives."""
    evidence=clean(hit.evidence)
    original=tokens(query,stop)
    matched=original & tokens(evidence,stop)
    concepts=sum(any(phrase(evidence,term) for term in group) for group in hints(query))
    refs=references(query)
    if refs and not refs<=references(hit.evidence):
        return None
    pages={int(m.group(1)) for m in PAGE.finditer(query)}
    if pages and hit.page not in pages:return None
    if not matched and not concepts:return None
    # Metadata is a tie-breaker, not independent evidence of relevance.
    title=len(original & tokens(hit.document,stop))
    literal=phrase(evidence," ".join(clean(query).split()))
    return (len(matched)+concepts, len(matched),int(literal),title)


def hybrid(library,query,stop,*,document=None,limit=6):
    if not tokens(query,stop):return []
    direct=" ".join(t for t in re.findall(r"[\w-]+",query) if len(t)>=2 and clean(t) not in stop)
    groups=hints(query)
    expanded=" ".join(dict.fromkeys(t for group in groups for t in group))
    queries=(direct,expanded) if expanded else (direct,)
    candidates={}
    for variant in queries:
        for rank,hit in enumerate(library.search(variant,limit=CANDIDATES,document=document,expand_aliases=False,unique_pages=False)):
            if not hit.is_pdf or hit.citation.document not in library.documents:continue
            cite=hit.citation
            relevance=score(query,cite,stop)
            if relevance is None:continue
            key=(cite.document,cite.page,cite.evidence)
            if key not in candidates:candidates[key]=[relevance,0.,cite]
            candidates[key][1]+=1/(60+rank+1)
    ordered=sorted(candidates.values(),key=lambda row:(row[0],row[1]),reverse=True)
    # Limit redundant page excerpts without discarding alternative editions.
    seen=set()
    result=[]
    for _,_,cite in ordered:
        key=(cite.document,cite.page)
        if key in seen:continue
        seen.add(key)
        result.append(cite)
        if len(result)>=limit:break
    return result
