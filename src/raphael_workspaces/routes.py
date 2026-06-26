"""Workspaces API — /v1/workspaces/{id}/modules/*."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from raphael_workspaces.store import WorkspacesStore

router = APIRouter(tags=["workspaces"])
_store = WorkspacesStore()


@router.get("/{workspace_id}/modules")
def list_modules(workspace_id: str) -> dict[str, list]:
    mods = _store.list_modules(workspace_id)
    return {"repos": mods, "modules": mods}


@router.post("/{workspace_id}/modules")
def create_module(workspace_id: str, body: dict[str, Any]) -> dict[str, Any]:
    module_id = body.get("id") or body["name"].lower().replace(" ", "-")
    return _store.create_module(workspace_id, module_id, body["name"])


@router.get("/{workspace_id}/modules/{module_id}")
def get_module(workspace_id: str, module_id: str) -> dict[str, Any]:
    mod = _store.get_module(workspace_id, module_id)
    if not mod:
        raise HTTPException(404, detail="not_found")
    return mod


@router.get("/{workspace_id}/modules/{module_id}/branches")
def list_branches(workspace_id: str, module_id: str) -> dict[str, list]:
    return {"branches": _store.list_branches(workspace_id, module_id)}


@router.get("/{workspace_id}/modules/{module_id}/tags")
def list_tags(workspace_id: str, module_id: str) -> dict[str, list]:
    return {"tags": _store.list_tags(workspace_id, module_id)}


@router.post("/{workspace_id}/modules/{module_id}/tag")
def create_tag(workspace_id: str, module_id: str, body: dict[str, Any]) -> dict[str, str]:
    return _store.create_tag(workspace_id, module_id, body["name"], body.get("branch", "main"))


@router.get("/{workspace_id}/modules/{module_id}/log")
def log(workspace_id: str, module_id: str, branch: str | None = None) -> dict[str, list]:
    return {"commits": _store.list_commits(workspace_id, module_id, branch)}


@router.post("/{workspace_id}/modules/{module_id}/commit")
def commit(workspace_id: str, module_id: str, body: dict[str, Any]) -> dict[str, Any]:
    events = body.get("events", [])
    return _store.create_commit(workspace_id, module_id, body.get("message", "commit"), events)


@router.get("/{workspace_id}/modules/{module_id}/commits/{commit_hash}/diff")
def commit_diff(workspace_id: str, module_id: str, commit_hash: str) -> dict[str, Any]:
    return _store.commit_diff(workspace_id, module_id, commit_hash)


@router.post("/{workspace_id}/modules/{module_id}/merge")
def merge(workspace_id: str, module_id: str, body: dict[str, Any]) -> dict[str, Any]:
    return _store.merge_branches(workspace_id, module_id, body["source"], body["target"])


@router.post("/{workspace_id}/modules/{module_id}/branch")
def create_branch(workspace_id: str, module_id: str, body: dict[str, Any]) -> dict[str, str]:
    return _store.create_branch(workspace_id, module_id, body["name"], body.get("from", "main"))
