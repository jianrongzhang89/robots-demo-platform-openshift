from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


class StoreError(RuntimeError):
    pass


class ConflictError(StoreError):
    pass


class NotFoundError(StoreError):
    pass


class Store:
    """Small SQLite-backed Phase 2 gateway store.

    SQLite is used for the development gateway so idempotency and event ordering
    are testable without adding a service dependency. The deployment mounts the
    database on persistent storage.
    """

    def __init__(self, path: str | Path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30, isolation_level=None, factory=ClosingConnection)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS episodes (
                    episode_id TEXT PRIMARY KEY,
                    rmf_generation_id TEXT NOT NULL,
                    site_id TEXT NOT NULL,
                    catalog_version TEXT NOT NULL,
                    active INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS previews (
                    preview_id TEXT PRIMARY KEY,
                    actor_id TEXT NOT NULL,
                    site_id TEXT NOT NULL,
                    catalog_version TEXT NOT NULL,
                    places_json TEXT NOT NULL,
                    rounds INTEGER NOT NULL,
                    payload_hash TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS missions (
                    mission_id TEXT PRIMARY KEY,
                    preview_id TEXT NOT NULL,
                    actor_id TEXT NOT NULL,
                    site_id TEXT NOT NULL,
                    episode_id TEXT NOT NULL,
                    rmf_generation_id TEXT NOT NULL,
                    catalog_version TEXT NOT NULL,
                    places_json TEXT NOT NULL,
                    rounds INTEGER NOT NULL,
                    payload_hash TEXT NOT NULL,
                    request_id TEXT NOT NULL UNIQUE,
                    rmf_task_id TEXT,
                    submission TEXT NOT NULL,
                    allocation TEXT NOT NULL,
                    execution TEXT NOT NULL,
                    cancellation TEXT NOT NULL,
                    freshness TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS idempotency_keys (
                    actor_id TEXT NOT NULL,
                    site_id TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    key TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    resource_id TEXT NOT NULL,
                    PRIMARY KEY (actor_id, site_id, operation, key)
                );
                CREATE TABLE IF NOT EXISTS dispatch_attempts (
                    mission_id TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL UNIQUE,
                    state TEXT NOT NULL,
                    publish_marker TEXT NOT NULL,
                    publication_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    event_id TEXT PRIMARY KEY,
                    mission_id TEXT,
                    event_type TEXT NOT NULL,
                    source TEXT NOT NULL,
                    source_event_id TEXT,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE (source, source_event_id)
                );
                CREATE UNIQUE INDEX IF NOT EXISTS one_active_episode ON episodes(active) WHERE active = 1;
                """
            )

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _hash(payload: Any) -> str:
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return "sha256:" + hashlib.sha256(encoded).hexdigest()

    def _active_episode(self, db: sqlite3.Connection) -> sqlite3.Row:
        row = db.execute("SELECT * FROM episodes WHERE active = 1").fetchone()
        if row:
            return row
        now = self._now()
        episode_id = "episode-" + uuid.uuid4().hex[:12]
        generation = "generation-" + uuid.uuid4().hex[:12]
        db.execute(
            "INSERT INTO episodes VALUES (?, ?, ?, ?, 1, ?)",
            (episode_id, generation, "hotel-demo", "sha256:4576e4eb1c95cfbb", now),
        )
        return db.execute("SELECT * FROM episodes WHERE episode_id = ?", (episode_id,)).fetchone()

    def create_preview(self, actor_id: str, site_id: str, catalog_version: str, places: list[str], rounds: int) -> dict[str, Any]:
        if not 2 <= len(places) <= 8 or rounds != 1:
            raise ConflictError("preview must contain 2-8 places and exactly one round")
        preview_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        payload_hash = self._hash({"site_id": site_id, "places": places, "rounds": rounds, "catalog_version": catalog_version})
        with self._connect() as db:
            db.execute(
                "INSERT INTO previews VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (preview_id, actor_id, site_id, catalog_version, json.dumps(places), rounds, payload_hash,
                 (now + timedelta(minutes=2)).isoformat(), now.isoformat()),
            )
        return {"preview_id": preview_id, "payload_hash": payload_hash, "expires_at": (now + timedelta(minutes=2)).isoformat()}

    def create_mission(self, actor_id: str, site_id: str, idempotency_key: str, preview_id: str) -> dict[str, Any]:
        if not idempotency_key:
            raise ConflictError("Idempotency-Key is required")
        with self._lock, self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            preview = db.execute("SELECT * FROM previews WHERE preview_id = ?", (preview_id,)).fetchone()
            if not preview:
                raise NotFoundError("preview not found")
            if preview["site_id"] != site_id or preview["actor_id"] != actor_id:
                raise ConflictError("preview scope mismatch")
            idem = db.execute(
                "SELECT * FROM idempotency_keys WHERE actor_id = ? AND site_id = ? AND operation = 'dispatch' AND key = ?",
                (actor_id, site_id, idempotency_key),
            ).fetchone()
            if idem:
                if idem["payload_hash"] != preview["payload_hash"]:
                    raise ConflictError("idempotency key was reused with a different payload")
                return self.get_mission(idem["resource_id"], db)
            if datetime.fromisoformat(preview["expires_at"]) <= datetime.now(timezone.utc):
                raise ConflictError("preview expired")
            episode = self._active_episode(db)
            mission_id = str(uuid.uuid4())
            request_id = str(uuid.uuid4())
            now = self._now()
            db.execute(
                "INSERT INTO missions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (mission_id, preview_id, actor_id, site_id, episode["episode_id"], episode["rmf_generation_id"],
                 preview["catalog_version"], preview["places_json"], preview["rounds"], preview["payload_hash"],
                 request_id, None, "publish_attempted", "pending", "unknown", "none", "fresh", 0, now, now),
            )
            db.execute(
                "INSERT INTO idempotency_keys VALUES (?, ?, 'dispatch', ?, ?, ?)",
                (actor_id, site_id, idempotency_key, preview["payload_hash"], mission_id),
            )
            db.execute(
                "INSERT INTO dispatch_attempts VALUES (?, ?, 'publish_attempted', ?, 1, ?)",
                (mission_id, request_id, "committed:" + now, now),
            )
            self._event(db, mission_id, "mission.created", "gateway", {"preview_id": preview_id})
            self._event(db, mission_id, "bridge.publish_attempted", "gateway", {"request_id": request_id})
            return self.get_mission(mission_id, db)

    def idempotency_mission(self, actor_id: str, site_id: str, key: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT resource_id FROM idempotency_keys WHERE actor_id = ? AND site_id = ? AND operation = 'dispatch' AND key = ?",
                (actor_id, site_id, key),
            ).fetchone()
            return self.get_mission(row["resource_id"], db) if row else None

    def _event(self, db: sqlite3.Connection, mission_id: str | None, event_type: str, source: str, payload: dict[str, Any], source_event_id: str | None = None) -> str:
        event_id = str(uuid.uuid4())
        db.execute(
            "INSERT OR IGNORE INTO events VALUES (?, ?, ?, ?, ?, ?, ?)",
            (event_id, mission_id, event_type, source, source_event_id, json.dumps(payload, sort_keys=True), self._now()),
        )
        return event_id

    @staticmethod
    def _mission_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "mission_id": row["mission_id"], "preview_id": row["preview_id"], "site_id": row["site_id"],
            "actor_id": row["actor_id"], "episode_id": row["episode_id"], "rmf_generation_id": row["rmf_generation_id"],
            "catalog_version": row["catalog_version"], "places": json.loads(row["places_json"]), "rounds": row["rounds"],
            "request_id": row["request_id"], "rmf_task_id": row["rmf_task_id"], "submission": row["submission"],
            "allocation": row["allocation"], "execution": row["execution"], "cancellation": row["cancellation"],
            "freshness": row["freshness"], "revision": row["revision"], "created_at": row["created_at"], "updated_at": row["updated_at"],
        }

    def get_mission(self, mission_id: str, db: sqlite3.Connection | None = None) -> dict[str, Any]:
        owned = db is None
        connection = db or self._connect()
        try:
            row = connection.execute("SELECT * FROM missions WHERE mission_id = ?", (mission_id,)).fetchone()
            if not row:
                raise NotFoundError("mission not found")
            return self._mission_dict(row)
        finally:
            if owned:
                connection.close()

    def record_event(self, mission_id: str, event_type: str, payload: dict[str, Any], source: str, source_event_id: str | None = None) -> dict[str, Any]:
        with self._lock, self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            mission = db.execute("SELECT * FROM missions WHERE mission_id = ?", (mission_id,)).fetchone()
            if not mission:
                raise NotFoundError("mission not found")
            event_mission_id = payload.get("mission_id")
            event_task_id = payload.get("rmf_task_id")
            if event_mission_id is not None and event_mission_id != mission_id:
                raise ConflictError("event belongs to a different mission")
            if event_task_id is not None and mission["rmf_task_id"] and event_task_id != mission["rmf_task_id"]:
                raise ConflictError("event belongs to a different RMF task")
            if source_event_id and db.execute(
                "SELECT 1 FROM events WHERE source = ? AND source_event_id = ?",
                (source, source_event_id),
            ).fetchone():
                return self.get_mission(mission_id, db)
            self._event(db, mission_id, event_type, source, payload, source_event_id)
            updates: dict[str, Any] = {}
            if event_type == "queued":
                updates = {"submission": "rmf_queued", "execution": "queued"}
            elif event_type == "underway":
                updates = {"submission": "rmf_queued", "execution": "underway"}
            elif event_type == "selected":
                updates = {"allocation": "selected"}
            elif event_type == "dispatched":
                updates = {"allocation": "dispatched", "execution": "underway", "rmf_task_id": payload.get("rmf_task_id")}
            elif event_type == "failed_to_assign":
                updates = {"allocation": "failed_to_assign"}
            elif event_type == "failed":
                updates = {"execution": "failed"}
            elif event_type == "completed":
                updates = {"execution": "completed"}
            elif event_type == "canceled":
                updates = {"execution": "canceled", "cancellation": "observed"}
            elif event_type == "cancel_requested":
                updates = {"cancellation": "requested"}
            if event_type == "queued" and mission["execution"] in {"underway", "completed", "canceled", "failed"}:
                updates.pop("execution", None)
            if event_type == "selected" and mission["allocation"] == "dispatched":
                updates.clear()
            if updates and mission["execution"] not in {"completed", "canceled", "failed"}:
                assignments = ", ".join(f"{key} = ?" for key in updates)
                values = list(updates.values()) + [mission["revision"] + 1, self._now(), mission_id]
                db.execute(f"UPDATE missions SET {assignments}, revision = ?, updated_at = ? WHERE mission_id = ?", values)
            return self.get_mission(mission_id, db)

    def bind_rmf_task(self, mission_id: str, task_id: str, response: dict[str, Any]) -> dict[str, Any]:
        with self._lock, self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            mission = db.execute("SELECT * FROM missions WHERE mission_id = ?", (mission_id,)).fetchone()
            if not mission:
                raise NotFoundError("mission not found")
            db.execute(
                "UPDATE missions SET rmf_task_id = ?, submission = 'rmf_queued', revision = revision + 1, updated_at = ? WHERE mission_id = ?",
                (task_id, self._now(), mission_id),
            )
            db.execute("UPDATE dispatch_attempts SET state = 'published' WHERE mission_id = ?", (mission_id,))
            self._event(db, mission_id, "bridge.response", "rmf-web", {"task_id": task_id, "response": response}, mission_id + ":rmf-task:" + task_id)
            return self.get_mission(mission_id, db)

    def mark_submission_unknown(self, mission_id: str, reason: str) -> dict[str, Any]:
        with self._lock, self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if not db.execute("SELECT 1 FROM missions WHERE mission_id = ?", (mission_id,)).fetchone():
                raise NotFoundError("mission not found")
            db.execute("UPDATE missions SET submission = 'submission_unknown', revision = revision + 1, updated_at = ? WHERE mission_id = ?", (self._now(), mission_id))
            db.execute("UPDATE dispatch_attempts SET state = 'submission_unknown' WHERE mission_id = ?", (mission_id,))
            self._event(db, mission_id, "bridge.error", "rmf-web", {"reason": reason})
            return self.get_mission(mission_id, db)

    def events(self, mission_id: str) -> list[dict[str, Any]]:
        with self._connect() as db:
            if not db.execute("SELECT 1 FROM missions WHERE mission_id = ?", (mission_id,)).fetchone():
                raise NotFoundError("mission not found")
            return [
                {"event_id": row["event_id"], "event_type": row["event_type"], "source": row["source"],
                 "payload": json.loads(row["payload_json"]), "created_at": row["created_at"]}
                for row in db.execute("SELECT * FROM events WHERE mission_id = ? ORDER BY rowid", (mission_id,))
            ]

    def reset_episode(self) -> dict[str, str]:
        with self._lock, self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("UPDATE episodes SET active = 0 WHERE active = 1")
            now = self._now()
            episode_id = "episode-" + uuid.uuid4().hex[:12]
            generation = "generation-" + uuid.uuid4().hex[:12]
            db.execute("INSERT INTO episodes VALUES (?, ?, 'hotel-demo', 'sha256:4576e4eb1c95cfbb', 1, ?)", (episode_id, generation, now))
            db.execute("UPDATE missions SET freshness = 'generation_changed', updated_at = ? WHERE execution NOT IN ('completed', 'canceled')", (now,))
            return {"episode_id": episode_id, "rmf_generation_id": generation}
