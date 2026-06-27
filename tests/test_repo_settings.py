"""Repo settings, collaborators, branch protection, webhooks tests."""

import uuid

from fastapi.testclient import TestClient

from raphael_workspaces.app import app

client = TestClient(app)
WS = "default"
BASE = f"/v1/workspaces/{WS}/modules"


def _module_base(module_id: str) -> str:
    return f"{BASE}/{module_id}"


def _create_module() -> str:
    module_id = f"settings-{uuid.uuid4().hex[:8]}"
    res = client.post(f"{BASE}", json={"id": module_id, "name": f"Settings {module_id}"})
    assert res.status_code == 200
    return module_id


def test_get_settings_defaults() -> None:
    module_id = _create_module()
    res = client.get(f"{_module_base(module_id)}/settings")
    assert res.status_code == 200
    body = res.json()
    assert body["name"] == f"Settings {module_id}"
    assert body["visibility"] == "private"
    assert body["default_branch"] == "main"
    assert body["artifact_type"] == "mixed"


def test_patch_settings() -> None:
    module_id = _create_module()
    res = client.patch(
        f"{_module_base(module_id)}/settings",
        json={
            "visibility": "internal",
            "artifact_type": "design",
            "license": "mit",
            "description": "Test repo",
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["visibility"] == "internal"
    assert body["artifact_type"] == "design"
    assert body["license"] == "mit"
    assert body["description"] == "Test repo"


def test_settings_not_found() -> None:
    res = client.get(f"{BASE}/missing-module-id/settings")
    assert res.status_code == 404


def test_collaborators_crud() -> None:
    module_id = _create_module()
    base = f"{_module_base(module_id)}/settings/collaborators"

    listed = client.get(base)
    assert listed.status_code == 200
    assert listed.json()["collaborators"] == []

    created = client.post(base, json={"user_id": "alice", "role": "write"})
    assert created.status_code == 200
    collab = created.json()
    assert collab["user_id"] == "alice"
    assert collab["role"] == "write"

    listed2 = client.get(base).json()["collaborators"]
    assert any(c["user_id"] == "alice" for c in listed2)

    deleted = client.delete(f"{base}/alice")
    assert deleted.status_code == 200
    assert client.get(base).json()["collaborators"] == []


def test_collaborator_duplicate() -> None:
    module_id = _create_module()
    base = f"{_module_base(module_id)}/settings/collaborators"
    client.post(base, json={"user_id": "bob", "role": "read"})
    dup = client.post(base, json={"user_id": "bob", "role": "admin"})
    assert dup.status_code == 409


def test_branch_protection_crud() -> None:
    module_id = _create_module()
    base = f"{_module_base(module_id)}/settings/branch-protection"

    assert client.get(base).json()["rules"] == []

    created = client.post(
        base,
        json={"branch_pattern": "main", "require_status_checks": True, "require_pr": True},
    )
    assert created.status_code == 200
    rule = created.json()
    assert rule["branch_pattern"] == "main"
    assert rule["require_status_checks"] is True
    rule_id = rule["id"]

    rules = client.get(base).json()["rules"]
    assert len(rules) == 1

    deleted = client.delete(f"{base}/{rule_id}")
    assert deleted.status_code == 200
    assert client.get(base).json()["rules"] == []


def test_webhooks_get_and_post() -> None:
    module_id = _create_module()
    base = f"{_module_base(module_id)}/settings/webhooks"

    assert client.get(base).json()["webhooks"] == []

    created = client.post(
        base,
        json={"url": "https://example.com/hook", "events": ["push", "commit"], "secret": "s3cr3t"},
    )
    assert created.status_code == 200
    hook = created.json()
    assert hook["url"] == "https://example.com/hook"
    assert hook["active"] is True
    assert "push" in hook["events"]

    hooks = client.get(base).json()["webhooks"]
    assert len(hooks) == 1
    assert hooks[0]["url"] == "https://example.com/hook"


def test_remove_collaborator_not_found() -> None:
    module_id = _create_module()
    base = f"{_module_base(module_id)}/settings/collaborators"
    res = client.delete(f"{base}/nobody")
    assert res.status_code == 404


def test_webhook_requires_url() -> None:
    module_id = _create_module()
    base = f"{_module_base(module_id)}/settings/webhooks"
    res = client.post(base, json={"events": ["push"]})
    assert res.status_code == 400
    assert res.json()["detail"] == "url_required"
