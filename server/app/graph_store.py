from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Literal

ListKind = Literal["followers", "following"]


class GraphStore:
    """Persistent, shared cache for public profile and relationship pages.

    The cache is intentionally keyed by Instagram username/user id rather than by
    FollowCheck visitor, so one successful public fetch can be reused by every
    visitor until it expires.
    """

    def __init__(self, path: str | Path, profile_ttl: int, page_ttl: int) -> None:
        self.path = Path(path)
        self.profile_ttl = max(0, int(profile_ttl))
        self.page_ttl = max(0, int(page_ttl))
        self._lock = threading.RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_db(self) -> None:
        with self._lock, self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS profiles (
                    handle TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    fetched_at REAL NOT NULL,
                    expires_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS pages (
                    handle TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    cursor_key TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    fetched_at REAL NOT NULL,
                    expires_at REAL NOT NULL,
                    PRIMARY KEY (handle, kind, cursor_key)
                );

                CREATE TABLE IF NOT EXISTS accounts (
                    user_id TEXT PRIMARY KEY,
                    username_lower TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    updated_at REAL NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_accounts_username
                    ON accounts(username_lower);

                CREATE TABLE IF NOT EXISTS edges (
                    subject_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    object_id TEXT NOT NULL,
                    username_lower TEXT NOT NULL,
                    seen_at REAL NOT NULL,
                    PRIMARY KEY (subject_id, kind, object_id)
                );

                CREATE INDEX IF NOT EXISTS idx_edges_subject_kind
                    ON edges(subject_id, kind);

                CREATE TABLE IF NOT EXISTS snapshots (
                    subject_id TEXT NOT NULL,
                    handle TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    expected_count INTEGER NOT NULL DEFAULT 0,
                    collected_count INTEGER NOT NULL DEFAULT 0,
                    complete INTEGER NOT NULL DEFAULT 0,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (subject_id, kind)
                );
                """
            )

    @staticmethod
    def _normalize_handle(handle: str) -> str:
        return str(handle or "").strip().lower()

    @staticmethod
    def _cursor_key(cursor: str | None) -> str:
        return str(cursor or "")

    def get_profile(self, handle: str) -> dict[str, Any] | None:
        key = self._normalize_handle(handle)
        now = time.time()
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT payload_json, expires_at FROM profiles WHERE handle = ?",
                (key,),
            ).fetchone()
            if row is None:
                return None
            if float(row["expires_at"]) <= now:
                conn.execute("DELETE FROM profiles WHERE handle = ?", (key,))
                return None
            return json.loads(str(row["payload_json"]))

    def set_profile(self, handle: str, payload: dict[str, Any]) -> None:
        if self.profile_ttl <= 0:
            return
        key = self._normalize_handle(handle)
        now = time.time()
        user_id = str(payload.get("id") or "")
        if not key or not user_id:
            return
        encoded = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO profiles(handle, user_id, payload_json, fetched_at, expires_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(handle) DO UPDATE SET
                    user_id = excluded.user_id,
                    payload_json = excluded.payload_json,
                    fetched_at = excluded.fetched_at,
                    expires_at = excluded.expires_at
                """,
                (key, user_id, encoded, now, now + self.profile_ttl),
            )

    def get_page(self, handle: str, kind: ListKind, cursor: str | None) -> dict[str, Any] | None:
        key = self._normalize_handle(handle)
        cursor_key = self._cursor_key(cursor)
        now = time.time()
        with self._lock, self._connect() as conn:
            row = conn.execute(
                """
                SELECT payload_json, expires_at
                FROM pages
                WHERE handle = ? AND kind = ? AND cursor_key = ?
                """,
                (key, kind, cursor_key),
            ).fetchone()
            if row is None:
                return None
            if float(row["expires_at"]) <= now:
                conn.execute(
                    "DELETE FROM pages WHERE handle = ? AND kind = ? AND cursor_key = ?",
                    (key, kind, cursor_key),
                )
                return None
            return json.loads(str(row["payload_json"]))

    def set_page(
        self,
        handle: str,
        subject_id: str,
        kind: ListKind,
        cursor: str | None,
        payload: dict[str, Any],
        expected_count: int,
    ) -> None:
        if self.page_ttl <= 0:
            return
        key = self._normalize_handle(handle)
        cursor_key = self._cursor_key(cursor)
        now = time.time()
        encoded = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
        items = payload.get("items") if isinstance(payload, dict) else []
        if not isinstance(items, list):
            items = []

        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO pages(handle, kind, cursor_key, payload_json, fetched_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(handle, kind, cursor_key) DO UPDATE SET
                    payload_json = excluded.payload_json,
                    fetched_at = excluded.fetched_at,
                    expires_at = excluded.expires_at
                """,
                (key, kind, cursor_key, encoded, now, now + self.page_ttl),
            )

            for item in items:
                if not isinstance(item, dict):
                    continue
                object_id = str(item.get("id") or "")
                username = str(item.get("username") or "").strip()
                if not object_id or not username:
                    continue
                item_json = json.dumps(item, separators=(",", ":"), ensure_ascii=False)
                conn.execute(
                    """
                    INSERT INTO accounts(user_id, username_lower, payload_json, updated_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(user_id) DO UPDATE SET
                        username_lower = excluded.username_lower,
                        payload_json = excluded.payload_json,
                        updated_at = excluded.updated_at
                    """,
                    (object_id, username.lower(), item_json, now),
                )
                conn.execute(
                    """
                    INSERT INTO edges(subject_id, kind, object_id, username_lower, seen_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(subject_id, kind, object_id) DO UPDATE SET
                        username_lower = excluded.username_lower,
                        seen_at = excluded.seen_at
                    """,
                    (subject_id, kind, object_id, username.lower(), now),
                )

            collected = int(
                conn.execute(
                    "SELECT COUNT(*) AS n FROM edges WHERE subject_id = ? AND kind = ?",
                    (subject_id, kind),
                ).fetchone()["n"]
            )
            complete = 0 if payload.get("next_cursor") else 1
            conn.execute(
                """
                INSERT INTO snapshots(
                    subject_id, handle, kind, expected_count, collected_count, complete, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(subject_id, kind) DO UPDATE SET
                    handle = excluded.handle,
                    expected_count = excluded.expected_count,
                    collected_count = excluded.collected_count,
                    complete = excluded.complete,
                    updated_at = excluded.updated_at
                """,
                (subject_id, key, kind, max(0, int(expected_count)), collected, complete, now),
            )

    def status(self, handle: str) -> dict[str, Any]:
        key = self._normalize_handle(handle)
        with self._lock, self._connect() as conn:
            profile = conn.execute(
                "SELECT user_id FROM profiles WHERE handle = ?",
                (key,),
            ).fetchone()
            if profile is None:
                return {"handle": key, "cached": False, "snapshots": {}}
            rows = conn.execute(
                """
                SELECT kind, expected_count, collected_count, complete, updated_at
                FROM snapshots
                WHERE subject_id = ?
                """,
                (str(profile["user_id"]),),
            ).fetchall()
            snapshots = {
                str(row["kind"]): {
                    "expected": int(row["expected_count"]),
                    "collected": int(row["collected_count"]),
                    "complete": bool(row["complete"]),
                    "updated_at": float(row["updated_at"]),
                }
                for row in rows
            }
            return {"handle": key, "cached": True, "snapshots": snapshots}
