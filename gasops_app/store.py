"""SQLite cache and local analysis history."""

from contextlib import closing
import os
from pathlib import Path
import sqlite3

from .data import ROOT
from .models import Run, utc_now

SCHEMA = """
CREATE TABLE IF NOT EXISTS source_cache (
    name TEXT PRIMARY KEY, fetched_at TEXT NOT NULL, payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY, started_at TEXT NOT NULL, payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reviews (
    run_id TEXT NOT NULL REFERENCES runs(id), finding_id TEXT NOT NULL, reviewed_at TEXT NOT NULL,
    PRIMARY KEY (run_id, finding_id)
);
"""


class Store:
    def __init__(self, path: Path | None = None):
        state = Path(os.environ.get("GASOPS_STATE_DIR") or ROOT / ".gasops")
        self.path = path if path is not None else state / "state.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection:
            connection.executescript(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5)
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def cached(self, name: str) -> tuple[str, str] | None:
        with closing(self._connect()) as db:
            return db.execute("SELECT fetched_at, payload FROM source_cache WHERE name=?", (name,)).fetchone()

    def cache(self, name: str, fetched_at: str, payload: str) -> None:
        with closing(self._connect()) as db, db:
            db.execute("""INSERT INTO source_cache VALUES (?, ?, ?)
                          ON CONFLICT(name) DO UPDATE SET fetched_at=excluded.fetched_at, payload=excluded.payload
                          WHERE excluded.fetched_at >= source_cache.fetched_at""", (name, fetched_at, payload))

    def save(self, run: Run) -> None:
        with closing(self._connect()) as db, db:
            db.execute("INSERT INTO runs VALUES (?, ?, ?) ON CONFLICT(id) DO NOTHING",
                       (run.id, run.started_at.isoformat(), run.model_dump_json()))

    def recent(self, limit: int = 20) -> list[Run]:
        with closing(self._connect()) as db:
            rows = db.execute("SELECT payload FROM runs ORDER BY started_at DESC LIMIT ?", (limit,)).fetchall()
        return [Run.model_validate_json(payload) for (payload,) in rows]

    def reviewed(self, run_id: str) -> dict[str, str]:
        with closing(self._connect()) as db:
            return dict(db.execute("SELECT finding_id, reviewed_at FROM reviews WHERE run_id=?", (run_id,)))

    def acknowledge(self, run_id: str, finding_id: str) -> None:
        with closing(self._connect()) as db, db:
            db.execute("INSERT INTO reviews VALUES (?, ?, ?) ON CONFLICT DO NOTHING",
                       (run_id, finding_id, utc_now().isoformat()))
