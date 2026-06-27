"""Workspaces store backed by calliope-vcs VCService."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import httpx

from raphael_workspaces.delta.engine import DeltaEngine
from raphael_workspaces.paths import raphael_home
from raphael_workspaces.vcs.service import VCService
from raphael_workspaces.vcs.storage import VCSStorage


class WorkspacesStore:
    def __init__(self, db_path: Path | None = None) -> None:
        if os.environ.get("RAPHAEL_DATABASE_URL"):
            path = None
        else:
            path = db_path or Path(os.environ.get("RAPHAEL_WORKSPACES_DB", str(raphael_home() / "workspaces-vcs.db")))
        self._vcs = VCService(VCSStorage(path), DeltaEngine())
        self._seed()

    def _seed(self) -> None:
        if self._vcs.storage.get_repo("power-board-v2", "default") is None:
            self._vcs.init_repo("power-board-v2", "Power Board V2", "default")
            self._vcs.create_commit(
                "power-board-v2",
                "default",
                "main",
                "Initial commit",
                "system",
                [{"event_type": "electrical.footprint_added", "payload": {"footprint_ref": "U1"}}],
                0,
                1,
            )

    def list_modules(self, workspace_id: str) -> list[dict[str, Any]]:
        return self._vcs.storage.list_repos(workspace_id)

    def get_module(self, workspace_id: str, module_id: str) -> dict[str, Any] | None:
        return self._vcs.storage.get_repo(module_id, workspace_id)

    def create_module(self, workspace_id: str, module_id: str, name: str) -> dict[str, Any]:
        self._vcs.init_repo(module_id, name, workspace_id)
        return self.get_module(workspace_id, module_id) or {"id": module_id, "name": name}

    def fork_module(self, workspace_id: str, module_id: str, new_id: str, name: str) -> dict[str, Any]:
        result = self._vcs.fork_repo(module_id, workspace_id, new_id, name)
        self._publish_fork(workspace_id, module_id, new_id, name)
        return result

    def slice_module(
        self, workspace_id: str, module_id: str, new_id: str, name: str, scope: str | None = None
    ) -> dict[str, Any]:
        result = self._vcs.slice_repo(module_id, workspace_id, new_id, name, scope)
        self._publish_slice(workspace_id, module_id, new_id, name, scope)
        return result

    def list_branches(self, workspace_id: str, module_id: str) -> list[dict[str, Any]]:
        return self._vcs.storage.list_branches(module_id, workspace_id)

    def list_tags(self, workspace_id: str, module_id: str) -> list[dict[str, Any]]:
        return self._vcs.storage.get_tags(module_id, workspace_id)

    def list_commits(self, workspace_id: str, module_id: str, branch: str | None = None) -> list[dict[str, Any]]:
        commits = self._vcs.get_log(module_id, workspace_id, branch)
        return [
            {
                "hash": c["hash"],
                "parent_hash": c.get("parent_hash"),
                "author": c.get("author"),
                "timestamp": c.get("timestamp"),
                "message": c.get("message"),
                "ops": c.get("ops"),
                "intent_summary": c.get("intent_summary"),
            }
            for c in commits
        ]

    def create_commit(
        self,
        workspace_id: str,
        module_id: str,
        message: str,
        events: list[dict] | None = None,
        branch: str = "main",
        intent_summary: str | None = None,
    ) -> dict[str, Any]:
        events = events or []
        wal_start = self._vcs.storage.get_last_wal_index(module_id, branch, workspace_id)
        wal_end = wal_start + len(events)
        h = self._vcs.create_commit(
            module_id, workspace_id, branch, message, "user", events, wal_start, wal_end, intent_summary
        )
        if not intent_summary:
            intent_summary = self._semantic_intent_label(events, message)
            if intent_summary:
                self._vcs.storage.set_commit_intent(h, module_id, workspace_id, intent_summary)
        self._publish_commit(workspace_id, module_id, branch, message, h, events, intent_summary)
        return {"hash": h, "message": message, "branch": branch, "intent_summary": intent_summary}

    def _publish_commit(
        self,
        workspace_id: str,
        module_id: str,
        branch: str,
        message: str,
        commit_hash: str,
        events: list[dict],
        intent_summary: str | None,
    ) -> None:
        self._publish_event(
            "raphael.workspaces.commit",
            {
                "workspace_id": workspace_id,
                "module_id": module_id,
                "branch": branch,
                "message": message,
                "hash": commit_hash,
                "event_count": len(events),
                "intent_summary": intent_summary,
            },
            workspace_id,
        )

    def _semantic_intent_label(self, events: list[dict], message: str) -> str | None:
        ai_url = os.environ.get("RAPHAEL_AI_URL", "http://127.0.0.1:8104").rstrip("/")
        try:
            with httpx.Client(timeout=3.0) as client:
                res = client.post(
                    f"{ai_url}/v1/intelligence/squash/label",
                    json={"events": events, "message": message},
                )
                if res.status_code == 200:
                    return res.json().get("intent_summary")
        except httpx.HTTPError:
            pass
        return None

    def create_branch(self, workspace_id: str, module_id: str, name: str, from_ref: str = "main") -> dict[str, str]:
        self._vcs.create_branch(module_id, workspace_id, name, from_ref)
        return {"name": name}

    def create_tag(self, workspace_id: str, module_id: str, name: str, branch: str = "main") -> dict[str, str]:
        self._vcs.create_tag(module_id, workspace_id, name, branch)
        return {"name": name}

    def merge_branches(self, workspace_id: str, module_id: str, source: str, target: str) -> dict[str, Any]:
        result = self._vcs.merge(module_id, workspace_id, source, target, "user")
        if result.get("status") != "conflict":
            self._publish_merge(workspace_id, module_id, source, target, result)
        return result

    def _publish_event(self, event_type: str, data: dict, workspace_id: str) -> None:
        try:
            from raphael_contracts.kafka import publish_event

            publish_event(event_type, data, source="raphael-workspaces", workspace_id=workspace_id)
        except Exception:
            pass

    def _publish_merge(
        self, workspace_id: str, module_id: str, source: str, target: str, result: dict[str, Any]
    ) -> None:
        self._publish_event(
            "raphael.workspaces.merge",
            {
                "workspace_id": workspace_id,
                "module_id": module_id,
                "source": source,
                "target": target,
                "hash": result.get("hash"),
                "status": result.get("status", "merged"),
            },
            workspace_id,
        )

    def _publish_fork(self, workspace_id: str, source_module_id: str, new_module_id: str, name: str) -> None:
        self._publish_event(
            "raphael.workspaces.fork",
            {
                "workspace_id": workspace_id,
                "source_module_id": source_module_id,
                "new_module_id": new_module_id,
                "name": name,
            },
            workspace_id,
        )

    def _publish_slice(
        self, workspace_id: str, source_module_id: str, new_module_id: str, name: str, scope: str | None
    ) -> None:
        self._publish_event(
            "raphael.workspaces.slice",
            {
                "workspace_id": workspace_id,
                "source_module_id": source_module_id,
                "new_module_id": new_module_id,
                "name": name,
                "scope": scope,
            },
            workspace_id,
        )

    def commit_diff(self, workspace_id: str, module_id: str, commit_hash: str) -> dict[str, Any]:
        commit = self._vcs.storage.get_commit(commit_hash, module_id, workspace_id)
        if not commit:
            return {"bom": [], "drc": [], "electrical": [], "schematic": [], "layout": [], "ops": [], "summary": {}}
        ops = json.loads(commit.get("ops") or "[]")
        bom = [{"change": "modified", "reference": _op_key(op), "value": str(op)} for op in ops]
        return {
            "bom": bom,
            "drc": [],
            "electrical": ops,
            "schematic": [],
            "layout": [],
            "ops": ops,
            "intent_summary": commit.get("intent_summary"),
            "summary": {
                "components": len(bom),
                "nets": 0,
                "drc_warnings": 0,
                "drc_errors": 0,
                "schematic": 0,
                "layout": 0,
            },
        }

    def list_projects(self, workspace_id: str = "default") -> list[dict[str, Any]]:
        modules = self.list_modules(workspace_id)
        return [
            {
                "id": m["id"],
                "name": m["name"],
                "module_count": 1,
                "open_reviews": 0,
                "compliance_score": 100,
                "fidelity_score": 95,
            }
            for m in modules
        ]


def _op_key(op: dict[str, Any]) -> str:
    return str(op.get("id") or op.get("name") or op.get("type") or "?")
