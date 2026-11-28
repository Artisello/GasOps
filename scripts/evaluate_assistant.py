"""Reproducible, read-only assistant evaluation. Offline by default.

Run from repository root: python -m scripts.evaluate_assistant
Optional paid/live inference: python -m scripts.evaluate_assistant --live
No public-data acquisition, credentials in artifacts, PDF or user data.
All observations below are artificial test fixtures, not market observations.
"""
import argparse
from contextlib import ExitStack, nullcontext
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from time import perf_counter
from unittest.mock import patch

from gasops_app import assistant_sources as src
from gasops_app import session
from gasops_app.assistant_lookup import lookup_report
from gasops_app.llm import CompatibleReasoner, LLMConfig, configuration

NOW = datetime(2026, 11, 22, 12, tzinfo=timezone.utc)
PRICE = {"source": src.PRICE, "scope": "Italia", "status": "available",
         "grain": "mese", "period": "2026-10-01", "unit": "€/MWh", "value": 34.123}
STORAGE = {"source": "GIE AGSI+", "scope": "IT", "status": "available",
           "kind": "observed", "gas_day": "2026-11-21",
           "values": {"fill_pct": 80, "stock_twh": 70}}
STALE = {"source": src.POWER[0], "scope": "Italia", "status": "stale",
         "period": "2026-11-16", "unit": "GWh elettrici", "values": {"load": 9999}}
FIXTURE_CONFIG = LLMConfig("openai/gpt-oss-120b", "https://api.groq.com/openai/v1")


def answer(text, *refs):
    return {"sections": [{"id": "answer", "text": text, "references": list(refs)}]}


def blocked(*args, **kwargs):
    raise AssertionError("Unexpected network or dataset acquisition")


class Response:
    """OpenAI-compatible fixture transport, not an actual LLM."""
    status_code = 200

    def __init__(self, value):
        self.value = value

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def iter_content(self, chunk_size):
        yield json.dumps({"choices": [{"message": {"content": json.dumps(self.value, ensure_ascii=False)},
                                       "finish_reason": "stop"}]}).encode()


def synthesis_case(name, question, public, replies, expected_mode, calls, *,
                   required=(), contains=(), forbidden=(), live_config=None):
    """Exercise the actual synthesis, citation, retry and fallback pipeline."""
    model = CompatibleReasoner(live_config or FIXTURE_CONFIG)
    bodies = []
    scripted = iter(replies)

    def fake_post(*args, **kwargs):
        bodies.append(kwargs["json"])
        return Response(next(scripted))

    with ExitStack() as stack:
        if live_config is None:
            stack.enter_context(patch("gasops_app.llm.requests.post", fake_post))
        report = lookup_report(question, deepcopy(public), NOW, reasoner=model)
    text = report.interpretation or ""
    refs = {ref for section in report.ai_sections for ref in section["references"]}
    checks = {
        "mode": report.mode == expected_mode,
        "required_citations": set(required) <= refs,
        "expected_values": all(re.search(pattern, text, re.I) for pattern in contains),
        "forbidden_claims": not any(re.search(pattern, text, re.I) for pattern in forbidden),
        "call_budget": model.calls <= calls,
        "payload_budget": model.request_bytes <= 12_000 * calls,
        "fallback_no_ai_sections": expected_mode != "Deterministic fallback"
                                    or (not report.ai_sections and not text),
    }
    if live_config is None:
        checks["exact_calls"] = len(bodies) == model.calls == calls
        checks["each_payload_budget"] = all(len(json.dumps(body).encode()) <= 12_000 for body in bodies)
    return checks, model.usage_summary()


def launch_case(question, expected_keys, expected_mode, *, compare=False):
    """Run the automatic assistant entry point without any real acquisition."""
    model = CompatibleReasoner(FIXTURE_CONFIG)
    state, acquired = {}, []

    def collect(context, base, requested, **kwargs):
        acquired.append(tuple(requested))
        if base is not None or not kwargs.get("automatic"):
            raise AssertionError("Assistant required a manual base")
        if compare:
            day = kwargs["day"]
            return {src.PRICE: {**PRICE, "period": day.isoformat(),
                                "value": 40 if day.month == 9 else 50}}
        if tuple(requested) != ("AGSI+",):
            raise AssertionError("Unexpected source")
        return {"AGSI+": deepcopy(STORAGE)}

    with ExitStack() as stack:
        for name, value in (("assistant_reasoner", lambda: model),
                            ("automatic_selection", blocked),
                            ("_collect_assistant_sources", collect),
                            ("utc_now", lambda: NOW)):
            stack.enter_context(patch.object(session, name, value))
        stack.enter_context(patch.object(session.st, "session_state", state))
        stack.enter_context(patch.object(session.st, "spinner", lambda *a, **k: nullcontext()))
        stack.enter_context(patch("gasops_app.llm.requests.post", blocked))
        report = session.launch(None, question, ai_policy="automatic")
    public = report.assumptions.get("public_operational_context", {})
    checks = {
        "sources": set(public) == set(expected_keys),
        "mode": report.mode == expected_mode,
        "zero_model_calls": model.calls == 0,
        "acquisition_budget": len(acquired) == (2 if compare else 1 if expected_keys == ("AGSI+",) else 0),
    }
    if compare:
        rows = report.assumptions.get("assistant_comparison", [])
        checks["comparison"] = len(rows) == 1 and rows[0]["delta"] == 10 and rows[0]["delta_pct"] == 25
    elif expected_keys == (src.ELECTRIC_PRICE,):
        checks["coverage_gap"] = public[src.ELECTRIC_PRICE]["status"] == "unavailable"
    elif expected_keys == ("AGSI+",):
        checks["direct_readout"] = bool(report.assumptions.get("assistant_fast_lookup")) and "70" in report.summary
    else:
        checks["clarification"] = "Comando non riconosciuto" in report.summary
    return checks, model.usage_summary()


def route_case(question, expected):
    return {"exact_sources": set(src.requested_sources(question)) == set(expected)}, {}


def cases(live_config=None):
    # Positive cases also support a separately requested live LLM smoke test.
    yield "cmem_observation", "grounding", lambda: synthesis_case(
        "cmem_observation", "Valore CMEM,m ottobre 2026 in Italia?",
        {src.PRICE: PRICE}, [answer("CMEM,m: 34,12 €/MWh, ottobre 2026, Italia.", "S1")],
        "LLM-assisted", 2 if live_config else 1, required=("src:" + src.PRICE,),
        contains=(r"34[,.]12", r"€/MWh"), live_config=live_config)
    yield "mixed_sources", "grounding", lambda: synthesis_case(
        "mixed_sources", "CMEM,m e giacenza degli stoccaggi italiani?",
        {src.PRICE: PRICE, "AGSI+": STORAGE},
        [answer("CMEM,m: 34,12 €/MWh. Giacenza: 70 TWh.", "S1", "S2")],
        "LLM-assisted", 2 if live_config else 1,
        required=("src:" + src.PRICE, "src:AGSI+"),
        contains=(r"34[,.]12", r"\b70(?:[,.]0+)?\s*TWh"), live_config=live_config)
    if live_config:
        return
    yield "electricity_price_route", "routing", lambda: route_case(
        "Costo giornaliero dell’elettricità", (src.ELECTRIC_PRICE,))
    yield "lng_electricity_route", "routing", lambda: route_case(
        "Prezzo dell'elettricità e del GNL", (src.ELECTRIC_PRICE, src.ACER))
    yield "ttf_route", "routing", lambda: route_case("Prezzo TTF spot oggi", (src.TTF_QUOTE,))
    yield "point_route", "routing", lambda: route_case("Qual è il flusso ENTSOG a Tarvisio?", (src.NETWORK,))
    yield "storage_route", "routing", lambda: route_case("Quali sono i prelievi da stoccaggio?", ("AGSI+",))
    yield "fast_storage", "efficiency", lambda: launch_case("/scorte", ("AGSI+",), "Deterministic")
    yield "electricity_gap", "coverage", lambda: launch_case(
        "Prezzo medio dell'energia elettrica ottobre 2026", (src.ELECTRIC_PRICE,), "Deterministic")
    yield "invalid_command", "coverage", lambda: launch_case("/inesistente", (), "Deterministic")
    yield "monthly_comparison", "calculation", lambda: launch_case(
        "Confronta CMEM,m settembre 2026 e ottobre 2026", (src.PRICE,), "Deterministic", compare=True)
    yield "hallucinated_value_repair", "grounding", lambda: synthesis_case(
        "hallucinated_value_repair", "Valore CMEM,m", {src.PRICE: PRICE},
        [answer("52 €/MWh.", "S1"), answer("34,12 €/MWh.", "S1")],
        "LLM-assisted", 2, required=("src:" + src.PRICE,), contains=(r"34,12",), forbidden=(r"\b52\b",))
    yield "hallucinated_value_fallback", "grounding", lambda: synthesis_case(
        "hallucinated_value_fallback", "Valore CMEM,m", {src.PRICE: PRICE},
        [answer("52 €/MWh.", "S1"), answer("99 €/MWh.", "S1")],
        "Deterministic fallback", 2)
    yield "invented_citation_fallback", "citations", lambda: synthesis_case(
        "invented_citation_fallback", "Valore CMEM,m", {src.PRICE: PRICE},
        [answer("34,12 €/MWh.", "S99"), answer("34,12 €/MWh.", "S99")],
        "Deterministic fallback", 2)
    yield "commodity_swap_fallback", "semantics", lambda: synthesis_case(
        "commodity_swap_fallback", "Valore CMEM,m", {src.PRICE: PRICE},
        [answer("Prezzo elettrico: 34,12 €/MWh.", "S1")] * 2,
        "Deterministic fallback", 2)
    yield "stale_value_fallback", "freshness", lambda: synthesis_case(
        "stale_value_fallback", "CMEM,m e dati Terna", {src.PRICE: PRICE, src.POWER[0]: STALE},
        [answer("CMEM,m: 34,12 €/MWh. Carico: 9999 GWh.", "S1", "S2")] * 2,
        "Deterministic fallback", 2)


def evaluate(live_config=None):
    rows = []
    with ExitStack() as stack:
        if live_config is None:
            # Even unintended HTTP outside the fixture transport fails closed.
            stack.enter_context(patch("requests.sessions.Session.request", blocked))
        for name, category, run in cases(live_config):
            start = perf_counter()
            try:
                checks, usage = run()
            except Exception as error:
                # Keep reports safe to upload: no prompts, response text,
                # credentials, exception messages or provider response bodies.
                checks, usage = {"execution": False}, {}
                error_type = type(error).__name__
            else:
                error_type = None
            rows.append({"id": name, "category": category, "passed": all(checks.values()),
                         "checks": checks, "error_type": error_type,
                         "elapsed_ms": round((perf_counter() - start) * 1000, 3), "usage": usage})
    passed = sum(row["passed"] for row in rows)
    # Missing token usage is unknown, not zero; offline provider time is
    # fixture overhead, not a latency measurement of the actual provider.
    usages = [row["usage"] for row in rows]
    reported = [u for u in usages if "total_tokens" in u]
    attempted = sum(u.get("calls", 0) for u in usages)
    reported_calls = sum(u.get("reported_calls", 0) for u in usages)
    return {
        "schema_version": 1, "mode": "live_inference_fixture_data" if live_config else "offline_fixture",
        "model": live_config.model if live_config else None,
        "passed": passed, "failed": len(rows) - passed, "total": len(rows),
        "pass_rate": round(passed / len(rows), 4),
        "model_calls": attempted, "reported_calls": reported_calls,
        "total_tokens": sum(u["total_tokens"] for u in reported) if reported else None,
        "tokens_complete": attempted > 0 and reported_calls == attempted,
        "request_bytes": sum(u.get("request_bytes", 0) for u in usages),
        "provider_elapsed_ms": sum(u.get("provider_elapsed_ms", 0) for u in usages) if live_config else None,
        "cases": rows,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("assistant-evaluation.json"))
    parser.add_argument("--live", action="store_true", help="Opt in to up to four real model requests using fixture data; provider charges may apply.")
    args = parser.parse_args()
    config = configuration() if args.live else None
    if args.live and config is None:
        parser.error("Configure a model in the environment first.")
    report = evaluate(config)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(f"Assistant evaluation ({report['mode']}): {report['passed']}/{report['total']} passed")
    for row in report["cases"]:
        failed = ", ".join(key for key, ok in row["checks"].items() if not ok)
        print(f"{'PASS' if row['passed'] else 'FAIL'} {row['id']}" + (f": {failed}" if failed else ""))
    return int(bool(report["failed"]))


if __name__ == "__main__":
    raise SystemExit(main())
