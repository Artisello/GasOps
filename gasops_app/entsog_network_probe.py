"""Opt-in bounded live smoke test; no credentials or raw numeric data in CI logs."""
from datetime import timedelta
import tempfile
from pathlib import Path

from .entsog import _last_completed
from .entsog_network import PRESETS, load_network, INDICATORS
from .models import utc_now
from .public_data import SourceUnavailable
from .store import Store


def main():
    now=utc_now()
    last=_last_completed(now)-timedelta(days=2)
    first=last-timedelta(days=2)
    point=next(iter(PRESETS.values()))
    print(f"Network probe: {point}, {first} to {last}.")
    try:
        with tempfile.TemporaryDirectory() as folder:
            result=load_network(Store(Path(folder)/"probe.db"),point,first,last,now=now)
    except (SourceUnavailable,ValueError) as exc:
        print("Probe:",str(exc) if isinstance(exc,SourceUnavailable) else type(exc).__name__)
        return 1
    print("Identity labels:", result.labels)
    print("Valid slots by indicator:", {ind:sum(r["indicator"]==ind and r["quality"]=="valido" for r in result.rows) for ind in INDICATORS})
    print("Metadata warning:",result.metadata_warning)
    if not any(r["indicator"]=="Physical Flow" and r["quality"]=="valido" for r in result.rows):
        print("No physical flow slot; investigate before use.")
        return 1
    return 0


if __name__=="__main__":
    raise SystemExit(main())
