"""Local report exports with the source snapshot, assumptions and findings."""

import json

from .models import AGENT_LABELS, Run


def _plain(text: str) -> str:
    return text.replace("<", "&lt;").replace(">", "&gt;").replace("[", "\\[").replace("]", "\\]")


def markdown(run: Run, reviewed: dict[str, str]) -> str:
    source = run.source
    lines = [
        "# GasOps AI — operations report", "", f"**Objective** {_plain(run.question)}",
        f"**Run** `{run.id}` · {run.started_at.isoformat()} UTC · {run.mode}",
        f"**Source** {_plain(source.name)} · {source.kind.value} · {source.grain}",
        f"**Data SHA-256** `{run.input_sha256}`", "", "## Executive summary", "", _plain(run.summary),
    ]
    if source.url:
        lines.extend(["", f"[Data source]({source.url})"])
    if run.warnings:
        lines.extend(["", *[f"- {_plain(warning)}" for warning in run.warnings]])
    if run.interpretation:
        refs = ", ".join(AGENT_LABELS[name] for name in run.interpretation_sources)
        lines.extend(["", f"**Model interpretation** {_plain(run.interpretation)}", f"Tools referenced · {refs}"])

    lines.extend(["", "## Agent evidence", ""])
    for agent, result in run.results.items():
        lines.extend([f"### {AGENT_LABELS[agent]} · {result.status}", "", _plain(result.summary), ""])
        for cite in result.evidence:
            page = f" · PDF p. {cite.page}" if cite.page else ""
            section = f" · {cite.section}" if cite.section else ""
            lines.append(f"- **{_plain(cite.document)}{page}{section}** · {_plain(cite.evidence)}")
        lines.append("")

    lines.extend(["## Findings and review", ""])
    for finding in run.findings:
        status = f"acknowledged {reviewed[finding.id]}" if finding.id in reviewed else "open"
        if finding.severity == "info":
            status = "informational"
        lines.append(f"- **{_plain(finding.title)}** · {finding.severity} · {status}. {_plain(finding.detail)}")
    lines.extend(["", "## Run assumptions", "", "```json"])
    lines.extend([json.dumps(run.assumptions, ensure_ascii=False, indent=2), "```", ""])
    return "\n".join(lines)
