import json
import os
import sqlite3
from pathlib import Path
from typing import Any

from raphael_workspaces.paths import raphael_home


class VCSStorage:
    def __init__(self, db_path: Path | None = None):
        from raphael_contracts import db as rdb

        self._postgres = rdb.is_postgres()
        if self._postgres:
            rdb.ensure_migrations()
            self.db_path = Path("postgres")
        else:
            if db_path is None:
                db_path = raphael_home() / "vcs.db"
            self.db_path = db_path
            self._init_db()

    def _connect_sqlite(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        return conn

    def _init_db(self) -> None:
        with self._connect_sqlite() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS repos (
                    id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL DEFAULT 'default',
                    name TEXT NOT NULL,
                    description TEXT,
                    parent_module_id TEXT,
                    slice_attribution TEXT,
                    PRIMARY KEY (id, workspace_id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS commits (
                    hash TEXT PRIMARY KEY,
                    repo_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL DEFAULT 'default',
                    parent_hash TEXT,
                    author TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    message TEXT,
                    ops JSON,
                    wal_range_start INTEGER,
                    wal_range_end INTEGER,
                    intent_summary TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS refs (
                    name TEXT,
                    repo_id TEXT,
                    workspace_id TEXT NOT NULL DEFAULT 'default',
                    commit_hash TEXT,
                    PRIMARY KEY (name, repo_id, workspace_id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tags (
                    name TEXT,
                    repo_id TEXT,
                    workspace_id TEXT NOT NULL DEFAULT 'default',
                    commit_hash TEXT,
                    PRIMARY KEY (name, repo_id, workspace_id)
                )
                """
            )
            self._migrate_legacy_schema(conn)

    def _migrate_legacy_schema(self, conn: sqlite3.Connection) -> None:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(repos)").fetchall()}
        if "workspace_id" not in cols:
            conn.execute("ALTER TABLE repos ADD COLUMN workspace_id TEXT NOT NULL DEFAULT 'default'")
        if "parent_module_id" not in cols:
            conn.execute("ALTER TABLE repos ADD COLUMN parent_module_id TEXT")
        if "slice_attribution" not in cols:
            conn.execute("ALTER TABLE repos ADD COLUMN slice_attribution TEXT")
        for table in ("commits", "refs", "tags"):
            tcols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
            if "workspace_id" not in tcols:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN workspace_id TEXT NOT NULL DEFAULT 'default'")
        ccols = {r[1] for r in conn.execute("PRAGMA table_info(commits)").fetchall()}
        if "intent_summary" not in ccols:
            conn.execute("ALTER TABLE commits ADD COLUMN intent_summary TEXT")

    def _execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        if self._postgres:
            from raphael_contracts.db import pg_execute

            pg_execute(sql, params)
            return
        with self._connect_sqlite() as conn:
            conn.execute(sql, params)

    def _fetchone(self, sql: str, params: tuple[Any, ...] = ()) -> Any | None:
        if self._postgres:
            from raphael_contracts.db import pg_fetchone

            return pg_fetchone(sql, params)
        with self._connect_sqlite() as conn:
            return conn.execute(sql, params).fetchone()

    def _fetchall(self, sql: str, params: tuple[Any, ...] = ()) -> list[Any]:
        if self._postgres:
            from raphael_contracts.db import pg_fetchall

            return pg_fetchall(sql, params)
        with self._connect_sqlite() as conn:
            return conn.execute(sql, params).fetchall()

    def _upsert_ref(self, name: str, repo_id: str, workspace_id: str, commit_hash: str | None) -> None:
        if self._postgres:
            from raphael_contracts.db import connection

            with connection() as conn:
                conn.execute(
                    """
                    INSERT INTO refs (name, repo_id, workspace_id, commit_hash)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (name, repo_id, workspace_id)
                    DO UPDATE SET commit_hash = EXCLUDED.commit_hash
                    """,
                    (name, repo_id, workspace_id, commit_hash),
                )
                conn.commit()
            return
        with self._connect_sqlite() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO refs (name, repo_id, workspace_id, commit_hash) VALUES (?, ?, ?, ?)",
                (name, repo_id, workspace_id, commit_hash),
            )

    def _upsert_tag(self, name: str, repo_id: str, workspace_id: str, commit_hash: str) -> None:
        if self._postgres:
            from raphael_contracts.db import connection

            with connection() as conn:
                conn.execute(
                    """
                    INSERT INTO tags (name, repo_id, workspace_id, commit_hash)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (name, repo_id, workspace_id)
                    DO UPDATE SET commit_hash = EXCLUDED.commit_hash
                    """,
                    (name, repo_id, workspace_id, commit_hash),
                )
                conn.commit()
            return
        with self._connect_sqlite() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO tags (name, repo_id, workspace_id, commit_hash) VALUES (?, ?, ?, ?)",
                (name, repo_id, workspace_id, commit_hash),
            )

    def create_repo(
        self,
        repo_id: str,
        name: str,
        workspace_id: str = "default",
        description: str | None = None,
        parent_module_id: str | None = None,
        slice_attribution: str | None = None,
    ) -> None:
        self._execute(
            "INSERT INTO repos (id, workspace_id, name, description, parent_module_id, slice_attribution) VALUES (?, ?, ?, ?, ?, ?)",
            (repo_id, workspace_id, name, description, parent_module_id, slice_attribution),
        )

    def get_repo(self, repo_id: str, workspace_id: str = "default") -> dict[str, Any] | None:
        row = self._fetchone(
            "SELECT id, name, description, parent_module_id, slice_attribution FROM repos WHERE id = ? AND workspace_id = ?",
            (repo_id, workspace_id),
        )
        if not row:
            return None
        out: dict[str, Any] = {
            "id": row[0] if not isinstance(row, dict) else row["id"],
            "name": row[1] if not isinstance(row, dict) else row["name"],
            "description": row[2] if not isinstance(row, dict) else row["description"],
        }
        parent = row[3] if not isinstance(row, dict) else row.get("parent_module_id")
        slice_attr = row[4] if not isinstance(row, dict) else row.get("slice_attribution")
        if parent:
            out["parent_module_id"] = parent
        if slice_attr:
            out["slice_attribution"] = slice_attr
        return out

    def list_repos(self, workspace_id: str = "default") -> list[dict[str, Any]]:
        rows = self._fetchall(
            "SELECT id, name, description, parent_module_id, slice_attribution FROM repos WHERE workspace_id = ? ORDER BY name",
            (workspace_id,),
        )
        out: list[dict[str, Any]] = []
        for r in rows:
            item: dict[str, Any] = {
                "id": r[0] if not isinstance(r, dict) else r["id"],
                "name": r[1] if not isinstance(r, dict) else r["name"],
                "description": r[2] if not isinstance(r, dict) else r["description"],
            }
            parent = r[3] if not isinstance(r, dict) else r.get("parent_module_id")
            slice_attr = r[4] if not isinstance(r, dict) else r.get("slice_attribution")
            if parent:
                item["parent_module_id"] = parent
            if slice_attr:
                item["slice_attribution"] = slice_attr
            out.append(item)
        return out

    def add_commit(
        self,
        commit_hash: str,
        repo_id: str,
        workspace_id: str,
        parent_hash: str | None,
        author: str,
        message: str,
        ops: str,
        wal_start: int,
        wal_end: int,
        intent_summary: str | None = None,
    ) -> None:
        ops_value: Any = ops
        if self._postgres:
            ops_value = json.loads(ops) if isinstance(ops, str) else ops
        self._execute(
            """
            INSERT INTO commits (hash, repo_id, workspace_id, parent_hash, author, message, ops, wal_range_start, wal_range_end, intent_summary)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (commit_hash, repo_id, workspace_id, parent_hash, author, message, ops_value, wal_start, wal_end, intent_summary),
        )

    def get_commit(self, commit_hash: str, repo_id: str, workspace_id: str = "default") -> dict[str, Any] | None:
        row = self._fetchone(
            """
            SELECT hash, parent_hash, author, timestamp, message, ops, wal_range_start, wal_range_end, intent_summary
            FROM commits WHERE hash = ? AND repo_id = ? AND workspace_id = ?
            """,
            (commit_hash, repo_id, workspace_id),
        )
        if not row:
            return None
        if isinstance(row, dict):
            ops = row["ops"]
            return {
                "hash": row["hash"],
                "parent_hash": row["parent_hash"],
                "author": row["author"],
                "timestamp": str(row["timestamp"]) if row.get("timestamp") else None,
                "message": row["message"],
                "ops": json.dumps(ops) if not isinstance(ops, str) else ops,
                "wal_range_start": row["wal_range_start"],
                "wal_range_end": row["wal_range_end"],
                "intent_summary": row.get("intent_summary"),
            }
        return {
            "hash": row[0],
            "parent_hash": row[1],
            "author": row[2],
            "timestamp": row[3],
            "message": row[4],
            "ops": row[5],
            "wal_range_start": row[6],
            "wal_range_end": row[7],
            "intent_summary": row[8],
        }

    def set_commit_intent(self, commit_hash: str, repo_id: str, workspace_id: str, intent_summary: str) -> None:
        self._execute(
            "UPDATE commits SET intent_summary = ? WHERE hash = ? AND repo_id = ? AND workspace_id = ?",
            (intent_summary, commit_hash, repo_id, workspace_id),
        )

    def update_ref(self, name: str, repo_id: str, workspace_id: str, commit_hash: str | None) -> None:
        self._upsert_ref(name, repo_id, workspace_id, commit_hash)

    def get_ref(self, name: str, repo_id: str, workspace_id: str = "default") -> str | None:
        row = self._fetchone(
            "SELECT commit_hash FROM refs WHERE name = ? AND repo_id = ? AND workspace_id = ?",
            (name, repo_id, workspace_id),
        )
        if not row:
            return None
        return row[0] if not isinstance(row, dict) else row["commit_hash"]

    def ref_exists(self, name: str, repo_id: str, workspace_id: str = "default") -> bool:
        row = self._fetchone(
            "SELECT 1 FROM refs WHERE name = ? AND repo_id = ? AND workspace_id = ?",
            (name, repo_id, workspace_id),
        )
        return row is not None

    def get_commits(self, repo_id: str, workspace_id: str = "default") -> list[dict[str, Any]]:
        order = "ORDER BY id DESC" if self._postgres else "ORDER BY rowid DESC"
        rows = self._fetchall(
            f"""
            SELECT hash, parent_hash, author, timestamp, message, ops, wal_range_start, wal_range_end, intent_summary
            FROM commits WHERE repo_id = ? AND workspace_id = ? {order}
            """,
            (repo_id, workspace_id),
        )
        commits: list[dict[str, Any]] = []
        for r in rows:
            if isinstance(r, dict):
                ops = r["ops"]
                commits.append(
                    {
                        "hash": r["hash"],
                        "parent_hash": r["parent_hash"],
                        "author": r["author"],
                        "timestamp": str(r["timestamp"]) if r.get("timestamp") else None,
                        "message": r["message"],
                        "ops": json.dumps(ops) if not isinstance(ops, str) else ops,
                        "wal_range_start": r["wal_range_start"],
                        "wal_range_end": r["wal_range_end"],
                        "intent_summary": r.get("intent_summary"),
                    }
                )
            else:
                commits.append(
                    {
                        "hash": r[0],
                        "parent_hash": r[1],
                        "author": r[2],
                        "timestamp": r[3],
                        "message": r[4],
                        "ops": r[5],
                        "wal_range_start": r[6],
                        "wal_range_end": r[7],
                        "intent_summary": r[8],
                    }
                )
        return commits

    def get_last_wal_index(self, repo_id: str, branch: str, workspace_id: str = "default") -> int:
        row = self._fetchone(
            """
            SELECT wal_range_end FROM commits
            WHERE repo_id = ? AND workspace_id = ? AND hash = (
                SELECT commit_hash FROM refs WHERE name = ? AND repo_id = ? AND workspace_id = ?
            )
            """,
            (repo_id, workspace_id, branch, repo_id, workspace_id),
        )
        if row:
            val = row[0] if not isinstance(row, dict) else row["wal_range_end"]
            if val is not None:
                return int(val)
        return 0

    def add_tag(self, name: str, repo_id: str, workspace_id: str, commit_hash: str) -> None:
        self._upsert_tag(name, repo_id, workspace_id, commit_hash)

    def get_tags(self, repo_id: str, workspace_id: str = "default") -> list[dict[str, Any]]:
        rows = self._fetchall(
            "SELECT name, commit_hash FROM tags WHERE repo_id = ? AND workspace_id = ?",
            (repo_id, workspace_id),
        )
        return [
            {
                "name": r[0] if not isinstance(r, dict) else r["name"],
                "commit_hash": r[1] if not isinstance(r, dict) else r["commit_hash"],
            }
            for r in rows
        ]

    def list_branches(self, repo_id: str, workspace_id: str = "default") -> list[dict[str, Any]]:
        rows = self._fetchall(
            "SELECT name, commit_hash FROM refs WHERE repo_id = ? AND workspace_id = ? ORDER BY name",
            (repo_id, workspace_id),
        )
        return [
            {
                "name": r[0] if not isinstance(r, dict) else r["name"],
                "commit_hash": r[1] if not isinstance(r, dict) else r["commit_hash"],
            }
            for r in rows
        ]

    def copy_repo(
        self,
        source_id: str,
        target_id: str,
        workspace_id: str,
        name: str,
        parent_module_id: str | None = None,
        slice_attribution: str | None = None,
    ) -> None:
        """Deep-copy repo refs/commits/tags within a workspace (fork/slice)."""
        src = self.get_repo(source_id, workspace_id)
        if not src:
            raise ValueError(f"Source repo {source_id} not found")
        self.create_repo(
            target_id,
            name,
            workspace_id,
            src.get("description"),
            parent_module_id,
            slice_attribution,
        )
        commits = self.get_commits(source_id, workspace_id)
        hash_map: dict[str, str] = {}
        for c in reversed(commits):
            new_hash = f"{c['hash'][:16]}-{target_id}"
            hash_map[c["hash"]] = new_hash
            parent = hash_map.get(c["parent_hash"]) if c.get("parent_hash") else None
            self.add_commit(
                new_hash,
                target_id,
                workspace_id,
                parent,
                c["author"],
                c["message"],
                c["ops"],
                c.get("wal_range_start") or 0,
                c.get("wal_range_end") or 0,
                c.get("intent_summary"),
            )
        for ref in self.list_branches(source_id, workspace_id):
            mapped = hash_map.get(ref["commit_hash"]) if ref["commit_hash"] else None
            self.update_ref(ref["name"], target_id, workspace_id, mapped)
        for tag in self.get_tags(source_id, workspace_id):
            mapped = hash_map.get(tag["commit_hash"])
            if mapped:
                self.add_tag(tag["name"], target_id, workspace_id, mapped)
