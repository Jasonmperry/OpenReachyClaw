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
    # Admin — update / delete people, faces, memories
    # ------------------------------------------------------------------

    async def update_person_name(self, person_id: int, new_name: str) -> dict:
        """Rename a person.  Returns the updated record or an error."""
        async with self._lock:
            assert self._conn is not None
            row = self._conn.execute(
                "SELECT id FROM people WHERE id = ?", (person_id,)
            ).fetchone()
            if not row:
                return {"error": f"Person id={person_id} not found"}
            now = datetime.now().isoformat()
            self._conn.execute(
                "UPDATE people SET name = ?, updated_at = ? WHERE id = ?",
                (new_name, now, person_id),
            )
            self._conn.commit()
            logger.info("Renamed person %d to %s", person_id, new_name)
            return {"status": "updated", "id": person_id, "name": new_name}

    async def delete_person(self, person_id: int) -> dict:
        """Delete a person and all their face sightings and related memories."""
        async with self._lock:
            assert self._conn is not None
            row = self._conn.execute(
                "SELECT name FROM people WHERE id = ?", (person_id,)
            ).fetchone()
            if not row:
                return {"error": f"Person id={person_id} not found"}
            name = row["name"]
            # Remove face sightings
            self._conn.execute(
                "DELETE FROM face_sightings WHERE person_id = ?", (person_id,)
            )
            # Remove memories about this person
            self._conn.execute(
                "DELETE FROM memories WHERE subject LIKE ? COLLATE NOCASE",
                (f"%{name}%",),
            )
            # Remove the person
            self._conn.execute("DELETE FROM people WHERE id = ?", (person_id,))
            self._conn.commit()
            logger.info("Deleted person %s (id=%d) and related data", name, person_id)
            return {"status": "deleted", "id": person_id, "name": name}

    async def delete_face_sighting(self, sighting_id: int) -> dict:
        """Delete a single face sighting by ID."""
        async with self._lock:
            assert self._conn is not None
            row = self._conn.execute(
                "SELECT id FROM face_sightings WHERE id = ?", (sighting_id,)
            ).fetchone()
            if not row:
                return {"error": f"Face sighting id={sighting_id} not found"}
            self._conn.execute(
                "DELETE FROM face_sightings WHERE id = ?", (sighting_id,)
            )
            self._conn.commit()
            logger.info("Deleted face sighting %d", sighting_id)
            return {"status": "deleted", "id": sighting_id}

    async def delete_memory(self, memory_id: int) -> dict:
        """Delete a single memory by ID."""
        async with self._lock:
            assert self._conn is not None
            row = self._conn.execute(
                "SELECT id FROM memories WHERE id = ?", (memory_id,)
            ).fetchone()
            if not row:
                return {"error": f"Memory id={memory_id} not found"}
            self._conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
            self._conn.commit()
            logger.info("Deleted memory %d", memory_id)
            return {"status": "deleted", "id": memory_id}

    async def update_memory(self, memory_id: int, fact: str | None = None, category: str | None = None) -> dict:
        """Update a memory's fact and/or category."""
        async with self._lock:
            assert self._conn is not None
            row = self._conn.execute(
                "SELECT * FROM memories WHERE id = ?", (memory_id,)
            ).fetchone()
            if not row:
                return {"error": f"Memory id={memory_id} not found"}
            new_fact = fact if fact is not None else row["fact"]
            new_cat = category if category is not None else row["category"]
            self._conn.execute(
                "UPDATE memories SET fact = ?, category = ? WHERE id = ?",
                (new_fact, new_cat, memory_id),
            )
            self._conn.commit()
            logger.info("Updated memory %d", memory_id)
            return {"status": "updated", "id": memory_id, "fact": new_fact, "category": new_cat}

    async def get_person_faces(self, person_id: int) -> list[dict]:
        """Get all face sightings for a person (for admin view)."""
        assert self._conn is not None
        rows = self._conn.execute(
            "SELECT id, image_path, confidence, seen_at FROM face_sightings "
            "WHERE person_id = ? ORDER BY seen_at DESC",
            (person_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    async def recall_all_with_ids(self) -> list[dict]:
        """Like recall_all but includes the memory id for admin editing."""
        assert self._conn is not None
        rows = self._conn.execute(
            "SELECT id, subject, fact, category, created_at FROM memories "
            "ORDER BY created_at DESC LIMIT 200"
        ).fetchall()
        return [dict(r) for r in rows]

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
