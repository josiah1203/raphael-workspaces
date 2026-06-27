"""Repo settings, collaborators, branch protection, and webhooks storage."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from raphael_contracts.vcs import ArtifactType, RepoVisibility

from raphael_workspaces.paths import raphael_home


class RepoSettingsStore:
    def __init__(self, db_path: Path | None = None) -> None:
        from raphael_contracts import db as rdb

        self._postgres = rdb.is_postgres()
        if self._postgres:
            rdb.ensure_migrations()
            self.db_path = Path("postgres")
        else:
            self.db_path = db_path or raphael_home() / "repo-settings.db"
            self._init_sqlite()

    def _connect_sqlite(self):
        import sqlite3

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        return sqlite3.connect(self.db_path)

    def _init_sqlite(self) -> None:
        with self._connect_sqlite() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS repo_settings (
                    workspace_id TEXT NOT NULL,
                    module_id TEXT NOT NULL,
                    visibility TEXT NOT NULL DEFAULT 'private',
                    artifact_type TEXT,
                    license TEXT,
                    description TEXT,
                    default_branch TEXT NOT NULL DEFAULT 'main',
                    PRIMARY KEY (workspace_id, module_id)
                );
                CREATE TABLE IF NOT EXISTS module_collaborators (
                    workspace_id TEXT NOT NULL,
                    module_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'read',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (workspace_id, module_id, user_id)
                );
                CREATE TABLE IF NOT EXISTS branch_protection_rules (
                    id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    module_id TEXT NOT NULL,
                    pattern TEXT NOT NULL,
                    require_reviews INTEGER NOT NULL DEFAULT 0,
                    enforce_admins INTEGER NOT NULL DEFAULT 0,
                    require_status_checks INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS module_webhooks (
                    id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    module_id TEXT NOT NULL,
                    url TEXT NOT NULL,
                    events TEXT NOT NULL DEFAULT '[]',
                    secret TEXT,
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            cols = {r[1] for r in conn.execute("PRAGMA table_info(branch_protection_rules)").fetchall()}
            if "require_status_checks" not in cols:
                conn.execute(
                    "ALTER TABLE branch_protection_rules ADD COLUMN require_status_checks INTEGER NOT NULL DEFAULT 0"
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

    def get_settings(self, workspace_id: str, module_id: str, module_name: str) -> dict[str, Any]:
        row = self._fetchone(
            """
            SELECT visibility, artifact_type, license, description, default_branch
            FROM repo_settings
            WHERE workspace_id = ? AND module_id = ?
            """,
            (workspace_id, module_id),
        )
        if row:
            if isinstance(row, dict):
                visibility, artifact_type, license_, description, default_branch = (
                    row["visibility"],
                    row["artifact_type"],
                    row["license"],
                    row["description"],
                    row["default_branch"],
                )
            else:
                visibility, artifact_type, license_, description, default_branch = row
        else:
            visibility, artifact_type, license_, description, default_branch = (
                RepoVisibility.PRIVATE.value,
                ArtifactType.MIXED.value,
                None,
                None,
                "main",
            )
        return {
            "name": module_name,
            "visibility": visibility,
            "artifact_type": artifact_type or ArtifactType.MIXED.value,
            "license": license_,
            "description": description,
            "default_branch": default_branch,
            "topics": [],
        }

    def patch_settings(self, workspace_id: str, module_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        existing = self._fetchone(
            "SELECT visibility, artifact_type, license, description, default_branch FROM repo_settings WHERE workspace_id = ? AND module_id = ?",
            (workspace_id, module_id),
        )
        if existing:
            if isinstance(existing, dict):
                cur = existing
            else:
                cur = {
                    "visibility": existing[0],
                    "artifact_type": existing[1],
                    "license": existing[2],
                    "description": existing[3],
                    "default_branch": existing[4],
                }
        else:
            cur = {
                "visibility": RepoVisibility.PRIVATE.value,
                "artifact_type": ArtifactType.MIXED.value,
                "license": None,
                "description": None,
                "default_branch": "main",
            }
        for key in ("visibility", "artifact_type", "license", "description", "default_branch"):
            if key in patch and patch[key] is not None:
                cur[key] = patch[key]

        if self._postgres:
            from raphael_contracts.db import connection

            with connection() as conn:
                conn.execute(
                    """
                    INSERT INTO repo_settings
                        (workspace_id, module_id, visibility, artifact_type, license, description, default_branch)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (workspace_id, module_id)
                    DO UPDATE SET
                        visibility = EXCLUDED.visibility,
                        artifact_type = EXCLUDED.artifact_type,
                        license = EXCLUDED.license,
                        description = EXCLUDED.description,
                        default_branch = EXCLUDED.default_branch
                    """,
                    (
                        workspace_id,
                        module_id,
                        cur["visibility"],
                        cur["artifact_type"],
                        cur["license"],
                        cur["description"],
                        cur["default_branch"],
                    ),
                )
                conn.commit()
        else:
            with self._connect_sqlite() as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO repo_settings
                        (workspace_id, module_id, visibility, artifact_type, license, description, default_branch)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        workspace_id,
                        module_id,
                        cur["visibility"],
                        cur["artifact_type"],
                        cur["license"],
                        cur["description"],
                        cur["default_branch"],
                    ),
                )
        return cur

    def list_collaborators(self, workspace_id: str, module_id: str) -> list[dict[str, Any]]:
        rows = self._fetchall(
            """
            SELECT user_id, role FROM module_collaborators
            WHERE workspace_id = ? AND module_id = ?
            ORDER BY user_id
            """,
            (workspace_id, module_id),
        )
        return [
            {"user_id": r["user_id"] if isinstance(r, dict) else r[0], "role": r["role"] if isinstance(r, dict) else r[1]}
            for r in rows
        ]

    def add_collaborator(self, workspace_id: str, module_id: str, user_id: str, role: str) -> dict[str, str]:
        existing = self._fetchone(
            "SELECT 1 FROM module_collaborators WHERE workspace_id = ? AND module_id = ? AND user_id = ?",
            (workspace_id, module_id, user_id),
        )
        if existing:
            raise ValueError("collaborator_exists")
        self._execute(
            """
            INSERT INTO module_collaborators (workspace_id, module_id, user_id, role)
            VALUES (?, ?, ?, ?)
            """,
            (workspace_id, module_id, user_id, role),
        )
        return {"user_id": user_id, "role": role}

    def remove_collaborator(self, workspace_id: str, module_id: str, user_id: str) -> bool:
        if self._postgres:
            from raphael_contracts.db import pg_execute

            cur = pg_execute(
                "DELETE FROM module_collaborators WHERE workspace_id = %s AND module_id = %s AND user_id = %s",
                (workspace_id, module_id, user_id),
            )
            return cur.rowcount > 0
        with self._connect_sqlite() as conn:
            cur = conn.execute(
                "DELETE FROM module_collaborators WHERE workspace_id = ? AND module_id = ? AND user_id = ?",
                (workspace_id, module_id, user_id),
            )
            return cur.rowcount > 0

    def list_branch_protection(self, workspace_id: str, module_id: str) -> list[dict[str, Any]]:
        rows = self._fetchall(
            """
            SELECT id, pattern, require_reviews, enforce_admins, require_status_checks
            FROM branch_protection_rules
            WHERE workspace_id = ? AND module_id = ?
            ORDER BY pattern
            """,
            (workspace_id, module_id),
        )
        rules = []
        for r in rows:
            if isinstance(r, dict):
                rules.append(
                    {
                        "id": r["id"],
                        "branch_pattern": r["pattern"],
                        "require_pr": bool(r["require_reviews"]),
                        "required_review_count": 1 if r["require_reviews"] else 0,
                        "require_status_checks": bool(r.get("require_status_checks", False)),
                        "required_status_checks": [],
                        "restrict_push": bool(r["enforce_admins"]),
                    }
                )
            else:
                rules.append(
                    {
                        "id": r[0],
                        "branch_pattern": r[1],
                        "require_pr": bool(r[2]),
                        "required_review_count": 1 if r[2] else 0,
                        "require_status_checks": bool(r[4]) if len(r) > 4 else False,
                        "required_status_checks": [],
                        "restrict_push": bool(r[3]),
                    }
                )
        return rules

    def add_branch_protection(self, workspace_id: str, module_id: str, body: dict[str, Any]) -> dict[str, Any]:
        rule_id = str(uuid.uuid4())
        pattern = body.get("branch_pattern") or body.get("pattern", "main")
        require_reviews = bool(body.get("require_pr") or body.get("require_reviews"))
        require_status_checks = bool(body.get("require_status_checks"))
        enforce_admins = bool(body.get("restrict_push") or body.get("enforce_admins"))
        self._execute(
            """
            INSERT INTO branch_protection_rules
                (id, workspace_id, module_id, pattern, require_reviews, enforce_admins, require_status_checks)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (rule_id, workspace_id, module_id, pattern, int(require_reviews), int(enforce_admins), int(require_status_checks)),
        )
        return {
            "id": rule_id,
            "branch_pattern": pattern,
            "require_pr": require_reviews,
            "required_review_count": 1 if require_reviews else 0,
            "require_status_checks": require_status_checks,
            "required_status_checks": body.get("required_status_checks") or [],
            "restrict_push": enforce_admins,
        }

    def remove_branch_protection(self, workspace_id: str, module_id: str, rule_id: str) -> bool:
        if self._postgres:
            from raphael_contracts.db import pg_execute

            cur = pg_execute(
                "DELETE FROM branch_protection_rules WHERE id = %s AND workspace_id = %s AND module_id = %s",
                (rule_id, workspace_id, module_id),
            )
            return cur.rowcount > 0
        with self._connect_sqlite() as conn:
            cur = conn.execute(
                "DELETE FROM branch_protection_rules WHERE id = ? AND workspace_id = ? AND module_id = ?",
                (rule_id, workspace_id, module_id),
            )
            return cur.rowcount > 0

    def list_webhooks(self, workspace_id: str, module_id: str) -> list[dict[str, Any]]:
        rows = self._fetchall(
            """
            SELECT id, url, events, secret, active, created_at
            FROM module_webhooks
            WHERE workspace_id = ? AND module_id = ?
            ORDER BY created_at
            """,
            (workspace_id, module_id),
        )
        hooks = []
        for r in rows:
            if isinstance(r, dict):
                events = r["events"]
                if isinstance(events, str):
                    events = json.loads(events)
                hooks.append(
                    {
                        "id": r["id"],
                        "url": r["url"],
                        "events": events,
                        "secret": r.get("secret"),
                        "active": bool(r["active"]),
                        "created_at": r.get("created_at"),
                    }
                )
            else:
                events = json.loads(r[2]) if isinstance(r[2], str) else r[2]
                hooks.append(
                    {
                        "id": r[0],
                        "url": r[1],
                        "events": events,
                        "secret": r[3],
                        "active": bool(r[4]),
                        "created_at": r[5] if len(r) > 5 else None,
                    }
                )
        return hooks

    def add_webhook(self, workspace_id: str, module_id: str, body: dict[str, Any]) -> dict[str, Any]:
        hook_id = str(uuid.uuid4())
        events = body.get("events") or ["push"]
        active = body.get("active", True)
        events_json = json.dumps(events)
        if self._postgres:
            from raphael_contracts.db import connection

            with connection() as conn:
                conn.execute(
                    """
                    INSERT INTO module_webhooks (id, workspace_id, module_id, url, events, secret, active)
                    VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s)
                    """,
                    (hook_id, workspace_id, module_id, body["url"], events_json, body.get("secret"), active),
                )
                conn.commit()
        else:
            with self._connect_sqlite() as conn:
                conn.execute(
                    """
                    INSERT INTO module_webhooks (id, workspace_id, module_id, url, events, secret, active)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (hook_id, workspace_id, module_id, body["url"], events_json, body.get("secret"), int(active)),
                )
        return {
            "id": hook_id,
            "url": body["url"],
            "events": events,
            "secret": body.get("secret"),
            "active": active,
        }
