"""Reproducible historical result, prepared before the audience opens the demo."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "data" / "demo" / "forecast.json"
INPUT = ROOT / "data" / "jrc" / "IT.v1.1.csv"
ENGINE_FILES = ("predictive.py", "bayesian.py", "quality.py", "data.py", "executive_demo.py")


def provenance():
    return {"source_sha256": hashlib.sha256(INPUT.read_bytes()).hexdigest(),
            "engine_sha256": {name: hashlib.sha256((ROOT / "gasops_app" / name).read_bytes()).hexdigest()
                              for name in ENGINE_FILES}}


def build():
    # Imports and fitting belong to preparation, never to the viewing experience.
    from .executive_demo import historical_study
    return {"schema": 1, "method": "D+1 · 730 ultimi giorni · 28 origini cronologiche · lag gas 2 giorni",
            **provenance(), **historical_study()}


def load():
    snapshot = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    if snapshot.get("schema") != 1 or any(snapshot.get(k) != v for k, v in provenance().items()):
        raise ValueError("Il confronto storico deve essere rigenerato per questa versione.")
    return snapshot


if __name__ == "__main__":
    SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT.write_text(json.dumps(build(), ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print("Confronto storico aggiornato: data/demo/forecast.json")
