"""Workspaces VCS integration tests."""

from fastapi.testclient import TestClient

from raphael_workspaces.app import app

client = TestClient(app)


def test_list_modules_seeded() -> None:
    res = client.get("/v1/workspaces/default/modules")
    assert res.status_code == 200
    mods = res.json()["modules"]
    assert any(m["id"] == "power-board-v2" for m in mods)


def test_branches_and_tags() -> None:
    base = "/v1/workspaces/default/modules/power-board-v2"
    branches = client.get(f"{base}/branches").json()["branches"]
    assert any(b["name"] == "main" for b in branches)
    client.post(f"{base}/tag", json={"name": "v1.0.0"})
    tags = client.get(f"{base}/tags").json()["tags"]
    assert any(t["name"] == "v1.0.0" for t in tags)


def test_commit_diff() -> None:
    base = "/v1/workspaces/default/modules/power-board-v2"
    log = client.get(f"{base}/log").json()["commits"]
    if log:
        diff = client.get(f"{base}/commits/{log[0]['hash']}/diff")
        assert diff.status_code == 200
        assert "bom" in diff.json()
