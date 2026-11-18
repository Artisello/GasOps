"""Opt-in diagnostic: verify actual CSV headers and coverage, no price logs."""
import tempfile
from pathlib import Path
from .acer_market import load_lng
from .store import Store
from .public_data import SourceUnavailable


def main():
    try:
        with tempfile.TemporaryDirectory() as folder:
            r=load_lng(Store(Path(folder)/"acer.db"))
        print("ACER validated CSV dates:",r.rows[0]["date"],r.rows[-1]["date"],"records:",len(r.rows))
        return 0
    except (SourceUnavailable,ValueError) as exc:
        print("ACER probe:",str(exc) if isinstance(exc,SourceUnavailable) else type(exc).__name__)
        return 1


if __name__=="__main__":
    raise SystemExit(main())
