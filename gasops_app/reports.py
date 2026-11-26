"""Esportazione di risultati, fonti, ipotesi e rilievi in Markdown."""

import json

from .italiano import ESITI, GRANULARITA, GRAVITA, MODALITA, TIPI
from .models import AGENT_LABELS, Run
from .executive_briefing import management_readout
from .ai_response import SECTION_TITLES, reference_labels
from .assistant_sources import source_rows


def _plain(text: str) -> str:
    return text.replace("<", "&lt;").replace(">", "&gt;").replace("[", "\\[").replace("]", "\\]")


def markdown(run: Run, reviewed: dict[str, str]) -> str:
    source = run.source
    lines = [
        "# I.G.O.R. — rapporto operativo", "", f"**Obiettivo** {_plain(run.question)}",
        f"**Analisi** `{run.id}` · {run.started_at.isoformat()} UTC · {MODALITA[run.mode]}",
        f"**Fonte** {_plain(source.name)} · {TIPI[source.kind]} · {GRANULARITA[source.grain]}",
        f"**Impronta dei dati SHA-256** `{run.input_sha256}`", "", "## Sintesi operativa", "",
    ]
    if run.assumptions.get("full_briefing"):
        overview,forecast,priorities=management_readout(run)
        lines.extend([_plain(overview), "", _plain(forecast), "", "### Priorità di verifica",
                      *[f"- {_plain(item)}" for item in priorities]])
    else:
        lines.append(_plain(run.summary))
    for feed in (source, *source.companions):
        if feed.url:
            lines.extend(["", f"[{_plain(feed.name)}]({feed.url})"])
    if run.warnings:
        lines.extend(["", *[f"- {_plain(warning)}" for warning in run.warnings]])
    if run.interpretation:
        lines.extend(["", "## Interpretazione AI"])
        for section in getattr(run,"ai_sections",[]):
            lines.extend(["", "### "+SECTION_TITLES[section["id"]], "", _plain(section["text"]),
                          "", "Fonti · "+_plain("; ".join(reference_labels(run,section["references"])))])
        if not getattr(run,"ai_sections",[]):
            refs=", ".join(AGENT_LABELS[name] for name in run.interpretation_sources)
            lines.extend(["", _plain(run.interpretation), f"Strumenti consultati · {refs}"])

    sources=source_rows(run)
    if sources:
        lines.extend(["", "## Contesto operativo pubblico", ""])
        for row in sources:
            status={"available":"Disponibile","partial":"Parziale","stale":"Non recente",
                    "unavailable":"Non disponibile"}.get(row["status"],"Stato non indicato")
            label=_plain(str(row["source"]))
            if row["url"]:
                label=f"[{label}]({row['url']})"
            metadata=(status,row["scope"],row["period"],"Acquisita "+row["acquired"] if row["acquired"] else None)
            lines.append("- "+label+" · "+" · ".join(_plain(str(part)) for part in metadata if part))
            lines.append("  - "+_plain(row["evidence"]))
            if row["limitation"]:
                lines.append("  - "+_plain(row["limitation"]))

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
