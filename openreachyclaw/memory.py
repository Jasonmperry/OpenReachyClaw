"""Persistent memory store backed by SQLite.

Stores facts, preferences, and face embeddings so Rosie remembers
people and information across restarts.  Thread-safe via sqlite3's
serialised mode and an asyncio lock for face-data writes.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path.home() / ".rosie" / "memory.db"


class MemoryStore:
    """SQLite-backed persistent memory for facts and faces."""

    def __init__(self, db_path: Path | None = None):
        self._db_path = db_path or DEFAULT_DB_PATH
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def open(self) -> None:
        self._conn = sqlite3.connect(
            str(self._db_path),
            check_same_thread=False,
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._create_tables()
        logger.info("Memory store opened at %s", self._db_path)

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    def _create_tables(self) -> None:
        assert self._conn is not None
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS memories (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                subject     TEXT NOT NULL,
                fact        TEXT NOT NULL,
                category    TEXT DEFAULT 'general',
                created_at  TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS people (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT NOT NULL UNIQUE,
                created_at  TEXT NOT NULL,
                updated_at  TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS face_sightings (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                person_id   INTEGER NOT NULL REFERENCES people(id),
                image_path  TEXT NOT NULL,
                embedding   TEXT,          -- JSON-serialised float list
                confidence  REAL DEFAULT 1.0,
                seen_at     TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS orders (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                person      TEXT NOT NULL,
                item        TEXT NOT NULL,
                notes       TEXT DEFAULT '',
                status      TEXT DEFAULT 'pending',
                created_at  TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_memories_subject
                ON memories(subject COLLATE NOCASE);
            CREATE INDEX IF NOT EXISTS idx_people_name
                ON people(name COLLATE NOCASE);
            CREATE INDEX IF NOT EXISTS idx_face_sightings_person
                ON face_sightings(person_id);
            CREATE INDEX IF NOT EXISTS idx_orders_person
                ON orders(person COLLATE NOCASE);
        """)
        self._conn.commit()

    # ------------------------------------------------------------------
    # Facts / memories
    # ------------------------------------------------------------------

    async def remember(self, subject: str, fact: str, category: str = "general") -> dict:
        async with self._lock:
            assert self._conn is not None
            now = datetime.now().isoformat()
            self._conn.execute(
                "INSERT INTO memories (subject, fact, category, created_at) VALUES (?, ?, ?, ?)",
                (subject, fact, category, now),
            )
            self._conn.commit()
            logger.info("Remembered about %s: %s", subject, fact[:80])
            return {"status": "remembered", "subject": subject, "fact": fact}

    async def recall(self, subject: str) -> list[dict]:
        assert self._conn is not None
        rows = self._conn.execute(
            "SELECT subject, fact, category, created_at FROM memories "
            "WHERE subject LIKE ? ORDER BY created_at DESC",
            (f"%{subject}%",),
        ).fetchall()
        return [dict(r) for r in rows]

    async def recall_all(self) -> list[dict]:
        assert self._conn is not None
        rows = self._conn.execute(
            "SELECT subject, fact, category, created_at FROM memories "
            "ORDER BY created_at DESC LIMIT 100"
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # People / faces
    # ------------------------------------------------------------------

    async def add_person(self, name: str) -> int:
        """Create or get a person record.  Returns the person ID."""
        async with self._lock:
            assert self._conn is not None
            now = datetime.now().isoformat()
            row = self._conn.execute(
                "SELECT id FROM people WHERE name = ? COLLATE NOCASE", (name,)
            ).fetchone()
            if row:
                return row["id"]
            cur = self._conn.execute(
                "INSERT INTO people (name, created_at, updated_at) VALUES (?, ?, ?)",
                (name, now, now),
            )
            self._conn.commit()
            return cur.lastrowid  # type: ignore[return-value]

    async def add_face_sighting(
        self,
        person_id: int,
        image_path: str,
        embedding: list[float] | None = None,
        confidence: float = 1.0,
    ) -> int:
        """Store a face sighting (photo + optional embedding) for a person."""
        async with self._lock:
            assert self._conn is not None
            now = datetime.now().isoformat()
            emb_json = json.dumps(embedding) if embedding else None
            cur = self._conn.execute(
                "INSERT INTO face_sightings (person_id, image_path, embedding, confidence, seen_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (person_id, image_path, emb_json, confidence, now),
            )
            self._conn.commit()
            return cur.lastrowid  # type: ignore[return-value]

    async def get_person_by_name(self, name: str) -> dict | None:
        assert self._conn is not None
        row = self._conn.execute(
            "SELECT * FROM people WHERE name = ? COLLATE NOCASE", (name,)
        ).fetchone()
        return dict(row) if row else None

    async def get_face_sightings(self, person_id: int, limit: int = 5) -> list[dict]:
        assert self._conn is not None
        rows = self._conn.execute(
            "SELECT * FROM face_sightings WHERE person_id = ? ORDER BY seen_at DESC LIMIT ?",
            (person_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    async def get_all_people(self) -> list[dict]:
        assert self._conn is not None
        rows = self._conn.execute(
            "SELECT p.id, p.name, p.created_at, "
            "  (SELECT COUNT(*) FROM face_sightings f WHERE f.person_id = p.id) as face_count, "
            "  (SELECT COUNT(*) FROM memories m WHERE m.subject LIKE '%' || p.name || '%') as memory_count "
            "FROM people p ORDER BY p.name"
        ).fetchall()
        return [dict(r) for r in rows]

    async def get_all_face_embeddings(self) -> list[dict]:
        """Return all people with their latest face embedding for matching."""
        assert self._conn is not None
        rows = self._conn.execute(
            "SELECT p.id, p.name, f.embedding, f.image_path "
            "FROM people p "
            "JOIN face_sightings f ON f.person_id = p.id "
            "WHERE f.embedding IS NOT NULL "
            "ORDER BY f.seen_at DESC"
        ).fetchall()
        # Deduplicate to latest per person
        seen: dict[int, dict] = {}
        results = []
        for r in rows:
            pid = r["id"]
            if pid not in seen:
                d = dict(r)
                d["embedding"] = json.loads(d["embedding"])
                seen[pid] = d
                results.append(d)
        return results

    # ------------------------------------------------------------------
    # Orders
    # ------------------------------------------------------------------

    async def take_order(self, person: str, item: str, notes: str = "") -> dict:
        async with self._lock:
            assert self._conn is not None
            now = datetime.now().isoformat()
            cur = self._conn.execute(
                "INSERT INTO orders (person, item, notes, status, created_at) VALUES (?, ?, ?, 'pending', ?)",
                (person, item, notes, now),
            )
            self._conn.commit()
            order_id = cur.lastrowid
            logger.info("Order #%d: %s ordered '%s'", order_id, person, item)
            return {
                "status": "confirmed",
                "order_id": order_id,
                "person": person,
                "item": item,
                "notes": notes,
            }

    async def list_orders(self, person: str = "") -> list[dict]:
        assert self._conn is not None
        if person:
            rows = self._conn.execute(
                "SELECT * FROM orders WHERE person LIKE ? ORDER BY created_at DESC",
                (f"%{person}%",),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM orders ORDER BY created_at DESC LIMIT 50"
            ).fetchall()
        return [dict(r) for r in rows]


# Singleton instance — created once, shared across threads
_store: MemoryStore | None = None


def get_memory_store() -> MemoryStore:
    """Get or create the global memory store singleton."""
    global _store
    if _store is None:
        _store = MemoryStore()
        _store.open()
    return _store
