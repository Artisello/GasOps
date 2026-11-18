"""Esportazione di risultati, fonti, ipotesi e rilievi in Markdown."""

import json

from .italiano import ESITI, GRANULARITA, GRAVITA, MODALITA, TIPI
from .models import AGENT_LABELS, Run


def _plain(text: str) -> str:
    return text.replace("<", "&lt;").replace(">", "&gt;").replace("[", "\\[").replace("]", "\\]")


def markdown(run: Run, reviewed: dict[str, str]) -> str:
    source = run.source
    lines = [
        "# I.G.O.R. — rapporto operativo", "", f"**Obiettivo** {_plain(run.question)}",
        f"**Analisi** `{run.id}` · {run.started_at.isoformat()} UTC · {MODALITA[run.mode]}",
        f"**Fonte** {_plain(source.name)} · {TIPI[source.kind]} · {GRANULARITA[source.grain]}",
        f"**Impronta dei dati SHA-256** `{run.input_sha256}`", "", "## Sintesi operativa", "", _plain(run.summary),
    ]
    for feed in (source, *source.companions):
        if feed.url:
            lines.extend(["", f"[{_plain(feed.name)}]({feed.url})"])
    if run.warnings:
        lines.extend(["", *[f"- {_plain(warning)}" for warning in run.warnings]])
    if run.interpretation:
        refs = ", ".join(AGENT_LABELS[name] for name in run.interpretation_sources)
        lines.extend(["", f"**Interpretazione del modello** {_plain(run.interpretation)}", f"Strumenti consultati · {refs}"])

    public=run.assumptions.get("public_operational_context") or {}
    if public:
        lines.extend(["", "## Contesto operativo pubblico", ""])
        for name,item in public.items():
            status={"available":"Disponibile","stale":"Non recente","unavailable":"Non disponibile"}.get(item.get("status"),"Stato non indicato")
            lines.append(f"- **{_plain(str(item.get('source',name)))}** · {status} · {_plain(str(item.get('gas_day') or item.get('acquired') or 'data non indicata'))}")
            if item.get("limitation") or item.get("reason"):
                lines.append(f"  - {_plain(str(item.get('limitation') or item.get('reason')))}")
        lines.append("Indicatori e metadati completi nelle ipotesi dell’analisi. Nessun record UMM originale.")

    lines.extend(["", "## Riscontri degli agenti", ""])
    for agent, result in run.results.items():
        lines.extend([f"### {AGENT_LABELS[agent]} · {ESITI[result.status]}", "", _plain(result.summary), ""])
        for cite in result.evidence:
            page = f" · PDF p. {cite.page}" if cite.page else ""
            section = f" · {cite.section}" if cite.section else ""
            lines.append(f"- **{_plain(cite.document)}{page}{section}** · {_plain(cite.evidence)}")
        lines.append("")

    lines.extend(["## Rilievi e revisione", ""])
    for finding in run.findings:
        status = f"preso in carico il {reviewed[finding.id]}" if finding.id in reviewed else "aperto"
        if finding.severity == "info":
            status = "informativo"
        lines.append(f"- **{_plain(finding.title)}** · {GRAVITA[finding.severity]} · {status}. {_plain(finding.detail)}")
    lines.extend(["", "## Ipotesi dell’analisi", "", "```json"])
    lines.extend([json.dumps(run.assumptions, ensure_ascii=False, indent=2), "```", ""])
    return "\n".join(lines)
