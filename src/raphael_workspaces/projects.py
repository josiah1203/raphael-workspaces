"""Projects API — /v1/projects (gateway proxies here)."""

from __future__ import annotations

from fastapi import APIRouter

from raphael_workspaces.store import WorkspacesStore

router = APIRouter(tags=["projects"])
_store = WorkspacesStore()


@router.get("")
def list_projects() -> dict[str, list]:
    return {"projects": _store.list_projects("default")}


@router.get("/{project_id}")
def get_project(project_id: str) -> dict:
    mod = _store.get_module("default", project_id)
    if not mod:
        return {"id": project_id, "name": project_id, "compliance_score": 0, "fidelity_score": 0}
    return {
        "id": mod["id"],
        "name": mod["name"],
        "compliance_score": 100,
        "fidelity_score": 95,
        "open_reviews": 0,
    }
