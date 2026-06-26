"""Workspaces and modules store — migrated from calliope-vcs concepts."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class WorkspacesStore:
    def __init__(self, db_path: Path | None = None) -> None:
        path = db_path or Path(os.environ.get("RAPHAEL_WORKSPACES_DB", "/tmp/raphael-workspaces.db"))
        self.db_path = path
        self._init_db()
        self._seed()

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS workspaces (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT
                );
                CREATE TABLE IF NOT EXISTS modules (
                    id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    description TEXT
                );
                CREATE TABLE IF NOT EXISTS refs (
                    workspace_id TEXT NOT NULL,
                    module_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    commit_hash TEXT,
                    PRIMARY KEY (workspace_id, module_id, name)
                );
                CREATE TABLE IF NOT EXISTS commits (
                    hash TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    module_id TEXT NOT NULL,
                    parent_hash TEXT,
                    author TEXT,
                    message TEXT,
                    timestamp TEXT,
                    ops TEXT
                );
                """
            )

    def _seed(self) -> None:
        with self._conn() as conn:
            if conn.execute("SELECT COUNT(*) FROM workspaces").fetchone()[0] == 0:
                conn.execute("INSERT INTO workspaces (id, name) VALUES ('default', 'Default Workspace')")
                conn.execute(
                    "INSERT INTO modules (id, workspace_id, name) VALUES ('power-board-v2', 'default', 'Power Board V2')"
                )
                conn.execute(
                    "INSERT INTO refs (workspace_id, module_id, name, commit_hash) VALUES ('default', 'power-board-v2', 'main', 'abc123')"
                )

    def list_modules(self, workspace_id: str) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, name, description FROM modules WHERE workspace_id = ? ORDER BY name",
                (workspace_id,),
            ).fetchall()
        return [{"id": r[0], "name": r[1], "description": r[2]} for r in rows]

    def get_module(self, workspace_id: str, module_id: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT id, name, description FROM modules WHERE workspace_id = ? AND id = ?",
                (workspace_id, module_id),
            ).fetchone()
        if not row:
            return None
        return {"id": row[0], "name": row[1], "description": row[2]}

    def create_module(self, workspace_id: str, module_id: str, name: str) -> dict[str, Any]:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO modules (id, workspace_id, name) VALUES (?, ?, ?)",
                (module_id, workspace_id, name),
            )
            conn.execute(
                "INSERT INTO refs (workspace_id, module_id, name, commit_hash) VALUES (?, ?, 'main', NULL)",
                (workspace_id, module_id),
            )
        return self.get_module(workspace_id, module_id) or {"id": module_id, "name": name}

    def list_branches(self, workspace_id: str, module_id: str) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT name, commit_hash FROM refs WHERE workspace_id = ? AND module_id = ?",
                (workspace_id, module_id),
            ).fetchall()
        return [{"name": r[0], "commit_hash": r[1]} for r in rows]

    def list_commits(self, workspace_id: str, module_id: str, branch: str | None = None) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT hash, parent_hash, author, timestamp, message, ops FROM commits WHERE workspace_id = ? AND module_id = ? ORDER BY timestamp DESC",
                (workspace_id, module_id),
            ).fetchall()
        return [
            {
                "hash": r[0],
                "parent_hash": r[1],
                "author": r[2],
                "timestamp": r[3],
                "message": r[4],
                "ops": r[5],
            }
            for r in rows
        ]

    def create_commit(self, workspace_id: str, module_id: str, message: str, author: str = "user") -> dict[str, Any]:
        h = f"c{int(datetime.now(timezone.utc).timestamp())}"
        ts = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO commits (hash, workspace_id, module_id, message, author, timestamp, ops) VALUES (?, ?, ?, ?, ?, ?, '[]')",
                (h, workspace_id, module_id, message, author, ts),
            )
            conn.execute(
                "UPDATE refs SET commit_hash = ? WHERE workspace_id = ? AND module_id = ? AND name = 'main'",
                (h, workspace_id, module_id),
            )
        return {"hash": h, "message": message, "timestamp": ts}

    def merge_branches(self, workspace_id: str, module_id: str, source: str, target: str) -> dict[str, Any]:
        with self._conn() as conn:
            src = conn.execute(
                "SELECT commit_hash FROM refs WHERE workspace_id = ? AND module_id = ? AND name = ?",
                (workspace_id, module_id, source),
            ).fetchone()
            if not src or not src[0]:
                return {"status": "error", "error": "source_branch_not_found"}
            conn.execute(
                "UPDATE refs SET commit_hash = ? WHERE workspace_id = ? AND module_id = ? AND name = ?",
                (src[0], workspace_id, module_id, target),
            )
        return {"status": "merged", "hash": src[0]}
