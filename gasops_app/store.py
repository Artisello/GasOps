"""SQLite cache and local analysis history."""

from contextlib import closing
import os
from pathlib import Path
import sqlite3
from datetime import timedelta

from .data import ROOT
from .models import Run, utc_now

SCHEMA = """
CREATE TABLE IF NOT EXISTS source_cache (
    name TEXT PRIMARY KEY, fetched_at TEXT NOT NULL, payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY, started_at TEXT NOT NULL, payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS llm_requests (
    id INTEGER PRIMARY KEY, attempted_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS llm_requests_time ON llm_requests(attempted_at);
CREATE TABLE IF NOT EXISTS llm_budget_resets (
    reset_id TEXT PRIMARY KEY, applied_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reviews (
    run_id TEXT NOT NULL REFERENCES runs(id), finding_id TEXT NOT NULL, reviewed_at TEXT NOT NULL,
    PRIMARY KEY (run_id, finding_id)
);
"""


LLM_RESET_ID = "operator-reset-2026-11-19"


class Store:
    def __init__(self, path: Path | None = None):
        state = Path(os.environ.get("GASOPS_STATE_DIR") or ROOT / ".gasops")
        self.path = path if path is not None else state / "state.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection:
            connection.executescript(SCHEMA)
        self._apply_budget_reset()

    def _apply_budget_reset(self):
        """One-time operator-requested daily reset; preserve minute throttling."""
        with closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            columns={row[1] for row in db.execute("PRAGMA table_info(llm_requests)")}
            if "daily_counted" not in columns:
                db.execute("ALTER TABLE llm_requests ADD COLUMN daily_counted INTEGER NOT NULL DEFAULT 1")
            added=db.execute("INSERT INTO llm_budget_resets VALUES (?,?) ON CONFLICT DO NOTHING",
                             (LLM_RESET_ID,utc_now().isoformat())).rowcount
            if added:
                db.execute("UPDATE llm_requests SET daily_counted=0")

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5)
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def cached(self, name: str) -> tuple[str, str] | None:
        with closing(self._connect()) as db:
            return db.execute("SELECT fetched_at, payload FROM source_cache WHERE name=?", (name,)).fetchone()

    def cached_entries(self, prefix: str, *, limit: int = 24, window=None):
        """Bound metadata reads. Ranged keys end their prefix with first:last."""
        if not prefix or not 1 <= limit <= 100:
            raise ValueError("Limite della cache non valido")
        where = "substr(name,1,?)=?"
        args = [len(prefix), prefix]
        if window is not None:
            first, last = window
            where += " AND substr(name,?,10)<=? AND substr(name,?,10)>=?"
            args += [len(prefix)+1, last.isoformat(), len(prefix)+12, first.isoformat()]
        with closing(self._connect()) as db:
            return db.execute(f"""SELECT name, fetched_at, length(CAST(payload AS BLOB))
                FROM source_cache WHERE {where}
                ORDER BY fetched_at DESC, name LIMIT ?""", (*args, limit)).fetchall()

    def cache(self, name: str, fetched_at: str, payload: str) -> None:
        with closing(self._connect()) as db, db:
            db.execute("""INSERT INTO source_cache VALUES (?, ?, ?)
                          ON CONFLICT(name) DO UPDATE SET fetched_at=excluded.fetched_at, payload=excluded.payload
                          WHERE excluded.fetched_at >= source_cache.fetched_at""", (name, fetched_at, payload))

    def reserve_llm(self, *, now=None, daily=30, minute=4) -> bool:
        """Atomic rolling limit shared by sessions using this SQLite file."""
        now=now or utc_now()
        day=(now-timedelta(hours=24)).isoformat()
        recent=(now-timedelta(minutes=1)).isoformat()
        with closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM llm_requests WHERE attempted_at<=?",(day,))
            count=db.execute("SELECT COUNT(*) FROM llm_requests WHERE daily_counted=1").fetchone()[0]
            short=db.execute("SELECT COUNT(*) FROM llm_requests WHERE attempted_at>?",(recent,)).fetchone()[0]
            if count>=daily or short>=minute:
                return False
            db.execute("INSERT INTO llm_requests(attempted_at) VALUES (?)",(now.isoformat(),))
            return True

    def llm_usage(self, *, now=None) -> int:
        cutoff=((now or utc_now())-timedelta(hours=24)).isoformat()
        with closing(self._connect()) as db:
            return db.execute("SELECT COUNT(*) FROM llm_requests WHERE attempted_at>? AND daily_counted=1",(cutoff,)).fetchone()[0]

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
