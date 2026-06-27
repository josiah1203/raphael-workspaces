"""Module file metadata and blob storage."""

from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import uuid
from pathlib import Path
from typing import Any

from raphael_artifacts.module_files import build_module_file_key
from raphael_contracts.vcs import FileTreeEntryKind

from raphael_workspaces.paths import raphael_home


def _blob_key(workspace_id: str, module_id: str, branch: str, path: str) -> str:
    return build_module_file_key(workspace_id, module_id, branch, path)


def _guess_content_type(path: str, explicit: str | None) -> str:
    if explicit:
        return explicit
    guessed, _ = mimetypes.guess_type(path)
    return guessed or "text/plain"


def _is_binary_content_type(content_type: str) -> bool:
    return not content_type.startswith("text/") and content_type not in (
        "application/json",
        "application/xml",
        "application/javascript",
    )


class ModuleFilesStore:
    def __init__(self, db_path: Path | None = None) -> None:
        from raphael_contracts import db as rdb

        self._postgres = rdb.is_postgres()
        if self._postgres:
            rdb.ensure_migrations()
            self.db_path = Path("postgres")
        else:
            self.db_path = db_path or raphael_home() / "module-files.db"
            self._init_sqlite()

    def _connect_sqlite(self):
        import sqlite3

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        return sqlite3.connect(self.db_path)

    def _init_sqlite(self) -> None:
        with self._connect_sqlite() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS module_files (
                    workspace_id TEXT NOT NULL,
                    module_id TEXT NOT NULL,
                    branch TEXT NOT NULL DEFAULT 'main',
                    path TEXT NOT NULL,
                    blob_key TEXT,
                    size INTEGER NOT NULL DEFAULT 0,
                    content_type TEXT,
                    is_binary INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (workspace_id, module_id, branch, path)
                );
                """
            )

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

    def _size_column(self) -> str:
        return "size_bytes" if self._postgres else "size"

    def list_tree(self, workspace_id: str, module_id: str, branch: str, path: str) -> list[dict[str, Any]]:
        prefix = path.strip("/")
        if prefix:
            prefix = prefix + "/"
        size_col = self._size_column()
        rows = self._fetchall(
            f"""
            SELECT path, {size_col}, content_type, is_binary
            FROM module_files
            WHERE workspace_id = ? AND module_id = ? AND branch = ?
            """,
            (workspace_id, module_id, branch),
        )
        entries: dict[str, dict[str, Any]] = {}
        for row in rows:
            rel = row["path"] if isinstance(row, dict) else row[0]
            if prefix and not rel.startswith(prefix):
                continue
            remainder = rel[len(prefix) :] if prefix else rel
            if not remainder:
                continue
            segment = remainder.split("/", 1)[0]
            child_path = f"{prefix}{segment}".rstrip("/") if prefix else segment
            if segment in entries:
                continue
            is_dir = "/" in remainder
            if is_dir:
                entries[segment] = {
                    "name": segment,
                    "path": child_path,
                    "kind": FileTreeEntryKind.DIRECTORY.value,
                    "size": None,
                    "is_binary": False,
                }
            else:
                size = row[size_col] if isinstance(row, dict) else row[1]
                content_type = row["content_type"] if isinstance(row, dict) else row[2]
                is_binary = row["is_binary"] if isinstance(row, dict) else row[3]
                entries[segment] = {
                    "name": segment,
                    "path": rel,
                    "kind": FileTreeEntryKind.FILE.value,
                    "size": size,
                    "content_type": content_type,
                    "is_binary": bool(is_binary),
                }
        return sorted(entries.values(), key=lambda e: (e["kind"] != "directory", e["name"]))

    def get_blob(
        self, workspace_id: str, module_id: str, branch: str, path: str
    ) -> dict[str, Any] | None:
        size_col = self._size_column()
        row = self._fetchone(
            f"""
            SELECT path, blob_key, {size_col}, content_type, is_binary
            FROM module_files
            WHERE workspace_id = ? AND module_id = ? AND branch = ? AND path = ?
            """,
            (workspace_id, module_id, branch, path),
        )
        if not row:
            return None
        if isinstance(row, dict):
            blob_key = row["blob_key"]
            size = row[size_col]
            content_type = row["content_type"]
            is_binary = row["is_binary"]
        else:
            _, blob_key, size, content_type, is_binary = row
        from raphael_artifacts.blob import get_blob

        data = get_blob(blob_key) if blob_key else None
        if data is None:
            return None
        content_type = content_type or "application/octet-stream"
        is_binary = bool(is_binary)
        result: dict[str, Any] = {
            "path": path,
            "branch": branch,
            "size": size,
            "content_type": content_type,
            "is_binary": is_binary,
            "encoding": "utf-8",
            "sha": hashlib.sha256(data).hexdigest(),
            "is_large": size > 1_048_576,
        }
        if is_binary:
            result["content_base64"] = base64.b64encode(data).decode("ascii")
        else:
            result["content"] = data.decode("utf-8")
            result["line_count"] = result["content"].count("\n") + (1 if result["content"] else 0)
        return result

    def put_blob(
        self,
        workspace_id: str,
        module_id: str,
        branch: str,
        path: str,
        *,
        content: str | None = None,
        content_base64: str | None = None,
        content_type: str | None = None,
        message: str | None = None,
    ) -> dict[str, Any]:
        if content_base64 is not None:
            data = base64.b64decode(content_base64)
            is_binary = True
        elif content is not None:
            data = content.encode("utf-8")
            is_binary = False
        else:
            raise ValueError("content_required")

        content_type = _guess_content_type(path, content_type)
        if content is not None and not content_type.startswith("text/"):
            is_binary = _is_binary_content_type(content_type) or is_binary

        key = _blob_key(workspace_id, module_id, branch, path)
        from raphael_artifacts.blob import put_blob

        stored_key = put_blob(key, data, content_type)
        size = len(data)
        sha = hashlib.sha256(data).hexdigest()

        if self._postgres:
            from raphael_contracts.db import connection

            with connection() as conn:
                conn.execute(
                    """
                    INSERT INTO module_files
                        (workspace_id, module_id, branch, path, blob_key, size_bytes, content_type, is_binary)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (workspace_id, module_id, branch, path)
                    DO UPDATE SET
                        blob_key = EXCLUDED.blob_key,
                        size_bytes = EXCLUDED.size_bytes,
                        content_type = EXCLUDED.content_type,
                        is_binary = EXCLUDED.is_binary,
                        updated_at = NOW()
                    """,
                    (workspace_id, module_id, branch, path, stored_key, size, content_type, is_binary),
                )
                conn.commit()
        else:
            with self._connect_sqlite() as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO module_files
                        (workspace_id, module_id, branch, path, blob_key, size, content_type, is_binary)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (workspace_id, module_id, branch, path, stored_key, size, content_type, int(is_binary)),
                )

        return {
            "path": path,
            "branch": branch,
            "size": size,
            "is_binary": is_binary,
            "sha": sha,
            "message": message,
            "is_large": size > 1_048_576,
        }
