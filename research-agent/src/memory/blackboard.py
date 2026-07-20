"""Shared run state: sources (current picture) and posts (what happened).

- ``sources``: one row per Source, updated in place as agents enrich it.
  An empty field is the to-do marker.
- ``posts``: append-only audit trail — every decision, tool call, note.

content_json per post kind:

    kind        posted by            shape
    ----------  -------------------  -----------------------------------------
    criteria    SupervisorAgent      {topic, research_question, min_words, min_sources}
    tool_call   Research/ParseAgent  {tool, args}
    note        Research/ParseAgent  {text}
    decision    any agent            Decision.to_dict()
    report      PublisherAgent       Report.to_dict()  (paths only, content on disk)

SQLite: queryable by run and kind and comes with Python. No installation necessary.
"""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from src.config.settings import settings
from src.models import Source

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    run_id     TEXT NOT NULL,
    id         TEXT NOT NULL,
    data_json  TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (run_id, id)
);
CREATE TABLE IF NOT EXISTS posts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id       TEXT NOT NULL,
    agent        TEXT NOT NULL,
    kind         TEXT NOT NULL,
    content_json TEXT NOT NULL,
    created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_posts_run_kind ON posts(run_id, kind);
"""


class Blackboard:
    def __init__(self, run_id: str, db_path: str | None = None) -> None:
        self.run_id = run_id
        self.db_path = db_path or str(Path(settings.data_dir) / "blackboard.db")
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as con:
            con.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        # One step runs at a time, so a fresh connection per call is fine.
        return sqlite3.connect(self.db_path)

    # -- sources: the current state, updated in place ----------------------

    def save_source(self, source: Source) -> None:
        """Insert a new source, or update the stored one in place.

        Update-then-insert (not INSERT OR REPLACE) so a source keeps its row
        and position — sources() lists them in first-found order.
        """
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as con:
            updated = con.execute(
                "UPDATE sources SET data_json = ?, updated_at = ? WHERE run_id = ? AND id = ?",
                (json.dumps(source.to_dict()), now, self.run_id, source.id),
            ).rowcount
            if not updated:
                con.execute(
                    "INSERT INTO sources (run_id, id, data_json, updated_at) VALUES (?, ?, ?, ?)",
                    (self.run_id, source.id, json.dumps(source.to_dict()), now),
                )

    def get_source(self, source_id: str) -> Source | None:
        with self._connect() as con:
            row = con.execute(
                "SELECT data_json FROM sources WHERE run_id = ? AND id = ?",
                (self.run_id, source_id),
            ).fetchone()
        return Source.from_dict(json.loads(row[0])) if row else None

    def sources(self) -> list[Source]:
        """This run's sources, in the order they were first saved."""
        with self._connect() as con:
            rows = con.execute(
                "SELECT data_json FROM sources WHERE run_id = ? ORDER BY rowid",
                (self.run_id,),
            ).fetchall()
        return [Source.from_dict(json.loads(r[0])) for r in rows]

    # -- posts: the append-only audit trail ---------------------------------

    def post(self, agent: str, kind: str, content: dict) -> int:
        """Append one post and return its row id. Never updated, never deleted."""
        with self._connect() as con:
            cur = con.execute(
                "INSERT INTO posts (run_id, agent, kind, content_json, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (self.run_id, agent, kind, json.dumps(content),
                 datetime.now(timezone.utc).isoformat()),
            )
            return int(cur.lastrowid)

    def posts(self, kind: str | None = None) -> list[dict]:
        """This run's posts, oldest first; optionally filtered to one kind."""
        query = "SELECT id, agent, kind, content_json, created_at FROM posts WHERE run_id = ?"
        params: list = [self.run_id]
        if kind is not None:
            query += " AND kind = ?"
            params.append(kind)
        query += " ORDER BY id"
        with self._connect() as con:
            rows = con.execute(query, params).fetchall()
        return [
            {"id": r[0], "agent": r[1], "kind": r[2], "content": json.loads(r[3]), "created_at": r[4]}
            for r in rows
        ]
