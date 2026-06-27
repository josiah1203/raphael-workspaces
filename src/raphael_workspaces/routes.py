"""Workspaces API — /v1/workspaces/{id}/modules/*."""

from __future__ import annotations

import os
import secrets
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException

from raphael_workspaces.files_store import ModuleFilesStore
from raphael_workspaces.settings_store import RepoSettingsStore
from raphael_workspaces.store import WorkspacesStore

router = APIRouter(tags=["workspaces"])
_store = WorkspacesStore()
_files = ModuleFilesStore()
_settings = RepoSettingsStore()
_share_links: dict[str, dict[str, str]] = {}


def _require_module(workspace_id: str, module_id: str) -> dict[str, Any]:
    mod = _store.get_module(workspace_id, module_id)
    if not mod:
        raise HTTPException(404, detail="not_found")
    return mod


def _record_lineage(from_id: str, to_id: str, edge_type: str) -> None:
    graph_url = os.environ.get("RAPHAEL_GRAPH_URL", "http://127.0.0.1:8100")
    try:
        with httpx.Client(timeout=5.0) as client:
            client.post(
                f"{graph_url}/v1/graph/edges",
                json={"from_id": to_id, "to_id": from_id, "edge_type": edge_type},
            )
    except httpx.HTTPError:
        pass  # ponytail: graph optional at fork time


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


@router.post("/{workspace_id}/modules/{module_id}/fork")
def fork_module(workspace_id: str, module_id: str, body: dict[str, Any]) -> dict[str, Any]:
    new_id = body.get("id") or body.get("name", "fork").lower().replace(" ", "-")
    name = body.get("name", new_id)
    if _store.get_module(workspace_id, new_id):
        raise HTTPException(409, detail="module_exists")
    result = _store.fork_module(workspace_id, module_id, new_id, name)
    _record_lineage(module_id, new_id, "forked_from")
    return result


@router.post("/{workspace_id}/modules/{module_id}/slice")
def slice_module(workspace_id: str, module_id: str, body: dict[str, Any]) -> dict[str, Any]:
    new_id = body.get("id") or body.get("name", "slice").lower().replace(" ", "-")
    name = body.get("name", new_id)
    if _store.get_module(workspace_id, new_id):
        raise HTTPException(409, detail="module_exists")
    result = _store.slice_module(workspace_id, module_id, new_id, name, body.get("scope"))
    _record_lineage(module_id, new_id, "sliced_from")
    return result


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
    return _store.create_commit(
        workspace_id,
        module_id,
        body.get("message", "commit"),
        events,
        body.get("branch", "main"),
        body.get("intent_summary"),
    )


@router.get("/{workspace_id}/modules/{module_id}/commits/{commit_hash}/diff")
def commit_diff(workspace_id: str, module_id: str, commit_hash: str) -> dict[str, Any]:
    return _store.commit_diff(workspace_id, module_id, commit_hash)


@router.post("/{workspace_id}/modules/{module_id}/merge")
def merge(workspace_id: str, module_id: str, body: dict[str, Any]) -> dict[str, Any]:
    return _store.merge_branches(workspace_id, module_id, body["source"], body["target"])


@router.post("/{workspace_id}/modules/{module_id}/branch")
def create_branch(workspace_id: str, module_id: str, body: dict[str, Any]) -> dict[str, str]:
    return _store.create_branch(workspace_id, module_id, body["name"], body.get("from", "main"))


@router.post("/{workspace_id}/modules/{module_id}/share-link")
def share_link(workspace_id: str, module_id: str, body: dict[str, Any] | None = None) -> dict[str, str]:
    if not _store.get_module(workspace_id, module_id):
        raise HTTPException(404, detail="not_found")
    token = secrets.token_urlsafe(16)
    _share_links[token] = {"workspace_id": workspace_id, "module_id": module_id}
    return {"token": token, "url": f"/modules/{module_id}?share={token}"}


@router.get("/{workspace_id}/modules/{module_id}/files/tree")
def file_tree(
    workspace_id: str,
    module_id: str,
    branch: str = "main",
    path: str = "",
) -> dict[str, Any]:
    _require_module(workspace_id, module_id)
    entries = _files.list_tree(workspace_id, module_id, branch, path)
    return {"branch": branch, "path": path, "entries": entries}


@router.get("/{workspace_id}/modules/{module_id}/files/blob")
def get_file_blob(
    workspace_id: str,
    module_id: str,
    branch: str = "main",
    path: str = "",
) -> dict[str, Any]:
    _require_module(workspace_id, module_id)
    if not path:
        raise HTTPException(400, detail="path_required")
    blob = _files.get_blob(workspace_id, module_id, branch, path)
    if not blob:
        raise HTTPException(404, detail="not_found")
    return blob


@router.put("/{workspace_id}/modules/{module_id}/files/blob")
def put_file_blob(workspace_id: str, module_id: str, body: dict[str, Any]) -> dict[str, Any]:
    _require_module(workspace_id, module_id)
    branch = body.get("branch", "main")
    path = body.get("path", "")
    if not path:
        raise HTTPException(400, detail="path_required")
    try:
        result = _files.put_blob(
            workspace_id,
            module_id,
            branch,
            path,
            content=body.get("content"),
            content_base64=body.get("content_base64"),
            content_type=body.get("content_type"),
            message=body.get("message"),
        )
    except ValueError as exc:
        if str(exc) == "content_required":
            raise HTTPException(400, detail="content_required") from exc
        raise
    message = body.get("message")
    if message:
        _store.create_commit(
            workspace_id,
            module_id,
            message,
            [{"path": path, "action": "modify", "branch": branch}],
            branch,
        )
    return result


@router.get("/{workspace_id}/modules/{module_id}/settings")
def get_settings(workspace_id: str, module_id: str) -> dict[str, Any]:
    mod = _require_module(workspace_id, module_id)
    return _settings.get_settings(workspace_id, module_id, mod["name"])


@router.patch("/{workspace_id}/modules/{module_id}/settings")
def patch_settings(workspace_id: str, module_id: str, body: dict[str, Any]) -> dict[str, Any]:
    mod = _require_module(workspace_id, module_id)
    _settings.patch_settings(workspace_id, module_id, body)
    return _settings.get_settings(workspace_id, module_id, mod["name"])


@router.get("/{workspace_id}/modules/{module_id}/settings/collaborators")
def list_collaborators(workspace_id: str, module_id: str) -> dict[str, list]:
    _require_module(workspace_id, module_id)
    return {"collaborators": _settings.list_collaborators(workspace_id, module_id)}


@router.post("/{workspace_id}/modules/{module_id}/settings/collaborators")
def add_collaborator(workspace_id: str, module_id: str, body: dict[str, Any]) -> dict[str, str]:
    _require_module(workspace_id, module_id)
    user_id = body.get("user_id")
    if not user_id:
        raise HTTPException(400, detail="user_id_required")
    role = body.get("role", "read")
    try:
        return _settings.add_collaborator(workspace_id, module_id, user_id, role)
    except ValueError as exc:
        if str(exc) == "collaborator_exists":
            raise HTTPException(409, detail="collaborator_exists") from exc
        raise


@router.delete("/{workspace_id}/modules/{module_id}/settings/collaborators/{user_id}")
def remove_collaborator(workspace_id: str, module_id: str, user_id: str) -> dict[str, str]:
    _require_module(workspace_id, module_id)
    if not _settings.remove_collaborator(workspace_id, module_id, user_id):
        raise HTTPException(404, detail="not_found")
    return {"status": "removed", "user_id": user_id}


@router.get("/{workspace_id}/modules/{module_id}/settings/branch-protection")
def list_branch_protection(workspace_id: str, module_id: str) -> dict[str, list]:
    _require_module(workspace_id, module_id)
    return {"rules": _settings.list_branch_protection(workspace_id, module_id)}


@router.post("/{workspace_id}/modules/{module_id}/settings/branch-protection")
def add_branch_protection(workspace_id: str, module_id: str, body: dict[str, Any]) -> dict[str, Any]:
    _require_module(workspace_id, module_id)
    return _settings.add_branch_protection(workspace_id, module_id, body)


@router.delete("/{workspace_id}/modules/{module_id}/settings/branch-protection/{rule_id}")
def remove_branch_protection(workspace_id: str, module_id: str, rule_id: str) -> dict[str, str]:
    _require_module(workspace_id, module_id)
    if not _settings.remove_branch_protection(workspace_id, module_id, rule_id):
        raise HTTPException(404, detail="not_found")
    return {"status": "removed", "id": rule_id}


@router.get("/{workspace_id}/modules/{module_id}/settings/webhooks")
def list_webhooks(workspace_id: str, module_id: str) -> dict[str, list]:
    _require_module(workspace_id, module_id)
    return {"webhooks": _settings.list_webhooks(workspace_id, module_id)}


@router.post("/{workspace_id}/modules/{module_id}/settings/webhooks")
def add_webhook(workspace_id: str, module_id: str, body: dict[str, Any]) -> dict[str, Any]:
    _require_module(workspace_id, module_id)
    if not body.get("url"):
        raise HTTPException(400, detail="url_required")
    return _settings.add_webhook(workspace_id, module_id, body)
