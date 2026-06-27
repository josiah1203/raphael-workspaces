"""Workspaces VCS integration tests."""

import uuid

from fastapi.testclient import TestClient

from raphael_workspaces.app import app

client = TestClient(app)
BASE = "/v1/workspaces/default/modules/power-board-v2"


def test_list_modules_seeded() -> None:
    res = client.get("/v1/workspaces/default/modules")
    assert res.status_code == 200
    mods = res.json()["modules"]
    assert any(m["id"] == "power-board-v2" for m in mods)


def test_branches_and_tags() -> None:
    tag_name = f"v-test-{uuid.uuid4().hex[:6]}"
    branches = client.get(f"{BASE}/branches").json()["branches"]
    assert any(b["name"] == "main" for b in branches)
    client.post(f"{BASE}/tag", json={"name": tag_name})
    tags = client.get(f"{BASE}/tags").json()["tags"]
    assert any(t["name"] == tag_name for t in tags)


def test_branch_commit() -> None:
    branch = f"feature-{uuid.uuid4().hex[:6]}"
    client.post(f"{BASE}/branch", json={"name": branch, "from": "main"})
    res = client.post(
        f"{BASE}/commit",
        json={
            "message": f"Feature work {branch}",
            "branch": branch,
            "events": [{"event_type": "parameter.update", "payload": {"name": "voltage", "value": "12"}}],
        },
    )
    assert res.status_code == 200
    log = client.get(f"{BASE}/log?branch={branch}").json()["commits"]
    assert any(c["message"] == f"Feature work {branch}" for c in log)


def test_commit_diff() -> None:
    log = client.get(f"{BASE}/log").json()["commits"]
    if log:
        diff = client.get(f"{BASE}/commits/{log[0]['hash']}/diff")
        assert diff.status_code == 200
        assert "bom" in diff.json()


def test_fork_and_slice() -> None:
    fork_id = f"fork-{uuid.uuid4().hex[:8]}"
    fork = client.post(f"{BASE}/fork", json={"id": fork_id, "name": "Power Board Fork"})
    assert fork.status_code == 200
    assert fork.json()["parent_module_id"] == "power-board-v2"
    slice_id = f"slice-{uuid.uuid4().hex[:8]}"
    sl = client.post(f"{BASE}/slice", json={"id": slice_id, "name": "Power Slice", "scope": "bom"})
    assert sl.status_code == 200
    assert sl.json()["parent_module_id"] == "power-board-v2"


def test_projects() -> None:
    res = client.get("/v1/projects")
    assert res.status_code == 200
    assert "projects" in res.json()
