"""WorldStore: the World Model's SQLite persistence (architecture §5.1).

One SQLite file (`WORLD_DB_PATH`, default `logs/world.db`) holds four tables:

- `entities`: Question, Metric, Segment, Hypothesis, Observation, Query, Source. The id is a content
  hash: the entity type plus its canonical fields as sorted-key JSON, SHA-256, a 16-hex-digit prefix
  behind a type tag (`obs_3f2a…`). The same content gets the same id in every process.
- `edges`: `tests` (query → hypothesis), `supports` / `refutes` (observation → hypothesis),
  `derived_from` (observation → query), `from_source` (query → source). The id hashes the type and
  both ends; each edge records the agent and run that first wrote it.
- `log`: one row per write (entity, edge or ingest checkpoint) with timestamp, agent, run id,
  operation and whether it was a no-op because the record already existed.
- `checkpoints`: ingest progress (see `ingest.py`), append-only like the log.

Nothing is updated in place or deleted: writes are `INSERT … ON CONFLICT DO NOTHING`, and triggers
abort any UPDATE or DELETE on every table, so the append-only rule holds even for code that does not
go through this class.
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Self

from app.config import Settings, get_settings, resolve_path

ENTITY_TAGS: dict[str, str] = {
    "question": "qst",
    "metric": "met",
    "segment": "seg",
    "hypothesis": "hyp",
    "observation": "obs",
    "query": "qry",
    "source": "src",
}
"""Entity type → id tag."""

CANONICAL_FIELDS: dict[str, tuple[str, ...]] = {
    "question": ("text",),
    "metric": ("name",),
    "segment": ("name",),
    "hypothesis": ("statement", "family", "question_id"),
    "observation": ("query_entity_id", "metric", "segment", "window", "baseline_window", "value", "baseline"),
    "query": ("source", "sql"),
    "source": ("name",),
}
"""Fields that make up an entity's identity. Other fields are stored but do not change the id."""

EDGE_TYPES: dict[str, tuple[str, str]] = {
    "tests": ("query", "hypothesis"),
    "supports": ("observation", "hypothesis"),
    "refutes": ("observation", "hypothesis"),
    "derived_from": ("observation", "query"),
    "from_source": ("query", "source"),
}
"""Edge type → (source entity type, target entity type)."""

TABLES: tuple[str, ...] = ("entities", "edges", "log", "checkpoints")

SCHEMA = """
CREATE TABLE IF NOT EXISTS entities (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    content TEXT NOT NULL,
    agent TEXT NOT NULL,
    run_id TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS entities_type ON entities (type, id);
CREATE TABLE IF NOT EXISTS edges (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    src TEXT NOT NULL REFERENCES entities (id),
    dst TEXT NOT NULL REFERENCES entities (id),
    agent TEXT NOT NULL,
    run_id TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS edges_src ON edges (src, type);
CREATE INDEX IF NOT EXISTS edges_dst ON edges (dst, type);
CREATE TABLE IF NOT EXISTS log (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    agent TEXT NOT NULL,
    run_id TEXT NOT NULL,
    operation TEXT NOT NULL,
    target_kind TEXT NOT NULL,
    target_id TEXT NOT NULL,
    target_type TEXT NOT NULL,
    noop INTEGER NOT NULL,
    detail TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS log_run ON log (run_id, seq);
CREATE TABLE IF NOT EXISTS checkpoints (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    ingest_key TEXT NOT NULL,
    query_id TEXT NOT NULL,
    rows_done INTEGER NOT NULL,
    rows_total INTEGER NOT NULL,
    finished INTEGER NOT NULL,
    truncated INTEGER NOT NULL,
    ts TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS checkpoints_key ON checkpoints (ingest_key, seq);
""" + "".join(
    f"""
CREATE TRIGGER IF NOT EXISTS {table}_no_update BEFORE UPDATE ON {table}
BEGIN SELECT RAISE(ABORT, '{table} is append-only'); END;
CREATE TRIGGER IF NOT EXISTS {table}_no_delete BEFORE DELETE ON {table}
BEGIN SELECT RAISE(ABORT, '{table} is append-only'); END;
"""
    for table in TABLES
)


def canonical(value: Any) -> Any:
    """Normalise a value for hashing: floats to 12 significant digits, integral floats to int.

    `3`, `3.0` and `3.0000000000001` hash alike, so a value that went through a float sum on another
    machine still maps to the same id. NaN and infinities become None.
    """
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        rounded = float(f"{value:.12g}")
        return int(rounded) if rounded.is_integer() else rounded
    if isinstance(value, dict):
        return {str(k): canonical(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [canonical(v) for v in value]
    return str(value)


def canonical_json(value: Any) -> str:
    """Sorted-key, compact JSON of the canonical form."""
    return json.dumps(canonical(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def entity_id(entity_type: str, fields: dict[str, Any]) -> str:
    """The content-hash id of an entity: `<tag>_<sha256 of type + canonical fields>[:16]`."""
    if entity_type not in ENTITY_TAGS:
        raise ValueError(f"unknown entity type {entity_type!r}; expected one of {', '.join(ENTITY_TAGS)}")
    identity = {name: fields.get(name) for name in CANONICAL_FIELDS[entity_type]}
    return f"{ENTITY_TAGS[entity_type]}_{_digest(entity_type + ':' + canonical_json(identity))}"


def edge_id(edge_type: str, src: str, dst: str) -> str:
    """The content-hash id of an edge: type and both ends."""
    return f"edg_{_digest(canonical_json({'type': edge_type, 'src': src, 'dst': dst}))}"


def entity_type_of(entity_id_: str) -> str | None:
    """The entity type from an id's tag, or None for an unknown tag."""
    tag = entity_id_.split("_", 1)[0]
    return next((name for name, value in ENTITY_TAGS.items() if value == tag), None)


@dataclass(frozen=True)
class Entity:
    """One stored entity."""

    id: str
    type: str
    content: dict[str, Any]
    agent: str
    run_id: str


@dataclass(frozen=True)
class Edge:
    """One stored edge."""

    id: str
    type: str
    src: str
    dst: str
    agent: str
    run_id: str


@dataclass(frozen=True)
class Checkpoint:
    """The latest ingest checkpoint for one ingest key."""

    ingest_key: str
    query_id: str
    rows_done: int
    rows_total: int
    finished: bool
    truncated: bool


def _now() -> str:
    return datetime.now(UTC).isoformat()


class WorldStore:
    """SQLite-backed World Model store with content-hash ids and an append-only log.

    Writes outside `transaction()` commit immediately; inside it they commit together, and an
    exception rolls the whole block back (entities, edges, log rows and checkpoints alike).
    """

    def __init__(
        self,
        path: Path | str | None = None,
        *,
        settings: Settings | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        settings = settings or get_settings()
        self.path = Path(path) if path else resolve_path(settings.world_db_path)
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        # Autocommit mode; `transaction()` issues BEGIN/COMMIT itself. The timeout bounds the wait
        # for another process's write lock.
        self._con = sqlite3.connect(str(self.path), timeout=timeout_seconds, isolation_level=None)
        self._con.row_factory = sqlite3.Row
        self._con.execute("PRAGMA foreign_keys = ON")
        if str(self.path) != ":memory:":
            self._con.execute("PRAGMA journal_mode = WAL")
            self._con.execute("PRAGMA synchronous = NORMAL")
        self._con.executescript(SCHEMA)
        self._depth = 0

    # --- lifecycle -------------------------------------------------------------------------------

    def close(self) -> None:
        """Close the connection."""
        self._con.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @property
    def connection(self) -> sqlite3.Connection:
        """The underlying connection (tests attach a trace callback to it)."""
        return self._con

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """Group writes into one atomic commit; nested blocks join the outer one."""
        if self._depth:
            self._depth += 1
            try:
                yield
            finally:
                self._depth -= 1
            return
        self._con.execute("BEGIN IMMEDIATE")
        self._depth = 1
        try:
            yield
        except BaseException:
            self._con.execute("ROLLBACK")
            raise
        else:
            self._con.execute("COMMIT")
        finally:
            self._depth = 0

    # --- writes ----------------------------------------------------------------------------------

    def _log(
        self,
        *,
        agent: str,
        run_id: str,
        operation: str,
        target_kind: str,
        target_id: str,
        target_type: str,
        noop: bool,
        detail: dict[str, Any] | None = None,
    ) -> None:
        self._con.execute(
            "INSERT INTO log (ts, agent, run_id, operation, target_kind, target_id, target_type, noop, detail) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (_now(), agent, run_id, operation, target_kind, target_id, target_type, int(noop),
             canonical_json(detail or {})),
        )

    def put_entity(self, entity_type: str, fields: dict[str, Any], *, agent: str, run_id: str) -> str:
        """Write an entity and return its content-hash id.

        Writing the same canonical content again returns the same id, stores nothing new (the first
        write's non-canonical fields are kept) and logs the write as a no-op.
        """
        new_id = entity_id(entity_type, fields)
        with self.transaction():
            cur = self._con.execute(
                "INSERT INTO entities (id, type, content, agent, run_id, created_at) VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT (id) DO NOTHING",
                (new_id, entity_type, canonical_json(fields), agent, run_id, _now()),
            )
            noop = cur.rowcount == 0
            self._log(agent=agent, run_id=run_id, operation="put_entity", target_kind="entity",
                      target_id=new_id, target_type=entity_type, noop=noop,
                      detail={"alert": True} if fields.get("alert") and not noop else {})
        return new_id

    def put_edge(self, edge_type: str, src: str, dst: str, *, agent: str, run_id: str) -> str:
        """Write an edge between two stored entities and return its id; idempotent like `put_entity`.

        Raises `ValueError` for an unknown edge type, wrong end types or a missing end.
        """
        if edge_type not in EDGE_TYPES:
            raise ValueError(f"unknown edge type {edge_type!r}; expected one of {', '.join(EDGE_TYPES)}")
        want_src, want_dst = EDGE_TYPES[edge_type]
        for end, want in ((src, want_src), (dst, want_dst)):
            stored = self.get(end)
            if stored is None:
                raise ValueError(f"{edge_type} edge: entity {end!r} is not in the store")
            if stored.type != want:
                raise ValueError(f"{edge_type} edge needs {want_src} -> {want_dst}, got {stored.type} at {end!r}")
        new_id = edge_id(edge_type, src, dst)
        with self.transaction():
            cur = self._con.execute(
                "INSERT INTO edges (id, type, src, dst, agent, run_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT (id) DO NOTHING",
                (new_id, edge_type, src, dst, agent, run_id, _now()),
            )
            self._log(agent=agent, run_id=run_id, operation="put_edge", target_kind="edge", target_id=new_id,
                      target_type=edge_type, noop=cur.rowcount == 0, detail={"src": src, "dst": dst})
        return new_id

    def put_checkpoint(self, checkpoint: Checkpoint, *, agent: str, run_id: str) -> None:
        """Append an ingest checkpoint (the latest row per key is the current state)."""
        with self.transaction():
            self._con.execute(
                "INSERT INTO checkpoints (ingest_key, query_id, rows_done, rows_total, finished, truncated, ts) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (checkpoint.ingest_key, checkpoint.query_id, checkpoint.rows_done, checkpoint.rows_total,
                 int(checkpoint.finished), int(checkpoint.truncated), _now()),
            )
            self._log(agent=agent, run_id=run_id, operation="checkpoint", target_kind="ingest",
                      target_id=checkpoint.ingest_key, target_type="ingest", noop=False,
                      detail={"query_id": checkpoint.query_id, "rows_done": checkpoint.rows_done,
                              "rows_total": checkpoint.rows_total, "finished": checkpoint.finished,
                              "truncated": checkpoint.truncated})

    # --- reads -----------------------------------------------------------------------------------

    @staticmethod
    def _entity(row: sqlite3.Row) -> Entity:
        return Entity(id=row["id"], type=row["type"], content=json.loads(row["content"]),
                      agent=row["agent"], run_id=row["run_id"])

    @staticmethod
    def _edge(row: sqlite3.Row) -> Edge:
        return Edge(id=row["id"], type=row["type"], src=row["src"], dst=row["dst"],
                    agent=row["agent"], run_id=row["run_id"])

    def get(self, entity_id_: str) -> Entity | None:
        """The entity with this id, or None."""
        row = self._con.execute("SELECT * FROM entities WHERE id = ?", (entity_id_,)).fetchone()
        return self._entity(row) if row else None

    def get_edge(self, edge_id_: str) -> Edge | None:
        """The edge with this id, or None."""
        row = self._con.execute("SELECT * FROM edges WHERE id = ?", (edge_id_,)).fetchone()
        return self._edge(row) if row else None

    def entities(self, entity_type: str) -> list[Entity]:
        """All entities of one type, ordered by id."""
        rows = self._con.execute("SELECT * FROM entities WHERE type = ? ORDER BY id", (entity_type,))
        return [self._entity(row) for row in rows]

    def edges(self, entity_id_: str, edge_type: str | None = None, *, direction: str = "out") -> list[Edge]:
        """Edges leaving (`out`) or entering (`in`) an entity, optionally of one type, ordered by id."""
        if direction not in ("out", "in"):
            raise ValueError("direction must be 'out' or 'in'")
        column = "src" if direction == "out" else "dst"
        sql = f"SELECT * FROM edges WHERE {column} = ?"
        params: tuple[str, ...] = (entity_id_,)
        if edge_type is not None:
            sql += " AND type = ?"
            params += (edge_type,)
        return [self._edge(row) for row in self._con.execute(sql + " ORDER BY id", params)]

    def neighbours(self, entity_id_: str, edge_type: str, *, direction: str = "out") -> list[Entity]:
        """Entities at the other end of this entity's edges of one type, ordered by id."""
        ends = sorted({edge.dst if direction == "out" else edge.src
                       for edge in self.edges(entity_id_, edge_type, direction=direction)})
        found = (self.get(end) for end in ends)
        return [entity for entity in found if entity is not None]

    def observations_for(self, hypothesis_id: str) -> list[Entity]:
        """Every observation tied to a hypothesis: by a `supports`/`refutes` edge, or derived from a
        query that `tests` it. Ordered by id, no duplicates."""
        ids: set[str] = set()
        for edge_type in ("supports", "refutes"):
            ids.update(edge.src for edge in self.edges(hypothesis_id, edge_type, direction="in"))
        for test in self.edges(hypothesis_id, "tests", direction="in"):
            ids.update(edge.src for edge in self.edges(test.src, "derived_from", direction="in"))
        found = (self.get(obs_id) for obs_id in sorted(ids))
        return [entity for entity in found if entity is not None]

    def latest_checkpoint(self, ingest_key: str) -> Checkpoint | None:
        """The most recent checkpoint for an ingest key, or None if it never started."""
        row = self._con.execute(
            "SELECT * FROM checkpoints WHERE ingest_key = ? ORDER BY seq DESC LIMIT 1", (ingest_key,)
        ).fetchone()
        if row is None:
            return None
        return Checkpoint(ingest_key=row["ingest_key"], query_id=row["query_id"], rows_done=row["rows_done"],
                          rows_total=row["rows_total"], finished=bool(row["finished"]),
                          truncated=bool(row["truncated"]))

    def log_rows(self, run_id: str | None = None) -> list[dict[str, Any]]:
        """The append log in write order, optionally for one run."""
        sql, params = "SELECT * FROM log", ()
        if run_id is not None:
            sql, params = sql + " WHERE run_id = ?", (run_id,)
        rows = self._con.execute(sql + " ORDER BY seq", params)
        return [{**dict(row), "noop": bool(row["noop"]), "detail": json.loads(row["detail"])} for row in rows]

    def counts(self) -> dict[str, Any]:
        """Entity counts by type, edge counts by type and the log size."""
        entities = dict(self._con.execute("SELECT type, count(*) FROM entities GROUP BY type ORDER BY type").fetchall())
        edges = dict(self._con.execute("SELECT type, count(*) FROM edges GROUP BY type ORDER BY type").fetchall())
        (log_rows,) = self._con.execute("SELECT count(*) FROM log").fetchone()
        return {
            "entities": sum(entities.values()),
            "entities_by_type": entities,
            "edges": sum(edges.values()),
            "edges_by_type": edges,
            "log_rows": log_rows,
        }

    def export_log_jsonl(self, run_id: str, path: Path | str) -> Path:
        """Write one run's log rows to `world-<run>.jsonl`-style JSONL (architecture §8); returns the path."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            for row in self.log_rows(run_id):
                handle.write(json.dumps(row, sort_keys=True) + "\n")
        return path
