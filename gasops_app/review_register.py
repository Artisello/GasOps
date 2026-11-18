"""Session-only human review register, bound to exact PDF editions and evidence."""
import hashlib
import json
from datetime import datetime
from .models import utc_now

LIMIT=40
STATUSES=("Da verificare","In revisione","Da approfondire","Archiviato")
KEY="review_register"


def valid_cases(cases,docs):
    """Drop a case when any supporting edition is no longer in the selected archive."""
    editions={name:pdf.digest for name,pdf in docs.documents.items()}
    return [case for case in cases if case["editions"] and
            all(editions.get(name)==digest for name,digest in case["editions"].items())][:LIMIT]


def register(cases,findings,docs,*,theme,model,now=None):
    """Deduplicate exact hypotheses, never silently overwrite decisions."""
    cases=valid_cases(cases,docs)
    known={case["id"] for case in cases}
    added=0
    omitted=0
    for item in findings:
        citations=[c.model_dump(mode="json") for c in item["citations"]]
        editions={c["document"]:docs.documents[c["document"]].digest for c in citations}
        body={"title":item["title"],"detail":item["detail"],"check":item["check"],
              "citations":sorted(citations,key=lambda c:(c["document"],c["page"],c["evidence"])),
              "editions":editions}
        case_id=hashlib.sha256(json.dumps(body,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
        if case_id in known:
            continue
        if len(cases)>=LIMIT:
            omitted+=1
            continue
        cases.append({**body,"id":case_id,"theme":theme,"model":model,
                      "created":(now or utc_now()).isoformat(),"status":STATUSES[0],
                      "history":[]})
        known.add(case_id)
        added+=1
    return cases,added,omitted


def decide(case,status,note,*,now=None):
    if status not in STATUSES:
        raise ValueError("Stato non valido.")
    note=note.strip()
    if not note or len(note)>600:
        raise ValueError("Inserisci una motivazione (1–600 caratteri).")
    if len(case["history"])>=20:
        raise ValueError("Limite storico raggiunto; esporta il registro.")
    event={"at":(now or utc_now()).isoformat(),"from":case["status"],"to":status,"note":note}
    return {**case,"status":status,"history":[*case["history"],event]}


def export_json(cases):
    return json.dumps({"scope":"sessione","notice":"Ipotesi AI e decisioni registrate dall'utente; non certificazione legale.",
                       "cases":cases},ensure_ascii=False,indent=2)


def _plain(value):
    # Exports are text reports, not executable content.
    return str(value).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;").replace("[","\\[").replace("]","\\]")


def export_markdown(cases):
    lines=["# I.G.O.R. – Registro di revisione","",
           "Ipotesi da verificare; le decisioni sono annotazioni dell'utente, non certificazioni legali.",""]
    for case in cases:
        lines.extend(["## "+_plain(case["title"]),"",
                      "**Stato:** "+case["status"],"**ID:** "+case["id"],"**Tema:** "+_plain(case["theme"]),
                      "**Modello:** "+_plain(case["model"])+" · "+case["created"],"",
                      _plain(case["detail"]),"","**Verifica suggerita:** "+_plain(case["check"]),""])
        for c in case["citations"]:
            lines.extend([f'- {_plain(c["document"])} · PDF p. {c["page"]} · SHA-256 {case["editions"][c["document"]]}',
                          "  > "+_plain(c["evidence"]),""])
        for event in case["history"]:
            lines.append(f'- {event["at"]} · {event["from"]} → {event["to"]}: {_plain(event["note"])}')
        lines.append("")
    return "\n".join(lines)
