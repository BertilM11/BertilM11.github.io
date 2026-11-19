"""Persistencia SQLite: trabajos (cola persistente), dispositivos y consumo diario."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    owner TEXT NOT NULL,
    client_job_id TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at REAL NOT NULL DEFAULT 0,
    heartbeat_at REAL,
    last_error TEXT,
    options TEXT NOT NULL DEFAULT '{}',
    image_hashes TEXT NOT NULL,
    image_count INTEGER NOT NULL,
    title TEXT,
    relevant INTEGER,
    result_json TEXT,
    files_json TEXT NOT NULL DEFAULT '[]',
    completed_at REAL,
    acked_at REAL,
    push_sent INTEGER NOT NULL DEFAULT 0,
    alert_sent INTEGER NOT NULL DEFAULT 0,
    UNIQUE(owner, client_job_id)
);
CREATE INDEX IF NOT EXISTS jobs_status ON jobs(status, next_attempt_at);
CREATE INDEX IF NOT EXISTS jobs_owner ON jobs(owner, created_at);
CREATE TABLE IF NOT EXISTS devices (
    owner TEXT NOT NULL,
    apns_token TEXT NOT NULL,
    environment TEXT NOT NULL,
    updated_at REAL NOT NULL,
    PRIMARY KEY(owner, apns_token)
);
CREATE TABLE IF NOT EXISTS usage (
    owner TEXT NOT NULL,
    day TEXT NOT NULL,
    jobs INTEGER NOT NULL DEFAULT 0,
    images INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(owner, day)
);
"""

# Estados de un trabajo en el servidor.
QUEUED = "queued"
PROCESSING = "processing"
COMPLETED = "completed"
FAILED = "failed"
ACKNOWLEDGED = "acknowledged"
EXPIRED = "expired"
ALL_STATUSES = {QUEUED, PROCESSING, COMPLETED, FAILED, ACKNOWLEDGED, EXPIRED}


@dataclass
class Job:
    id: str
    owner: str
    client_job_id: str
    status: str
    created_at: float
    updated_at: float
    attempts: int
    next_attempt_at: float
    heartbeat_at: float | None
    last_error: str | None
    options: dict[str, Any]
    image_hashes: list[str]
    image_count: int
    title: str | None
    relevant: bool | None
    result: dict[str, Any] | None
    files: list[dict[str, Any]] = field(default_factory=list)
    completed_at: float | None = None
    acked_at: float | None = None
    push_sent: bool = False
    alert_sent: bool = False

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Job":
        return cls(
            id=row["id"],
            owner=row["owner"],
            client_job_id=row["client_job_id"],
            status=row["status"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            attempts=row["attempts"],
            next_attempt_at=row["next_attempt_at"],
            heartbeat_at=row["heartbeat_at"],
            last_error=row["last_error"],
            options=json.loads(row["options"] or "{}"),
            image_hashes=[h for h in row["image_hashes"].split(",") if h],
            image_count=row["image_count"],
            title=row["title"],
            relevant=None if row["relevant"] is None else bool(row["relevant"]),
            result=json.loads(row["result_json"]) if row["result_json"] else None,
            files=json.loads(row["files_json"] or "[]"),
            completed_at=row["completed_at"],
            acked_at=row["acked_at"],
            push_sent=bool(row["push_sent"]),
            alert_sent=bool(row["alert_sent"]),
        )


class Database:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        with self.connect() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        with self._lock, self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise

    # ------------------------------------------------------------------ jobs
    def find_by_client_id(self, owner: str, client_job_id: str) -> Job | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM jobs WHERE owner=? AND client_job_id=?", (owner, client_job_id)
            ).fetchone()
        return Job.from_row(row) if row else None

    def find_by_image_hashes(self, owner: str, hashes: list[str], since: float) -> Job | None:
        """Devuelve un trabajo previo con exactamente las mismas imágenes (no fallido)."""
        key = ",".join(sorted(hashes))
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM jobs WHERE owner=? AND image_hashes=? AND created_at>=? "
                "AND status NOT IN (?, ?) ORDER BY created_at DESC LIMIT 1",
                (owner, key, since, FAILED, EXPIRED),
            ).fetchone()
        return Job.from_row(row) if row else None

    def create_job(
        self,
        conn: sqlite3.Connection,
        *,
        owner: str,
        client_job_id: str,
        image_hashes: list[str],
        options: dict[str, Any],
        job_id: str | None = None,
        image_count: int | None = None,
    ) -> Job:
        now = time.time()
        job_id = job_id or uuid.uuid4().hex
        conn.execute(
            "INSERT INTO jobs (id, owner, client_job_id, status, created_at, updated_at, options, "
            "image_hashes, image_count) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                job_id,
                owner,
                client_job_id,
                QUEUED,
                now,
                now,
                json.dumps(options),
                ",".join(sorted(image_hashes)),
                len(image_hashes) if image_count is None else image_count,
            ),
        )
        row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return Job.from_row(row)

    def get_job(self, job_id: str, owner: str | None = None) -> Job | None:
        with self.connect() as conn:
            if owner is None:
                row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            else:
                row = conn.execute("SELECT * FROM jobs WHERE id=? AND owner=?", (job_id, owner)).fetchone()
        return Job.from_row(row) if row else None

    def list_jobs(self, owner: str, statuses: set[str] | None = None, limit: int = 50) -> list[Job]:
        q = "SELECT * FROM jobs WHERE owner=?"
        args: list[Any] = [owner]
        if statuses:
            q += " AND status IN (%s)" % ",".join("?" * len(statuses))
            args.extend(sorted(statuses))
        q += " ORDER BY created_at DESC LIMIT ?"
        args.append(limit)
        with self.connect() as conn:
            return [Job.from_row(r) for r in conn.execute(q, args).fetchall()]

    def claim_next(self, now: float | None = None) -> Job | None:
        """Reclama atómicamente el siguiente trabajo listo de la cola."""
        now = now or time.time()
        with self.tx() as conn:
            row = conn.execute(
                "SELECT * FROM jobs WHERE status=? AND next_attempt_at<=? ORDER BY created_at LIMIT 1",
                (QUEUED, now),
            ).fetchone()
            if not row:
                return None
            conn.execute(
                "UPDATE jobs SET status=?, attempts=attempts+1, heartbeat_at=?, updated_at=? WHERE id=?",
                (PROCESSING, now, now, row["id"]),
            )
            row = conn.execute("SELECT * FROM jobs WHERE id=?", (row["id"],)).fetchone()
        return Job.from_row(row)

    def heartbeat(self, job_id: str) -> None:
        now = time.time()
        with self.tx() as conn:
            conn.execute("UPDATE jobs SET heartbeat_at=?, updated_at=? WHERE id=?", (now, now, job_id))

    def requeue_stale(self, stale_seconds: float) -> int:
        """Recupera trabajos que quedaron 'processing' (p. ej. tras un reinicio)."""
        limit = time.time() - stale_seconds
        with self.tx() as conn:
            cur = conn.execute(
                "UPDATE jobs SET status=?, updated_at=? WHERE status=? AND (heartbeat_at IS NULL OR heartbeat_at<?)",
                (QUEUED, time.time(), PROCESSING, limit),
            )
            return cur.rowcount

    def mark_completed(
        self, job_id: str, *, title: str | None, relevant: bool, result: dict[str, Any], files: list[dict[str, Any]]
    ) -> None:
        now = time.time()
        with self.tx() as conn:
            conn.execute(
                "UPDATE jobs SET status=?, title=?, relevant=?, result_json=?, files_json=?, completed_at=?, "
                "updated_at=?, last_error=NULL WHERE id=?",
                (COMPLETED, title, int(relevant), json.dumps(result), json.dumps(files), now, now, job_id),
            )

    def mark_retry(self, job_id: str, error: str, delay: float) -> None:
        now = time.time()
        with self.tx() as conn:
            conn.execute(
                "UPDATE jobs SET status=?, last_error=?, next_attempt_at=?, updated_at=? WHERE id=?",
                (QUEUED, error[:2000], now + delay, now, job_id),
            )

    def mark_failed(self, job_id: str, error: str) -> None:
        now = time.time()
        with self.tx() as conn:
            conn.execute(
                "UPDATE jobs SET status=?, last_error=?, updated_at=? WHERE id=?",
                (FAILED, error[:2000], now, job_id),
            )

    def requeue_failed(self, job_id: str, owner: str) -> bool:
        now = time.time()
        with self.tx() as conn:
            cur = conn.execute(
                "UPDATE jobs SET status=?, attempts=0, next_attempt_at=0, last_error=NULL, updated_at=? "
                "WHERE id=? AND owner=? AND status=?",
                (QUEUED, now, job_id, owner, FAILED),
            )
            return cur.rowcount == 1

    def mark_acknowledged(self, job_id: str, owner: str) -> bool:
        now = time.time()
        with self.tx() as conn:
            cur = conn.execute(
                "UPDATE jobs SET status=?, acked_at=?, updated_at=? WHERE id=? AND owner=? AND status IN (?, ?)",
                (ACKNOWLEDGED, now, now, job_id, owner, COMPLETED, ACKNOWLEDGED),
            )
            return cur.rowcount == 1

    def set_flag(self, job_id: str, flag: str) -> None:
        if flag not in {"push_sent", "alert_sent"}:
            raise ValueError(flag)
        with self.tx() as conn:
            conn.execute(f"UPDATE jobs SET {flag}=1 WHERE id=?", (job_id,))

    def jobs_needing_alert(self, older_than: float) -> list[Job]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM jobs WHERE status=? AND alert_sent=0 AND completed_at<=?",
                (COMPLETED, older_than),
            ).fetchall()
        return [Job.from_row(r) for r in rows]

    def jobs_to_expire(self, acked_before: float, unacked_before: float) -> list[Job]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM jobs WHERE (status=? AND acked_at<=?) OR (status=? AND completed_at<=?) "
                "OR (status=? AND updated_at<=?)",
                (ACKNOWLEDGED, acked_before, COMPLETED, unacked_before, FAILED, unacked_before),
            ).fetchall()
        return [Job.from_row(r) for r in rows]

    def mark_expired(self, job_id: str) -> None:
        with self.tx() as conn:
            conn.execute(
                "UPDATE jobs SET status=?, files_json='[]', result_json=NULL, updated_at=? WHERE id=?",
                (EXPIRED, time.time(), job_id),
            )

    # --------------------------------------------------------------- devices
    def upsert_device(self, owner: str, token: str, environment: str) -> None:
        with self.tx() as conn:
            conn.execute(
                "INSERT INTO devices (owner, apns_token, environment, updated_at) VALUES (?,?,?,?) "
                "ON CONFLICT(owner, apns_token) DO UPDATE SET environment=excluded.environment, "
                "updated_at=excluded.updated_at",
                (owner, token, environment, time.time()),
            )

    def remove_device(self, token: str) -> None:
        with self.tx() as conn:
            conn.execute("DELETE FROM devices WHERE apns_token=?", (token,))

    def devices_for(self, owner: str) -> list[tuple[str, str]]:
        with self.connect() as conn:
            return [
                (r["apns_token"], r["environment"])
                for r in conn.execute("SELECT * FROM devices WHERE owner=?", (owner,)).fetchall()
            ]

    # ----------------------------------------------------------------- usage
    def usage_today(self, conn: sqlite3.Connection, owner: str, day: str) -> tuple[int, int]:
        row = conn.execute("SELECT jobs, images FROM usage WHERE owner=? AND day=?", (owner, day)).fetchone()
        return (row["jobs"], row["images"]) if row else (0, 0)

    def add_usage(self, conn: sqlite3.Connection, owner: str, day: str, images: int) -> None:
        conn.execute(
            "INSERT INTO usage (owner, day, jobs, images) VALUES (?,?,1,?) "
            "ON CONFLICT(owner, day) DO UPDATE SET jobs=jobs+1, images=images+excluded.images",
            (owner, day, images),
        )
