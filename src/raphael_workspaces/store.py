"""Workspaces store backed by calliope-vcs VCService."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from raphael_workspaces.delta.engine import DeltaEngine
from raphael_workspaces.paths import raphael_home
from raphael_workspaces.vcs.service import VCService
from raphael_workspaces.vcs.storage import VCSStorage

DEFAULT_WORKSPACE = "default"


class WorkspacesStore:
    def __init__(self, db_path: Path | None = None) -> None:
        path = db_path or Path(os.environ.get("RAPHAEL_WORKSPACES_DB", str(raphael_home() / "workspaces-vcs.db")))
        self._vcs = VCService(VCSStorage(path), DeltaEngine())
        self._seed()

    def _seed(self) -> None:
        if self._vcs.storage.get_repo("power-board-v2") is None:
            self._vcs.init_repo("power-board-v2", "Power Board V2")
            self._vcs.create_commit(
                "power-board-v2",
                "main",
                "Initial commit",
                "system",
                [{"event_type": "electrical.footprint_added", "payload": {"footprint_ref": "U1"}}],
                0,
                1,
            )

    def list_modules(self, workspace_id: str) -> list[dict[str, Any]]:
        # ponytail: workspace_id maps 1:1 to repo namespace for now
        _ = workspace_id
        repos: list[dict[str, Any]] = []
        with self._vcs.storage.db_path.open("rb"):
            pass
        # list repos from sqlite
        import sqlite3

        with sqlite3.connect(self._vcs.storage.db_path) as conn:
            rows = conn.execute("SELECT id, name, description FROM repos ORDER BY name").fetchall()
        return [{"id": r[0], "name": r[1], "description": r[2]} for r in rows]

    def get_module(self, workspace_id: str, module_id: str) -> dict[str, Any] | None:
        _ = workspace_id
        return self._vcs.storage.get_repo(module_id)

    def create_module(self, workspace_id: str, module_id: str, name: str) -> dict[str, Any]:
        _ = workspace_id
        self._vcs.init_repo(module_id, name)
        return self.get_module(workspace_id, module_id) or {"id": module_id, "name": name}

    def list_branches(self, workspace_id: str, module_id: str) -> list[dict[str, Any]]:
        _ = workspace_id
        return self._vcs.storage.list_branches(module_id)

    def list_tags(self, workspace_id: str, module_id: str) -> list[dict[str, Any]]:
        _ = workspace_id
        return self._vcs.storage.get_tags(module_id)

    def list_commits(self, workspace_id: str, module_id: str, branch: str | None = None) -> list[dict[str, Any]]:
        _ = workspace_id
        commits = self._vcs.get_log(module_id, branch)
        return [
            {
                "hash": c["hash"],
                "parent_hash": c.get("parent_hash"),
                "author": c.get("author"),
                "timestamp": c.get("timestamp"),
                "message": c.get("message"),
                "ops": c.get("ops"),
            }
            for c in commits
        ]

    def create_commit(self, workspace_id: str, module_id: str, message: str, events: list[dict] | None = None) -> dict[str, Any]:
        _ = workspace_id
        events = events or []
        h = self._vcs.create_commit(module_id, "main", message, "user", events, 0, len(events))
        return {"hash": h, "message": message}

    def create_branch(self, workspace_id: str, module_id: str, name: str, from_ref: str = "main") -> dict[str, str]:
        _ = workspace_id
        self._vcs.create_branch(module_id, name, from_ref)
        return {"name": name}

    def create_tag(self, workspace_id: str, module_id: str, name: str, branch: str = "main") -> dict[str, str]:
        _ = workspace_id
        self._vcs.create_tag(module_id, name, branch)
        return {"name": name}

    def merge_branches(self, workspace_id: str, module_id: str, source: str, target: str) -> dict[str, Any]:
        _ = workspace_id
        return self._vcs.merge(module_id, source, target, "user")

    def commit_diff(self, workspace_id: str, module_id: str, commit_hash: str) -> dict[str, Any]:
        _ = workspace_id
        commits = self._vcs.get_log(module_id)
        commit = next((c for c in commits if c["hash"] == commit_hash), None)
        if not commit:
            return {"bom": [], "drc": [], "electrical": [], "schematic": [], "layout": [], "ops": [], "summary": {}}
        ops = json.loads(commit.get("ops") or "[]")
        bom = [{"change": "modified", "reference": op.get("id") or op.get("name", "?"), "value": str(op)} for op in ops]
        return {
            "bom": bom,
            "drc": [],
            "electrical": ops,
            "schematic": [],
            "layout": [],
            "ops": ops,
            "summary": {"components": len(bom), "nets": 0, "drc_warnings": 0, "drc_errors": 0, "schematic": 0, "layout": 0},
        }
